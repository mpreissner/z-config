"""REST router for scheduled cross-tenant sync tasks.

All endpoints require authentication. No admin restriction — any authenticated
user may manage scheduled tasks, subject to tenant entitlement checks on the
referenced source/target tenant IDs.

Prefix: /api/v1/scheduled-tasks
"""

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator

from api.dependencies import require_auth, check_tenant_access, AuthUser

router = APIRouter(prefix="/api/v1/scheduled-tasks", tags=["Scheduled Tasks"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ScheduledTaskCreate(BaseModel):
    name: str
    source_tenant_id: int
    target_tenant_id: int
    resource_groups: List[str]
    schedule: str                    # interval preset or cron expression
    sync_deletes: bool = False
    enabled: bool = True
    owner_email: Optional[str] = None
    sync_mode: str = "resource_type"
    label_name: Optional[str] = None
    label_resource_types: Optional[List[str]] = None

    @model_validator(mode="after")
    def _validate_mode(self) -> "ScheduledTaskCreate":
        if self.sync_mode not in ("resource_type", "label"):
            raise ValueError("sync_mode must be 'resource_type' or 'label'.")
        if self.sync_mode == "resource_type":
            if not self.resource_groups:
                raise ValueError("resource_groups must be non-empty when sync_mode is 'resource_type'.")
            if self.label_name:
                raise ValueError("label_name must be absent when sync_mode is 'resource_type'.")
        elif self.sync_mode == "label":
            if not self.label_name or not self.label_name.strip():
                raise ValueError("label_name is required when sync_mode is 'label'.")
        return self


class ScheduledTaskUpdate(BaseModel):
    name: Optional[str] = None
    source_tenant_id: Optional[int] = None
    target_tenant_id: Optional[int] = None
    resource_groups: Optional[List[str]] = None
    schedule: Optional[str] = None
    sync_deletes: Optional[bool] = None
    enabled: Optional[bool] = None
    owner_email: Optional[str] = None
    sync_mode: Optional[str] = None
    label_name: Optional[str] = None
    label_resource_types: Optional[List[str]] = None

    @model_validator(mode="after")
    def _validate_mode(self) -> "ScheduledTaskUpdate":
        if self.sync_mode is not None and self.sync_mode not in ("resource_type", "label"):
            raise ValueError("sync_mode must be 'resource_type' or 'label'.")
        if self.sync_mode == "resource_type":
            if self.label_name is not None:
                raise ValueError("label_name must be absent when sync_mode is 'resource_type'.")
        if self.sync_mode == "label":
            if self.label_name is not None and not self.label_name.strip():
                raise ValueError("label_name cannot be empty when sync_mode is 'label'.")
        return self


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _next_run(cron_expression: str) -> Optional[str]:
    """Compute the next fire time for a cron expression (UTC ISO string)."""
    try:
        it = croniter(cron_expression, datetime.utcnow())
        nxt: datetime = it.get_next(datetime)
        return nxt.isoformat() + "Z"
    except Exception:
        return None


def _serialize_task(task, last_run=None) -> Dict[str, Any]:
    """Build the API response dict for a ScheduledTask.

    last_run is an optional TaskRunHistory row (or None).
    """
    from db.models import TenantConfig
    from db.database import get_session

    with get_session() as session:
        src = session.get(TenantConfig, task.source_tenant_id)
        tgt = session.get(TenantConfig, task.target_tenant_id)
        src_name = src.name if src else str(task.source_tenant_id)
        tgt_name = tgt.name if tgt else str(task.target_tenant_id)

    return {
        "id": task.id,
        "name": task.name,
        "source_tenant_id": task.source_tenant_id,
        "source_tenant_name": src_name,
        "target_tenant_id": task.target_tenant_id,
        "target_tenant_name": tgt_name,
        "resource_groups": task.resource_groups,
        "cron_expression": task.cron_expression,
        "sync_deletes": task.sync_deletes,
        "enabled": task.enabled,
        "owner_email": task.owner_email,
        "last_run_at": last_run.started_at.isoformat() + "Z" if last_run and last_run.started_at else None,
        "last_run_status": last_run.status if last_run else None,
        "next_run_at": _next_run(task.cron_expression) if task.enabled else None,
        "created_at": task.created_at.isoformat() + "Z" if task.created_at else None,
        "updated_at": task.updated_at.isoformat() + "Z" if task.updated_at else None,
        "sync_mode": task.sync_mode or "resource_type",
        "label_name": task.label_name,
        "label_resource_types": task.label_resource_types,
    }


def _get_last_run(task_id: int):
    """Return the most recent TaskRunHistory for a task, or None."""
    from db.models import TaskRunHistory
    from db.database import get_session

    with get_session() as session:
        run = (
            session.query(TaskRunHistory)
            .filter_by(task_id=task_id)
            .order_by(TaskRunHistory.started_at.desc())
            .first()
        )
        if run is None:
            return None
        # Detach
        return _copy_run(run)


def _copy_run(run):
    from db.models import TaskRunHistory
    return TaskRunHistory(
        id=run.id,
        task_id=run.task_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        resources_synced=run.resources_synced,
        errors_json=run.errors_json,
    )


def _serialize_run(run, include_errors: bool = False) -> Dict[str, Any]:
    duration = None
    if run.finished_at and run.started_at:
        delta = run.finished_at - run.started_at
        duration = int(delta.total_seconds())

    result = {
        "id": run.id,
        "task_id": run.task_id,
        "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
        "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
        "duration_seconds": duration,
        "status": run.status,
        "resources_synced": run.resources_synced,
        "error_count": len(run.errors_json) if run.errors_json else 0,
    }
    if include_errors:
        result["errors"] = run.errors_json or []
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_tasks(user: AuthUser = Depends(require_auth)):
    """List all scheduled tasks with last-run summary and next-run time."""
    from services.scheduled_task_service import list_tasks as _list

    tasks = _list()
    result = []
    for task in tasks:
        last_run = _get_last_run(task.id)
        result.append(_serialize_task(task, last_run=last_run))
    return result


@router.post("", status_code=201)
def create_task(body: ScheduledTaskCreate, user: AuthUser = Depends(require_auth)):
    """Create a new scheduled sync task."""
    from services.scheduled_task_service import create_task as _create

    check_tenant_access(body.source_tenant_id, user)
    check_tenant_access(body.target_tenant_id, user)

    try:
        task = _create(
            name=body.name,
            source_tenant_id=body.source_tenant_id,
            target_tenant_id=body.target_tenant_id,
            resource_groups=body.resource_groups,
            schedule=body.schedule,
            sync_deletes=body.sync_deletes,
            enabled=body.enabled,
            owner_email=body.owner_email,
            sync_mode=body.sync_mode,
            label_name=body.label_name,
            label_resource_types=body.label_resource_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _serialize_task(task)


@router.get("/{task_id}")
def get_task(task_id: int, user: AuthUser = Depends(require_auth)):
    """Get full detail for a single scheduled task."""
    from services.scheduled_task_service import get_task as _get

    task = _get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(task.source_tenant_id, user)
    check_tenant_access(task.target_tenant_id, user)

    last_run = _get_last_run(task_id)
    return _serialize_task(task, last_run=last_run)


@router.put("/{task_id}")
def update_task(task_id: int, body: ScheduledTaskUpdate, user: AuthUser = Depends(require_auth)):
    """Update a scheduled task definition."""
    from services.scheduled_task_service import get_task as _get, update_task as _update

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    # Entitlement check on both old and new tenant IDs
    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)
    if body.source_tenant_id is not None:
        check_tenant_access(body.source_tenant_id, user)
    if body.target_tenant_id is not None:
        check_tenant_access(body.target_tenant_id, user)

    try:
        updated = _update(
            task_id=task_id,
            name=body.name,
            source_tenant_id=body.source_tenant_id,
            target_tenant_id=body.target_tenant_id,
            resource_groups=body.resource_groups,
            schedule=body.schedule,
            sync_deletes=body.sync_deletes,
            enabled=body.enabled,
            owner_email=body.owner_email,
            sync_mode=body.sync_mode,
            label_name=body.label_name,
            label_resource_types=body.label_resource_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    last_run = _get_last_run(task_id)
    return _serialize_task(updated, last_run=last_run)


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, user: AuthUser = Depends(require_auth)):
    """Delete a scheduled task and its run history."""
    from services.scheduled_task_service import get_task as _get, delete_task as _delete

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)

    _delete(task_id)


@router.post("/{task_id}/enable")
def enable_task(task_id: int, user: AuthUser = Depends(require_auth)):
    """Enable a scheduled task and register it with the scheduler."""
    from services.scheduled_task_service import get_task as _get, enable_task as _enable

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)

    updated = _enable(task_id)
    last_run = _get_last_run(task_id)
    return _serialize_task(updated, last_run=last_run)


