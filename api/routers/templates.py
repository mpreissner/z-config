"""Templates API router.

Endpoints for ZIA template management.  Templates are sanitised ZIA snapshots
with tenant-specific resource types stripped, making them portable across tenants.

A template belongs to whoever created it.  Reading and applying it require the
same permission — applying is separately gated on tenant access, so a read-only
share would protect nothing.  Renaming, re-sharing, and deleting belong to the
owner and to admins.  template_share_service owns those decisions; this router
only translates them into status codes.

A template the caller cannot see answers 404, not 403: a 403 would confirm that a
template with that ID exists and tell them its neighbours' IDs.

Registered in api/main.py with prefix /api/v1/templates.
"""

from datetime import datetime
from typing import Dict, List, Optional

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
    #: {resource_type: [entry_id, …]}.  Omitted or empty means a full template
    #: over everything portable in the snapshot — the historical behaviour.
    selection: Optional[Dict[str, List[str]]] = None
    visibility: str = "private"


class TemplateUpdateRequest(BaseModel):
    """Everything about a template that can change after creation.

    Not its contents: a template is a snapshot of a moment, and editing the
    resources inside one would silently change what every past reference to it
    means.  Re-create instead.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None
    #: Admin-only — used to adopt a legacy (unowned) template.
    owner_user_id: Optional[int] = None


class TemplateShareRequest(BaseModel):
    user_ids: List[int] = []
    group_ids: List[int] = []


class TemplateApplyRequest(BaseModel):
    template_id: int
    wipe_mode: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(
    tmpl,
    source_tenant_name: Optional[str] = None,
    user: Optional[AuthUser] = None,
    share_count: int = 0,
) -> dict:
    """Serialize a ZIATemplate ORM row to a dict safe for API responses.

    `can_manage` is computed here rather than left to the client to infer from
    owner_user_id, because the admin case and the legacy-template case both make
    that inference wrong.
    """
    is_owner = bool(
        user is not None
        and tmpl.owner_user_id is not None
        and tmpl.owner_user_id == user.user_id
    )
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
        "owner_user_id": tmpl.owner_user_id,
        "owner_username": tmpl.owner_username,
        "visibility": tmpl.visibility or "private",
        "scope": tmpl.scope or "full",
        "is_owner": is_owner,
        "can_manage": is_owner or (user is not None and user.role == "admin"),
        "share_count": share_count,
    }


def _serialize_full(
    tmpl,
    source_tenant_name: Optional[str] = None,
    user: Optional[AuthUser] = None,
    share_count: int = 0,
) -> dict:
    """Full serialization including snapshot blob."""
    result = _serialize(tmpl, source_tenant_name, user, share_count)
    result["selection_meta"] = tmpl.selection_meta
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
        gov_tier = tenant.gov_cloud_tier
        oneapi_base_url = tenant.oneapi_base_url
        zidentity_base_url = tenant.zidentity_base_url

    if not client_secret:
        raise HTTPException(status_code=503, detail="Tenant credentials not configured")

    auth = ZscalerAuth(zidentity_base_url, client_id, client_secret, govcloud=govcloud, gov_tier=gov_tier)
    client = ZIAClient(auth, oneapi_base_url)
    return client, tenant_name


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_templates(user: AuthUser = Depends(require_auth)):
    """List the templates this account can see, newest first."""
    from db.database import get_session
    from services.template_service import list_templates as _list
    from services import template_share_service as shares

    with get_session() as session:
        visible = shares.visible_template_ids(user.user_id, user.role, session)
        templates = _list(session, visible_ids=visible)
        counts = shares.share_counts([t.id for t in templates], session)
        # Collect raw data while session is open; resolve tenant names afterwards
        # to avoid a nested get_session() call (SQLite write-lock rule).
        rows = [
            _serialize(tmpl, user=user, share_count=counts.get(tmpl.id, 0))
            for tmpl in templates
        ]
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


@router.post("/preview/detail")
def preview_template_entries(
    req: TemplatePreviewRequest,
    user: AuthUser = Depends(require_auth),
):
    """Every selectable entry in a snapshot, for the resource picker.

    Returns the same breakdown as /preview plus an `entries` map of
    {resource_type: [{id, name, predefined, summary, order}]}.  Deliberately no
    raw_config: a rule's full configuration can name internal hosts, and the
    picker only needs enough to tell two rules apart.
    """
    check_tenant_access(req.source_tenant_id, user)

    from db.database import get_session
    from services.template_service import preview_template_detail

    with get_session() as session:
        try:
            return preview_template_detail(
                snapshot_id=req.snapshot_id,
                source_tenant_id=req.source_tenant_id,
                session=session,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.get("/share-targets")
def list_share_targets(user: AuthUser = Depends(require_auth)):
    """The people and groups a template can be shared with.

    Any authenticated account may read this: sharing is not an admin action, and
    the admin user/group listings are closed to ordinary users, so without it an
    owner would have nobody to pick from.  Deliberately narrow — a name and an
    id, never a role, an email, or an entitlement.

    Declared ahead of /{template_id} so the literal path wins the match.
    """
    from db.database import get_session
    from db.models import User, UserGroup

    with get_session() as session:
        users = [
            {"id": u.id, "username": u.username}
            for u in session.query(User)
            .filter(User.is_active.is_(True))
            .order_by(User.username)
            .all()
        ]
        groups = [
            {"id": g.id, "display_name": g.display_name}
            for g in session.query(UserGroup).order_by(UserGroup.display_name).all()
        ]

    return {"users": users, "groups": groups}


@router.post("", status_code=201)
def create_template(
    req: TemplateCreateRequest,
    user: AuthUser = Depends(require_auth),
):
    """Create a ZIA template from a snapshot.

    Returns the new template record.  The caller becomes its owner.

    409 if name is already taken.
    422 if the snapshot has no portable resources after stripping, if the
    selection names something unselectable, or if visibility is not one of
    private / shared / org.
    """
    check_tenant_access(req.source_tenant_id, user)

    if req.visibility not in ("private", "shared", "org"):
        raise HTTPException(
            status_code=422,
            detail="visibility must be one of: private, shared, org",
        )

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
                selection=req.selection or None,
                owner_user_id=user.user_id,
                owner_username=user.username,
                visibility=req.visibility,
            )
            tmpl_id = tmpl.id
            tmpl_name = tmpl.name
            tmpl_resource_count = tmpl.resource_count
            tmpl_stripped_types = list(tmpl.stripped_types or [])
            tmpl_scope = tmpl.scope

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
                "scope": tmpl_scope,
                "visibility": req.visibility,
            },
        ))

    except ValueError as exc:
        err_str = str(exc)
        if err_str.startswith("duplicate_name:"):
            raise HTTPException(status_code=409, detail=err_str.split(":", 1)[1])
        if err_str.startswith(("no_portable_resources:", "invalid_selection:")):
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
        return _serialize(tmpl, tenant_name, user=user)


@router.get("/{template_id}")
def get_template(
    template_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Return a single template including its included resource type summary.

    404 — not 403 — when the caller cannot see it; see the module docstring.
    """
    from db.database import get_session
    from services.template_service import get_template as _get
    from services import template_share_service as shares

    with get_session() as session:
        try:
            tmpl = _get(template_id, session)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        if not shares.can_read(tmpl, user.user_id, user.role, session):
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        count = shares.share_counts([template_id], session).get(template_id, 0)
        row = _serialize_full(tmpl, None, user=user, share_count=count)
        source_tenant_id = tmpl.source_tenant_id

    row["source_tenant_name"] = _get_tenant_name(source_tenant_id)
    return row


