"""Scheduled sync engine — import → diff → push pipeline.

Runs as a plain synchronous function called by APScheduler's thread pool.
Must not be a coroutine.

Design: Option 3 from spec §9.5 — standalone diff that calls import service
and push methods directly, without coupling to ZIAPushService's interactive
state machine.  Uses _is_zscaler_managed(), _WRITE_METHODS, _DELETE_METHODS,
and PUSH_ORDER from zia_push_service for correct ordering and field handling.

client_secret is never logged or included in audit entries.
Audit entries are collected in a list and written after all sessions close.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from db.database import get_session
from db.models import ScheduledTask, TaskRunHistory, ZIAResource


# ---------------------------------------------------------------------------
# Label helper
# ---------------------------------------------------------------------------

def _has_label(raw_config: Dict, label_name: str) -> bool:
    """Return True if raw_config['labels'] contains an entry with name == label_name.

    Matching is case-sensitive. The labels field may be absent, None, or an empty
    list — all of which return False. Only dicts with a 'name' key are matched;
    entries without a 'name' key are skipped.
    """
    labels = raw_config.get("labels")
    if not labels:
        return False
    return any(
        isinstance(entry, dict) and entry.get("name") == label_name
        for entry in labels
    )


# ---------------------------------------------------------------------------
# Diff record
# ---------------------------------------------------------------------------

@dataclass
class _DiffRecord:
    resource_type: str
    name: str
    operation: str       # "create" | "update" | "delete"
    source_raw: Optional[Dict] = None   # None for deletes
    target_id: Optional[str] = None     # existing ID on target (update/delete)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_sync_task(task_id: int) -> Optional[TaskRunHistory]:
    """Execute one full import→diff→push cycle for a scheduled task.

    Called by APScheduler in a background thread.  Returns the completed
    TaskRunHistory, or None if the task is not found or not enabled.
    """
    # 1. Load task — quick read, session closed immediately
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None or not task.enabled:
            return None
        # Copy scalar fields out before session closes
        t_id = task.id
        t_name = task.name
        t_source = task.source_tenant_id
        t_target = task.target_tenant_id
        t_groups = list(task.resource_groups)
        t_sync_deletes = task.sync_deletes
        t_sync_mode = task.sync_mode or "resource_type"
        t_label_name = task.label_name
        t_label_resource_types = list(task.label_resource_types) if task.label_resource_types else None

    # 2. Create a "running" run record
    run_started = datetime.utcnow()
    run_id: int
    with get_session() as session:
        run = TaskRunHistory(
            task_id=t_id,
            started_at=run_started,
            status="running",
            resources_synced=0,
        )
        session.add(run)
        session.flush()
        run_id = run.id

    # 3. Expand resource groups to concrete resource_type strings
    if t_sync_mode == "label":
        from services.scheduled_task_service import LABEL_SUPPORTED_RESOURCE_TYPES
        resource_types = t_label_resource_types if t_label_resource_types else LABEL_SUPPORTED_RESOURCE_TYPES
    else:
        from services.scheduled_task_service import expand_resource_groups
        resource_types = expand_resource_groups(t_groups)

    errors: List[Dict[str, str]] = []
    synced = 0
    pending_audit: List[Dict] = []

    try:
        # 4. Build clients (sessions closed before clients are used)
        source_client = _build_zia_client(t_source)
        target_client = _build_zia_client(t_target)

        # 5. Import source state
        from services.zia_import_service import ZIAImportService
        ZIAImportService(source_client, tenant_id=t_source).run(
            resource_types=resource_types
        )

        # 6. Import target state
        ZIAImportService(target_client, tenant_id=t_target).run(
            resource_types=resource_types
        )

        # 7. Compute diff between source and target DB rows
        diff = _compute_diff(
            t_source, t_target, resource_types,
            sync_deletes=t_sync_deletes,
            label_name=t_label_name if t_sync_mode == "label" else None,
        )

        # 8. Push diff to target (best-effort)
        for rec in diff:
            try:
                _apply_one(target_client, t_target, rec)
                synced += 1
                pending_audit.append(dict(
                    tenant_id=t_target,
                    product="ZIA",
                    operation="scheduled_sync",
                    action=rec.operation.upper(),
                    status="SUCCESS",
                    resource_type=rec.resource_type,
                    resource_name=rec.name,
                    details={
                        "task_id": t_id,
                        "task_name": t_name,
                        "source_tenant_id": t_source,
                    },
                ))
            except Exception as exc:
                errors.append({
                    "resource_type": rec.resource_type,
                    "resource_name": rec.name,
                    "operation": rec.operation,
                    "error": str(exc),
                })
                pending_audit.append(dict(
                    tenant_id=t_target,
                    product="ZIA",
                    operation="scheduled_sync",
                    action=rec.operation.upper(),
                    status="FAILURE",
                    resource_type=rec.resource_type,
                    resource_name=rec.name,
                    details={
                        "task_id": t_id,
                        "task_name": t_name,
                        "source_tenant_id": t_source,
                    },
                    error_message=str(exc),
                ))

        # 9. Activate target if any resources were pushed
        if synced > 0:
            try:
                target_client.activate()
            except Exception as exc:
                errors.append({
                    "resource_type": "_activation",
                    "resource_name": "_activation",
                    "operation": "activate",
                    "error": str(exc),
                })

    except Exception as exc:
        errors.append({
            "resource_type": "_engine",
            "resource_name": "_engine",
            "operation": "run",
            "error": str(exc),
        })

    # 10. Write audit entries — all sessions from import/push are already closed
    from services import audit_service
    for entry in pending_audit:
        audit_service.log(**entry)

    # 11. Update run record
    finished_at = datetime.utcnow()
    if not errors:
        status = "success"
    elif synced > 0:
        status = "partial"
    else:
        status = "failed"

    with get_session() as session:
        run = session.get(TaskRunHistory, run_id)
        if run is not None:
            run.finished_at = finished_at
            run.status = status
            run.resources_synced = synced
            run.errors_json = errors if errors else None

    return run


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

def _build_zia_client(tenant_id: int):
    """Load tenant from DB, decrypt secret, return a ZIAClient.

    The session is closed before the client is returned.
    client_secret is never logged or stored in any audit entry.
    """
    from db.models import TenantConfig
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret

    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
        if t is None:
            raise ValueError(f"Tenant {tenant_id} not found or inactive.")
        zidentity = t.zidentity_base_url
        client_id = t.client_id
        secret = decrypt_secret(t.client_secret_enc)
        oneapi = t.oneapi_base_url
        govcloud = t.govcloud

    auth = ZscalerAuth(zidentity, client_id, secret, govcloud=govcloud)
    return ZIAClient(auth, oneapi)


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def _compute_diff(
    source_tenant_id: int,
    target_tenant_id: int,
    resource_types: List[str],
    sync_deletes: bool = False,
    label_name: Optional[str] = None,
) -> List[_DiffRecord]:
    """Compare source and target ZIAResource rows; return ordered diff list.

    Matching is by name (cross-tenant IDs differ).
    Config comparison uses config_hash (SHA-256 of sorted JSON).
    Zscaler-managed resources are excluded via _is_zscaler_managed().
    When label_name is set, only resources carrying that label are included.
    """
    from services.zia_push_service import _is_zscaler_managed, PUSH_ORDER

    diff: List[_DiffRecord] = []

    # Iterate in PUSH_ORDER so creates/updates are applied in dependency order.
    # Types not in PUSH_ORDER are appended after (should not normally occur for
    # the resource types in RESOURCE_GROUP_MAP).
    ordered_types = [rt for rt in PUSH_ORDER if rt in resource_types]
    remaining = [rt for rt in resource_types if rt not in ordered_types]
    all_types = ordered_types + remaining

    with get_session() as session:
        for rtype in all_types:
            # Source rows (non-deleted, same tenant)
            src_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=source_tenant_id, resource_type=rtype, is_deleted=False)
                .all()
            )
            # Target rows
            tgt_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=target_tenant_id, resource_type=rtype, is_deleted=False)
                .all()
            )

            # Build name-keyed maps
            src_by_name: Dict[str, ZIAResource] = {}
            for r in src_rows:
                if r.name and not _is_zscaler_managed(rtype, r.raw_config or {}):
                    src_by_name[r.name] = r

            tgt_by_name: Dict[str, ZIAResource] = {}
            for r in tgt_rows:
                if r.name and not _is_zscaler_managed(rtype, r.raw_config or {}):
                    tgt_by_name[r.name] = r

            # Filter to labelled resources only when label_name is specified.
            # _has_label() operates on already-loaded raw_config dicts — no new
            # session is opened here.
            if label_name is not None:
                src_by_name = {
                    name: r for name, r in src_by_name.items()
                    if _has_label(r.raw_config or {}, label_name)
                }
                tgt_by_name = {
                    name: r for name, r in tgt_by_name.items()
                    if _has_label(r.raw_config or {}, label_name)
                }

            # CREATE — in source, not in target
            for name, src in src_by_name.items():
                if name not in tgt_by_name:
                    diff.append(_DiffRecord(
                        resource_type=rtype,
                        name=name,
                        operation="create",
                        source_raw=copy.deepcopy(src.raw_config or {}),
                    ))

            # UPDATE — in both, different hash
            for name, src in src_by_name.items():
                if name in tgt_by_name:
                    tgt = tgt_by_name[name]
                    if src.config_hash != tgt.config_hash:
                        diff.append(_DiffRecord(
                            resource_type=rtype,
                            name=name,
                            operation="update",
                            source_raw=copy.deepcopy(src.raw_config or {}),
                            target_id=tgt.zia_id,
                        ))

            # DELETE — in target, not in source (only if sync_deletes=True)
            if sync_deletes:
                for name, tgt in tgt_by_name.items():
                    if name not in src_by_name:
                        diff.append(_DiffRecord(
                            resource_type=rtype,
                            name=name,
                            operation="delete",
                            target_id=tgt.zia_id,
                        ))

    return diff


# ---------------------------------------------------------------------------
# Apply a single diff record to the target
# ---------------------------------------------------------------------------

def _apply_one(target_client, target_tenant_id: int, rec: _DiffRecord) -> None:
    """Apply a single diff record to the target tenant.

    For creates: strips read-only fields and calls the SDK create method.
    For updates: strips read-only fields, injects target_id, calls update.
    For deletes: calls the SDK delete method.

    Raises on any failure — caller catches and logs to errors list.
    """
    from services.zia_push_service import (
        _WRITE_METHODS,
        _DELETE_METHODS,
        READONLY_FIELDS,
    )

    rtype = rec.resource_type

    if rec.operation == "delete":
        if rtype not in _DELETE_METHODS:
            raise ValueError(f"No delete method for {rtype}")
        delete_method_name = _DELETE_METHODS[rtype]
        if delete_method_name is None:
            # cloud_app_control_rule needs special handling — skip for now
            raise NotImplementedError(f"delete not implemented for {rtype} in sync engine")
        delete_method = getattr(target_client, delete_method_name)
        delete_method(rec.target_id)
        return

    if rtype not in _WRITE_METHODS:
        raise ValueError(f"No write method for {rtype}")

    create_method_name, update_method_name = _WRITE_METHODS[rtype]

    # Build a cleaned payload: strip read-only fields
    payload = {
        k: v for k, v in (rec.source_raw or {}).items()
        if k not in READONLY_FIELDS
    }
    # Strip 'id' field from creates (target assigns its own)
    if rec.operation == "create":
        payload.pop("id", None)

    if rec.operation == "create":
        create_method = getattr(target_client, create_method_name)
        create_method(payload)
    else:
        # update — inject the target's ID
        payload["id"] = rec.target_id
        update_method = getattr(target_client, update_method_name)
        update_method(rec.target_id, payload)
