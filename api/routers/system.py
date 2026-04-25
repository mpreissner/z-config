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
    "access_token_ttl":        "300",
    "refresh_token_ttl":       "3600",
    "idle_timeout_minutes":    "15",
    "max_login_attempts":      "0",
    "audit_log_retention_days": "90",
    "idp_enabled":             "false",
    "idp_provider":            "",
    "idp_issuer_url":          "",
    "idp_client_id":           "",
    "ssl_mode":                "none",
    "ssl_domain":              "",
}

_KEYS = set(_DEFAULTS.keys())


def _coerce(raw: dict) -> dict:
    return {
        "access_token_ttl":        int(raw["access_token_ttl"]),
        "refresh_token_ttl":       int(raw["refresh_token_ttl"]),
        "idle_timeout_minutes":    int(raw["idle_timeout_minutes"]),
        "max_login_attempts":      int(raw["max_login_attempts"]),
        "audit_log_retention_days": int(raw["audit_log_retention_days"]),
        "idp_enabled":             raw["idp_enabled"] == "true",
        "idp_provider":            raw["idp_provider"],
        "idp_issuer_url":          raw["idp_issuer_url"],
        "idp_client_id":           raw["idp_client_id"],
        "ssl_mode":                raw["ssl_mode"],
        "ssl_domain":              raw["ssl_domain"],
    }


def _load() -> dict:
    return {k: (get_setting(k) or v) for k, v in _DEFAULTS.items()}


class SettingsPatch(BaseModel):
    access_token_ttl:        Optional[int] = None
    refresh_token_ttl:       Optional[int] = None
    idle_timeout_minutes:    Optional[int] = None
    max_login_attempts:      Optional[int] = None
    audit_log_retention_days: Optional[int] = None
    idp_enabled:             Optional[bool] = None
    idp_provider:            Optional[str] = None
    idp_issuer_url:          Optional[str] = None
    idp_client_id:           Optional[str] = None
    ssl_mode:                Optional[str] = None
    ssl_domain:              Optional[str] = None


@router.get("/api/v1/system/settings", tags=["System"])
def get_settings(_: AuthUser = Depends(require_admin)):
    return _coerce(_load())


@router.patch("/api/v1/system/settings", tags=["System"])
def patch_settings(body: SettingsPatch, _: AuthUser = Depends(require_admin)):
    for k, v in body.model_dump(exclude_none=True).items():
        if k in _KEYS:
            set_setting(k, str(v).lower() if isinstance(v, bool) else str(v))
    return _coerce(_load())
