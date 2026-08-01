"""System info and admin settings router."""

import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cli.banner import VERSION
from db.database import get_setting, set_setting
from api.dependencies import require_admin, AuthUser

router = APIRouter()


# ── System info ───────────────────────────────────────────────────────────────

@router.get("/api/v1/system/info", tags=["System"])
def system_info():
    try:
        idle_minutes = int(get_setting("idle_timeout_minutes") or "15")
    except Exception:
        idle_minutes = 15
    return {
        "version": VERSION,
        "container_mode": os.environ.get("ZS_CONTAINER_MODE", "0") == "1",
        "db_path": os.environ.get("ZSCALER_DB_PATH", "~/.local/share/zs-config/zscaler.db"),
        "plugin_dir": os.environ.get("ZS_PLUGIN_DIR", None),
        "idle_timeout_minutes": idle_minutes,
    }


# ── Settings ──────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "access_token_ttl":           "300",
    "refresh_token_ttl":          "3600",
    "idle_timeout_minutes":       "15",
    "max_login_attempts":         "0",
    "audit_log_retention_days":   "90",
    # ── Identity provider (SSO) ──
    "idp_enabled":                "false",
    "idp_provider":               "",
    "idp_auto_provision":         "true",
    "idp_default_role":           "user",
    "idp_group_claim":            "groups",
    "idp_issuer_url":             "",
    "idp_client_id":              "",
    "idp_client_secret":          "",   # encrypted at rest, never returned
    "idp_scopes":                 "openid profile email",
    "saml_idp_metadata_xml":      "",
    "saml_idp_metadata_url":      "",
    "saml_sp_entity_id":          "",
    "saml_sp_cert":               "",
    "saml_sp_key":                "",   # encrypted at rest, never returned
    "sso_base_url":               "",
    "ssl_mode":                   "none",
    "ssl_domain":                 "",
    "encryption_algorithm":       "fernet",
    "fips_mode":                  "false",
    "key_rotation_interval_days": "0",
    "key_last_rotated_at":        "",
    # Update notifications
    "update_notify_enabled":      "false",
    "update_notify_email":        "",
    "smtp_host":                  "",
    "smtp_port":                  "587",
    "smtp_username":              "",
    "smtp_password":              "",
    "smtp_from_address":          "",
    "smtp_tls":                   "true",
}

_KEYS = set(_DEFAULTS.keys())


def _coerce(raw: dict) -> dict:
    try:
        smtp_port = int(raw["smtp_port"])
    except (ValueError, KeyError):
        smtp_port = 587
    return {
        "access_token_ttl":           int(raw["access_token_ttl"]),
        "refresh_token_ttl":          int(raw["refresh_token_ttl"]),
        "idle_timeout_minutes":       int(raw["idle_timeout_minutes"]),
        "max_login_attempts":         int(raw["max_login_attempts"]),
        "audit_log_retention_days":   int(raw["audit_log_retention_days"]),
        "idp_enabled":                raw["idp_enabled"] == "true",
        "idp_provider":               raw["idp_provider"],
        "idp_auto_provision":         raw["idp_auto_provision"] == "true",
        "idp_default_role":           raw["idp_default_role"],
        "idp_group_claim":            raw["idp_group_claim"],
        "idp_issuer_url":             raw["idp_issuer_url"],
        "idp_client_id":              raw["idp_client_id"],
        # Secrets are write-only: the UI needs to know whether one is on file,
        # never what it is.
        "idp_client_secret_set":      bool(raw["idp_client_secret"]),
        "idp_scopes":                 raw["idp_scopes"],
        "saml_idp_metadata_xml":      raw["saml_idp_metadata_xml"],
        "saml_idp_metadata_url":      raw["saml_idp_metadata_url"],
        "saml_sp_entity_id":          raw["saml_sp_entity_id"],
        "saml_sp_cert":               raw["saml_sp_cert"],
        "saml_sp_key_set":            bool(raw["saml_sp_key"]),
        "sso_base_url":               raw["sso_base_url"],
        "ssl_mode":                   raw["ssl_mode"],
        "ssl_domain":                 raw["ssl_domain"],
        "encryption_algorithm":       raw["encryption_algorithm"],
        "fips_mode":                  raw["fips_mode"] == "true",
        "key_rotation_interval_days": int(raw["key_rotation_interval_days"]),
        "key_last_rotated_at":        raw["key_last_rotated_at"] or None,
        "update_notify_enabled":      raw.get("update_notify_enabled", "false") == "true",
        "update_notify_email":        raw.get("update_notify_email", ""),
        "smtp_host":                  raw.get("smtp_host", ""),
        "smtp_port":                  smtp_port,
        "smtp_username":              raw.get("smtp_username", ""),
        "smtp_password":              raw.get("smtp_password", ""),
        "smtp_from_address":          raw.get("smtp_from_address", ""),
        "smtp_tls":                   raw.get("smtp_tls", "true") == "true",
    }


