"""Traffic simulation endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import AuthUser, require_auth
from db.database import get_session
from db.models import TenantConfig

router = APIRouter(prefix="/api/v1/tenants", tags=["Simulator"])


class SimulateRequest(BaseModel):
    destination: str
    port: int = 443
    protocol: str = "HTTPS"
    nw_application: str | None = None
    app_service_group: str | None = None
    src_ip: str | None = None
    user_name: str | None = None
    dept_name: str | None = None
    group_name: str | None = None
    location_name: str | None = None


@router.post("/{tenant_id}/simulate")
def simulate_traffic(tenant_id: int, req: SimulateRequest, user: AuthUser = Depends(require_auth)):
    if user.role != "admin":
        from api.routers.tenants import check_tenant_access
        check_tenant_access(tenant_id, user)

    with get_session() as s:
        t = s.get(TenantConfig, tenant_id)
        if not t or not t.is_active:
            raise HTTPException(status_code=404, detail="Tenant not found")

    from services.traffic_sim_service import simulate
    result = simulate(
        tenant_id, req.destination, req.port, req.protocol,
        req.nw_application, req.app_service_group,
        req.src_ip, req.user_name, req.dept_name, req.group_name, req.location_name,
    )
    return asdict(result)


@router.get("/{tenant_id}/simulate/applications")
def list_sim_applications(tenant_id: int, user: AuthUser = Depends(require_auth)):
    """Return unique nw_application IDs referenced by this tenant's firewall rules."""
    if user.role != "admin":
        from api.routers.tenants import check_tenant_access
        check_tenant_access(tenant_id, user)

    from db.models import ZIAResource
    with get_session() as s:
        rules = s.query(ZIAResource).filter_by(
            tenant_id=tenant_id, resource_type="firewall_rule", is_deleted=False
        ).all()

    apps: set[str] = set()
    for r in rules:
        for app in (r.raw_config or {}).get("nw_applications", []):
            if app:
                apps.add(str(app))
    return sorted(apps)


def _check_access(tenant_id: int, user: AuthUser):
    if user.role != "admin":
        from api.routers.tenants import check_tenant_access
        check_tenant_access(tenant_id, user)


def _unique_names(tenant_id: int, resource_type: str, name_field: str = "name") -> list[str]:
    from db.models import ZIAResource
    with get_session() as s:
        rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type=resource_type, is_deleted=False).all()
    names: set[str] = set()
    for r in rows:
        v = (r.raw_config or {}).get(name_field)
        if v:
            names.add(str(v))
    return sorted(names)


@router.get("/{tenant_id}/simulate/users")
def list_sim_users(tenant_id: int, user: AuthUser = Depends(require_auth)):
    _check_access(tenant_id, user)
    return _unique_names(tenant_id, "user", "name")


@router.get("/{tenant_id}/simulate/departments")
def list_sim_departments(tenant_id: int, user: AuthUser = Depends(require_auth)):
    _check_access(tenant_id, user)
    return _unique_names(tenant_id, "department", "name")


@router.get("/{tenant_id}/simulate/groups")
def list_sim_groups(tenant_id: int, user: AuthUser = Depends(require_auth)):
    _check_access(tenant_id, user)
    return _unique_names(tenant_id, "group", "name")


@router.get("/{tenant_id}/simulate/locations")
def list_sim_locations(tenant_id: int, user: AuthUser = Depends(require_auth)):
    _check_access(tenant_id, user)
    return _unique_names(tenant_id, "location", "name")


@router.get("/{tenant_id}/simulate/app-service-groups")
def list_sim_app_service_groups(tenant_id: int, user: AuthUser = Depends(require_auth)):
    """Return unique app_service_group names referenced by this tenant's firewall rules."""
    if user.role != "admin":
        from api.routers.tenants import check_tenant_access
        check_tenant_access(tenant_id, user)

    from db.models import ZIAResource
    with get_session() as s:
        rules = s.query(ZIAResource).filter_by(
            tenant_id=tenant_id, resource_type="firewall_rule", is_deleted=False
        ).all()

    groups: set[str] = set()
    for r in rules:
        for grp in (r.raw_config or {}).get("app_service_groups", []):
            name = grp.get("name") if isinstance(grp, dict) else str(grp)
            if name:
                groups.add(name)
    return sorted(groups)
