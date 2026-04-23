"""Tenant configuration management with encrypted secret storage.

Secrets (client_secret) are encrypted with Fernet symmetric encryption before
being stored in the database.

Key resolution order:
  1. ZSCALER_SECRET_KEY environment variable (explicit override)
  2. Key file at ~/.config/zs-config/secret.key (auto-created on first run)

On first launch the key is generated automatically — no manual setup required.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.fernet import Fernet, InvalidToken

from db.database import get_session
from db.models import TenantConfig

_KEY_FILE = Path.home() / ".config" / "zs-config" / "secret.key"
_KEY_FILE_LEGACY = Path.home() / ".config" / "z-config" / "secret.key"
_KEY_FILE_LEGACY2 = Path.home() / ".config" / "zscaler-cli" / "secret.key"


def _chmod_600(path: Path) -> None:
    """Set file permissions to 600 on platforms that support it."""
    if sys.platform != "win32":
        path.chmod(0o600)


def _get_fernet() -> Fernet:
    # 1. Explicit env var override
    key = os.environ.get("ZSCALER_SECRET_KEY")
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)

    # 2. Key stored alongside the DB file (persistent in Docker volume)
    if db_path_env := os.environ.get("ZSCALER_DB_PATH"):
        _db_sibling_key = Path(db_path_env).parent / "secret.key"
        if _db_sibling_key.exists():
            return Fernet(_db_sibling_key.read_text().strip().encode())

    # 3. Migrate from legacy key paths (zscaler-cli → z-config → zs-config)
    for _legacy in (_KEY_FILE_LEGACY, _KEY_FILE_LEGACY2):
        if not _KEY_FILE.exists() and _legacy.exists():
            _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _KEY_FILE.write_text(_legacy.read_text())
            _chmod_600(_KEY_FILE)
            break

    # 4. Persisted key file
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
        return Fernet(key.encode())

    # 5. First run — auto-generate and save
    key = Fernet.generate_key().decode()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(key)
    _chmod_600(_KEY_FILE)
    return Fernet(key.encode())


def generate_key() -> str:
    """Generate a new Fernet encryption key and persist it to the key file."""
    key = Fernet.generate_key().decode()
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(key)
    _chmod_600(_KEY_FILE)
    return key


def encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise ValueError(
            "Failed to decrypt client secret — ZSCALER_SECRET_KEY may be wrong or the record is corrupted."
        ) from e


def fetch_org_info(
    zidentity_base_url: str,
    client_id: str,
    client_secret: str,
    oneapi_base_url: str = "https://api.zsapi.net",
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """Fetch orgInformation and subscriptions from the ZIA API.

    Returns (org_info, subscriptions, error_message).
    On success, error_message is None. On failure, org_info and/or subscriptions may be None.
    """
    try:
        token_resp = requests.post(
            f"{zidentity_base_url.rstrip('/')}/oauth2/v1/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": "https://api.zscaler.com",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]
    except Exception as e:
        return None, None, f"Token error: {e}"

    headers = {"Authorization": f"Bearer {token}"}
    base = oneapi_base_url.rstrip("/")

    try:
        org_resp = requests.get(f"{base}/zia/api/v1/orgInformation", headers=headers, timeout=15)
        org_resp.raise_for_status()
        org_info = org_resp.json()
    except Exception as e:
        return None, None, f"orgInformation error: {e}"

    subscriptions = None
    try:
        sub_resp = requests.get(f"{base}/zia/api/v1/subscriptions", headers=headers, timeout=15)
        sub_resp.raise_for_status()
        subscriptions = sub_resp.json()
    except Exception:
        pass  # subscriptions failure is non-fatal

    return org_info, subscriptions, None


def add_tenant(
    name: str,
    zidentity_base_url: str,
    client_id: str,
    client_secret: str,
    oneapi_base_url: str = "https://api.zsapi.net",
    govcloud: bool = False,
    zpa_customer_id: Optional[str] = None,
    zpa_tenant_cloud: Optional[str] = None,
    zia_tenant_id: Optional[str] = None,
    zia_cloud: Optional[str] = None,
    zia_subscriptions: Optional[Any] = None,
    notes: Optional[str] = None,
) -> TenantConfig:
    """Add a new tenant configuration to the database."""
    with get_session() as session:
        tenant = session.query(TenantConfig).filter_by(name=name).first()
        if tenant and tenant.is_active:
            raise ValueError(f"Tenant '{name}' already exists.")
        if tenant:
            # Reactivate a previously soft-deleted tenant with fresh credentials.
            tenant.zidentity_base_url = zidentity_base_url.rstrip("/")
            tenant.oneapi_base_url = oneapi_base_url.rstrip("/")
            tenant.client_id = client_id
            tenant.client_secret_enc = encrypt_secret(client_secret)
            tenant.govcloud = govcloud
            tenant.zpa_customer_id = zpa_customer_id or None
            tenant.zpa_tenant_cloud = zpa_tenant_cloud or None
            tenant.zia_tenant_id = zia_tenant_id or None
            tenant.zia_cloud = zia_cloud or None
            tenant.zia_subscriptions = zia_subscriptions or None
            tenant.notes = notes
            tenant.last_validation_error = None
            tenant.is_active = True
        else:
            tenant = TenantConfig(
                name=name,
                zidentity_base_url=zidentity_base_url.rstrip("/"),
                oneapi_base_url=oneapi_base_url.rstrip("/"),
                client_id=client_id,
                client_secret_enc=encrypt_secret(client_secret),
                govcloud=govcloud,
                zpa_customer_id=zpa_customer_id or None,
                zpa_tenant_cloud=zpa_tenant_cloud or None,
                zia_tenant_id=zia_tenant_id or None,
                zia_cloud=zia_cloud or None,
                zia_subscriptions=zia_subscriptions or None,
                notes=notes,
            )
            session.add(tenant)
        session.flush()
        session.refresh(tenant)
        return tenant


def get_tenant(name: str) -> Optional[TenantConfig]:
    """Retrieve an active tenant by name."""
    with get_session() as session:
        return session.query(TenantConfig).filter_by(name=name, is_active=True).first()


def list_tenants() -> List[TenantConfig]:
    """Return all active tenants."""
    with get_session() as session:
        return session.query(TenantConfig).filter_by(is_active=True).order_by(TenantConfig.name).all()


def update_tenant(
    name: str,
    zidentity_base_url: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    oneapi_base_url: Optional[str] = None,
    govcloud: Optional[bool] = None,
    zpa_customer_id: Optional[str] = None,
    zpa_tenant_cloud: Optional[str] = None,
    zia_tenant_id: Optional[str] = None,
    zia_cloud: Optional[str] = None,
    zia_subscriptions: Optional[Any] = None,
    notes: Optional[str] = None,
) -> Optional[TenantConfig]:
    """Update fields on an existing tenant. Only provided fields are changed."""
    with get_session() as session:
        tenant = session.query(TenantConfig).filter_by(name=name, is_active=True).first()
        if not tenant:
            return None
        if zidentity_base_url is not None:
            tenant.zidentity_base_url = zidentity_base_url.rstrip("/")
        if oneapi_base_url is not None:
            tenant.oneapi_base_url = oneapi_base_url.rstrip("/")
        if govcloud is not None:
            tenant.govcloud = govcloud
        if client_id is not None:
            tenant.client_id = client_id
        if client_secret is not None:
            tenant.client_secret_enc = encrypt_secret(client_secret)
        if zpa_customer_id is not None:
            tenant.zpa_customer_id = zpa_customer_id
        if zpa_tenant_cloud is not None:
            tenant.zpa_tenant_cloud = zpa_tenant_cloud
        if zia_tenant_id is not None:
            tenant.zia_tenant_id = zia_tenant_id
        if zia_cloud is not None:
            tenant.zia_cloud = zia_cloud
        if zia_subscriptions is not None:
            tenant.zia_subscriptions = zia_subscriptions
        if notes is not None:
            tenant.notes = notes
        session.flush()
        session.refresh(tenant)
        return tenant


def get_tenants_needing_org_backfill() -> List[TenantConfig]:
    """Return active tenants that are missing org info (zia_tenant_id IS NULL)."""
    with get_session() as session:
        return (
            session.query(TenantConfig)
            .filter_by(is_active=True)
            .filter(TenantConfig.zia_tenant_id.is_(None))
            .all()
        )


def backfill_org_info_for_tenant(tenant: TenantConfig) -> Tuple[bool, Optional[str]]:
    """Fetch and store orgInformation + subscriptions for a single tenant.

    Returns (success, error_message). error_message is None on success.
    """
    try:
        secret = decrypt_secret(tenant.client_secret_enc)
        org_info, subscriptions, err = fetch_org_info(
            tenant.zidentity_base_url, tenant.client_id, secret, tenant.oneapi_base_url
        )
        if err or not org_info:
            return False, err or "empty response"
        pdomain_raw = org_info.get("pdomain") or ""
        update_tenant(
            name=tenant.name,
            zpa_customer_id=str(_zpa_raw) if (_zpa_raw := org_info.get("zpaTenantId")) else None,
            zpa_tenant_cloud=org_info.get("zpaTenantCloud") or None,
            zia_tenant_id=pdomain_raw.split(".")[0] or None,
            zia_cloud=org_info.get("cloudName") or None,
            zia_subscriptions=subscriptions,
        )
        return True, None
    except Exception as e:
        return False, str(e)


def set_tenant_metadata(
    name: str,
    zpa_customer_id: Optional[str],
    zpa_tenant_cloud: Optional[str],
    zia_tenant_id: Optional[str],
    zia_cloud: Optional[str],
) -> Optional[TenantConfig]:
    """Explicitly overwrite org metadata fields. Pass None to clear a field.

    Unlike update_tenant (which skips None args), this always writes every field,
    allowing manual correction when the API returns incorrect auto-fetched values.
    """
    with get_session() as session:
        tenant = session.query(TenantConfig).filter_by(name=name, is_active=True).first()
        if not tenant:
            return None
        tenant.zpa_customer_id = zpa_customer_id
        tenant.zpa_tenant_cloud = zpa_tenant_cloud
        tenant.zia_tenant_id = zia_tenant_id
        tenant.zia_cloud = zia_cloud
        session.flush()
        session.refresh(tenant)
        return tenant


def deactivate_tenant(name: str) -> bool:
    """Soft-delete a tenant (sets is_active=False)."""
    with get_session() as session:
        tenant = session.query(TenantConfig).filter_by(name=name, is_active=True).first()
        if not tenant:
            return False
        tenant.is_active = False
        return True
