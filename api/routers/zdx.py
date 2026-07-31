"""ZDX API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_auth, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zdx_client import ZDXClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zdx_service import ZDXService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
        govcloud=bool(tenant.govcloud),
        gov_tier=tenant.gov_cloud_tier,
    )
    client = ZDXClient(auth)
    return ZDXService(client, tenant_id=tenant.id)


@router.get("/{tenant}/devices")
def list_devices(
    tenant: str,
    query: Optional[str] = None,
    hours: int = 2,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_service(tenant, user)
    return svc.search_devices(query=query, hours=hours)


@router.get("/{tenant}/devices/{device_id}")
def get_device(
    tenant: str,
    device_id: str,
    hours: int = 2,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_service(tenant, user)
    return svc.get_device_summary(device_id=device_id, hours=hours)


@router.get("/{tenant}/users")
def lookup_users(
    tenant: str,
    query: Optional[str] = None,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_service(tenant, user)
    return svc.lookup_user(query=query or "")