@router.patch("/{template_id}")
def update_template(
    template_id: int,
    req: TemplateUpdateRequest,
    user: AuthUser = Depends(require_auth),
):
    """Rename a template, change its description, or change who can see it.

    Owner or admin only.  Contents are immutable — see TemplateUpdateRequest.

    Dropping to visibility='private' leaves the share rows in place: an owner
    hiding a work-in-progress should get their share list back when they unhide
    it, and can_read ignores shares unless visibility is 'shared'.
    """
    from db.database import get_session
    from db.models import User, ZIATemplate
    from services.template_service import get_template as _get
    from services import template_share_service as shares, audit_service

    if req.visibility is not None and req.visibility not in ("private", "shared", "org"):
        raise HTTPException(
            status_code=422, detail="visibility must be one of: private, shared, org"
        )
    if req.owner_user_id is not None and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can reassign ownership")

    changes = {}
    try:
        with get_session() as session:
            tmpl = _get(template_id, session)
            if not shares.can_read(tmpl, user.user_id, user.role, session):
                raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
            if not shares.can_manage(tmpl, user.user_id, user.role):
                raise HTTPException(
                    status_code=403,
                    detail="Only the template's owner or an admin can change it",
                )

            if req.name is not None and req.name != tmpl.name:
                clash = session.query(ZIATemplate).filter(
                    ZIATemplate.name == req.name, ZIATemplate.id != template_id
                ).first()
                if clash is not None:
                    owner = clash.owner_username
                    suffix = f" (owned by {owner})" if owner else ""
                    raise HTTPException(
                        status_code=409,
                        detail=f'A template named "{req.name}" already exists{suffix}',
                    )
                changes["name"] = req.name
                tmpl.name = req.name
            if req.description is not None:
                changes["description"] = req.description
                tmpl.description = req.description
            if req.visibility is not None:
                changes["visibility"] = req.visibility
                tmpl.visibility = req.visibility
            if req.owner_user_id is not None:
                new_owner = session.get(User, req.owner_user_id)
                if new_owner is None or not new_owner.is_active:
                    raise HTTPException(
                        status_code=422, detail=f"Unknown or inactive user {req.owner_user_id}"
                    )
                changes["owner_user_id"] = req.owner_user_id
                tmpl.owner_user_id = new_owner.id
                tmpl.owner_username = new_owner.username

            if changes:
                tmpl.updated_at = datetime.utcnow()
            session.flush()

            count = shares.share_counts([template_id], session).get(template_id, 0)
            row = _serialize(tmpl, None, user=user, share_count=count)
            source_tenant_id = tmpl.source_tenant_id
            tmpl_name = tmpl.name
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if changes:
        audit_service.log(
            product="ZIA",
            operation="update_template",
            action="UPDATE",
            status="SUCCESS",
            resource_type="zia_template",
            resource_id=str(template_id),
            resource_name=tmpl_name,
            details=changes,
        )

    row["source_tenant_name"] = _get_tenant_name(source_tenant_id)
    return row


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Delete a template by ID.  Owner or admin only.

    A legacy template (no owner) is admin-only: it is visible org-wide, and
    handing delete rights to whoever happens to open it would let one account
    remove something everyone else depends on.
    """
    from db.database import get_session
    from services.template_service import delete_template as _delete, get_template as _get
    from services import template_share_service as shares, audit_service

    pending_audit = []
    try:
        with get_session() as session:
            tmpl = _get(template_id, session)
            if not shares.can_read(tmpl, user.user_id, user.role, session):
                raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
            if not shares.can_manage(tmpl, user.user_id, user.role):
                detail = (
                    "This template has no owner; only an admin can delete it"
                    if tmpl.owner_user_id is None
                    else "Only the template's owner or an admin can delete it"
                )
                raise HTTPException(status_code=403, detail=detail)
            tmpl_name = tmpl.name
            tmpl_owner = tmpl.owner_username
            _delete(template_id, session)

        pending_audit.append(dict(
            product="ZIA",
            operation="delete_template",
            action="DELETE",
            status="SUCCESS",
            resource_type="zia_template",
            resource_id=str(template_id),
            resource_name=tmpl_name,
            details={"owner": tmpl_owner},
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    for ev in pending_audit:
        audit_service.log(**ev)


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------

def _load_manageable(template_id: int, user: AuthUser, session):
    """Fetch a template the caller is allowed to re-share, or raise.

    404 when they cannot see it at all, 403 when they can see it but do not own
    it — the distinction is safe to make at that point, since they already know
    the template exists.
    """
    from services.template_service import get_template as _get
    from services import template_share_service as shares

    tmpl = _get(template_id, session)
    if not shares.can_read(tmpl, user.user_id, user.role, session):
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    if not shares.can_manage(tmpl, user.user_id, user.role):
        raise HTTPException(
            status_code=403, detail="Only the template's owner or an admin can share it"
        )
    return tmpl


@router.get("/{template_id}/shares")
def list_template_shares(
    template_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Who this template is shared with.  Owner or admin only."""
    from db.database import get_session
    from services import template_share_service as shares

    try:
        with get_session() as session:
            _load_manageable(template_id, user, session)
            return shares.list_shares(template_id, session)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{template_id}/shares", status_code=200)
