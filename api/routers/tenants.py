from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from api.dependencies import require_admin, require_auth, check_tenant_access, AuthUser
from lib.conf_writer import build_zidentity_url, GOVCLOUD_ONEAPI_URL

COMMERCIAL_ONEAPI_URL = "https://api.zsapi.net"

router = APIRouter(prefix="/api/v1/tenants", tags=["Tenants"])


def _vanity(zidentity_base_url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(zidentity_base_url).hostname.split(".")[0]


def _serialize(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "vanity_domain": _vanity(t.zidentity_base_url),
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
    vanity_domain: str
    client_id: str
    client_secret: str
    govcloud: bool = False
    govcloud_oneapi_url: Optional[str] = None  # only used for GovCloud; defaults to GOVCLOUD_ONEAPI_URL
    zpa_customer_id: Optional[str] = None
    notes: Optional[str] = None


class TenantUpdate(BaseModel):
    vanity_domain: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    govcloud: Optional[bool] = None
    govcloud_oneapi_url: Optional[str] = None
    zpa_customer_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_tenants(user: AuthUser = Depends(require_auth)):
    from services.config_service import list_tenants as _list
    all_tenants = _list()
    if user.role == "admin":
        return [_serialize(t) for t in all_tenants]
    from db.database import get_session
    from db.models import UserTenantEntitlement
    with get_session() as session:
        entitled = {
            row.tenant_id
            for row in session.query(UserTenantEntitlement).filter_by(user_id=user.user_id).all()
        }
    return [_serialize(t) for t in all_tenants if t.id in entitled]


@router.get("/{tenant_id}")
def get_tenant(tenant_id: int, user: AuthUser = Depends(require_auth)):
    from db.database import get_session
    from db.models import TenantConfig
    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    check_tenant_access(tenant_id, user)
    return _serialize(t)


@router.post("", status_code=201)
def create_tenant(body: TenantCreate, user: AuthUser = Depends(require_admin)):
    from services.config_service import add_tenant, fetch_org_info
    from db.database import get_session
    from db.models import TenantConfig

    zidentity_base_url = build_zidentity_url(body.vanity_domain, govcloud=body.govcloud)
    if body.govcloud:
        oneapi_base_url = (body.govcloud_oneapi_url or GOVCLOUD_ONEAPI_URL).rstrip("/")
    else:
        oneapi_base_url = COMMERCIAL_ONEAPI_URL

    try:
        t = add_tenant(
            name=body.name,
            zidentity_base_url=zidentity_base_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
            oneapi_base_url=oneapi_base_url,
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
        zidentity_base_url=zidentity_base_url,
        client_id=body.client_id,
        client_secret=body.client_secret,
        oneapi_base_url=oneapi_base_url,
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
    # Rebuild URLs from vanity if provided; otherwise leave existing values in place.
    new_govcloud = body.govcloud  # may be None (no change)
    new_zidentity = (
        build_zidentity_url(body.vanity_domain, govcloud=bool(new_govcloud))
        if body.vanity_domain else None
    )
    if new_govcloud is True:
        new_oneapi = (body.govcloud_oneapi_url or GOVCLOUD_ONEAPI_URL).rstrip("/")
    elif new_govcloud is False:
        new_oneapi = COMMERCIAL_ONEAPI_URL
    else:
        new_oneapi = None  # no change

    updated = _update(
        name=name,
        zidentity_base_url=new_zidentity,
        client_id=body.client_id,
        client_secret=body.client_secret,
        oneapi_base_url=new_oneapi,
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
        govcloud = t.govcloud
        name = t.name

    auth = ZscalerAuth(zidentity, client_id, secret, govcloud=govcloud)
    client = ZIAClient(auth, oneapi)
    return client, name


@router.post("/{tenant_id}/import/zia", status_code=202)
def import_zia(tenant_id: int, user: AuthUser = Depends(require_auth)):
    import threading
    from api.jobs import store

    check_tenant_access(tenant_id, user)
    client, tenant_name = _get_import_client(tenant_id)
    job_id = store.create()

    def run():
        from services.zia_import_service import ZIAImportService

        def on_progress(resource_type: str, done: int, total: int):
            store.append(job_id, {
                "type": "progress", "phase": "import",
                "resource_type": resource_type, "done": done, "total": total,
            })

        try:
            sync_log = ZIAImportService(client, tenant_id=tenant_id).run(progress_callback=on_progress)
            store.complete(job_id, {
                "status": sync_log.status,
                "resources_synced": sync_log.resources_synced,
                "resources_updated": sync_log.resources_updated,
                "error_message": sync_log.error_message,
            })
            _write_audit([dict(
                tenant_id=tenant_id, product="ZIA", operation="import",
                action="CREATE", status=sync_log.status,
                resource_type="tenant", resource_name=tenant_name,
                details={"resources_synced": sync_log.resources_synced,
                         "resources_updated": sync_log.resources_updated},
                timestamp=datetime.utcnow(),
            )])
        except Exception as exc:
            store.fail(job_id, str(exc))
            _write_audit([dict(
                tenant_id=tenant_id, product="ZIA", operation="import",
                action="CREATE", status="FAILURE",
                resource_type="tenant", resource_name=tenant_name,
                error_message=str(exc), timestamp=datetime.utcnow(),
            )])

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@router.post("/{tenant_id}/import/zpa", status_code=202)
def import_zpa(tenant_id: int, user: AuthUser = Depends(require_auth)):
    import threading
    from api.jobs import store
    from db.database import get_session
    from db.models import TenantConfig
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret

    check_tenant_access(tenant_id, user)
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
        govcloud = t.govcloud
        govcloud_cloud = t.zpa_tenant_cloud if t.govcloud else None
        customer_id = t.zpa_customer_id
        tenant_name = t.name

    auth = ZscalerAuth(zidentity, client_id, secret, govcloud=govcloud)
    zpa_client = ZPAClient(auth, customer_id, oneapi_base_url=oneapi, govcloud_cloud=govcloud_cloud)
    job_id = store.create()

    def run():
        from services.zpa_import_service import ZPAImportService

        def on_progress(resource_type: str, done: int, total: int):
            store.append(job_id, {
                "type": "progress", "phase": "import",
                "resource_type": resource_type, "done": done, "total": total,
            })

        try:
            sync_log = ZPAImportService(zpa_client, tenant_id=tenant_id).run(progress_callback=on_progress)
            store.complete(job_id, {
                "status": sync_log.status,
                "resources_synced": sync_log.resources_synced,
                "resources_updated": sync_log.resources_updated,
                "error_message": sync_log.error_message,
            })
            _write_audit([dict(
                tenant_id=tenant_id, product="ZPA", operation="import",
                action="CREATE", status=sync_log.status,
                resource_type="tenant", resource_name=tenant_name,
                details={"resources_synced": sync_log.resources_synced,
                         "resources_updated": sync_log.resources_updated},
                timestamp=datetime.utcnow(),
            )])
        except Exception as exc:
            store.fail(job_id, str(exc))
            _write_audit([dict(
                tenant_id=tenant_id, product="ZPA", operation="import",
                action="CREATE", status="FAILURE",
                resource_type="tenant", resource_name=tenant_name,
                error_message=str(exc), timestamp=datetime.utcnow(),
            )])

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


# ── Apply Snapshot ────────────────────────────────────────────────────────────

class ApplySnapshotRequest(BaseModel):
    source_tenant_id: int
    snapshot_id: int
    wipe_mode: bool = False


@router.post("/{tenant_id}/snapshots/preview", status_code=202)
def preview_apply_snapshot(
    tenant_id: int,
    req: ApplySnapshotRequest,
    user: AuthUser = Depends(require_auth),
):
    """Fresh-import the target tenant, classify changes needed to match the
    source snapshot, and stream progress via SSE job. Returns a job_id."""
    import threading
    from api.jobs import store
    from db.database import get_session
    from db.models import RestorePoint
    from services.zia_push_service import ZIAPushService

    check_tenant_access(tenant_id, user)
    check_tenant_access(req.source_tenant_id, user)

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=req.snapshot_id, tenant_id=req.source_tenant_id, product="ZIA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snap_name = snap.name
        snap_comment = snap.comment
        snap_created = snap.created_at.isoformat() + "Z"
        snap_resource_count = snap.resource_count
        snap_resources = snap.snapshot["resources"]

    client, _tenant_name = _get_import_client(tenant_id)
    job_id = store.create()

    def run():
        service = ZIAPushService(client, tenant_id=tenant_id)
        baseline = {"product": "ZIA", "resources": snap_resources}

        def on_import_progress(resource_type: str, done: int, total: int):
            store.append(job_id, {
                "type": "progress", "phase": "import",
                "resource_type": resource_type, "done": done, "total": total,
            })

        try:
            dry_run = service.classify_baseline(baseline, import_progress_callback=on_import_progress)
            delete_candidates = service.classify_snapshot_deletes(snap_resources)

            creates, updates, deletes_list = dry_run.changes_by_action()
            for rec in delete_candidates:
                deletes_list.append((rec.resource_type, rec.name))

            items: List[dict] = (
                [{"action": "create", "resource_type": rt, "name": n} for rt, n in creates]
                + [{"action": "update", "resource_type": rt, "name": n} for rt, n in updates]
                + [{"action": "delete", "resource_type": rt, "name": n} for rt, n in deletes_list]
            )

            store.complete(job_id, {
                "snapshot_name": snap_name,
                "snapshot_comment": snap_comment,
                "snapshot_created": snap_created,
                "snapshot_resource_count": snap_resource_count,
                "creates": dry_run.create_count,
                "updates": dry_run.update_count,
                "skips": dry_run.skip_count,
                "deletes": len(delete_candidates),
                "items": items,
            })
        except Exception as exc:
            store.fail(job_id, str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@router.post("/{tenant_id}/snapshots/apply", status_code=202)
def apply_snapshot(
    tenant_id: int,
    req: ApplySnapshotRequest,
    user: AuthUser = Depends(require_auth),
):
    """Apply a source snapshot to the target tenant. Returns a job_id for SSE streaming."""
    import threading
    from api.jobs import store
    from db.database import get_session
    from db.models import RestorePoint
    from services.zia_push_service import ZIAPushService, _PushCancelled

    check_tenant_access(tenant_id, user)
    check_tenant_access(req.source_tenant_id, user)

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=req.snapshot_id, tenant_id=req.source_tenant_id, product="ZIA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snap_name = snap.name
        snap_resources = snap.snapshot["resources"]

    client, tenant_name = _get_import_client(tenant_id)
    job_id = store.create()

    def run():
        service = ZIAPushService(client, tenant_id=tenant_id)
        baseline = {"product": "ZIA", "resources": snap_resources}

        wipe_done = [0]

        def on_import_progress(resource_type: str, done: int, total: int):
            store.append(job_id, {
                "type": "progress", "phase": "import",
                "resource_type": resource_type, "done": done, "total": total,
            })

        def on_wipe_progress(resource_type: str, record):
            wipe_done[0] += 1
            store.append(job_id, {
                "type": "progress", "phase": "wipe",
                "resource_type": resource_type,
                "name": record.name,
                "status": record.status,
                "done": wipe_done[0],
            })

        push_totals: dict = {}

        def on_push_progress(_pass_num: int, resource_type: str, record):
            push_totals.setdefault(resource_type, {"done": 0})
            push_totals[resource_type]["done"] += 1
            store.append(job_id, {
                "type": "progress", "phase": "push",
                "resource_type": resource_type,
                "name": record.name,
                "status": record.status,
                "done": push_totals[resource_type]["done"],
            })

        rollback_done = [0]

        def on_rollback_progress(resource_type: str, record):
            rollback_done[0] += 1
            store.append(job_id, {
                "type": "progress", "phase": "rollback",
                "resource_type": resource_type,
                "name": record.name,
                "status": record.status,
                "done": rollback_done[0],
            })

        stop_fn = lambda: store.is_cancel_requested(job_id)

        try:
            try:
                if req.wipe_mode:
                    wipe_records, push_records = service.apply_baseline(
                        baseline,
                        wipe_progress_callback=on_wipe_progress,
                        import_progress_callback=on_import_progress,
                        push_progress_callback=on_push_progress,
                        stop_fn=stop_fn,
                    )
                    wiped = sum(1 for r in wipe_records if r.is_deleted)
                    wipe_failed_items = [
                        {"resource_type": r.resource_type, "name": r.name, "reason": r.status[len("failed:"):]}
                        for r in wipe_records if r.is_failed
                    ]
                else:
                    wipe_records = []
                    wipe_failed_items = []
                    wiped = 0
                    dry_run = service.classify_baseline(baseline, import_progress_callback=on_import_progress)
                    push_records = service.push_classified(
                        dry_run, progress_callback=on_push_progress, stop_fn=stop_fn
                    )
            except _PushCancelled as exc:
                rollback_records = service.rollback_pushed(
                    exc.pushed_records, on_rollback_progress
                )
                rolled_back = sum(
                    1 for r in rollback_records
                    if r.status in ("rollback_deleted", "rollback_restored")
                )
                rollback_failed = sum(
                    1 for r in rollback_records if r.status.startswith("rollback_failed")
                )
                store.complete(job_id, {
                    "cancelled": True,
                    "rolled_back": rolled_back,
                    "rollback_failed": rollback_failed,
                })
                return

            created = sum(1 for r in push_records if r.is_created)
            updated = sum(1 for r in push_records if r.is_updated)
            push_failed_items = [
                {"resource_type": r.resource_type, "name": r.name, "reason": r.failure_reason}
                for r in push_records if r.is_failed
            ]
            warnings = [
                {"resource_type": r.resource_type, "name": r.name, "warnings": r.warnings}
                for r in push_records if r.warnings
            ]
            failed_items = wipe_failed_items + push_failed_items
            total_failed = len(failed_items)
            status = "SUCCESS" if total_failed == 0 else "PARTIAL"

            _write_audit([dict(
                tenant_id=tenant_id,
                product="ZIA",
                operation="apply_snapshot",
                action="CREATE",
                status=status,
                resource_type="tenant",
                resource_name=tenant_name,
                details={
                    "source_tenant_id": req.source_tenant_id,
                    "snapshot_name": snap_name,
                    "mode": "wipe" if req.wipe_mode else "delta",
                    "wiped": wiped,
                    "created": created,
                    "updated": updated,
                    "failed": total_failed,
                },
                timestamp=datetime.utcnow(),
            )])

            store.complete(job_id, {
                "status": status,
                "snapshot_name": snap_name,
                "mode": "wipe" if req.wipe_mode else "delta",
                "wiped": wiped,
                "created": created,
                "updated": updated,
                "failed": total_failed,
                "failed_items": failed_items,
                "warnings": warnings,
            })
        except Exception as exc:
            store.fail(job_id, str(exc))
            _write_audit([dict(
                tenant_id=tenant_id,
                product="ZIA",
                operation="apply_snapshot",
                action="CREATE",
                status="FAILURE",
                resource_type="tenant",
                resource_name=tenant_name,
                error_message=str(exc),
                timestamp=datetime.utcnow(),
            )])

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}