def _load() -> dict:
    return {k: (get_setting(k) or v) for k, v in _DEFAULTS.items()}


class SettingsPatch(BaseModel):
    access_token_ttl:           Optional[int] = None
    refresh_token_ttl:          Optional[int] = None
    idle_timeout_minutes:       Optional[int] = None
    max_login_attempts:         Optional[int] = None
    audit_log_retention_days:   Optional[int] = None
    idp_enabled:                Optional[bool] = None
    idp_provider:               Optional[str] = None
    idp_auto_provision:         Optional[bool] = None
    idp_default_role:           Optional[str] = None
    idp_group_claim:            Optional[str] = None
    idp_issuer_url:             Optional[str] = None
    idp_client_id:              Optional[str] = None
    idp_client_secret:          Optional[str] = None
    idp_scopes:                 Optional[str] = None
    saml_idp_metadata_xml:      Optional[str] = None
    saml_idp_metadata_url:      Optional[str] = None
    saml_sp_entity_id:          Optional[str] = None
    saml_sp_cert:               Optional[str] = None
    saml_sp_key:                Optional[str] = None
    sso_base_url:               Optional[str] = None
    ssl_mode:                   Optional[str] = None
    ssl_domain:                 Optional[str] = None
    encryption_algorithm:       Optional[str] = None
    fips_mode:                  Optional[bool] = None
    key_rotation_interval_days: Optional[int] = None
    update_notify_enabled:      Optional[bool] = None
    update_notify_email:        Optional[str] = None
    smtp_host:                  Optional[str] = None
    smtp_port:                  Optional[int] = None
    smtp_username:              Optional[str] = None
    smtp_password:              Optional[str] = None
    smtp_from_address:          Optional[str] = None
    smtp_tls:                   Optional[bool] = None


@router.get("/api/v1/system/settings", tags=["System"])
def get_settings(_: AuthUser = Depends(require_admin)):
    return _coerce(_load())


# Settings whose value is encrypted before it hits the DB and is never read back
# out through the API.
_SECRET_KEYS = {"idp_client_secret", "saml_sp_key"}


@router.patch("/api/v1/system/settings", tags=["System"])
def patch_settings(body: SettingsPatch, _: AuthUser = Depends(require_admin)):
    from fastapi import HTTPException
    from services.config_service import encrypt_secret

    patch = body.model_dump(exclude_none=True)

    provider = patch.get("idp_provider")
    if provider is not None and provider not in ("", "oidc", "saml"):
        raise HTTPException(status_code=400, detail="idp_provider must be 'oidc' or 'saml'")
    role = patch.get("idp_default_role")
    if role is not None and role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="idp_default_role must be 'admin' or 'user'")

    for k, v in patch.items():
        if k not in _KEYS:
            continue
        if k in _SECRET_KEYS:
            # An empty string means "leave what is on file alone" — the UI sends
            # a blank box when the admin did not retype the secret. Clearing is
            # done with the explicit sentinel below.
            if v == "":
                continue
            set_setting(k, "" if v == "__CLEAR__" else encrypt_secret(str(v)))
            continue
        set_setting(k, str(v).lower() if isinstance(v, bool) else str(v))
    return _coerce(_load())


@router.post("/api/v1/system/update-notify/test", tags=["System"])
def test_update_notify(_: AuthUser = Depends(require_admin)):
    from services.update_notify_service import send_test_email
    from fastapi import HTTPException

    raw = _load()
    to_addr = raw.get("update_notify_email", "")
    host = raw.get("smtp_host", "")
    if not to_addr or not host:
        raise HTTPException(status_code=400, detail="update_notify_email and smtp_host must be configured first.")
    try:
        port = int(raw.get("smtp_port", "587"))
    except ValueError:
        port = 587
    try:
        send_test_email(
            host=host,
            port=port,
            username=raw.get("smtp_username", ""),
            password=raw.get("smtp_password", ""),
            from_addr=raw.get("smtp_from_address", ""),
            to_addr=to_addr,
            use_tls=raw.get("smtp_tls", "true") == "true",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"sent": True}