@router.post("/{task_id}/disable")
def disable_task(task_id: int, user: AuthUser = Depends(require_auth)):
    """Disable a scheduled task and remove its scheduler job."""
    from services.scheduled_task_service import get_task as _get, disable_task as _disable

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)

    updated = _disable(task_id)
    last_run = _get_last_run(task_id)
    return _serialize_task(updated, last_run=last_run)


@router.post("/{task_id}/trigger", status_code=202)
def trigger_task(task_id: int, user: AuthUser = Depends(require_auth)):
    """Trigger a manual one-shot run of a scheduled task.

    Returns a job_id for SSE progress monitoring at
    GET /api/v1/jobs/{job_id}/events, following the same pattern as
    Import Config.
    """
    from api.jobs import store
    from services.scheduled_task_service import get_task as _get

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)

    job_id = store.create()

    def run():
        from services.scheduled_sync_engine import run_sync_task

        try:
            run_result = run_sync_task(task_id)
            if run_result is None:
                store.fail(job_id, "Task not found or disabled")
                return
            store.complete(job_id, {
                "status": run_result.status,
                "resources_synced": run_result.resources_synced,
                "error_count": len(run_result.errors_json) if run_result.errors_json else 0,
                "run_id": run_result.id,
            })
        except Exception as exc:
            store.fail(job_id, str(exc))

    threading.Thread(target=run, daemon=True).start()

    return {"job_id": job_id, "message": "Task triggered"}


@router.get("/{task_id}/runs")
def list_runs(
    task_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(require_auth),
):
    """Get run history for a task (paginated)."""
    from services.scheduled_task_service import get_task as _get
    from db.models import TaskRunHistory
    from db.database import get_session

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)

    with get_session() as session:
        runs = (
            session.query(TaskRunHistory)
            .filter_by(task_id=task_id)
            .order_by(TaskRunHistory.started_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_serialize_run(_copy_run(r)) for r in runs]


@router.get("/{task_id}/runs/{run_id}")
def get_run(task_id: int, run_id: int, user: AuthUser = Depends(require_auth)):
    """Get full detail for one run (includes full errors_json)."""
    from services.scheduled_task_service import get_task as _get
    from db.models import TaskRunHistory
    from db.database import get_session

    existing = _get(task_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    check_tenant_access(existing.source_tenant_id, user)
    check_tenant_access(existing.target_tenant_id, user)

    with get_session() as session:
        run = session.query(TaskRunHistory).filter_by(id=run_id, task_id=task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _serialize_run(_copy_run(run), include_errors=True)
