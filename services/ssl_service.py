import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat, load_pem_private_key,
)
from cryptography.hazmat.primitives.serialization.pkcs12 import load_pkcs12

from db.database import get_setting, get_session, set_setting
from db.models import WebAuthnCredential
from services import audit_service

SSL_DIR  = Path(os.environ.get("ZSCALER_DB_PATH", "/data/db/zscaler.db")).parent / "ssl"
CERT_PATH = SSL_DIR / "cert.pem"
KEY_PATH  = SSL_DIR / "key.pem"

# ssl_mode values that mean "a certificate is installed"; anything else is HTTP.
_ACTIVE_MODES = ("upload", "letsencrypt")


class SSLValidationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ParsedCertBundle:
    leaf: x509.Certificate
    chain: list
    private_key: object


@dataclass
class SSLStatus:
    active: bool
    mode: str
    domain: str
    subject: Optional[str]
    sans: Optional[list]
    not_before: Optional[str]
    not_after: Optional[str]
    days_until_expiry: Optional[int]


_PEM_BLOCK_RE = re.compile(
    rb'-----BEGIN ([A-Z ]+)-----\r?\n.*?-----END \1-----',
    re.DOTALL,
)
_KEY_LABELS = {b'PRIVATE KEY', b'RSA PRIVATE KEY', b'EC PRIVATE KEY'}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _parse_pem_blocks(pem_bytes: bytes) -> tuple:
    """Return (certs_list, private_keys_list) from a PEM bytestring."""
    certs: list = []
    keys: list = []
    for m in _PEM_BLOCK_RE.finditer(pem_bytes):
        label = m.group(1)
        block = m.group(0)
        if label == b'CERTIFICATE':
            try:
                certs.append(x509.load_pem_x509_certificate(block))
            except Exception:
                pass
        elif label in _KEY_LABELS:
            try:
                keys.append(load_pem_private_key(block, password=None))
            except Exception:
                pass
    return certs, keys


def _order_chain(certs: list) -> list:
    """Return certs reordered leaf-first."""
    if len(certs) == 1:
        return certs

    leaf = None
    for cert in certs:
        others_issuers = {c.issuer for c in certs if c is not cert}
        if cert.subject not in others_issuers:
            if leaf is not None:
                raise SSLValidationError(
                    "chain_order",
                    "Could not determine certificate chain order; multiple potential leaf certificates found.",
                )
            leaf = cert

    if leaf is None:
        raise SSLValidationError(
            "chain_order",
            "Could not determine certificate chain order; no clear leaf certificate found.",
        )

    ordered = [leaf]
    remaining = [c for c in certs if c is not leaf]
    while remaining:
        current = ordered[-1]
        next_cert = next((c for c in remaining if c.subject == current.issuer), None)
        if next_cert is None:
            ordered.extend(remaining)
            break
        ordered.append(next_cert)
        remaining.remove(next_cert)

    return ordered


def _verify_key_match(key: object, cert: x509.Certificate) -> None:
    try:
        key_pub = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        cert_pub = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    except Exception:
        raise SSLValidationError("unsupported_key_type", "Unsupported key type; cannot verify key-cert match.")
    if key_pub != cert_pub:
        raise SSLValidationError("key_cert_mismatch", "The private key does not match the certificate.")


def _validate_domain(domain: str, cert: x509.Certificate) -> None:
    domain = re.sub(r'^https?://', '', domain, flags=re.IGNORECASE)
    domain = domain.split(':')[0].strip('/').strip().lower()

    candidates: list = []
    try:
        cns = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        if cns:
            candidates.append(cns[0].value.lower())
    except Exception:
        pass
    candidates.extend(s.lower() for s in _get_sans(cert))

    def _match(d: str, pattern: str) -> bool:
        if pattern.startswith('*.'):
            suffix = pattern[2:]
            parts = d.split('.', 1)
            return len(parts) == 2 and parts[1] == suffix
        return d == pattern

    if not any(_match(domain, p) for p in candidates):
        raise SSLValidationError(
            "domain_mismatch",
            f"Domain '{domain}' does not match any Subject CN or SAN in the certificate.",
        )


def _get_sans(cert: x509.Certificate) -> list:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return ext.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        return []
    except Exception:
        return []


def _serialize_chain(chain: list) -> str:
    return "".join(cert.public_bytes(Encoding.PEM).decode() for cert in chain)


def _serialize_key(key: object) -> str:
    return key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()


# ── Public API ─────────────────────────────────────────────────────────────────

