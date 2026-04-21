from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from api.dependencies import require_admin, AuthUser

router = APIRouter(prefix="/api/v1/tenants", tags=["Tenants"])


def _serialize(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "zidentity_base_url": t.zidentity_base_url,
        "oneapi_base_url": t.oneapi_base_url,
        "client_id": t.client_id,
        "has_credentials": bool(t.client_secret_enc),
        "govcloud": t.govcloud,
        "zpa_customer_id": t.zpa_customer_id,
        "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


class TenantCreate(BaseModel):
    name: str
    zidentity_base_url: str
    client_id: str
    client_secret: str
    oneapi_base_url: str = "https://api.zsapi.net"
    govcloud: bool = False
    zpa_customer_id: Optional[str] = None
    notes: Optional[str] = None


class TenantUpdate(BaseModel):
    zidentity_base_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    oneapi_base_url: Optional[str] = None
    govcloud: Optional[bool] = None
    zpa_customer_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_tenants(user: AuthUser = Depends(require_admin)):
    from services.config_service import list_tenants as _list
    return [_serialize(t) for t in _list()]


@router.get("/{tenant_id}")
def get_tenant(tenant_id: int, user: AuthUser = Depends(require_admin)):
    from db.database import get_session
    from db.models import TenantConfig
    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _serialize(t)


@router.post("", status_code=201)
def create_tenant(body: TenantCreate, user: AuthUser = Depends(require_admin)):
    from services.config_service import add_tenant
    try:
        t = add_tenant(
            name=body.name,
            zidentity_base_url=body.zidentity_base_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
            oneapi_base_url=body.oneapi_base_url,
            govcloud=body.govcloud,
            zpa_customer_id=body.zpa_customer_id,
            notes=body.notes,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _serialize(t)


@router.put("/{tenant_id}")
def update_tenant(tenant_id: int, body: TenantUpdate, user: AuthUser = Depends(require_admin)):
    from db.database import get_session
    from db.models import TenantConfig
    from services.config_service import update_tenant as _update
    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found")
        name = t.name
    updated = _update(
        name=name,
        zidentity_base_url=body.zidentity_base_url,
        client_id=body.client_id,
        client_secret=body.client_secret,
        oneapi_base_url=body.oneapi_base_url,
        govcloud=body.govcloud,
        zpa_customer_id=body.zpa_customer_id,
        notes=body.notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _serialize(updated)


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: int, user: AuthUser = Depends(require_admin)):
    from db.database import get_session
    from db.models import TenantConfig
    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found")
        t.is_active = False
