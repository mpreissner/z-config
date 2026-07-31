"""Federated login for the zs-config web UI — OIDC and SAML.

zs-config is the service provider in both flows. Everything here is
application-level identity for zs-config's own accounts; it has nothing to do
with the Zscaler tenants the app manages.

The two protocol front-ends converge on `resolve_user()`, which turns an IdP
subject plus a set of group names into a local `User` row.
"""

from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from db.database import get_session, get_setting
from db.models import ScimGroup, ScimGroupMember, User

# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass
class SsoConfig:
    enabled: bool
    provider: str                 # "oidc" | "saml" | ""
    auto_provision: bool
    default_role: str
    group_claim: str
    issuer_url: str
    client_id: str
    client_secret: str
    scopes: str
    saml_idp_metadata_xml: str
    saml_idp_metadata_url: str
    saml_sp_entity_id: str
    saml_sp_cert: str
    saml_sp_key: str
    base_url: str

    @property
    def is_oidc(self) -> bool:
        return self.provider == "oidc"

    @property
    def is_saml(self) -> bool:
        return self.provider == "saml"

    def acs_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1/auth/sso/acs"

    def sls_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1/auth/sso/slo"

    def redirect_uri(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1/auth/sso/callback"

    def entity_id(self) -> str:
        return self.saml_sp_entity_id or f"{self.base_url.rstrip('/')}/api/v1/auth/sso/metadata"


def _secret_setting(key: str) -> str:
    """Read and decrypt a write-only setting. Blank if unset or undecryptable."""
    raw = get_setting(key) or ""
    if not raw:
        return ""
    from services.config_service import decrypt_secret
    try:
        return decrypt_secret(raw)
    except Exception:
        return ""


def load_config() -> SsoConfig:
    return SsoConfig(
        enabled=(get_setting("idp_enabled") or "false") == "true",
        provider=get_setting("idp_provider") or "",
        auto_provision=(get_setting("idp_auto_provision") or "true") == "true",
        default_role=get_setting("idp_default_role") or "user",
        group_claim=get_setting("idp_group_claim") or "groups",
        issuer_url=issuer_from_url(get_setting("idp_issuer_url") or ""),
        client_id=get_setting("idp_client_id") or "",
        client_secret=_secret_setting("idp_client_secret"),
        scopes=get_setting("idp_scopes") or "openid profile email",
        saml_idp_metadata_xml=get_setting("saml_idp_metadata_xml") or "",
        saml_idp_metadata_url=get_setting("saml_idp_metadata_url") or "",
        saml_sp_entity_id=get_setting("saml_sp_entity_id") or "",
        saml_sp_cert=get_setting("saml_sp_cert") or "",
        saml_sp_key=_secret_setting("saml_sp_key"),
        base_url=(get_setting("sso_base_url") or "").rstrip("/"),
    )


class SsoError(Exception):
    """Anything that should surface to the browser as a failed login."""


# ── OIDC ──────────────────────────────────────────────────────────────────────

_DISCOVERY_TTL = 900  # seconds
_discovery_cache: Dict[str, Tuple[float, dict]] = {}
_jwks_cache: Dict[str, Tuple[float, dict]] = {}


_WELL_KNOWN_SUFFIX = "/.well-known/openid-configuration"


def issuer_from_url(url: str) -> str:
    """Reduce anything an admin might paste to a bare issuer URL.

    IdP consoles hand out the full discovery URL far more often than the
    issuer, and the two differ only by a fixed suffix, so accept either.
    """
    cleaned = (url or "").strip().rstrip("/")
    if cleaned.lower().endswith(_WELL_KNOWN_SUFFIX):
        cleaned = cleaned[: -len(_WELL_KNOWN_SUFFIX)]
    return cleaned.rstrip("/")


def discover(issuer_url: str, *, force: bool = False) -> dict:
    """Fetch and cache the OIDC discovery document."""
    if not issuer_url:
        raise SsoError("No issuer URL configured")
    now = time.time()
    hit = _discovery_cache.get(issuer_url)
    if hit and not force and now - hit[0] < _DISCOVERY_TTL:
        return hit[1]
    url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:
        raise SsoError(f"OIDC discovery failed at {url}: {exc}") from exc
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if required not in doc:
            raise SsoError(f"Discovery document is missing {required}")
    _discovery_cache[issuer_url] = (now, doc)
    return doc


def _jwks(jwks_uri: str) -> dict:
    now = time.time()
    hit = _jwks_cache.get(jwks_uri)
    if hit and now - hit[0] < _DISCOVERY_TTL:
        return hit[1]
    try:
        resp = requests.get(jwks_uri, timeout=10)
        resp.raise_for_status()
        keys = resp.json()
    except Exception as exc:
        raise SsoError(f"Could not fetch JWKS: {exc}") from exc
    _jwks_cache[jwks_uri] = (now, keys)
    return keys


def pkce_pair() -> Tuple[str, str]:
    """Return (verifier, S256 challenge)."""
    import hashlib
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(cfg: SsoConfig, state: str, nonce: str, challenge: str) -> str:
    from urllib.parse import urlencode
    doc = discover(cfg.issuer_url)
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri(),
        "scope": cfg.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    sep = "&" if "?" in doc["authorization_endpoint"] else "?"
    return f"{doc['authorization_endpoint']}{sep}{urlencode(params)}"


def exchange_code(cfg: SsoConfig, code: str, verifier: str, nonce: str) -> dict:
    """Trade an authorization code for a verified set of ID token claims."""
    doc = discover(cfg.issuer_url)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.redirect_uri(),
        "client_id": cfg.client_id,
        "code_verifier": verifier,
    }
    auth = None
    if cfg.client_secret:
        # client_secret_basic is the default for confidential clients; fall back
        # to posting the secret only if the IdP advertises no basic support.
        methods = doc.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if "client_secret_basic" in methods:
            auth = (cfg.client_id, cfg.client_secret)
        else:
            data["client_secret"] = cfg.client_secret
    try:
        resp = requests.post(doc["token_endpoint"], data=data, auth=auth, timeout=15)
    except Exception as exc:
        raise SsoError(f"Token exchange failed: {exc}") from exc
    if resp.status_code != 200:
        # The IdP's error body can echo request parameters; keep it out of the
        # response and log only the status.
        raise SsoError(f"Token exchange rejected by the IdP (HTTP {resp.status_code})")
    payload = resp.json()
    id_token = payload.get("id_token")
    if not id_token:
        raise SsoError("IdP response contained no id_token")
    return verify_id_token(cfg, id_token, nonce, doc)