def process_pfx(pfx_bytes: bytes, password: str, domain: str) -> ParsedCertBundle:
    try:
        p12 = load_pkcs12(pfx_bytes, password.encode() if password else None)
    except ValueError:
        raise SSLValidationError("pfx_decrypt_failed", "Failed to decrypt the PFX file. Check the password.")
    if p12.key is None:
        raise SSLValidationError("no_private_key", "No private key found in the PFX file.")
    if p12.cert is None:
        raise SSLValidationError("no_certificates", "No certificate found in the PFX file.")
    additional = [c.certificate for c in (p12.additional_certs or [])]
    all_certs = [p12.cert.certificate] + additional
    chain = _order_chain(all_certs)
    _verify_key_match(p12.key, chain[0])
    _validate_domain(domain, chain[0])
    return ParsedCertBundle(leaf=chain[0], chain=chain, private_key=p12.key)


def process_pem_bytes(pem_bytes: bytes, domain: str) -> ParsedCertBundle:
    certs, keys = _parse_pem_blocks(pem_bytes)
    if not certs:
        raise SSLValidationError("no_certificates", "No certificates found in the uploaded file.")
    if len(keys) > 1:
        raise SSLValidationError(
            "no_private_key",
            "Multiple private key blocks found. Bundle must contain exactly one private key.",
        )
    if len(keys) == 0:
        raise SSLValidationError("no_private_key", "No private key found in the uploaded file.")
    chain = _order_chain(certs)
    _verify_key_match(keys[0], chain[0])
    _validate_domain(domain, chain[0])
    return ParsedCertBundle(leaf=chain[0], chain=chain, private_key=keys[0])


def process_pem_text(pem_text: str, domain: str) -> ParsedCertBundle:
    return process_pem_bytes(pem_text.encode(), domain)


def save_bundle(bundle: ParsedCertBundle, domain: str, mode: str = "upload") -> None:
    # Read before write so we can decide whether credentials need invalidating.
    old_mode   = get_setting("ssl_mode") or "none"
    old_domain = get_setting("ssl_domain") or ""
    # A Let's Encrypt renewal keeps the same origin, so it must not wipe
    # anyone's passkeys — only a genuine change of host or of how the cert got
    # here counts as the origin moving.
    origin_changing = old_mode != mode or old_domain != domain

    try:
        SSL_DIR.mkdir(parents=True, exist_ok=True)
        CERT_PATH.write_text(_serialize_chain(bundle.chain))
        KEY_PATH.write_text(_serialize_key(bundle.private_key))
        os.chmod(KEY_PATH, 0o600)
    except OSError as e:
        raise SSLValidationError("write_failed", f"Failed to write SSL files: {e}")
    set_setting("ssl_mode", mode)
    set_setting("ssl_domain", domain)
    set_setting("webauthn_origin", f"https://{domain}:8443")
    set_setting("webauthn_rp_id", domain)
    if origin_changing:
        with get_session() as session:
            session.query(WebAuthnCredential).delete()
    audit_service.log(
        product="system",
        operation="ssl_upload" if mode == "upload" else f"ssl_{mode}",
        action="upload",
        status="success",
        resource_type="ssl_certificate",
        resource_name=domain,
    )


def get_status() -> SSLStatus:
    try:
        mode = get_setting("ssl_mode") or "none"
        domain = get_setting("ssl_domain") or ""
        if mode not in _ACTIVE_MODES or not CERT_PATH.exists():
            return SSLStatus(active=False, mode=mode, domain=domain,
                             subject=None, sans=None, not_before=None,
                             not_after=None, days_until_expiry=None)
        certs, _ = _parse_pem_blocks(CERT_PATH.read_bytes())
        if not certs:
            return SSLStatus(active=False, mode=mode, domain=domain,
                             subject=None, sans=None, not_before=None,
                             not_after=None, days_until_expiry=None)
        leaf = certs[0]
        try:
            cns = leaf.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
            subject = cns[0].value if cns else leaf.subject.rfc4514_string()
        except Exception:
            subject = leaf.subject.rfc4514_string()
        sans = _get_sans(leaf)
        not_before = leaf.not_valid_before_utc.isoformat()
        not_after  = leaf.not_valid_after_utc.isoformat()
        days = (leaf.not_valid_after_utc - datetime.now(timezone.utc)).days
        return SSLStatus(
            active=True, mode=mode, domain=domain,
            subject=subject, sans=sans,
            not_before=not_before, not_after=not_after,
            days_until_expiry=days,
        )
    except Exception:
        return SSLStatus(active=False, mode="none", domain="",
                         subject=None, sans=None, not_before=None,
                         not_after=None, days_until_expiry=None)


def remove_ssl() -> None:
    try:
        if CERT_PATH.exists():
            CERT_PATH.unlink()
        if KEY_PATH.exists():
            KEY_PATH.unlink()
    except OSError:
        pass
    set_setting("ssl_mode", "none")
    set_setting("ssl_domain", "")
    set_setting("webauthn_origin", "")
    set_setting("webauthn_rp_id", "")
    audit_service.log(
        product="system",
        operation="ssl_remove",
        action="delete",
        status="success",
        resource_type="ssl_certificate",
    )
