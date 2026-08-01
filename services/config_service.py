"""Tenant configuration management with encrypted secret storage.

Secrets (client_secret) are encrypted before being stored in the database.
The active algorithm is read from app_settings; key material from env or key file.
"""

from typing import Any, Dict, List, Optional, Tuple

import requests

from db.database import get_session, get_setting
from db.models import TenantConfig
from lib.auth import DEFAULT_GOV_TIER
from lib.crypto import CryptoAlgorithm, decrypt, encrypt, load_key


def _active_algorithm() -> str:
    return get_setting("encryption_algorithm") or CryptoAlgorithm.FERNET


def encrypt_secret(value: str) -> str:
    algo = _active_algorithm()
    return encrypt(value, algo, load_key(algo))


def decrypt_secret(value: str) -> str:
    algo = _active_algorithm()
    try:
        return decrypt(value, algo, load_key(algo))
    except ValueError as e:
        raise ValueError(
            "Failed to decrypt client secret — key may be wrong or the record is corrupted."
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
    gov_tier: Optional[str] = None,
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
            tenant.gov_cloud_tier = (gov_tier or DEFAULT_GOV_TIER) if govcloud else None
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
                gov_cloud_tier=(gov_tier or DEFAULT_GOV_TIER) if govcloud else None,
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
    gov_tier: Optional[str] = None,
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
            # Tier only means anything for GovCloud tenants; clear it otherwise.
            tenant.gov_cloud_tier = (gov_tier or tenant.gov_cloud_tier or DEFAULT_GOV_TIER) if govcloud else None
        elif gov_tier is not None and tenant.govcloud:
            tenant.gov_cloud_tier = gov_tier
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