def verify_id_token(cfg: SsoConfig, id_token: str, nonce: str, doc: Optional[dict] = None) -> dict:
    from jose import jwt as jose_jwt, JWTError

    doc = doc or discover(cfg.issuer_url)
    keys = _jwks(doc["jwks_uri"])
    try:
        claims = jose_jwt.decode(
            id_token,
            keys,
            audience=cfg.client_id,
            issuer=doc.get("issuer") or cfg.issuer_url,
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise SsoError(f"ID token verification failed: {exc}") from exc
    if nonce and claims.get("nonce") != nonce:
        raise SsoError("ID token nonce mismatch")
    if not claims.get("sub"):
        raise SsoError("ID token carries no subject")
    return claims


def claims_to_identity(cfg: SsoConfig, claims: dict) -> "Identity":
    groups = claims.get(cfg.group_claim) or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
    )
    return Identity(
        subject=str(claims["sub"]),
        username=str(username),
        email=claims.get("email"),
        given_name=claims.get("given_name"),
        family_name=claims.get("family_name"),
        groups=[str(g) for g in groups],
    )


# ── SAML ──────────────────────────────────────────────────────────────────────


def saml_settings(cfg: SsoConfig) -> dict:
    """Build a python3-saml settings dict from stored settings — no files."""
    from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser

    if cfg.saml_idp_metadata_xml.strip():
        parsed = OneLogin_Saml2_IdPMetadataParser.parse(cfg.saml_idp_metadata_xml)
    elif cfg.saml_idp_metadata_url.strip():
        try:
            parsed = OneLogin_Saml2_IdPMetadataParser.parse_remote(
                cfg.saml_idp_metadata_url, timeout=10
            )
        except Exception as exc:
            raise SsoError(f"Could not fetch IdP metadata: {exc}") from exc
    else:
        raise SsoError("No SAML IdP metadata configured")

    idp = parsed.get("idp")
    if not idp or not idp.get("singleSignOnService"):
        raise SsoError("IdP metadata contains no SingleSignOnService endpoint")

    sign_requests = bool(cfg.saml_sp_cert and cfg.saml_sp_key)
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": cfg.entity_id(),
            "assertionConsumerService": {
                "url": cfg.acs_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "singleLogoutService": {
                "url": cfg.sls_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": cfg.saml_sp_cert,
            "privateKey": cfg.saml_sp_key,
        },
        "idp": idp,
        "security": {
            # Assertions must be signed. Request signing is only possible once
            # an SP keypair exists, so it follows the cert being configured.
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "authnRequestsSigned": sign_requests,
            "logoutRequestSigned": sign_requests,
            "logoutResponseSigned": sign_requests,
            "signMetadata": False,
            "wantNameId": True,
            "requestedAuthnContext": False,
            "rejectUnsolicitedResponsesWithInResponseTo": True,
        },
    }


