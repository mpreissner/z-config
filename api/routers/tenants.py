from datetime import datetime
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
        "zia_tenant_id": t.zia_tenant_id,
        "zia_cloud": t.zia_cloud,
        "last_validation_error": t.last_validation_error,
        "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _write_audit(events: list) -> None:
    from db.database import get_session
    from db.models import AuditLog
    if not events:
        return
    with get_session() as session:
        for ev in events:
            session.add(AuditLog(**ev))


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
    from services.config_service import add_tenant, fetch_org_info
    from db.database import get_session
    from db.models import TenantConfig

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

    tenant_id = t.id
    audit_events = []

    # Validate credentials and pull org metadata
    org_info, subscriptions, err = fetch_org_info(
        zidentity_base_url=body.zidentity_base_url,
        client_id=body.client_id,
        client_secret=body.client_secret,
        oneapi_base_url=body.oneapi_base_url,
    )

    with get_session() as session:
        tenant = session.query(TenantConfig).filter_by(id=tenant_id).first()
        if err:
            tenant.last_validation_error = f"Validation failed; check API credentials. ({err})"
            audit_events.append(dict(
                tenant_id=tenant_id,
                product="ZIA",
                operation="validate_credentials",
                action="CREATE",
                status="FAILURE",
                resource_type="tenant",
                resource_name=body.name,
                error_message=err,
                timestamp=datetime.utcnow(),
            ))
        else:
            tenant.last_validation_error = None
            if org_info:
                tenant.zia_tenant_id = str(org_info.get("pdomain", "")) or None
                tenant.zia_cloud = org_info.get("cloudName") or None
                tenant.zpa_tenant_cloud = org_info.get("zpaTenantCloud") or None
            if subscriptions:
                tenant.zia_subscriptions = subscriptions
            audit_events.append(dict(
                tenant_id=tenant_id,
                product="ZIA",
                operation="validate_credentials",
                action="CREATE",
                status="SUCCESS",
                resource_type="tenant",
                resource_name=body.name,
                timestamp=datetime.utcnow(),
            ))
        session.flush()
        session.refresh(tenant)
        result = _serialize(tenant)

    _write_audit(audit_events)
    return result


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

    _write_audit([dict(
        tenant_id=tenant_id,
        product=None,
        operation="update_tenant",
        action="UPDATE",
        status="SUCCESS",
        resource_type="tenant",
        resource_name=name,
        timestamp=datetime.utcnow(),
    )])
    return _serialize(updated)


@router.delete("/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: int, user: AuthUser = Depends(require_admin)):
    from db.database import get_session
    from db.models import TenantConfig
    name = None
    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found")
        name = t.name
        t.is_active = False

    _write_audit([dict(
        tenant_id=tenant_id,
        product=None,
        operation="delete_tenant",
        action="DELETE",
        status="SUCCESS",
        resource_type="tenant",
        resource_name=name,
        timestamp=datetime.utcnow(),
    )])


def _get_import_client(tenant_id: int):
    """Build auth + client pair for a tenant by ID."""
    from db.database import get_session
    from db.models import TenantConfig
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret

    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found")
        zidentity = t.zidentity_base_url
        client_id = t.client_id
        secret = decrypt_secret(t.client_secret_enc)
        oneapi = t.oneapi_base_url
        name = t.name

    auth = ZscalerAuth(zidentity, client_id, secret)
    client = ZIAClient(auth, oneapi)
    return client, name


@router.post("/{tenant_id}/import/zia", status_code=202)
def import_zia(tenant_id: int, user: AuthUser = Depends(require_admin)):
    from services.zia_import_service import ZIAImportService

    client, tenant_name = _get_import_client(tenant_id)
    try:
        sync_log = ZIAImportService(client, tenant_id=tenant_id).run()
    except Exception as exc:
        _write_audit([dict(
            tenant_id=tenant_id,
            product="ZIA",
            operation="import",
            action="CREATE",
            status="FAILURE",
            resource_type="tenant",
            resource_name=tenant_name,
            error_message=str(exc),
            timestamp=datetime.utcnow(),
        )])
        raise HTTPException(status_code=502, detail=f"ZIA import failed: {exc}")

    _write_audit([dict(
        tenant_id=tenant_id,
        product="ZIA",
        operation="import",
        action="CREATE",
        status=sync_log.status,
        resource_type="tenant",
        resource_name=tenant_name,
        details={
            "resources_synced": sync_log.resources_synced,
            "resources_updated": sync_log.resources_updated,
        },
        timestamp=datetime.utcnow(),
    )])
    return {
        "status": sync_log.status,
        "resources_synced": sync_log.resources_synced,
        "resources_updated": sync_log.resources_updated,
        "error_message": sync_log.error_message,
    }


@router.post("/{tenant_id}/import/zpa", status_code=202)
def import_zpa(tenant_id: int, user: AuthUser = Depends(require_admin)):
    from db.database import get_session
    from db.models import TenantConfig
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret
    from services.zpa_import_service import ZPAImportService

    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if not t:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if not t.zpa_customer_id:
            raise HTTPException(status_code=400, detail="Tenant has no ZPA customer ID configured")
        zidentity = t.zidentity_base_url
        client_id = t.client_id
        secret = decrypt_secret(t.client_secret_enc)
        oneapi = t.oneapi_base_url
        customer_id = t.zpa_customer_id
        tenant_name = t.name

    auth = ZscalerAuth(zidentity, client_id, secret)
    client = ZPAClient(auth, customer_id, oneapi_base_url=oneapi)

    try:
        sync_log = ZPAImportService(client, tenant_id=tenant_id).run()
    except Exception as exc:
        _write_audit([dict(
            tenant_id=tenant_id,
            product="ZPA",
            operation="import",
            action="CREATE",
            status="FAILURE",
            resource_type="tenant",
            resource_name=tenant_name,
            error_message=str(exc),
            timestamp=datetime.utcnow(),
        )])
        raise HTTPException(status_code=502, detail=f"ZPA import failed: {exc}")

    _write_audit([dict(
        tenant_id=tenant_id,
        product="ZPA",
        operation="import",
        action="CREATE",
        status=sync_log.status,
        resource_type="tenant",
        resource_name=tenant_name,
        details={
            "resources_synced": sync_log.resources_synced,
            "resources_updated": sync_log.resources_updated,
        },
        timestamp=datetime.utcnow(),
    )])
    return {
        "status": sync_log.status,
        "resources_synced": sync_log.resources_synced,
        "resources_updated": sync_log.resources_updated,
        "error_message": sync_log.error_message,
    }
