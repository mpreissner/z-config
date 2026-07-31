"""Let's Encrypt certificate issuance over the ACME dns-01 challenge.

dns-01 is the only challenge implemented, on purpose. This app is normally
deployed on an internal network — often reachable only through ZPA — so the
http-01 and tls-alpn-01 challenges could never be answered: they require Let's
Encrypt to connect inbound from the public internet. dns-01 proves control of
the name instead of the host, which works no matter where the container sits.

Cloudflare is the only DNS provider wired up. Everything provider-specific
lives in ``cloudflare_dns``; the order flow below is generic.
"""
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from db.database import get_setting, set_setting
from services import audit_service, cloudflare_dns, ssl_service
from services.cloudflare_dns import CloudflareError
from services.config_service import decrypt_secret, encrypt_secret

DIRECTORY_PROD = "https://acme-v02.api.letsencrypt.org/directory"
DIRECTORY_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"

# Let's Encrypt issues 90-day certificates and recommends renewing at 30 days
# remaining, which leaves a month of daily retries before anything breaks.
RENEW_WINDOW_DAYS = 30

_USER_AGENT = "zs-config"
_DOH_URL = "https://cloudflare-dns.com/dns-query"
_PROPAGATION_TIMEOUT = 180
_PROPAGATION_FLOOR = 10
_PROPAGATION_POLL = 5

# Deliberately RSA rather than ECDSA. The reason this feature exists is to put a
# publicly-trusted cert in front of ZPA Browser Access, and RSA is the option
# with no chance of an interop surprise in that path.
_KEY_SIZE = 2048

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AcmeError(Exception):
    pass


@dataclass
class AcmeConfig:
    domain: str
    email: str
    staging: bool
    auto_renew: bool
    token_set: bool
    last_issued: Optional[str]
    last_error: Optional[str]


# ── Settings ───────────────────────────────────────────────────────────────────

