import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.jobs import store, import_job_key
from api.dependencies import AuthUser, require_auth_sse, require_auth, check_tenant_access

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.get("/active/import")
def active_import_job(
    tenant_id: int = Query(...),
    product: Literal["ZIA", "ZPA", "ZCC"] = Query(...),
    user: AuthUser = Depends(require_auth),
):
    """Return the in-flight import job for a tenant/product, if one is running.

    Lets a client that closed the import modal reattach to the job it started
    (or one started in another tab) instead of kicking off a duplicate import.
    """
    if user.role != "admin":
        check_tenant_access(tenant_id, user)
    job_id = store.find_active(import_job_key(tenant_id, product))
    if not job_id:
        return {"job_id": None}
    return store.describe(job_id) or {"job_id": None}


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str, _=Depends(require_auth_sse)):
    """SSE stream of progress events for a background job."""
    async def generate():
        cursor = 0
        while True:
            snap = store.snapshot(job_id)
            if snap is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'job not found'})}\n\n"
                return
            events, status, result, error = snap
            while cursor < len(events):
                yield f"data: {json.dumps(events[cursor])}\n\n"
                cursor += 1
            if status == "done":
                yield f"data: {json.dumps({'type': 'done', 'result': result})}\n\n"
                return
            if status == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': error})}\n\n"
                return
            if status == "cancelled":
                yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                return
            # cancel_requested: keep streaming while the thread runs rollback
            await asyncio.sleep(0.2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, _=Depends(require_auth)):
    if not store.request_cancel(job_id):
        raise HTTPException(status_code=404, detail="Job not found or already complete")
    return {"cancelled": True}
