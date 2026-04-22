"""ZIA API router."""

from fastapi import APIRouter, HTTPException, Depends

from api.schemas.zia import UrlLookupRequest
from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zia_service import ZIAService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
    )
    client = ZIAClient(auth, tenant.oneapi_base_url)
    return ZIAService(client, tenant_id=tenant.id)


# ------------------------------------------------------------------
# Activation
# ------------------------------------------------------------------

@router.get("/{tenant}/activation/status")
def get_activation_status(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the current ZIA activation status."""
    return _get_service(tenant, user).get_activation_status()


@router.post("/{tenant}/activation/activate")
def activate(tenant: str, user: AuthUser = Depends(require_admin)):
    """Activate all pending ZIA configuration changes."""
    try:
        return _get_service(tenant, user).activate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Categories
# ------------------------------------------------------------------

@router.get("/{tenant}/url-categories")
def list_url_categories(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all URL categories (lite)."""
    return _get_service(tenant, user).list_url_categories()


@router.post("/{tenant}/url-lookup")
def url_lookup(tenant: str, req: UrlLookupRequest, user: AuthUser = Depends(require_auth)):
    """Look up category classifications for a list of URLs."""
    try:
        return _get_service(tenant, user).url_lookup(req.urls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Filtering Rules
# ------------------------------------------------------------------

@router.get("/{tenant}/url-filtering-rules")
def list_url_filtering_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all URL filtering rules."""
    return _get_service(tenant, user).list_url_filtering_rules()


# ------------------------------------------------------------------
# Users / Locations / Departments / Groups
# ------------------------------------------------------------------

@router.get("/{tenant}/users")
def list_users(tenant: str, name: str = None, user: AuthUser = Depends(require_auth)):
    """List ZIA users, optionally filtered by name."""
    return _get_service(tenant, user).list_users(name=name)


@router.get("/{tenant}/locations")
def list_locations(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA locations (lite)."""
    return _get_service(tenant, user).list_locations()


@router.get("/{tenant}/departments")
def list_departments(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA departments."""
    return _get_service(tenant, user).list_departments()


@router.get("/{tenant}/groups")
def list_groups(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA groups."""
    return _get_service(tenant, user).list_groups()


# ------------------------------------------------------------------
# Allow / Deny Lists
# ------------------------------------------------------------------

@router.get("/{tenant}/allowlist")
def get_allowlist(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the ZIA allowlist (whitelist URLs)."""
    return _get_service(tenant, user).get_allowlist()


@router.get("/{tenant}/denylist")
def get_denylist(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the ZIA denylist (blacklist URLs)."""
    return _get_service(tenant, user).get_denylist()
