"""ZPA API router.

Each endpoint resolves a tenant, builds the ZPA client, and delegates to
the ZPAService layer — the same layer used by the CLI and headless scripts.
"""

from fastapi import APIRouter, HTTPException, Depends

from api.schemas.zpa import CertificateRotateRequest
from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zpa_service import ZPAService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    if not tenant.zpa_customer_id:
        raise HTTPException(status_code=400, detail=f"Tenant '{tenant_name}' has no ZPA Customer ID")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
    )
    client = ZPAClient(auth, tenant.zpa_customer_id, tenant.oneapi_base_url)
    return ZPAService(client, tenant_id=tenant.id)


# ------------------------------------------------------------------
# Certificates
# ------------------------------------------------------------------

@router.get("/{tenant}/certificates")
def list_certificates(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all certificates for a ZPA tenant."""
    return _get_service(tenant, user).list_certificates()


@router.delete("/{tenant}/certificates/{cert_id}")
def delete_certificate(tenant: str, cert_id: str, user: AuthUser = Depends(require_admin)):
    """Delete a certificate by ID."""
    success = _get_service(tenant, user).delete_certificate(cert_id)
    return {"deleted": success}


@router.post("/{tenant}/certificates/rotate")
def rotate_certificate(tenant: str, req: CertificateRotateRequest, user: AuthUser = Depends(require_admin)):
    """Certificate rotation is not supported via the web API. Use the CLI."""
    raise HTTPException(
        status_code=400,
        detail="Certificate rotation is not supported via the web API. Use the CLI (`zs-config`).",
    )


# ------------------------------------------------------------------
# Applications
# ------------------------------------------------------------------

@router.get("/{tenant}/applications")
def list_applications(tenant: str, app_type: str = "BROWSER_ACCESS", user: AuthUser = Depends(require_auth)):
    """List application segments, optionally filtered by type."""
    return _get_service(tenant, user).list_applications(app_type)


# ------------------------------------------------------------------
# PRA Portals
# ------------------------------------------------------------------

@router.get("/{tenant}/pra-portals")
def list_pra_portals(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all PRA portals."""
    return _get_service(tenant, user).list_pra_portals()
