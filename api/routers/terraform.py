"""Terraform export endpoints — generate .tf files from imported ZIA / ZPA config."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.auth import AuthUser, require_auth
from db.database import get_session
from db.models import TenantConfig

router = APIRouter(prefix="/api/v1/tenants", tags=["Terraform"])


def _check_access(tenant_id: int, user: AuthUser) -> str:
    """Verify access and return the tenant name."""
    with get_session() as session:
        t = session.get(TenantConfig, tenant_id)
        if not t or not t.is_active:
            raise HTTPException(status_code=404, detail="Tenant not found")
        name = t.name
    if user.role != "admin":
        from api.routers.tenants import check_tenant_access
        check_tenant_access(tenant_id, user)
    return name


@router.get("/{tenant_id}/terraform/zia")
def export_terraform_zia(tenant_id: int, user: AuthUser = Depends(require_auth)):
    from services.terraform_export_service import generate_zia
    tenant_name = _check_access(tenant_id, user)
    hcl = generate_zia(tenant_id)
    safe_name = tenant_name.replace(" ", "_").lower()
    return Response(
        content=hcl,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_zia.tf"'},
    )


@router.get("/{tenant_id}/terraform/zpa")
def export_terraform_zpa(tenant_id: int, user: AuthUser = Depends(require_auth)):
    from services.terraform_export_service import generate_zpa
    tenant_name = _check_access(tenant_id, user)
    hcl = generate_zpa(tenant_id)
    safe_name = tenant_name.replace(" ", "_").lower()
    return Response(
        content=hcl,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_zpa.tf"'},
    )