def saml_attribute(attrs: Dict[str, List[str]], *names: str) -> Optional[str]:
    """First non-empty value among `names`, matched case-insensitively.

    IdPs disagree wildly on attribute naming — Entra emits long claim URIs,
    Okta emits bare names — so callers pass every spelling they know.
    """
    lowered = {k.lower(): v for k, v in attrs.items()}
    for name in names:
        vals = lowered.get(name.lower())
        if vals:
            first = vals[0]
            if first:
                return first
    return None


def saml_to_identity(cfg: SsoConfig, name_id: str, attrs: Dict[str, List[str]]) -> "Identity":
    groups = []
    for key, vals in attrs.items():
        if key.lower().endswith(cfg.group_claim.lower()) or key.lower() == cfg.group_claim.lower():
            groups = [v for v in vals if v]
            break
    email = saml_attribute(
        attrs,
        "email",
        "emailAddress",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    ) or (name_id if "@" in name_id else None)
    username = saml_attribute(
        attrs,
        "username",
        "uid",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    ) or email or name_id
    return Identity(
        subject=name_id,
        username=username,
        email=email,
        given_name=saml_attribute(
            attrs, "firstName", "givenName",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
        ),
        family_name=saml_attribute(
            attrs, "lastName", "surname",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
        ),
        groups=groups,
    )


# ── Account resolution ────────────────────────────────────────────────────────


@dataclass
class Identity:
    """Protocol-neutral view of who just authenticated."""
    subject: str
    username: str
    email: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    groups: List[str] = field(default_factory=list)


def role_for_groups(session, group_names: List[str], default_role: str) -> str:
    """Highest-privilege role mapped by any of the user's groups.

    Called with an open session — group lookup is part of the caller's
    transaction.
    """
    if not group_names:
        return default_role
    lowered = {g.lower() for g in group_names}
    rows = session.query(ScimGroup).filter(ScimGroup.mapped_role.isnot(None)).all()
    roles = {r.mapped_role for r in rows if r.display_name.lower() in lowered}
    if "admin" in roles:
        return "admin"
    if "user" in roles:
        return "user"
    return default_role


def resolve_user(cfg: SsoConfig, identity: Identity) -> Tuple[int, str, str]:
    """Map an authenticated IdP identity onto a local account.

    Returns (user_id, username, role). Raises SsoError when the login should be
    refused. Runs entirely inside one session; the caller logs audit events
    after it closes.
    """
    provider = cfg.provider or "sso"
    with get_session() as session:
        user = (
            session.query(User)
            .filter_by(sso_provider=provider, sso_subject=identity.subject)
            .first()
        )
        if user is None:
            # First federated login for an account that already exists locally.
            q = session.query(User).filter(User.username == identity.username)
            user = q.first()
            if user is None and identity.email:
                user = session.query(User).filter(User.email == identity.email).first()
            if user is not None:
                user.sso_provider = provider
                user.sso_subject = identity.subject

        if user is None:
            if not cfg.auto_provision:
                raise SsoError("No matching account and auto-provisioning is disabled")
            user = User(
                username=identity.username,
                email=identity.email,
                role=role_for_groups(session, identity.groups, cfg.default_role),
                password_hash=None,
                force_password_change=False,
                sso_provider=provider,
                sso_subject=identity.subject,
                given_name=identity.given_name,
                family_name=identity.family_name,
                is_active=True,
            )
            session.add(user)
        else:
            if not user.is_active:
                raise SsoError("Account is disabled")
            if identity.email:
                user.email = identity.email
            if identity.given_name:
                user.given_name = identity.given_name
            if identity.family_name:
                user.family_name = identity.family_name
            # Group-derived roles are authoritative while the IdP owns the user.
            # A user with no mapped groups keeps whatever role they have, so a
            # locally-promoted admin is not silently demoted on every login.
            if identity.groups:
                mapped = role_for_groups(session, identity.groups, "")
                if mapped:
                    user.role = mapped

        user.last_login_at = datetime.utcnow()
        session.flush()
        session.refresh(user)
        return user.id, user.username, user.role


def group_names_for_user(user_id: int) -> List[str]:
    with get_session() as session:
        rows = (
            session.query(ScimGroup.display_name)
            .join(ScimGroupMember, ScimGroupMember.group_id == ScimGroup.id)
            .filter(ScimGroupMember.user_id == user_id)
            .all()
        )
    return [r[0] for r in rows]
