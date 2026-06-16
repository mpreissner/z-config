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
    result = simulate(tenant_id, req.destination, req.port, req.protocol)
    return asdict(result)