def add_template_shares(
    template_id: int,
    req: TemplateShareRequest,
    user: AuthUser = Depends(require_auth),
):
    """Grant a template to users and/or groups.  Owner or admin only.

    200, not 201: the call is idempotent, and re-posting a grant that already
    exists is a no-op rather than a conflict — the UI grants from a checkbox
    list, where one stale box should not reject the rest of the selection.

    Sharing implies visibility='shared'; leaving it 'private' would create grants
    that can_read ignores, which reads as the feature being broken.
    """
    from db.database import get_session
    from services import template_share_service as shares, audit_service

    pending_audit = []
    try:
        with get_session() as session:
            tmpl = _load_manageable(template_id, user, session)
            try:
                created = shares.add_shares(
                    tmpl, req.user_ids, req.group_ids, user.username, session
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            if tmpl.visibility == "private":
                tmpl.visibility = "shared"
            tmpl.updated_at = datetime.utcnow()
            session.flush()
            all_shares = shares.list_shares(template_id, session)
            tmpl_name = tmpl.name

        if created:
            pending_audit.append(dict(
                product="ZIA",
                operation="share_template",
                action="UPDATE",
                status="SUCCESS",
                resource_type="zia_template",
                resource_id=str(template_id),
                resource_name=tmpl_name,
                details={
                    "granted_user_ids": [c["user_id"] for c in created if c["user_id"]],
                    "granted_group_ids": [c["group_id"] for c in created if c["group_id"]],
                },
            ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    for ev in pending_audit:
        audit_service.log(**ev)

    return all_shares


@router.delete("/{template_id}/shares/{share_id}", status_code=204)
def remove_template_share(
    template_id: int,
    share_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Revoke one grant.  Owner or admin only."""
    from db.database import get_session
    from services import template_share_service as shares, audit_service

    pending_audit = []
    try:
        with get_session() as session:
            tmpl = _load_manageable(template_id, user, session)
            removed = shares.remove_share(template_id, share_id, session)
            if removed is None:
                raise HTTPException(status_code=404, detail="Share not found")
            tmpl.updated_at = datetime.utcnow()
            tmpl_name = tmpl.name

        pending_audit.append(dict(
            product="ZIA",
            operation="unshare_template",
            action="UPDATE",
            status="SUCCESS",
            resource_type="zia_template",
            resource_id=str(template_id),
            resource_name=tmpl_name,
            details={
                "revoked_user_id": removed["user_id"],
                "revoked_group_id": removed["group_id"],
            },
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

    from services import template_share_service as shares

    check_tenant_access(tenant_id, user)

    with get_session() as session:
        tmpl = session.get(ZIATemplate, req.template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        if not shares.can_apply(tmpl, user.user_id, user.role, session):
            raise HTTPException(status_code=404, detail="Template not found")
        if req.wipe_mode and (tmpl.scope or "full") == "scoped":
            # Wipe deletes everything the template does not name, and a scoped
            # template names only a handful of resources on purpose — the pair
            # would empty the target tenant.  Rejected here rather than only
            # hidden in the UI, since the API is reachable without it.
            raise HTTPException(
                status_code=422,
                detail=(
                    "Wipe mode cannot be used with a scoped template: it would "
                    "delete every resource the template does not contain. Apply "
                    "it in merge mode, or use a full template."
                ),
            )
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

            # Per-resource audit entries — two separate log_many calls so wipe entries
            # get an earlier timestamp than push entries, matching the actual execution
            # order (wipe-before-push) and keeping "newest first" display correct.
            tmpl_ctx = {"template_id": req.template_id, "template_name": tmpl_name}

            wipe_audit: list = []
            for r in wipe_records:
                if r.is_deleted:
                    wipe_audit.append(dict(
                        product="ZIA", operation="apply_template", action="DELETE",
                        status="success", tenant_id=tenant_id,
                        resource_type=r.resource_type, resource_name=r.name,
                        details=tmpl_ctx,
                    ))
                elif r.is_failed:
                    wipe_audit.append(dict(
                        product="ZIA", operation="apply_template", action="DELETE",
                        status="failure", tenant_id=tenant_id,
                        resource_type=r.resource_type, resource_name=r.name,
                        details=tmpl_ctx,
                        error_message=r.status[len("failed:"):],
                    ))
            audit_service.log_many(wipe_audit)

            push_audit: list = []
            for r in push_records:
                if r.is_created or r.is_updated:
                    d = dict(tmpl_ctx)
                    if r.warnings:
                        d["warnings"] = r.warnings
                    push_audit.append(dict(
                        product="ZIA", operation="apply_template",
                        action="CREATE" if r.is_created else "UPDATE",
                        status="success", tenant_id=tenant_id,
                        resource_type=r.resource_type, resource_name=r.name,
                        details=d,
                    ))
                elif r.is_failed:
                    push_audit.append(dict(
                        product="ZIA", operation="apply_template",
                        action="CREATE",
                        status="failure", tenant_id=tenant_id,
                        resource_type=r.resource_type, resource_name=r.name,
                        details=tmpl_ctx,
                        error_message=r.failure_reason,
                    ))
            audit_service.log_many(push_audit)

            # Summary entry
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
