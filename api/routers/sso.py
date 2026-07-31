"""Federated login endpoints — OIDC authorization-code and SAML 2.0.

These endpoints establish authentication, so they are unauthenticated by
design. They all end at the same place: a one-time code the SPA trades for the
same JWT pair that password login issues.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, PlainTextResponse
from pydantic import BaseModel

from api.auth_utils import issue_access_token, issue_refresh_token
from api.dependencies import require_admin, AuthUser
from db.database import get_session, get_setting
from db.models import User
from services import sso_service
from services.sso_service import Identity, SsoConfig, SsoError

router = APIRouter(prefix="/api/v1/auth/sso", tags=["SSO"])


# ── Transient in-process stores ───────────────────────────────────────────────
# Same shape as the WebAuthn challenge store in api/routers/auth.py: a dict
# swept on access. Both hold seconds-lived values, so losing them on restart is
# the correct behaviour — an in-flight login simply restarts.

_LOGIN_TTL = 600   # seconds an in-flight IdP round trip may take
_CODE_TTL = 60     # seconds the SPA has to redeem its one-time code

_login_states: Dict[str, Tuple[dict, datetime]] = {}
_handoff_codes: Dict[str, Tuple[dict, datetime]] = {}


def _sweep(store: Dict[str, Tuple[Any, datetime]]) -> None:
    now = datetime.utcnow()
    for k in [k for k, (_, exp) in store.items() if exp <= now]:
        del store[k]


def _put(store: Dict[str, Tuple[Any, datetime]], key: str, value: Any, ttl: int) -> None:
    _sweep(store)
    store[key] = (value, datetime.utcnow() + timedelta(seconds=ttl))


def _take(store: Dict[str, Tuple[Any, datetime]], key: str) -> Optional[Any]:
    _sweep(store)
    entry = store.pop(key, None)
    if entry is None:
        return None
    value, expiry = entry
    return None if datetime.utcnow() > expiry else value


@dataclass
class _TokenUser:
    """Minimal stand-in so auth_utils can mint tokens without a live session."""
    id: int
    username: str
    role: str
    force_password_change: bool = False


def _config_or_400() -> SsoConfig:
    cfg = sso_service.load_config()
    if not cfg.enabled or not cfg.provider:
        raise HTTPException(status_code=400, detail="SSO is not enabled")
    if not cfg.base_url:
        raise HTTPException(
            status_code=400,
            detail="sso_base_url must be set before SSO can be used",
        )
    return cfg


def _fail(message: str) -> RedirectResponse:
    """Send the browser back to the login page with a displayable reason."""
    return RedirectResponse(f"/login?{urlencode({'sso_error': message})}", status_code=302)


def _complete_login(cfg: SsoConfig, identity: Identity) -> RedirectResponse:
    """Turn a verified identity into a one-time code and bounce to the SPA."""
    user_id, username, role = sso_service.resolve_user(cfg, identity)

    shim = _TokenUser(id=user_id, username=username, role=role)
    payload = {
        "access_token": issue_access_token(shim),
        "refresh_token": issue_refresh_token(shim),
        "username": username,
    }
    code = secrets.token_urlsafe(32)
    _put(_handoff_codes, code, payload, _CODE_TTL)

    from services import audit_service
    audit_service.log(
        product=None,
        operation="sso_login",
        action="READ",
        status="SUCCESS",
        tenant_id=None,
        resource_type="user",
        resource_name=username,
        details={"provider": cfg.provider},
    )
    return RedirectResponse(f"/sso/complete?{urlencode({'code': code})}", status_code=302)


# ── Public status ─────────────────────────────────────────────────────────────


@router.get("/status")
def sso_status():
    """Told to the login page before anyone has authenticated.

    Deliberately says only whether SSO is on and which protocol — no issuer,
    no client id, nothing that describes the deployment.
    """
    cfg = sso_service.load_config()
    ready = bool(cfg.enabled and cfg.provider and cfg.base_url)
    if ready and cfg.is_oidc:
        ready = bool(cfg.issuer_url and cfg.client_id)
    if ready and cfg.is_saml:
        ready = bool(cfg.saml_idp_metadata_xml or cfg.saml_idp_metadata_url)
    return {"enabled": ready, "provider": cfg.provider if ready else ""}


# ── Login initiation ──────────────────────────────────────────────────────────


@router.get("/login")
def sso_login():
    cfg = _config_or_400()

    if cfg.is_oidc:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier, challenge = sso_service.pkce_pair()
        _put(_login_states, state, {"nonce": nonce, "verifier": verifier}, _LOGIN_TTL)
        try:
            url = sso_service.authorization_url(cfg, state, nonce, challenge)
        except SsoError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return RedirectResponse(url, status_code=302)

    if cfg.is_saml:
        auth = _saml_auth(cfg, {})
        # RelayState round-trips through the IdP; python3-saml returns it to the
        # ACS, where it is used to confirm the response answers our request.
        relay = secrets.token_urlsafe(24)
        _put(_login_states, relay, {"saml": True}, _LOGIN_TTL)
        return RedirectResponse(auth.login(return_to=relay), status_code=302)

    raise HTTPException(status_code=400, detail="Unknown SSO provider")


# ── OIDC callback ─────────────────────────────────────────────────────────────


@router.get("/callback")
def oidc_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    if error:
        return _fail(error_description or error)

    cfg = sso_service.load_config()
    if not cfg.enabled or not cfg.is_oidc:
        return _fail("OIDC is not enabled")
    if not code or not state:
        return _fail("Malformed response from the identity provider")

    pending = _take(_login_states, state)
    if pending is None:
        return _fail("Login request expired or was already used")

    try:
        claims = sso_service.exchange_code(cfg, code, pending["verifier"], pending["nonce"])
        identity = sso_service.claims_to_identity(cfg, claims)
        return _complete_login(cfg, identity)
    except SsoError as exc:
        return _fail(str(exc))


# ── SAML ──────────────────────────────────────────────────────────────────────


def _saml_auth(cfg: SsoConfig, req: dict):
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="SAML not available (python3-saml not installed)",
        )
    try:
        settings = sso_service.saml_settings(cfg)
    except SsoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    base = {
        "https": "on" if cfg.base_url.startswith("https://") else "off",
        "http_host": cfg.base_url.split("://", 1)[-1].split("/")[0],
        "script_name": "/api/v1/auth/sso/acs",
        "get_data": {},
        "post_data": {},
    }
    base.update(req)
    return OneLogin_Saml2_Auth(base, settings)


async def _saml_request_dict(request: Request) -> dict:
    form = await request.form()
    return {
        "get_data": dict(request.query_params),
        "post_data": {k: v for k, v in form.items() if isinstance(v, str)},
        "script_name": request.url.path,
    }


@router.post("/acs")
async def saml_acs(request: Request):
    """SAML Assertion Consumer Service."""
    cfg = sso_service.load_config()
    if not cfg.enabled or not cfg.is_saml:
        return _fail("SAML is not enabled")

    req = await _saml_request_dict(request)
    auth = _saml_auth(cfg, req)

    relay = req["post_data"].get("RelayState") or ""
    if _take(_login_states, relay) is None:
        # No matching in-flight request. Unsolicited assertions are refused
        # rather than trusted — IdP-initiated login is out of scope.
        return _fail("Unsolicited or expired SAML response")

    auth.process_response()
    errors = auth.get_errors()
    if errors:
        # get_last_error_reason() can contain assertion fragments; keep the
        # browser-visible text generic.
        return _fail("SAML assertion could not be validated")
    if not auth.is_authenticated():
        return _fail("SAML authentication failed")

    name_id = auth.get_nameid()
    if not name_id:
        return _fail("SAML assertion carried no NameID")

    identity = sso_service.saml_to_identity(cfg, name_id, auth.get_attributes() or {})
    try:
        return _complete_login(cfg, identity)
    except SsoError as exc:
        return _fail(str(exc))


@router.get("/metadata", response_class=PlainTextResponse)
def saml_metadata():
    """SP metadata XML for upload into the IdP."""
    cfg = sso_service.load_config()
    if not cfg.base_url:
        raise HTTPException(status_code=400, detail="sso_base_url must be set first")

    try:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="SAML not available (python3-saml not installed)",
        )
    try:
        settings_dict = sso_service.saml_settings(cfg)
    except SsoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    settings = OneLogin_Saml2_Settings(settings_dict, validate_cert=False)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise HTTPException(status_code=500, detail=f"Invalid SP metadata: {', '.join(errors)}")
    return Response(content=metadata, media_type="application/xml")


@router.get("/slo")
async def saml_slo(request: Request):
    """Single Logout. Clears the local refresh cookie either way."""
    cfg = sso_service.load_config()
    if not cfg.enabled or not cfg.is_saml:
        return RedirectResponse("/login", status_code=302)

    req = await _saml_request_dict(request)
    auth = _saml_auth(cfg, req)
    try:
        auth.process_slo()
    except Exception:
        pass
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(key="refresh_token", path="/api/v1/auth/refresh")
    return response


@router.post("/slo")
async def saml_slo_post(request: Request):
    return await saml_slo(request)


# ── One-time code exchange ────────────────────────────────────────────────────


class ExchangeRequest(BaseModel):
    code: str


@router.post("/exchange")
def sso_exchange(body: ExchangeRequest, response: Response):
    """Trade the one-time code from the redirect for the real tokens.

    Keeps JWTs out of the URL bar, browser history, and any Referer header the
    redirect might produce.
    """
    payload = _take(_handoff_codes, body.code)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired login code")

    response.set_cookie(
        key="refresh_token",
        value=payload["refresh_token"],
        httponly=True,
        samesite="strict",
        path="/api/v1/auth/refresh",
        secure=False,  # set ZS_SECURE_COOKIES=1 in production
    )
    return {
        "access_token": payload["access_token"],
        "token_type": "bearer",
        "force_password_change": False,
    }


# ── Admin-only discovery helper ───────────────────────────────────────────────


class DiscoverRequest(BaseModel):
    url: str


@router.post("/discover")
def sso_discover(body: DiscoverRequest, _: AuthUser = Depends(require_admin)):
    """Read an IdP's discovery document so the form can fill itself in.

    Takes either the issuer or the full .well-known URL — IdP consoles publish
    the latter far more often. Nothing is saved; the admin still reviews the
    values and presses Save.
    """
    issuer = sso_service.issuer_from_url(body.url)
    if not issuer:
        raise HTTPException(status_code=400, detail="Enter a discovery or issuer URL")
    if not issuer.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    try:
        doc = sso_service.discover(issuer, force=True)
    except SsoError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    scopes = doc.get("scopes_supported") or []
    return {
        # The issuer the IdP reports wins over the one that was pasted — they
        # differ often enough (trailing paths, tenant aliases) that trusting the
        # document avoids a token-validation failure later.
        "issuer_url": doc.get("issuer") or issuer,
        "authorization_endpoint": doc.get("authorization_endpoint"),
        "token_endpoint": doc.get("token_endpoint"),
        "jwks_uri": doc.get("jwks_uri"),
        "scopes_supported": [s for s in scopes if isinstance(s, str)],
    }


# ── Admin-only connection test ────────────────────────────────────────────────


@router.post("/test")
def sso_test(_: AuthUser = Depends(require_admin)):
    """Validate the current configuration without saving or logging anyone in."""
    cfg = sso_service.load_config()
    if not cfg.provider:
        raise HTTPException(status_code=400, detail="Select a provider first")

    if cfg.is_oidc:
        if not cfg.issuer_url:
            raise HTTPException(status_code=400, detail="Issuer URL is required")
        try:
            doc = sso_service.discover(cfg.issuer_url, force=True)
        except SsoError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return {
            "ok": True,
            "provider": "oidc",
            "issuer": doc.get("issuer"),
            "authorization_endpoint": doc.get("authorization_endpoint"),
            "client_secret_configured": bool(cfg.client_secret),
            "redirect_uri": cfg.redirect_uri(),
        }

    try:
        settings = sso_service.saml_settings(cfg)
    except SsoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ImportError:
        raise HTTPException(status_code=501, detail="SAML not available (python3-saml not installed)")
    idp = settings["idp"]
    return {
        "ok": True,
        "provider": "saml",
        "idp_entity_id": idp.get("entityId"),
        "sso_url": (idp.get("singleSignOnService") or {}).get("url"),
        "sp_entity_id": cfg.entity_id(),
        "acs_url": cfg.acs_url(),
        "signing_configured": bool(cfg.saml_sp_cert and cfg.saml_sp_key),
    }
