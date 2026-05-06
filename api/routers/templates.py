"""Templates API router.

Endpoints for ZIA template management.  Templates are sanitised ZIA snapshots
with tenant-specific resource types stripped, making them portable across tenants.

All authenticated users can read and apply templates.
Only authenticated users can create and delete templates (no admin-only restriction
per spec section 5.1 — templates are visible to all authenticated users).

Registered in api/main.py with prefix /api/v1/templates.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import require_auth, check_tenant_access, AuthUser

router = APIRouter(prefix="/api/v1/templates", tags=["Templates"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class TemplatePreviewRequest(BaseModel):
    source_tenant_id: int
    snapshot_id: int


class TemplateCreateRequest(BaseModel):
    source_tenant_id: int
    snapshot_id: int
    name: str
    description: Optional[str] = None


class TemplateApplyRequest(BaseModel):
    template_id: int
    wipe_mode: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(tmpl, source_tenant_name: Optional[str] = None) -> dict:
    """Serialize a ZIATemplate ORM row to a dict safe for API responses."""
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "description": tmpl.description,
        "source_tenant_id": tmpl.source_tenant_id,
        "source_tenant_name": source_tenant_name,
        "source_snapshot_id": tmpl.source_snapshot_id,
        "created_at": tmpl.created_at.isoformat() + "Z" if tmpl.created_at else None,
        "updated_at": tmpl.updated_at.isoformat() + "Z" if tmpl.updated_at else None,
        "resource_count": tmpl.resource_count,
        "stripped_types": tmpl.stripped_types,
    }


def _serialize_full(tmpl, source_tenant_name: Optional[str] = None) -> dict:
    """Full serialization including snapshot blob."""
    result = _serialize(tmpl, source_tenant_name)
    # snapshot is stored as the resources dict (not wrapped in {"resources": ...})
    resources = tmpl.snapshot or {}
    result["snapshot"] = {
        rtype: [{"resource_type": rtype, "count": len(entries)}]
        for rtype, entries in resources.items()
    }
    result["included_types"] = [
        {"resource_type": rtype, "count": len(entries)}
        for rtype, entries in resources.items()
    ]
    return result


def _get_tenant_name(tenant_id: Optional[int]) -> Optional[str]:
    """Return tenant name or None if tenant_id is null or tenant was deleted."""
    if not tenant_id:
        return None
    from db.database import get_session
    from db.models import TenantConfig
    with get_session() as session:
        t = session.get(TenantConfig, tenant_id)
        return t.name if t else None


def _get_import_client(tenant_id: int):
    """Return (client, tenant_name) for the given tenant_id.

    Raises 404 if the tenant does not exist, 503 if credentials cannot be loaded.
    """
    from db.database import get_session
    from db.models import TenantConfig
    from services.config_service import decrypt_secret
    from lib.zia_client import ZIAClient
    from lib.auth import ZscalerAuth

    with get_session() as session:
        tenant = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        tenant_name = tenant.name
        client_id = tenant.client_id
        client_secret = decrypt_secret(tenant.client_secret_enc) if tenant.client_secret_enc else None
        govcloud = tenant.govcloud
        oneapi_base_url = tenant.oneapi_base_url
        zidentity_base_url = tenant.zidentity_base_url

    if not client_secret:
        raise HTTPException(status_code=503, detail="Tenant credentials not configured")

    auth = ZscalerAuth(zidentity_base_url, client_id, client_secret, govcloud=govcloud)
    client = ZIAClient(auth, oneapi_base_url)
    return client, tenant_name


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_templates(user: AuthUser = Depends(require_auth)):
    """List all ZIA templates, newest first."""
    from db.database import get_session
    from services.template_service import list_templates as _list

    with get_session() as session:
        templates = _list(session)
        # Collect raw data while session is open; resolve tenant names afterwards
        # to avoid a nested get_session() call (SQLite write-lock rule).
        rows = [_serialize(tmpl) for tmpl in templates]
        tenant_ids = [tmpl.source_tenant_id for tmpl in templates]

    for row, tid in zip(rows, tenant_ids):
        row["source_tenant_name"] = _get_tenant_name(tid)

    return rows


@router.post("/preview")
def preview_template(
    req: TemplatePreviewRequest,
    user: AuthUser = Depends(require_auth),
):
    """Compute included/stripped resource breakdown for a snapshot without writing to DB."""
    check_tenant_access(req.source_tenant_id, user)

    from db.database import get_session
    from services.template_service import preview_template_from_snapshot

    with get_session() as session:
        try:
            return preview_template_from_snapshot(
                snapshot_id=req.snapshot_id,
                source_tenant_id=req.source_tenant_id,
                session=session,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.post("", status_code=201)
def create_template(
    req: TemplateCreateRequest,
    user: AuthUser = Depends(require_auth),
):
    """Create a ZIA template from a snapshot.

    Returns the new template record.
    409 if name is already taken.
    422 if the snapshot has no portable resources after stripping.
    """
    check_tenant_access(req.source_tenant_id, user)

    from db.database import get_session
    from services.template_service import create_template_from_snapshot
    from services import audit_service

    pending_audit = []
    try:
        with get_session() as session:
            tmpl = create_template_from_snapshot(
                snapshot_id=req.snapshot_id,
                source_tenant_id=req.source_tenant_id,
                name=req.name,
                description=req.description,
                session=session,
            )
            tmpl_id = tmpl.id
            tmpl_name = tmpl.name
            tmpl_resource_count = tmpl.resource_count
            tmpl_stripped_types = list(tmpl.stripped_types or [])

        # Audit after session closes (SQLite write-lock rule)
        pending_audit.append(dict(
            product="ZIA",
            operation="create_template",
            action="CREATE",
            status="SUCCESS",
            resource_type="zia_template",
            resource_id=str(tmpl_id),
            resource_name=tmpl_name,
            details={
                "source_tenant_id": req.source_tenant_id,
                "source_snapshot_id": req.snapshot_id,
                "resource_count": tmpl_resource_count,
                "stripped_types": tmpl_stripped_types,
            },
        ))

    except ValueError as exc:
        err_str = str(exc)
        if err_str.startswith("duplicate_name:"):
            raise HTTPException(status_code=409, detail=err_str.split(":", 1)[1])
        if err_str.startswith("no_portable_resources:"):
            raise HTTPException(status_code=422, detail=err_str.split(":", 1)[1])
        raise HTTPException(status_code=422, detail=err_str)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    for ev in pending_audit:
        audit_service.log(**ev)

    tenant_name = _get_tenant_name(req.source_tenant_id)

    # Re-read the created template to return full data
    from db.database import get_session as _gs
    from db.models import ZIATemplate
    with _gs() as session:
        tmpl = session.get(ZIATemplate, tmpl_id)
        if not tmpl:
            raise HTTPException(status_code=500, detail="Template created but not found on re-read")
        return _serialize(tmpl, tenant_name)


@router.get("/{template_id}")
def get_template(
    template_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Return a single template including its included resource type summary."""
    from db.database import get_session
    from services.template_service import get_template as _get

    with get_session() as session:
        try:
            tmpl = _get(template_id, session)
            tenant_name = _get_tenant_name(tmpl.source_tenant_id)
            return _serialize_full(tmpl, tenant_name)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Delete a template by ID."""
    from db.database import get_session
    from services.template_service import delete_template as _delete, get_template as _get
    from services import audit_service

    pending_audit = []
    try:
        with get_session() as session:
            tmpl = _get(template_id, session)
            tmpl_name = tmpl.name
            _delete(template_id, session)

        pending_audit.append(dict(
            product="ZIA",
            operation="delete_template",
            action="DELETE",
            status="SUCCESS",
            resource_type="zia_template",
            resource_id=str(template_id),
            resource_name=tmpl_name,
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    for ev in pending_audit:
        audit_service.log(**ev)


# ---------------------------------------------------------------------------
# Apply template handler — registered in tenants.py at
# POST /api/v1/tenants/{tenant_id}/templates/apply (spec section 9.2)
# ---------------------------------------------------------------------------

def apply_template_to_tenant(
    tenant_id: int,
    req: TemplateApplyRequest,
    user: AuthUser = Depends(require_auth),
):
    """Apply a template to a target tenant.  Returns a job_id for SSE streaming.

    Internally this is identical to applying a snapshot (portable resources only,
    full_clone=False).  The template's snapshot blob is treated as the baseline.
    """
    import threading
    from api.jobs import store
    from db.database import get_session
    from db.models import ZIATemplate
    from services.zia_push_service import ZIAPushService, _PushCancelled
    from services import audit_service

    check_tenant_access(tenant_id, user)

    with get_session() as session:
        tmpl = session.get(ZIATemplate, req.template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl_name = tmpl.name
        # Template snapshot is stored as the resources dict directly
        snap_resources = tmpl.snapshot or {}

    client, tenant_name = _get_import_client(tenant_id)
    job_id = store.create()

    def run():
        service = ZIAPushService(client, tenant_id=tenant_id, full_clone=False)
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
                        {"resource_type": r.resource_type, "name": r.name,
                         "reason": r.status[len("failed:"):]}
                        for r in wipe_records if r.is_failed
                    ]
                else:
                    wipe_records = []
                    wipe_failed_items = []
                    wiped = 0
                    dry_run = service.classify_baseline(
                        baseline, import_progress_callback=on_import_progress
                    )
                    push_records = service.push_classified(
                        dry_run, progress_callback=on_push_progress, stop_fn=stop_fn
                    )

                # Re-import target tenant so DB reflects pushed state
                from services.zia_import_service import ZIAImportService
                ZIAImportService(client, tenant_id=tenant_id).run(
                    progress_callback=on_import_progress
                )

            except _PushCancelled as exc:
                rollback_records = service.rollback_pushed(exc.pushed_records)
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
                {"resource_type": r.resource_type, "name": r.name,
                 "reason": r.failure_reason}
                for r in push_records if r.is_failed
            ]
            warnings = [
                {"resource_type": r.resource_type, "name": r.name,
                 "warnings": r.warnings}
                for r in push_records if r.warnings
            ]
            failed_items = wipe_failed_items + push_failed_items
            total_failed = len(failed_items)
            status = "SUCCESS" if total_failed == 0 else "PARTIAL"

            audit_service.log(
                product="ZIA",
                operation="apply_template",
                action="CREATE",
                status=status,
                tenant_id=tenant_id,
                resource_type="tenant",
                resource_name=tenant_name,
                details={
                    "template_id": req.template_id,
                    "template_name": tmpl_name,
                    "mode": "wipe" if req.wipe_mode else "delta",
                    "wiped": wiped,
                    "created": created,
                    "updated": updated,
                    "failed": total_failed,
                },
            )

            store.complete(job_id, {
                "status": status,
                "template_name": tmpl_name,
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
            audit_service.log(
                product="ZIA",
                operation="apply_template",
                action="CREATE",
                status="FAILURE",
                tenant_id=tenant_id,
                resource_type="tenant",
                resource_name=tenant_name,
                error_message=str(exc),
            )

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}