def _flag(key: str, default: bool) -> bool:
    raw = get_setting(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def load_config() -> AcmeConfig:
    return AcmeConfig(
        domain=(get_setting("le_domain") or "").strip(),
        email=(get_setting("le_email") or "").strip(),
        staging=_flag("le_staging", False),
        auto_renew=_flag("le_auto_renew", True),
        token_set=bool(get_setting("le_cf_api_token")),
        last_issued=get_setting("le_last_issued") or None,
        last_error=get_setting("le_last_error") or None,
    )


def save_config(
    domain: str,
    email: str,
    staging: bool,
    auto_renew: bool,
    cf_api_token: str = "",
) -> None:
    """Persist the Let's Encrypt settings. A blank token leaves the stored one alone."""
    set_setting("le_domain", domain.strip())
    set_setting("le_email", email.strip())
    set_setting("le_staging", "true" if staging else "false")
    set_setting("le_auto_renew", "true" if auto_renew else "false")
    if cf_api_token.strip():
        set_setting("le_cf_api_token", encrypt_secret(cf_api_token.strip()))


def _cf_token() -> str:
    stored = get_setting("le_cf_api_token")
    if not stored:
        raise AcmeError("No Cloudflare API token is saved.")
    try:
        return decrypt_secret(stored)
    except ValueError as e:
        raise AcmeError(f"Could not read the stored Cloudflare API token: {e}") from e


def validate_config(cfg: AcmeConfig) -> None:
    if not cfg.domain:
        raise AcmeError("A domain is required.")
    if cfg.domain.startswith("*."):
        raise AcmeError(
            "Wildcard certificates are not supported here — enter the exact "
            "hostname this app is reached at."
        )
    if not _HOSTNAME_RE.match(cfg.domain):
        raise AcmeError(f"'{cfg.domain}' is not a valid fully qualified domain name.")
    if not _EMAIL_RE.match(cfg.email):
        raise AcmeError("A valid contact email is required — Let's Encrypt uses it for expiry warnings.")
    if not cfg.token_set:
        raise AcmeError("A Cloudflare API token is required.")


# ── ACME plumbing ──────────────────────────────────────────────────────────────

def _account_suffix(staging: bool) -> str:
    # Staging and production are separate ACME servers with separate account
    # registries, so the account key and URI have to be tracked per directory.
    return "staging" if staging else "prod"


def _account_key(staging: bool):
    suffix = _account_suffix(staging)
    stored = get_setting(f"le_account_key_{suffix}")
    if stored:
        try:
            pem = decrypt_secret(stored).encode()
        except ValueError as e:
            raise AcmeError(f"Could not read the stored ACME account key: {e}") from e
        return serialization.load_pem_private_key(pem, password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    set_setting(f"le_account_key_{suffix}", encrypt_secret(pem))
    set_setting(f"le_account_uri_{suffix}", "")
    return key


def _build_client(staging: bool, email: str):
    import josepy as jose
    from acme import client as acme_client, messages

    suffix = _account_suffix(staging)
    jwk = jose.JWKRSA(key=jose.ComparableRSAKey(_account_key(staging)))
    directory_url = DIRECTORY_STAGING if staging else DIRECTORY_PROD

    net = acme_client.ClientNetwork(jwk, user_agent=_USER_AGENT)
    try:
        directory = acme_client.ClientV2.get_directory(directory_url, net)
    except Exception as e:
        raise AcmeError(
            f"Could not reach the ACME directory at {directory_url}. "
            f"Check that this container has outbound internet access. ({e})"
        ) from e

    client = acme_client.ClientV2(directory, net=net)

    uri = get_setting(f"le_account_uri_{suffix}")
    if uri:
        net.account = messages.RegistrationResource(body=messages.Registration(), uri=uri)
        return client

    try:
        regr = client.new_account(
            messages.NewRegistration.from_data(email=email, terms_of_service_agreed=True)
        )
    except Exception as e:
        raise AcmeError(f"Let's Encrypt rejected the account registration: {e}") from e
    set_setting(f"le_account_uri_{suffix}", regr.uri)
    return client


def _make_csr(key, domain: str) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM)


def _await_propagation(name: str, expected: str, log: Callable[[str], None]) -> None:
    """Wait until a public resolver can see the challenge record.

    Best effort only. Let's Encrypt does its own authoritative lookup, so a
    failure to confirm here is never fatal — it just means we stop waiting and
    let the CA be the judge.
    """
    time.sleep(_PROPAGATION_FLOOR)
    deadline = time.time() + _PROPAGATION_TIMEOUT
    while time.time() < deadline:
        try:
            resp = requests.get(
                _DOH_URL,
                params={"name": name, "type": "TXT"},
                headers={"accept": "application/dns-json"},
                timeout=10,
            )
            answers = resp.json().get("Answer") or []
        except (requests.RequestException, ValueError):
            log("Could not query a public resolver from here — continuing anyway.")
            return
        if any(expected in (a.get("data") or "") for a in answers):
            log("Challenge record is visible to public resolvers.")
            return
        time.sleep(_PROPAGATION_POLL)
    log("Propagation not confirmed within the timeout — continuing anyway.")


def _run_order(cfg: AcmeConfig, log: Callable[[str], None]) -> tuple:
    """Drive one full ACME order. Returns (fullchain_pem, private_key_pem)."""
    from acme import challenges

    token = _cf_token()
    log("Verifying the Cloudflare API token…")
    cloudflare_dns.verify_token(token)
    zone_id, zone_name = cloudflare_dns.find_zone(token, cfg.domain)
    log(f"Found Cloudflare zone '{zone_name}'.")

    env = "staging" if cfg.staging else "production"
    log(f"Connecting to the Let's Encrypt {env} directory…")
    client = _build_client(cfg.staging, cfg.email)

    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    log(f"Requesting a certificate for {cfg.domain}…")
    try:
        order = client.new_order(_make_csr(key, cfg.domain))
    except Exception as e:
        raise AcmeError(f"Let's Encrypt rejected the certificate order: {e}") from e

    created: list = []
    try:
        for authz in order.authorizations:
            identifier = authz.body.identifier.value
            challb = next(
                (c for c in authz.body.challenges if isinstance(c.chall, challenges.DNS01)),
                None,
            )
            if challb is None:
                raise AcmeError(
                    f"Let's Encrypt did not offer a dns-01 challenge for {identifier}."
                )

            value = challb.chall.validation(client.net.key)
            record_name = challb.chall.validation_domain_name(identifier)

            # A previous run that died before cleanup leaves its TXT behind, and
            # the CA will happily validate against the stale value and fail.
            for stale in cloudflare_dns.find_txt_records(token, zone_id, record_name):
                cloudflare_dns.delete_record(token, zone_id, stale)

            log(f"Creating TXT record {record_name}")
            created.append(cloudflare_dns.create_txt(token, zone_id, record_name, value))

            log("Waiting for DNS propagation…")
            _await_propagation(record_name, value, log)

            client.answer_challenge(challb, challb.chall.response(client.net.key))

        log("Waiting for Let's Encrypt to validate and issue…")
        try:
            order = client.poll_and_finalize(order)
        except Exception as e:
            raise AcmeError(f"Validation or issuance failed: {e}") from e
    finally:
        for record_id in created:
            try:
                cloudflare_dns.delete_record(token, zone_id, record_id)
            except CloudflareError:
                # The cert either issued or it didn't; a leftover TXT record is
                # cleaned up on the next run and is not worth failing over.
                pass

    log("Certificate issued.")
    return order.fullchain_pem, key_pem


# ── Public API ─────────────────────────────────────────────────────────────────

def verify_dns_access() -> str:
    """Confirm the saved token works, and return the zone that covers the domain.

    Raises AcmeError or CloudflareError.
    """
    cfg = load_config()
    validate_config(cfg)
    token = _cf_token()
    cloudflare_dns.verify_token(token)
    _, zone_name = cloudflare_dns.find_zone(token, cfg.domain)
    return zone_name


def issue(log: Optional[Callable[[str], None]] = None) -> dict:
    """Obtain a certificate with the saved configuration and install it.

    Raises AcmeError on any failure; the caller is responsible for restarting
    the server so uvicorn picks up the new certificate.
    """
    emit = log or (lambda _m: None)
    cfg = load_config()
    validate_config(cfg)

    try:
        fullchain_pem, key_pem = _run_order(cfg, emit)
    except CloudflareError as e:
        raise AcmeError(str(e)) from e

    bundle = ssl_service.process_pem_text(f"{fullchain_pem}\n{key_pem}", cfg.domain)
    ssl_service.save_bundle(bundle, cfg.domain, mode="letsencrypt")

    set_setting("le_last_issued", datetime.now(timezone.utc).isoformat())
    set_setting("le_last_error", "")

    audit_service.log(
        product="system",
        operation="ssl_letsencrypt_issue",
        action="create",
        status="success",
        resource_type="ssl_certificate",
        resource_name=cfg.domain,
        details={"staging": cfg.staging},
    )
    not_after = bundle.leaf.not_valid_after_utc.isoformat()
    return {"domain": cfg.domain, "staging": cfg.staging, "not_after": not_after}


def record_failure(message: str) -> None:
    """Persist why the last issuance attempt failed, for the settings page."""
    set_setting("le_last_error", message[:500])
    audit_service.log(
        product="system",
        operation="ssl_letsencrypt_issue",
        action="create",
        status="failure",
        resource_type="ssl_certificate",
        resource_name=(get_setting("le_domain") or ""),
        error_message=message[:500],
    )


def renew_if_due() -> bool:
    """Renew when the installed Let's Encrypt cert is inside the renewal window.

    Returns True when a new certificate was installed, which means the caller
    must restart for it to take effect.
    """
    if (get_setting("ssl_mode") or "none") != "letsencrypt":
        return False
    if not _flag("le_auto_renew", True):
        return False

    status = ssl_service.get_status()
    if status.days_until_expiry is None or status.days_until_expiry > RENEW_WINDOW_DAYS:
        return False

    try:
        issue()
    except Exception as e:
        record_failure(str(e))
        return False
    return True
