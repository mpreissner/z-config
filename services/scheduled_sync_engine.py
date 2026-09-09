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
from typing import Any, Dict, List, Optional, Set, Tuple

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
# Config normalization for cross-tenant equality checks
# ---------------------------------------------------------------------------

# Fields that are tenant-specific and must be excluded when comparing whether
# two resource configs are functionally identical across tenants.
# Mirrors READONLY_FIELDS in zia_push_service plus any extras found in the wild.
_COMPARE_STRIP = frozenset({
    "id", "predefined", "last_modified_by", "last_modified_time", "last_mod_time",
    "created_by", "creation_time", "created_at", "updated_at", "modified_time",
    "modified_by", "last_modified_by_user", "is_deleted", "db_category_index",
    "deleted", "default_rule", "access_control", "managed_by",
    # cloud_app_instance: instance_id is the tenant-local PK (top level and inside
    # every instance_identifiers entry) and modified_at is server-assigned.  Both
    # differ on every tenant, so leaving them in makes each run re-update the
    # instance forever.  _norm_for_compare filters these keys at every depth.
    "instance_id", "modified_at",
})


def _norm_for_compare(obj: Any, _top_level: bool = True) -> Any:
    """Return a normalised copy of a resource config suitable for equality checks.

    - Strips all fields in _COMPARE_STRIP (tenant-specific IDs, timestamps, etc.).
    - For nested reference objects that carry a 'name' key, strips 'id' so
      comparison is by name only (cross-tenant IDs always differ for the same
      logical resource).
    - Lists of named objects are sorted by name; lists of unnamed dicts (e.g.
      port ranges) are sorted by their JSON representation for stable comparison.
    """
    if isinstance(obj, dict):
        result = {k: _norm_for_compare(v, _top_level=False) for k, v in obj.items() if k not in _COMPARE_STRIP}
        if not _top_level and "id" in obj and "name" in obj:
            result.pop("id", None)
        return result
    if isinstance(obj, list):
        import json as _json
        items = [_norm_for_compare(i, _top_level=False) for i in obj]
        if items and isinstance(items[0], dict):
            if "name" in items[0]:
                items = sorted(items, key=lambda x: str(x.get("name", "")))
            else:
                items = sorted(items, key=lambda x: _json.dumps(x, sort_keys=True))
        return items
    return obj


# Fields excluded from content fingerprinting so that rules differing only in
# name or position are still recognised as the same logical rule.
_MATCH_EXCLUDE = frozenset({"name", "order", "rank"})


def _content_fingerprint(raw_config: dict) -> str:
    """Stable content fingerprint excluding name, order, and rank.

    Used for content-first matching across tenants: two rules with the same
    logical behaviour but different names or positions hash to the same value.
    """
    import json
    stripped = {k: v for k, v in raw_config.items() if k not in _MATCH_EXCLUDE}
    return json.dumps(_norm_for_compare(stripped), sort_keys=True)


def _configs_equal(a: dict, b: dict) -> bool:
    """Return True if two raw resource configs are functionally identical."""
    import json
    return json.dumps(_norm_for_compare(a), sort_keys=True) == json.dumps(_norm_for_compare(b), sort_keys=True)


# ---------------------------------------------------------------------------
# License comparison helper
# ---------------------------------------------------------------------------

def _compare_subscriptions(src_subs: Any, tgt_subs: Any) -> Optional[str]:
    """Return a warning string if src and tgt subscription data differ, else None.

    Handles both array-of-feature-objects and {features: [...]} shapes.
    Falls back to a generic mismatch message if neither structure is recognized.
    """
    import json

    if not src_subs or not tgt_subs:
        return None
    if json.dumps(src_subs, sort_keys=True) == json.dumps(tgt_subs, sort_keys=True):
        return None

    def _extract(subs: Any):
        arr = subs if isinstance(subs, list) else (subs.get("features") if isinstance(subs, dict) else None)
        if not isinstance(arr, list):
            return None
        return {(f.get("name") if isinstance(f, dict) else str(f)) for f in arr if f}

    src_feats = _extract(src_subs)
    tgt_feats = _extract(tgt_subs)

    if src_feats is not None and tgt_feats is not None:
        only_src = sorted(src_feats - tgt_feats)
        only_tgt = sorted(tgt_feats - src_feats)
        parts = []
        if only_src:
            parts.append(f"source-only: {', '.join(only_src)}")
        if only_tgt:
            parts.append(f"target-only: {', '.join(only_tgt)}")
        return f"Subscription mismatch — {'; '.join(parts)}" if parts else None

    return "Subscription data differs between source and target tenants"


# ---------------------------------------------------------------------------
# Diff record
# ---------------------------------------------------------------------------

def _blocking(errors: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Entries that should count against a run's status.

    The dependency closure records what it pulled in as an INFO entry, because an
    operator needs to see which objects arrived and why.  That is the feature
    working, not a degradation, so it must not push every dependency-carrying run
    to "partial".  INFO entries stay in errors_json and are shown; they just do not
    decide status.
    """
    return [e for e in errors if not str(e.get("error", "")).startswith("INFO:")]


@dataclass
class _DiffRecord:
    resource_type: str
    name: str
    operation: str       # "create" | "update" | "delete"
    source_raw: Optional[Dict] = None   # None for deletes
    target_id: Optional[str] = None     # existing ID on target (update/delete)
    target_raw: Optional[Dict] = None   # target's raw_config; set on deletes, where
                                        # source_raw is None but the delete call still
                                        # needs type-specific args (e.g. rule_type)
    pulled_in_by: Optional[str] = None  # name of the selected rule that required this
                                        # object; None means it was selected directly


# ---------------------------------------------------------------------------
# Apply ordering
# ---------------------------------------------------------------------------

def _push_order_index() -> Dict[str, int]:
    """resource_type → its index in PUSH_ORDER (the dependency tier sequence).

    zia_push_service is imported lazily, matching the rest of this module, which
    keeps the import graph acyclic.
    """
    from services.zia_push_service import PUSH_ORDER
    return {rt: i for i, rt in enumerate(PUSH_ORDER)}


def _sort_content_batch(records: List[_DiffRecord]) -> None:
    """Sort create/update/rename records in place, dependency tier first.

    Keying the sort on the resource_type *string* alphabetises the types, which
    puts dependents ahead of the things they depend on: "cloud_app_control_rule"
    sorts before "cloud_app_instance", "firewall_rule" before "ip_source_group".
    A rule applied before its referenced object loses that reference and is
    stripped, self-healing only on a later run.  Key on the PUSH_ORDER index
    instead.

    Types absent from PUSH_ORDER sort last, which is where they land today.
    resource_type stays as a secondary key so records of one type remain grouped,
    and the source `order` as a tertiary key so creates within a type keep the
    ascending sequence the order_tracker depends on.
    """
    index = _push_order_index()
    fallback = len(index)

    def _key(rec: _DiffRecord):
        tier = index.get(rec.resource_type, fallback)
        if rec.operation != "create":
            return (tier, rec.resource_type, float("inf"))
        return (tier, rec.resource_type, (rec.source_raw or {}).get("order", float("inf")))

    records.sort(key=_key)


def _sort_delete_batch(records: List[_DiffRecord]) -> None:
    """Sort delete records in place into reverse PUSH_ORDER.

    ZIA refuses to delete a resource another resource still references, so the
    referencing rule has to be deleted first — the mirror of _sort_content_batch.
    """
    index = _push_order_index()
    fallback = len(index)
    records.sort(key=lambda rec: (-index.get(rec.resource_type, fallback), rec.resource_type))


# ---------------------------------------------------------------------------
# Public entry point — dispatches by task_type
# ---------------------------------------------------------------------------

def run_task(task_id: int) -> Optional[TaskRunHistory]:
    """Dispatch to the correct engine path based on task_type.

    Called by APScheduler. Returns the completed TaskRunHistory (parent row
    for fan-out sync, single row for single-target sync and import).
    """
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None or not task.enabled:
            return None
        task_type = task.task_type or "sync"
        target_tenant_ids = list(task.target_tenant_ids) if task.target_tenant_ids else None

    if task_type == "import":
        return _run_import_task(task_id)
    elif target_tenant_ids and len(target_tenant_ids) > 1:
        return _run_fanout_sync_task(task_id, target_tenant_ids)
    else:
        return _run_single_sync_task(task_id)


# ---------------------------------------------------------------------------
# Import task
# ---------------------------------------------------------------------------

def _run_import_task(task_id: int) -> Optional[TaskRunHistory]:
    """Run scheduled import for one or more products against the source tenant.

    No diff, no push, no activation — only pulls remote state into local DB.
    """
    # 1. Load task
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None or not task.enabled:
            return None
        t_id = task.id
        t_name = task.name
        t_source = task.source_tenant_id
        t_products = list(task.import_products) if task.import_products else []

    # 2. Create "running" run record — target_tenant_id is NULL for import tasks
    run_started = datetime.utcnow()
    run_id: int
    with get_session() as session:
        run = TaskRunHistory(
            task_id=t_id,
            started_at=run_started,
            status="running",
            resources_synced=0,
            target_tenant_id=None,
        )
        session.add(run)
        session.flush()
        run_id = run.id

    errors: List[Dict[str, str]] = []
    pending_audit: List[Dict] = []
    total_synced = 0
    products_succeeded = 0
    products_attempted = 0

    # 3. Run each product import in order
    for product in t_products:
        products_attempted += 1
        product_error: Optional[str] = None
        product_synced = 0
        try:
            client = _build_client(t_source, product)

            if product == "ZIA":
                from services.zia_import_service import ZIAImportService
                sync_log = ZIAImportService(client, tenant_id=t_source).run()
            elif product == "ZPA":
                from services.zpa_import_service import ZPAImportService
                sync_log = ZPAImportService(client, tenant_id=t_source).run()
            elif product == "ZCC":
                from services.zcc_import_service import ZCCImportService
                sync_log = ZCCImportService(client, tenant_id=t_source).run()
            else:
                raise ValueError(f"Unknown product: '{product}'")

            product_synced = sync_log.resources_synced if sync_log else 0
            total_synced += product_synced
            products_succeeded += 1

        except Exception as exc:
            product_error = str(exc)
            errors.append({
                "resource_type": "_import",
                "resource_name": product,
                "operation": "import",
                "error": product_error,
            })

        # 4. Collect audit entry for this product
        pending_audit.append(dict(
            tenant_id=t_source,
            product=product,
            operation="scheduled_import",
            action="IMPORT",
            status="FAILURE" if product_error else "SUCCESS",
            resource_type="_import",
            resource_name=product,
            details={"task_id": t_id, "task_name": t_name},
        ))

    # 5. Write all audit entries after all sessions close
    from services import audit_service
    for entry in pending_audit:
        audit_service.log(**entry)

    # 6. Update run record
    finished_at = datetime.utcnow()
    if not errors:
        status = "success"
    elif products_succeeded > 0:
        status = "partial"
    else:
        status = "failed"

    with get_session() as session:
        run = session.get(TaskRunHistory, run_id)
        if run is not None:
            run.finished_at = finished_at
            run.status = status
            run.resources_synced = total_synced
            run.errors_json = errors if errors else None

    return run


# ---------------------------------------------------------------------------
# Fan-out sync task
# ---------------------------------------------------------------------------

def _run_fanout_sync_task(task_id: int, target_tenant_ids: List[int]) -> Optional[TaskRunHistory]:
    """Fan out a sync run to multiple target tenants.

    Creates a parent TaskRunHistory row and one child row per target.
    All targets run regardless of earlier failures (fail-open).
    """
    # 1. Load task
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None or not task.enabled:
            return None
        t_id = task.id
        t_name = task.name
        t_source = task.source_tenant_id
        t_groups = list(task.resource_groups) if task.resource_groups else []
        t_sync_deletes = task.sync_deletes
        t_sync_mode = task.sync_mode or "resource_type"
        t_label_name = task.label_name
        t_label_resource_types = list(task.label_resource_types) if task.label_resource_types else None

    # 2. Create parent run record
    run_started = datetime.utcnow()
    parent_run_id: int
    with get_session() as session:
        parent_run = TaskRunHistory(
            task_id=t_id,
            started_at=run_started,
            status="running",
            resources_synced=0,
            parent_run_id=None,
            target_tenant_id=None,
        )
        session.add(parent_run)
        session.flush()
        parent_run_id = parent_run.id

    # Accumulators across all targets
    all_pending_audit: List[Dict] = []
    child_results: List[tuple] = []  # (child_status, child_synced)

    # 3. Run pipeline for each target
    for target_id in target_tenant_ids:
        # 3a. Create child run record
        child_run_id: int
        with get_session() as session:
            child_run = TaskRunHistory(
                task_id=t_id,
                started_at=datetime.utcnow(),
                status="running",
                resources_synced=0,
                parent_run_id=parent_run_id,
                target_tenant_id=target_id,
            )
            session.add(child_run)
            session.flush()
            child_run_id = child_run.id

        # 3b. Load source/target metadata for this pair
        from db.models import TenantConfig
        t_source_zia_id: Optional[str] = None
        t_license_warning: Optional[str] = None
        with get_session() as session:
            src_tenant = session.get(TenantConfig, t_source)
            tgt_tenant = session.get(TenantConfig, target_id)
            t_source_zia_id = (
                str(src_tenant.zia_tenant_id)
                if src_tenant and src_tenant.zia_tenant_id
                else None
            )
            t_license_warning = _compare_subscriptions(
                src_tenant.zia_subscriptions if src_tenant else None,
                tgt_tenant.zia_subscriptions if tgt_tenant else None,
            )

        # 3c. Run pipeline
        child_synced, child_errors, child_audit = _execute_sync_pipeline(
            task_id=t_id,
            t_name=t_name,
            t_source=t_source,
            t_target=target_id,
            t_groups=t_groups,
            t_sync_deletes=t_sync_deletes,
            t_sync_mode=t_sync_mode,
            t_label_name=t_label_name,
            t_label_resource_types=t_label_resource_types,
            t_source_zia_id=t_source_zia_id,
            t_license_warning=t_license_warning,
        )
        all_pending_audit.extend(child_audit)

        # 3d. Compute child status and update child row
        if not _blocking(child_errors):
            child_status = "success"
        elif child_synced > 0:
            child_status = "partial"
        else:
            child_status = "failed"

        child_results.append((child_status, child_synced))

        with get_session() as session:
            child = session.get(TaskRunHistory, child_run_id)
            if child is not None:
                child.finished_at = datetime.utcnow()
                child.status = child_status
                child.resources_synced = child_synced
                child.errors_json = child_errors if child_errors else None

    # 4. Write all collected audit entries after all child sessions close
    from services import audit_service
    for entry in all_pending_audit:
        audit_service.log(**entry)

    # 5. Compute parent rollup
    finished_at = datetime.utcnow()
    total_synced = sum(s for st, s in child_results if st != "failed")

    all_success = all(st == "success" for st, _ in child_results)
    all_failed  = all(st == "failed"  for st, _ in child_results)

    if all_success:
        parent_status = "success"
    elif all_failed:
        parent_status = "failed"
    else:
        parent_status = "partial"

    with get_session() as session:
        parent = session.get(TaskRunHistory, parent_run_id)
        if parent is not None:
            parent.finished_at = finished_at
            parent.status = parent_status
            parent.resources_synced = total_synced
            parent.errors_json = None  # errors are on child rows

    return parent


# ---------------------------------------------------------------------------
# Single-target sync task (renamed from run_sync_task)
# ---------------------------------------------------------------------------

def _run_single_sync_task(task_id: int) -> Optional[TaskRunHistory]:
    """Execute one full import→diff→push cycle for a single-target scheduled task.

    Called by run_task for single-target sync. Returns the completed
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
        t_groups = list(task.resource_groups) if task.resource_groups else []
        t_sync_deletes = task.sync_deletes
        t_sync_mode = task.sync_mode or "resource_type"
        t_label_name = task.label_name
        t_label_resource_types = list(task.label_resource_types) if task.label_resource_types else None

    # 1b. Load source and target tenant metadata
    from db.models import TenantConfig
    t_license_warning: Optional[str] = None
    with get_session() as session:
        src_tenant = session.get(TenantConfig, t_source)
        tgt_tenant = session.get(TenantConfig, t_target)
        t_source_zia_id = (
            str(src_tenant.zia_tenant_id)
            if src_tenant and src_tenant.zia_tenant_id
            else None
        )
        t_license_warning = _compare_subscriptions(
            src_tenant.zia_subscriptions if src_tenant else None,
            tgt_tenant.zia_subscriptions if tgt_tenant else None,
        )

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

    # 3–10. Run the full sync pipeline
    synced, errors, pending_audit = _execute_sync_pipeline(
        task_id=t_id,
        t_name=t_name,
        t_source=t_source,
        t_target=t_target,
        t_groups=t_groups,
        t_sync_deletes=t_sync_deletes,
        t_sync_mode=t_sync_mode,
        t_label_name=t_label_name,
        t_label_resource_types=t_label_resource_types,
        t_source_zia_id=t_source_zia_id,
        t_license_warning=t_license_warning,
    )

    # 11. Write audit entries — all sessions from import/push are already closed
    from services import audit_service
    for entry in pending_audit:
        audit_service.log(**entry)

    # 12. Update run record
    finished_at = datetime.utcnow()
    if not _blocking(errors):
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
# Shared sync pipeline (extracted from former run_sync_task body)
# ---------------------------------------------------------------------------

def _execute_sync_pipeline(
    task_id: int,
    t_name: str,
    t_source: int,
    t_target: int,
    t_groups: List[str],
    t_sync_deletes: bool,
    t_sync_mode: str,
    t_label_name: Optional[str],
    t_label_resource_types: Optional[List[str]],
    t_source_zia_id: Optional[str],
    t_license_warning: Optional[str],
) -> tuple:
    """Run the full sync pipeline for one (source, target) pair.

    Returns (resources_synced, errors, pending_audit).
    Never raises — all exceptions are caught and appended to errors.
    """
    # 3. Expand resource groups to concrete resource_type strings
    if t_sync_mode == "label":
        from services.scheduled_task_service import LABEL_SUPPORTED_RESOURCE_TYPES
        resource_types = t_label_resource_types if t_label_resource_types else LABEL_SUPPORTED_RESOURCE_TYPES
    else:
        from services.scheduled_task_service import expand_resource_groups
        resource_types = expand_resource_groups(t_groups)

    errors: List[Dict[str, str]] = []
    if t_license_warning:
        errors.append({
            "resource_type": "system",
            "resource_name": "license_check",
            "operation": "license_comparison",
            "error": f"WARNING: {t_license_warning}",
        })
    synced = 0
    pending_audit: List[Dict] = []
    # Fresh order_tracker per pipeline call — not shared across fan-out targets
    order_tracker: Dict[str, int] = {}
    # Same lifetime, same fan-out isolation: resources created during this run,
    # as rtype → {name.lower(): target_id}, so a rule can resolve a reference to
    # something created after the target snapshot was imported.
    created_ids: Dict[str, Dict[str, str]] = {}

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

        # 6a. Close over the selected rules' dependencies.  Selecting a rule without
        # the types it references lands it on the target with those references
        # dropped — widened to Any, or disabled.  Pull the required objects into the
        # job so the rule arrives intact.
        label_for_diff = t_label_name if t_sync_mode == "label" else None
        # The walk can only follow a reference into a type whose source rows are
        # current, and step 5 imported the selected types only.  Import what the
        # walk asks for and walk again — the second pass reaches the depth-2 edges
        # (a service group's services) that the first could not see.  Bounded by
        # the same depth limit; in practice it settles in two rounds.
        loaded = set(resource_types)
        pulled: Dict[str, Set[str]] = {}
        origin: Dict[Tuple[str, str], str] = {}
        closure_warnings: List[str] = []
        resolve_only: Set[str] = set()
        for _ in range(_CLOSURE_MAX_DEPTH):
            pulled, origin, closure_warnings, missing, round_resolve = _close_over(
                t_source, resource_types, label_for_diff, loaded
            )
            resolve_only |= round_resolve
            to_load = sorted(missing - loaded)
            if not to_load:
                break
            ZIAImportService(source_client, tenant_id=t_source).run(
                resource_types=to_load
            )
            loaded |= set(to_load)
        all_types = list(resource_types)
        if pulled:
            # 6b. A pulled-in type was not in the import above, so its rows are stale
            # or absent for both tenants.  The added API cost is bounded by the
            # number of types pulled in, not the number of objects.
            new_types = [rt for rt in pulled if rt not in all_types]
            all_types = all_types + new_types
            if new_types:
                # Source rows for these are already current from the walk loop; the
                # target has never been imported for them.
                ZIAImportService(target_client, tenant_id=t_target).run(
                    resource_types=new_types
                )
            listed = [
                f"{rt} '{n}' (for '{origin.get((rt, n), '?')}')"
                for rt in sorted(pulled) for n in sorted(pulled[rt])
            ]
            # errors_json is rendered in the run-history UI; a closure over a large
            # rule set can run to hundreds of entries, so name the first 20 and count
            # the rest.  The audit log carries the full per-object attribution.
            summary = ", ".join(listed[:20])
            if len(listed) > 20:
                summary += f", and {len(listed) - 20} more"
            errors.append({
                "resource_type": "system",
                "resource_name": "dependency_closure",
                "operation": "closure",
                "error": f"INFO: included {sum(len(v) for v in pulled.values())} "
                         f"dependencies required by the selected rules: {summary}",
            })
        for warning in closure_warnings:
            errors.append({
                "resource_type": "system",
                "resource_name": "dependency_closure",
                "operation": "closure",
                "error": f"WARNING: {warning}",
            })

        # 6c. Refresh the target's rows for the resolve-only types these rules point
        # at.  Steps 5, 6 and 6b import the selected types and the types the closure
        # replicates; a location, group or department is neither, so nothing in the
        # run had ever refreshed it and _remap_refs resolved rule scope by name
        # against whatever an earlier import happened to leave behind.  A row that
        # has since been deleted on the target resolves to a dead ID and the API
        # rejects the rule; worse, an ID the target has since reassigned resolves to
        # a live object that is not the one the operator scoped to, and the rule
        # lands silently pointing at it.  Neither is recoverable from the source
        # side, so refresh before diffing.
        #
        # These are the types the closure deliberately will not replicate, and user
        # and group can run to tens of thousands of rows — which is why this imports
        # only the types a selected rule actually references, and only on the target.
        # The source side does not need them: a rule's own reference arrays carry
        # the names, which is what the remap resolves through.
        if resolve_only:
            from services.zia_import_service import RESOURCE_DEFINITIONS
            importable = {d.resource_type for d in RESOURCE_DEFINITIONS}
            # Widen through the companion map for the same reason _ref_name_index
            # does: the remap resolves a location name against location_lite rows
            # too, so refreshing only `location` leaves the other half stale and the
            # dead ID still answers.
            wanted_refresh = set(resolve_only)
            for primary, companions in _REF_TYPE_COMPANIONS.items():
                if primary in wanted_refresh:
                    wanted_refresh.update(companions)
            to_refresh = sorted(wanted_refresh & importable)
            skipped = sorted(resolve_only - importable)
            if to_refresh:
                ZIAImportService(target_client, tenant_id=t_target).run(
                    resource_types=to_refresh
                )
            if skipped:
                errors.append({
                    "resource_type": "system",
                    "resource_name": "reference_refresh",
                    "operation": "closure",
                    "error": "WARNING: the selected rules reference "
                             + ", ".join(skipped)
                             + ", which cannot be imported; those references are "
                               "resolved against whatever the target snapshot holds "
                               "and may be stale",
                })

        # 7. Compute diff between source and target DB rows
        diff = _compute_diff(
            t_source, t_target, all_types,
            sync_deletes=t_sync_deletes,
            label_name=label_for_diff,
            type_scope={rt: names for rt, names in pulled.items()
                        if rt not in resource_types},
            sync_delete_types=set(resource_types),
            origin=origin,
        )

        # 8. Split diff into phases:
        #    phase 1 — create / update / rename  (content operations)
        #    phase 2 — delete   (reverse dependency order)
        #    phase 3 — reorder  (positional, last)
        #
        # Deletes are split out of phase 1 rather than mixed into it: a resource
        # that is still referenced cannot be deleted, so a rule has to be removed
        # before the object it points at, which is the opposite of the create
        # ordering.  They run after phase 1 for that reason — an update that drops
        # a reference has to land before the referent goes away.
        #
        # Deletes run *before* the reorder phase because a delete is addressed by
        # target_id and is position-independent, while a reorder writes an absolute
        # position taken from the source.  Removing a rule compacts every position
        # below it, so a reorder applied first would be silently shifted up by each
        # later delete above it.  Deleting first makes the target's membership match
        # the source's, which is the list the source `order` values are numbered
        # against.
        content = [r for r in diff if r.operation not in ("reorder", "delete")]
        deletes = [r for r in diff if r.operation == "delete"]
        reorders = [r for r in diff if r.operation == "reorder"]

        _sort_content_batch(content)
        _sort_delete_batch(deletes)

        def _apply_batch(batch):
            nonlocal synced
            for rec in batch:
                try:
                    _apply_one(target_client, t_target, t_source, rec,
                               source_zia_id=t_source_zia_id,
                               order_tracker=order_tracker,
                               created_ids=created_ids,
                               warning_sink=errors)
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
                            "task_id": task_id,
                            "task_name": t_name,
                            "source_tenant_id": t_source,
                            **({"pulled_in_by": rec.pulled_in_by} if rec.pulled_in_by else {}),
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
                            "task_id": task_id,
                            "task_name": t_name,
                            "source_tenant_id": t_source,
                            **({"pulled_in_by": rec.pulled_in_by} if rec.pulled_in_by else {}),
                        },
                        error_message=str(exc),
                    ))

        _apply_batch(content)
        _apply_batch(deletes)
        _apply_batch(reorders)

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

        # 10. Re-import target for the affected resource types so the DB reflects
        # the actual post-push state (real API-assigned order values, etc.).
        try:
            ZIAImportService(target_client, tenant_id=t_target).run(
                resource_types=all_types
            )
        except Exception as exc:
            errors.append({
                "resource_type": "_post_push_import",
                "resource_name": "_post_push_import",
                "operation": "import",
                "error": str(exc),
            })

    except Exception as exc:
        errors.append({
            "resource_type": "_engine",
            "resource_name": "_engine",
            "operation": "run",
            "error": str(exc),
        })

    return synced, errors, pending_audit


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

def _build_client(tenant_id: int, product: str):
    """Load tenant from DB and return the appropriate product client.

    client_secret is never logged or stored.
    Session is closed before the client is returned.
    """
    from db.models import TenantConfig
    from lib.auth import ZscalerAuth
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
        gov_tier = t.gov_cloud_tier
        zpa_customer_id = t.zpa_customer_id
        zpa_tenant_cloud = t.zpa_tenant_cloud
        zia_cloud = t.zia_cloud
        zia_tenant_id = t.zia_tenant_id

    auth = ZscalerAuth(zidentity, client_id, secret, govcloud=govcloud, gov_tier=gov_tier)

    if product == "ZIA":
        from lib.zia_client import ZIAClient
        return ZIAClient(auth, oneapi)
    elif product == "ZPA":
        if not zpa_customer_id:
            raise ValueError("ZPA requires zpa_customer_id")
        from lib.zpa_client import ZPAClient
        return ZPAClient(auth, zpa_customer_id, oneapi)
    elif product == "ZCC":
        from lib.zcc_client import ZCCClient
        return ZCCClient(auth, oneapi, zia_cloud=zia_cloud, zia_tenant_id=zia_tenant_id)
    else:
        raise ValueError(f"Unknown product: '{product}'")


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
        gov_tier = t.gov_cloud_tier

    auth = ZscalerAuth(zidentity, client_id, secret, govcloud=govcloud, gov_tier=gov_tier)
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
    type_scope: Optional[Dict[str, Set[str]]] = None,
    sync_delete_types: Optional[Set[str]] = None,
    origin: Optional[Dict[Tuple[str, str], str]] = None,
) -> List[_DiffRecord]:
    """Compare source and target ZIAResource rows; return ordered diff list.

    Matching is content-first: each source rule is matched against the target by
    its content fingerprint (config normalised without name/order/rank) before
    falling back to name.  This produces four operation types:

      create  — no target match by content or name
      update  — name match found but content differs
      rename  — content match found under a different name
      reorder — content+name match but order/rank value differs

    Reorder records are appended after all content operations so callers can
    process them in a second phase once all rules exist on the target.

    Zscaler-managed resources are excluded via _is_zscaler_managed().
    When label_name is set, only source rules carrying that label are synced;
    deletes are also scoped to labelled target rules.

    type_scope restricts a type to a named set of source objects instead of diffing
    every row of it.  Dependency-pulled types are scoped this way: a rule needing
    one network service must not drag every network service on the tenant along
    with it.  A type absent from type_scope is unscoped, which is the existing
    behavior for everything the operator selected directly.

    sync_delete_types limits deletes to the explicitly-selected types.  A pulled-in
    type must never produce one: an unscoped delete pass over network_service,
    added to the job because a single rule referenced one, would reap every target
    network service the source lacks — including those belonging to target-local
    rules that have nothing to do with this task.  None preserves today's behavior
    for existing callers.

    origin supplies the seed rule name recorded on each pulled-in record, so an
    audit row can say which rule caused the object to appear.
    """
    from services.zia_push_service import _is_zscaler_managed, PUSH_ORDER

    content_diff: List[_DiffRecord] = []  # create / update / rename / delete
    reorder_diff: List[_DiffRecord] = []  # reorder (processed after content)

    ordered_types = [rt for rt in PUSH_ORDER if rt in resource_types]
    remaining = [rt for rt in resource_types if rt not in ordered_types]
    all_types = ordered_types + remaining

    with get_session() as session:
        for rtype in all_types:
            src_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=source_tenant_id, resource_type=rtype, is_deleted=False)
                .all()
            )
            tgt_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=target_tenant_id, resource_type=rtype, is_deleted=False)
                .all()
            )

            # Source: name → row
            src_by_name: Dict[str, ZIAResource] = {}
            for r in src_rows:
                nm = _resource_name(r)
                if nm and not _is_zscaler_managed(rtype, r.raw_config or {}):
                    src_by_name[nm] = r

            # Target: name → [all rows]  and  content_fingerprint → [all rows]
            tgt_by_name_all: Dict[str, List[ZIAResource]] = {}
            tgt_by_content: Dict[str, List[ZIAResource]] = {}
            for r in tgt_rows:
                nm = _resource_name(r)
                if nm and not _is_zscaler_managed(rtype, r.raw_config or {}):
                    tgt_by_name_all.setdefault(nm, []).append(r)
                    ck = _content_fingerprint(r.raw_config or {})
                    tgt_by_content.setdefault(ck, []).append(r)

            scoped = type_scope is not None and rtype in type_scope

            # Label filtering: restrict source to labelled rules; deletes are
            # scoped to labelled target rules only (tgt_labelled_names).
            #
            # A pulled-in type is never label-supported — a network_service carries
            # no labels field — so applying the label filter to one would empty it
            # and the closure would achieve nothing.  A type is filtered by label or
            # scoped by identity, never both: the seed rules are chosen by label,
            # their dependencies by reference.
            if label_name is not None and not scoped:
                src_by_name = {
                    name: r for name, r in src_by_name.items()
                    if _has_label(r.raw_config or {}, label_name)
                }
                tgt_labelled_names = {
                    name
                    for name, rows in tgt_by_name_all.items()
                    if any(_has_label(r.raw_config or {}, label_name) for r in rows)
                }
            else:
                tgt_labelled_names = set(tgt_by_name_all.keys())

            # Dependency-pulled types carry only the identities the selected rules
            # actually referenced.
            if scoped:
                allowed = type_scope[rtype]
                src_by_name = {n: r for n, r in src_by_name.items() if n in allowed}

            # Track claimed target zia_ids to prevent double-matching.
            claimed: set = set()

            for name, src in src_by_name.items():
                src_ck = _content_fingerprint(src.raw_config or {})
                src_order = (src.raw_config or {}).get("order")
                content_matches = tgt_by_content.get(src_ck, [])

                # 1. Content match with same name → no-op or reorder
                same_name = next(
                    (r for r in content_matches if r.name == name and r.zia_id not in claimed),
                    None,
                )
                if same_name:
                    claimed.add(same_name.zia_id)
                    tgt_order = (same_name.raw_config or {}).get("order")
                    if src_order is not None and src_order != tgt_order:
                        reorder_diff.append(_DiffRecord(
                            resource_type=rtype, name=name, operation="reorder",
                            source_raw=copy.deepcopy(src.raw_config or {}),
                            pulled_in_by=(origin or {}).get((rtype, name)) if scoped else None,
                            target_id=same_name.zia_id,
                        ))
                    continue

                # 2. Content match with different name → rename
                diff_name = next(
                    (r for r in content_matches if r.zia_id not in claimed),
                    None,
                )
                if diff_name:
                    claimed.add(diff_name.zia_id)
                    content_diff.append(_DiffRecord(
                        resource_type=rtype, name=name, operation="rename",
                        source_raw=copy.deepcopy(src.raw_config or {}),
                        pulled_in_by=(origin or {}).get((rtype, name)) if scoped else None,
                        target_id=diff_name.zia_id,
                    ))
                    continue

                # 3. Name match but content differs → update
                name_match = next(
                    (r for r in tgt_by_name_all.get(name, []) if r.zia_id not in claimed),
                    None,
                )
                if name_match:
                    claimed.add(name_match.zia_id)
                    content_diff.append(_DiffRecord(
                        resource_type=rtype, name=name, operation="update",
                        source_raw=copy.deepcopy(src.raw_config or {}),
                        pulled_in_by=(origin or {}).get((rtype, name)) if scoped else None,
                        target_id=name_match.zia_id,
                    ))
                    continue

                # 4. No match → create
                content_diff.append(_DiffRecord(
                    resource_type=rtype, name=name, operation="create",
                    source_raw=copy.deepcopy(src.raw_config or {}),
                    pulled_in_by=(origin or {}).get((rtype, name)) if scoped else None,
                ))

            # DELETE — unclaimed labelled target rows not matched by any source rule.
            # Never for a pulled-in type: see sync_delete_types in the docstring.
            if sync_deletes and (sync_delete_types is None or rtype in sync_delete_types):
                for del_name in tgt_labelled_names:
                    for r in tgt_by_name_all.get(del_name, []):
                        if r.zia_id not in claimed:
                            content_diff.append(_DiffRecord(
                                resource_type=rtype, name=del_name, operation="delete",
                                target_id=r.zia_id,
                                target_raw=copy.deepcopy(r.raw_config or {}),
                            ))

    return content_diff + reorder_diff


# ---------------------------------------------------------------------------
# Payload normalisation for sync engine
# ---------------------------------------------------------------------------

# Arrays of embedded objects that the API accepts only as [{id}].
_REF_FIELDS: frozenset = frozenset({
    "locations", "location_groups",
    "groups", "departments", "users",
    "devices", "device_groups",
    "source_ip_groups", "dest_ip_groups",
    "src_ip_groups", "src_ipv6_groups", "dest_ipv6_groups",
    "workload_groups", "proxy_gateways",
    "time_windows", "labels",
    "nw_services", "nw_service_groups",
    # A network_svc_group's member services.  The SDK models this field on exactly one
    # resource, so the name is unambiguous.  Note the write path takes it as
    # service_ids; the wire key is services either way.
    "services",
    "nw_applications", "nw_application_groups",
    "ec_groups", "zpa_app_segments",
    "zpa_application_segments", "zpa_application_segment_groups",
    "threat_categories",
    "applications", "application_groups",
    "cloud_app_instances",
    "override_users", "override_groups",
    "dlp_engines", "bandwidth_classes", "tenancy_profile_ids",
})

# Ref fields the API accepts in either form: a flat list of Zscaler-defined string
# constants, or a list of embedded objects for tenant-local entries.  They cannot go
# in _REF_FIELDS because _slim_payload's ref loop finds no dicts in the string form,
# empties the list and drops the field — which the ZIA UI reads as "Any", widening
# the rule.  Each element is classified individually instead.
_MIXED_REF_FIELDS: Dict[str, str] = {
    "url_categories":  "url_category",
    "url_categories2": "url_category",
}

# Every ref field above, mapped to the resource type its IDs belong to — the type
# name the importer stores in ZIAResource.resource_type.  ZIA IDs are tenant-local:
# the same object has a different ID on each tenant, and because the ID space is
# small and dense a source ID almost always collides with some unrelated object on
# the target.  The reference is then accepted rather than rejected, and the rule
# silently scopes to the wrong thing.  Every field here is remapped by name.
_REF_TYPE_MAP: Dict[str, str] = {
    "locations":             "location",
    "location_groups":       "location_group",
    "groups":                "group",
    "departments":           "department",
    "users":                 "user",
    "device_groups":         "device_group",
    "source_ip_groups":      "ip_source_group",
    "src_ip_groups":         "ip_source_group",
    "dest_ip_groups":        "ip_destination_group",
    "src_ipv6_groups":       "ip_source_group",
    "dest_ipv6_groups":      "ip_destination_group",
    "workload_groups":       "workload_group",
    "proxy_gateways":        "proxy_gateway",
    "time_windows":          "time_interval",
    "labels":                "rule_label",
    "nw_services":           "network_service",
    "services":              "network_service",
    "nw_service_groups":     "network_svc_group",
    "nw_applications":       "network_app",
    "nw_application_groups": "network_app_group",
    "cloud_app_instances":   "cloud_app_instance",
    "override_users":        "user",
    "override_groups":       "group",
    "dlp_engines":           "dlp_engine",
    "bandwidth_classes":     "bandwidth_class",
    "tenancy_profile_ids":   "tenancy_restriction_profile",
}

# Ref fields whose referent type the importer does not collect, so there is no
# target-side name index to match against.  Their source IDs cannot be made
# meaningful on the target, and shipping them anyway is the mis-scoping bug above,
# so they are dropped and reported.  This matches ZIAPushService._ref_resolved,
# which strips the same references for the same reason.
_UNRESOLVABLE_REF_FIELDS: frozenset = frozenset({
    "devices",
    "ec_groups",
    "zpa_app_segments",
    "zpa_application_segments",
    "zpa_application_segment_groups",
    "threat_categories",
    "application_groups",
})

# Scope fields: losing every ref widens the rule to "Any" rather than narrowing it.
# Mirrors ZIAPushService._SCOPE_CHECKS — a rule that lost its whole audience is
# created DISABLED instead of being allowed to fire against the entire tenant.
_SCOPE_REF_FIELDS: frozenset = frozenset({
    "locations", "location_groups", "groups", "departments", "users",
    "devices", "device_groups", "zpa_app_segments", "cloud_app_instances",
})


# ---------------------------------------------------------------------------
# Dependency closure
# ---------------------------------------------------------------------------

# Types a closure may create on the target from source content.  Everything else
# reachable from a rule is resolve-only: identity and environment objects
# (location, group, department, user, device_group, proxy_gateway) carry
# tenant-specific state — IPs, VPN credentials, gateway bindings, IdP membership —
# that a dependency walk has no business inventing on another tenant, and
# predefined catalogs (network_app, threat_category) exist identically everywhere
# and need no help.  Those still resolve by name in _remap_refs; they are simply
# never created.
#
# location is deliberately absent even though it has a write path.  That path
# exists for the Full Clone flow, which carries static IPs, VPN credentials, GRE
# tunnels and sublocations alongside it.  A closure has none of that context.
_REPLICABLE_TYPES: frozenset = frozenset({
    "rule_label", "time_interval",
    "ip_source_group", "ip_destination_group",
    "network_service", "network_svc_group", "network_app_group",
    "workload_group", "bandwidth_class",
    "cloud_app_instance", "tenancy_restriction_profile",
    "url_category", "dlp_engine", "dlp_dictionary",
})

# Some reference types are imported under more than one resource_type, and a name
# lookup has to consider all of them: predefined locations (Road Warrior, Mobile
# Users) arrive as location_lite rather than location.  _ref_name_index widens its
# query through this map and folds the results together, and the pipeline refreshes
# the target through it too -- a companion left stale resolves names the primary
# type no longer has, which is exactly how a deleted location kept answering.
_REF_TYPE_COMPANIONS: Dict[str, Tuple[str, ...]] = {
    "location": ("location_lite",),
}


# The real structural maximum is 2 (rule -> network_svc_group -> network_service);
# every other replicable type is a leaf.  5 leaves headroom while still bounding a
# runaway walk over a malformed import.  Hitting it is a bug, so it is reported.
_CLOSURE_MAX_DEPTH = 5


def _resource_name(row) -> str:
    """The name every stage of the sync must agree on for one imported row.

    Custom url_categories are the reason this exists: the API returns the operator's
    name in configured_name and leaves the top-level name empty, so the importer
    stores an empty name column for some of them.  Keying on that column alone made
    those rows invisible to the diff and the remap while the closure still pulled
    them in by their real name — a dependency that could never be satisfied.

    Every stage resolves the name through here so they cannot drift apart again.
    """
    if getattr(row, "name", None):
        return row.name
    cfg = getattr(row, "raw_config", None) or {}
    return cfg.get("configured_name") or ""


def _close_over(
    source_tenant_id: int,
    resource_types: List[str],
    label_name: Optional[str],
    loaded_types: Set[str],
) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, str], str], List[str], Set[str], Set[str]]:
    """Walk the selected source rules' references and return what they require.

    Selecting a rule for sync without the types it depends on produces a rule that
    lands on the target with its references dropped — scope widened to Any, or the
    rule disabled.  The operator picked a rule; they did not knowingly opt out of
    the objects that rule needs.  This walk closes that gap by pulling the required
    objects into the same job.

    Source-side only: it answers "what does this rule need?", not "what is missing
    on the target?".  The second question is _compute_diff's, which is where target
    state already lives — a dependency that already matches on the target produces
    no record at all, so a steady-state run costs nothing.

    loaded_types names the types whose source rows are known to be current in the
    DB.  A reference into a type outside that set cannot be followed — the rows are
    absent or stale — so it is reported in `missing` instead of being silently
    dropped, and the caller imports those types and walks again.  Without this a
    first-ever sync would find no dependencies at all, because nothing but the
    selected types has ever been imported for that tenant.

    Returns (pulled, origin, warnings, missing, resolve_only):
      pulled   rtype -> set of source names to add to the job
      origin   (rtype, name) -> name of the seed rule that required it, for audit
      warnings human-readable strings for the run history
      missing  replicable types referenced but not yet loaded
      resolve_only  non-replicable types a selected rule actually points at.  The
               walk will not create these, but _remap_refs still has to resolve
               them by name against the target's rows, so the caller refreshes
               them there before diffing — see step 6c in _execute_sync_pipeline.

    Breadth-first, so origin records the shortest path to a seed rule, which is the
    most useful attribution for an operator reading an audit row.  Runs entirely in
    one session and holds none while writing, matching _execute_sync_pipeline.
    """
    from services.zia_push_service import _is_zscaler_managed

    pulled: Dict[str, Set[str]] = {}
    origin: Dict[Tuple[str, str], str] = {}
    warnings: List[str] = []
    missing: Set[str] = set()
    resolve_only: Set[str] = set()
    selected = set(resource_types)

    with get_session() as session:
        # Only the seed types and the types a walk can actually replicate.  The
        # resolve-only types are deliberately excluded: user, group and location can
        # run to tens of thousands of rows per tenant and the walk never follows a
        # reference into them.
        wanted = sorted(selected | (_REPLICABLE_TYPES & loaded_types))
        rows = (
            session.query(ZIAResource)
            .filter(
                ZIAResource.tenant_id == source_tenant_id,
                ZIAResource.resource_type.in_(wanted),
                ZIAResource.is_deleted == False,  # noqa: E712
            )
            .all()
        )
        # (rtype, source_id) -> (name, raw_config), the whole source tenant.  Loaded
        # once: the walk hops between types by ID and a query per hop would mean one
        # round trip per reference.
        by_id: Dict[Tuple[str, str], Tuple[str, Dict]] = {}
        for r in rows:
            if r.zia_id is None:
                continue
            rname = _resource_name(r)
            if rname:
                by_id[(r.resource_type, str(r.zia_id))] = (rname, r.raw_config or {})

        # Seeds: the rows this job already selected, filtered exactly as
        # _compute_diff filters them, so the walk starts from the same set that
        # will actually be pushed.
        seeds: List[Tuple[str, str, Dict]] = []
        for r in rows:
            seed_nm = _resource_name(r)
            if r.resource_type not in selected or not seed_nm:
                continue
            cfg = r.raw_config or {}
            if _is_zscaler_managed(r.resource_type, cfg):
                continue
            if label_name is not None and not _has_label(cfg, label_name):
                continue
            seeds.append((r.resource_type, seed_nm, cfg))

    visited: Set[Tuple[str, str]] = set()
    queue: List[Tuple[str, Dict, str, int]] = [(rt, cfg, name, 0) for rt, name, cfg in seeds]
    depth_exceeded = False

    while queue:
        _rt, cfg, seed_name, depth = queue.pop(0)
        if depth >= _CLOSURE_MAX_DEPTH:
            depth_exceeded = True
            continue

        refs: List[Tuple[str, Any]] = []
        for field, ref_type in _REF_TYPE_MAP.items():
            for ref in cfg.get(field) or []:
                refs.append((ref_type, ref))
        for field, ref_type in _MIXED_REF_FIELDS.items():
            for ref in cfg.get(field) or []:
                if isinstance(ref, dict):
                    refs.append((ref_type, ref))
                elif isinstance(ref, str):
                    # Flat-string form.  A custom category is a tenant-local slot
                    # ("CUSTOM_01") and so is a genuine dependency that has to be
                    # pulled in; a Zscaler-defined constant ("ADULT_THEMES") has no
                    # name in by_id and drops out at the lookup below.
                    refs.append((ref_type, {"id": ref}))

        for ref_type, ref in refs:
            if not isinstance(ref, dict):
                continue
            raw_id = ref.get("id")
            if raw_id is None:
                continue
            if isinstance(raw_id, (int, float)) and raw_id < 0:
                continue  # Zscaler system constant, identical on every tenant
            if ref_type not in _REPLICABLE_TYPES:
                # Not ours to create, but the rule is still scoped by it and
                # _remap_refs has to find it by name on the target.  Name the type
                # so the caller can refresh the target's rows for it; a stale row
                # here resolves to an ID that no longer exists (the API rejects the
                # rule) or that a different object now holds (it does not, and the
                # rule lands silently mis-scoped).
                resolve_only.add(ref_type)
                continue
            if ref_type not in loaded_types:
                # Rows for this type are absent or stale; the caller imports it and
                # calls again rather than losing the dependency here.
                missing.add(ref_type)
                continue
            key = (ref_type, str(raw_id))
            if key in visited:
                continue
            visited.add(key)

            found = by_id.get(key)
            if found is None:
                # Dangling in the source tenant — already broken before this sync,
                # and there is nothing to replicate.
                continue
            dep_name, dep_cfg = found
            # Predefined objects exist identically on every tenant and resolve by
            # name without help; creating them is what the API refuses.  This is the
            # same predicate _compute_diff applies, so a pulled-in name that would
            # be filtered out there is never added here.
            if _is_zscaler_managed(ref_type, dep_cfg):
                continue

            if ref_type not in selected:
                pulled.setdefault(ref_type, set()).add(dep_name)
                origin.setdefault((ref_type, dep_name), seed_name)
                if ref_type == "dlp_engine":
                    # A DLP engine names its dictionaries inside engine_expression
                    # ("((D63.S > 1))"), not through a reference array, so the walk
                    # cannot see that edge.  Say so rather than implying the engine
                    # arrived complete.
                    warnings.append(
                        f"dlp_engine '{dep_name}' was replicated for rule "
                        f"'{seed_name}'; its engine_expression may name dictionary "
                        f"IDs that do not exist on the target and were not verified"
                    )
            # Recurse regardless of whether the type was already selected: a
            # selected network_svc_group still leads to network_services that are not.
            queue.append((ref_type, dep_cfg, seed_name, depth + 1))

    if depth_exceeded:
        warnings.append(
            f"dependency walk hit its depth bound of {_CLOSURE_MAX_DEPTH}; some "
            f"nested dependencies may not have been included"
        )

    return pulled, origin, warnings, missing, resolve_only


def _drop_nulls(obj):
    """Recursively remove None values from dicts; preserve empty lists."""
    if isinstance(obj, dict):
        return {k: _drop_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_nulls(item) for item in obj]
    return obj


# String-enum arrays that must be omitted rather than sent empty.
_EMPTY_STRIP_FIELDS: frozenset = frozenset({
    "platforms", "device_trust_levels", "user_agent_types",
    "cloud_applications", "url_categories", "time_windows",
    "proxy_gateways", "user_risk_score_levels",
})


def _cloud_app_rule_type(raw_config: Optional[Dict]) -> Optional[str]:
    """Return the cloud app control rule's rule_type, or None if absent.

    The ZIA cloud app control endpoints are keyed by rule type (WEBMAIL,
    STREAMING_MEDIA, ...) as a path segment.  The rule body carries it as
    'type'; 'rule_type' is accepted as a fallback for configs captured before
    the field settled.  Matches ZIAPushService._push_cloud_app_rule.
    """
    cfg = raw_config or {}
    return cfg.get("type") or cfg.get("rule_type")


def _slim_payload(rtype: str, payload: Dict) -> Dict:
    """Reduce ref-array fields to [{id}] and apply per-type fixups.

    Lightweight equivalent of ZIAPushService._norm_*() — no ID remapping,
    just strips extra embedded fields so the API accepts the payload.
    """
    # Strip null values from the entire payload (null enum sub-fields cause 400s)
    payload = _drop_nulls(payload)

    ref_fields = _REF_FIELDS
    if rtype == "cloud_app_control_rule":
        # 'applications' on this type is a flat list of app-name strings
        # (["GOOGLE_WEBMAIL", ...]), not [{id}].  Running it through the ref loop
        # below finds no dicts, empties the list and drops the field, which the
        # ZIA UI reads as "Any" — silently widening the rule.  Exempt it here and
        # handle it in the per-type fixup instead.
        ref_fields = _REF_FIELDS - {"applications"}

    for f in ref_fields:
        val = payload.get(f)
        if isinstance(val, list):
            if val:
                slimmed = [
                    {"id": item["id"]}
                    for item in val
                    if isinstance(item, dict) and item.get("id") is not None
                ]
                if slimmed:
                    payload[f] = slimmed
                else:
                    payload.pop(f, None)
            else:
                payload.pop(f, None)  # drop empty ref arrays

    # Mixed-form fields keep their Zscaler-defined string constants verbatim; only
    # the embedded tenant-local objects are reduced to [{id}].
    for f in _MIXED_REF_FIELDS:
        val = payload.get(f)
        if isinstance(val, list):
            if val:
                payload[f] = [
                    {"id": item["id"]} if isinstance(item, dict) else item
                    for item in val
                    if not isinstance(item, dict) or item.get("id") is not None
                ]
                if not payload[f]:
                    payload.pop(f, None)
            else:
                payload.pop(f, None)

    # Strip empty string-enum arrays that the API rejects when empty
    for f in _EMPTY_STRIP_FIELDS:
        if not payload.get(f):
            payload.pop(f, None)

    if rtype == "ssl_inspection_rule":
        action = payload.get("action")
        if isinstance(action, dict):
            sub = action.get("decrypt_sub_actions")
            if isinstance(sub, dict):
                for old, new in (
                    ("min_client_tls_version", "minClientTLSVersion"),
                    ("min_server_tls_version", "minServerTLSVersion"),
                ):
                    if old in sub:
                        sub[new] = sub.pop(old)

    if rtype == "firewall_dns_rule":
        for f in ("default_dns_rule_name_used", "is_web_eun_enabled"):
            payload.pop(f, None)

    if rtype == "cloud_app_control_rule":
        # Mirrors ZIAPushService._norm_cloud_app_control_rule: an empty
        # 'applications' means "Any", which the API expresses by omitting the
        # field — sending [] is rejected as invalid.
        if not payload.get("applications"):
            payload.pop("applications", None)
        if not payload.get("cloud_app_instances"):
            payload.pop("cloud_app_instances", None)

    if rtype == "cloud_app_instance":
        # Mirrors ZIAPushService._norm_cloud_app_instance.  READONLY_FIELDS is
        # applied at the top level only, so the instance_id inside each
        # instance_identifiers entry would otherwise ride along to the target.
        idents = payload.get("instance_identifiers")
        cleaned = []
        if isinstance(idents, list):
            for ident in idents:
                if not isinstance(ident, dict):
                    continue
                entry = {k: v for k, v in ident.items()
                         if k not in ("instance_id", "modified_at", "modified_by")}
                if entry:
                    cleaned.append(entry)
        if cleaned:
            payload["instance_identifiers"] = cleaned
        else:
            payload.pop("instance_identifiers", None)

    if rtype == "forwarding_rule":
        gw = payload.get("zpa_gateway")
        if isinstance(gw, dict):
            gw_id = gw.get("id")
            if gw_id:
                payload["zpa_gateway"] = {"id": gw_id}
            else:
                payload.pop("zpa_gateway", None)

    return payload


def _next_order(target_tenant_id: int, rtype: str) -> int:
    """Return max(order) + 1 across user-created rules of this type in the target tenant.

    Predefined/system rules (predefined=True, default_rule=True) are excluded —
    they sit at the end of the list with high order values and would skew the
    insertion point for user rules.

    Reads the DB snapshot populated by the most recent target import.  The caller
    (run_sync_task) re-imports the target after the push so subsequent runs read
    accurate state.
    """
    with get_session() as session:
        rows = (
            session.query(ZIAResource)
            .filter_by(tenant_id=target_tenant_id, resource_type=rtype, is_deleted=False)
            .all()
        )
    max_order = 0
    for r in rows:
        cfg = r.raw_config or {}
        if cfg.get("predefined") or cfg.get("default_rule"):
            continue
        order = cfg.get("order", 0)
        if isinstance(order, int) and order > max_order:
            max_order = order
    return max_order + 1


def _ref_name_index(
    source_tenant_id: int,
    target_tenant_id: int,
    rtypes: Set[str],
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    """Build per-type name indexes for both tenants in a single DB session.

    Returns (src_id_to_name, tgt_name_to_id), each keyed by resource type.  One
    query per tenant covering every type the payload actually references, rather
    than a session per field — _apply_one runs once per resource, so a session per
    ref field would mean tens of thousands of opens on a large sync.

    Predefined locations (Road Warrior, Mobile Users) are imported as location_lite
    rather than location, so a location lookup has to consider both.
    """
    if not rtypes:
        return {}, {}
    lookup = set(rtypes)
    for primary, companions in _REF_TYPE_COMPANIONS.items():
        if primary in lookup:
            lookup.update(companions)

    src_id_to_name: Dict[str, Dict[str, str]] = {rt: {} for rt in lookup}
    tgt_name_to_id: Dict[str, Dict[str, str]] = {rt: {} for rt in lookup}

    with get_session() as session:
        rows = (
            session.query(ZIAResource)
            .filter(ZIAResource.tenant_id.in_([source_tenant_id, target_tenant_id]),
                    ZIAResource.resource_type.in_(sorted(lookup)),
                    ZIAResource.is_deleted == False)  # noqa: E712
            .all()
        )
        for r in rows:
            nm = _resource_name(r)
            if r.tenant_id == source_tenant_id:
                src_id_to_name[r.resource_type][str(r.zia_id)] = nm
            else:
                if nm:
                    tgt_name_to_id[r.resource_type][nm.strip().lower()] = r.zia_id

    # Fold each companion into its primary in both directions so callers see one
    # type.  setdefault keeps the primary's own row when both carry the same name.
    for primary, companions in _REF_TYPE_COMPANIONS.items():
        if primary not in rtypes:
            continue
        for companion in companions:
            for name, zid in tgt_name_to_id.get(companion, {}).items():
                tgt_name_to_id[primary].setdefault(name, zid)
            for sid, name in src_id_to_name.get(companion, {}).items():
                src_id_to_name[primary].setdefault(sid, name)

    return src_id_to_name, tgt_name_to_id


def _remap_refs(
    payload: Dict,
    rtype: str,
    source_raw: Optional[Dict],
    source_tenant_id: int,
    target_tenant_id: int,
    created_ids: Optional[Dict[str, Dict[str, str]]] = None,
) -> Tuple[Dict, Dict[str, List[str]]]:
    """Rewrite every reference array from source-tenant IDs to the target's, by name.

    The sync engine previously remapped only labels, locations and location_groups.
    Every other reference — ip groups, network services, service groups, time
    windows, app groups, workload groups, proxy gateways — shipped the source
    tenant's ID unchanged.  ZIA IDs are small dense integers, so such an ID usually
    *does* exist on the target as some unrelated object: the API accepts the rule
    and it silently scopes to the wrong resource.  That is the failure this fixes.

    Resolution order per ref, mirroring ZIAPushService:
      1. negative IDs pass through — Zscaler system constants (-3 = Mobile Users)
         mean the same thing on every tenant
      2. created_ids — objects created earlier in this same run, which the target
         DB snapshot (imported before any write) cannot know about
      3. the target's imported objects, matched on name

    A ref that resolves nowhere is dropped, and its name recorded in the returned
    dict so the caller can warn and, for scope fields, disable the rule.  Fields in
    _UNRESOLVABLE_REF_FIELDS are dropped wholesale: their referent type is never
    imported, so no name index exists to match against.

    Names come from source_raw's pre-slim refs first — _slim_payload has by now
    reduced the payload to [{id}] — and from the source tenant's imported rows
    second, which covers a rule whose refs carry no inline name.
    """
    dropped: Dict[str, List[str]] = {}
    src_raw = source_raw or {}

    present = [f for f in _REF_TYPE_MAP if isinstance(payload.get(f), list) and payload.get(f)]
    mixed = [f for f in _MIXED_REF_FIELDS if isinstance(payload.get(f), list) and payload.get(f)]
    needed = {_REF_TYPE_MAP[f] for f in present} | {_MIXED_REF_FIELDS[f] for f in mixed}
    src_index, tgt_index = _ref_name_index(source_tenant_id, target_tenant_id, needed)

    for field in present:
        ref_type = _REF_TYPE_MAP[field]
        by_id = src_index.get(ref_type, {})
        by_name = tgt_index.get(ref_type, {})
        in_run = (created_ids or {}).get(ref_type, {})

        # Inline names off the source config, which survive even when the source
        # tenant's rows for this type were never imported.
        inline: Dict[str, str] = {
            str(r.get("id", "")): (r.get("name") or "")
            for r in (src_raw.get(field) or [])
            if isinstance(r, dict) and r.get("name")
        }

        remapped: List[Dict] = []
        lost: List[str] = []
        for ref in payload[field]:
            if not isinstance(ref, dict):
                continue
            raw_id = ref.get("id")
            if isinstance(raw_id, (int, float)) and raw_id < 0:
                remapped.append({"id": raw_id})
                continue
            src_id = str(raw_id if raw_id is not None else "")
            name = ref.get("name") or inline.get(src_id) or by_id.get(src_id) or ""
            key = name.strip().lower()
            tgt_id = (in_run.get(key) or by_name.get(key)) if key else None
            if tgt_id:
                try:
                    remapped.append({"id": int(tgt_id)})
                except (ValueError, TypeError):
                    remapped.append({"id": tgt_id})
            else:
                lost.append(name or src_id or "?")

        if remapped:
            payload[field] = remapped
        else:
            payload.pop(field, None)
        if lost:
            dropped[field] = lost

    # Mixed-form fields carry two kinds of element.  A dict is a tenant-local object
    # and is remapped exactly as above.  A string is either a Zscaler-defined
    # constant ("ADULT_THEMES"), identical on every tenant, or a custom category
    # slot ("CUSTOM_01") whose number is assigned in creation order and therefore
    # routinely names a *different* category on the target.  Both are remapped by
    # name, which is what tells them apart: only the tenant-local ones have one.
    for field in mixed:
        ref_type = _MIXED_REF_FIELDS[field]
        by_id = src_index.get(ref_type, {})
        by_name = tgt_index.get(ref_type, {})
        in_run = (created_ids or {}).get(ref_type, {})
        inline = {
            str(r.get("id", "")): (r.get("name") or r.get("configured_name") or "")
            for r in (src_raw.get(field) or [])
            if isinstance(r, dict) and (r.get("name") or r.get("configured_name"))
        }

        remapped_mixed: List[Any] = []
        lost = []
        for ref in payload[field]:
            if isinstance(ref, str):
                nm = inline.get(ref) or by_id.get(ref) or ""
                key = nm.strip().lower()
                if not key:
                    # No name on either side: a Zscaler-defined constant, which
                    # means the same thing on the target.  Ship it unchanged.
                    remapped_mixed.append(ref)
                    continue
                tgt_id = in_run.get(key) or by_name.get(key)
                if tgt_id:
                    remapped_mixed.append(str(tgt_id))
                else:
                    lost.append(nm)
                continue
            if not isinstance(ref, dict):
                remapped_mixed.append(ref)
                continue
            src_id = str(ref.get("id", "") or "")
            name = (ref.get("name") or ref.get("configured_name")
                    or inline.get(src_id) or by_id.get(src_id) or "")
            key = name.strip().lower()
            tgt_id = (in_run.get(key) or by_name.get(key)) if key else None
            if tgt_id:
                remapped_mixed.append({"id": tgt_id})
            else:
                lost.append(name or src_id or "?")

        if remapped_mixed:
            payload[field] = remapped_mixed
        else:
            payload.pop(field, None)
        if lost:
            dropped[field] = lost

    for field in _UNRESOLVABLE_REF_FIELDS:
        refs = payload.get(field)
        if not isinstance(refs, list) or not refs:
            continue
        keep = [r for r in refs if isinstance(r, dict)
                and isinstance(r.get("id"), (int, float)) and r["id"] < 0]
        lost = [
            (r.get("name") or str(r.get("id", "?"))) if isinstance(r, dict) else str(r)
            for r in refs if r not in keep
        ]
        if keep:
            payload[field] = keep
        else:
            payload.pop(field, None)
        if lost:
            dropped[field] = lost

    return payload, dropped


# ---------------------------------------------------------------------------
# Apply a single diff record to the target
# ---------------------------------------------------------------------------

def _apply_one(
    target_client,
    target_tenant_id: int,
    source_tenant_id: int,
    rec: _DiffRecord,
    source_zia_id: Optional[str] = None,
    order_tracker: Optional[Dict[str, int]] = None,
    created_ids: Optional[Dict[str, Dict[str, str]]] = None,
    warning_sink: Optional[List[Dict[str, str]]] = None,
) -> None:
    """Apply a single diff record to the target tenant.

    For creates: strips read-only fields and calls the SDK create method.
    For updates: strips read-only fields, injects target_id, calls update.
    For deletes: calls the SDK delete method.

    created_ids: rtype → {name.lower(): target_id} for resources created earlier in
    this same pipeline run, so a rule can reference an object the target DB snapshot
    predates.  warning_sink: the run's errors list, for non-fatal WARNING: entries.

    Raises on any failure — caller catches and logs to errors list.
    """
    from services.zia_push_service import (
        _WRITE_METHODS,
        _DELETE_METHODS,
        READONLY_FIELDS,
    )

    rtype = rec.resource_type

    if rec.operation == "delete":
        if rtype == "cloud_app_control_rule":
            # Deletes carry no source_raw — take the rule type off the target row.
            rule_type = _cloud_app_rule_type(rec.target_raw)
            if not rule_type:
                raise ValueError(
                    f"cloud_app_control_rule '{rec.name}' has no rule type in its "
                    "target config; cannot delete"
                )
            target_client.delete_cloud_app_rule(rule_type, rec.target_id)
            return
        if rtype not in _DELETE_METHODS:
            raise ValueError(f"No delete method for {rtype}")
        delete_method_name = _DELETE_METHODS[rtype]
        if delete_method_name is None:
            raise NotImplementedError(f"delete not implemented for {rtype} in sync engine")
        delete_method = getattr(target_client, delete_method_name)
        delete_method(rec.target_id)
        return

    # cloud_app_control_rule is absent from _WRITE_METHODS on purpose: its create
    # and update calls take a leading rule_type argument, which the two-name
    # (create, update) tuple cannot express.  It is dispatched separately below,
    # after the payload is built.
    if rtype != "cloud_app_control_rule" and rtype not in _WRITE_METHODS:
        raise ValueError(f"No write method for {rtype}")

    # Build a cleaned payload: strip read-only fields
    payload = {
        k: v for k, v in (rec.source_raw or {}).items()
        if k not in READONLY_FIELDS
    }
    # Strip 'id' field from creates (target assigns its own)
    if rec.operation == "create":
        payload.pop("id", None)
        # Only inject order for types that actually use it — unordered types
        # (tenancy_restriction_profile, dlp_engine, etc.) lack the field entirely
        # and the ZIA API rejects the unexpected key with a 400.
        if "order" in (rec.source_raw or {}):
            src_order = (rec.source_raw or {}).get("order")
            # Seed the tracker from the DB snapshot on first create for this type.
            if order_tracker is not None and rtype not in order_tracker:
                order_tracker[rtype] = _next_order(target_tenant_id, rtype)
            next_order = order_tracker[rtype] if order_tracker is not None else _next_order(target_tenant_id, rtype)
            if isinstance(src_order, int) and src_order <= next_order:
                # Source position is within the target's current range — use it directly.
                payload["order"] = src_order
            else:
                # Source position exceeds target range — append in order and advance
                # the tracker so subsequent clamped creates stack correctly.
                payload["order"] = next_order
                if order_tracker is not None:
                    order_tracker[rtype] = next_order + 1

    # Reduce embedded ref objects to [{id}] and apply per-type fixups
    payload = _slim_payload(rtype, payload)

    # Rewrite every reference array from source-tenant IDs to the target's, by name.
    payload, dropped_refs = _remap_refs(
        payload, rtype, rec.source_raw,
        source_tenant_id, target_tenant_id, created_ids,
    )

    # Report references that resolved nowhere.  A scope field that lost *every*
    # ref widens the rule to "Any" rather than narrowing it, so on a create the
    # rule is inserted DISABLED rather than allowed to fire against the whole
    # tenant; on an update the target's own state is left as the operator set it.
    # Partial loss narrows and passes silently, matching ZIAPushService._SCOPE_CHECKS.
    if dropped_refs:
        widened = [
            f for f in dropped_refs
            if f in _SCOPE_REF_FIELDS and not payload.get(f)
        ]
        disabled = bool(widened) and rec.operation == "create"
        if disabled:
            payload["state"] = "DISABLED"
        if warning_sink is not None:
            for field, names in sorted(dropped_refs.items()):
                total = not payload.get(field)
                scope = field in _SCOPE_REF_FIELDS
                if total and scope:
                    detail = "; rule scope widened to Any" + (
                        " and rule disabled" if disabled else ""
                    )
                elif total:
                    detail = "; the reference was dropped entirely"
                else:
                    detail = "; the remaining references were kept"
                warning_sink.append({
                    "resource_type": rtype,
                    "resource_name": rec.name,
                    "operation": rec.operation,
                    "error": (
                        f"WARNING: {field} could not be resolved on the target "
                        f"({', '.join(names)}){detail}"
                    ),
                })

    # Clamp reorder operations to the target's valid range
    if rec.operation == "reorder" and "order" in payload:
        src_order = payload["order"]
        if isinstance(src_order, int):
            max_target = _next_order(target_tenant_id, rtype) - 1
            if max_target > 0 and src_order > max_target:
                payload["order"] = max_target

    if rtype == "cloud_app_control_rule":
        # rule_type is a path segment on this endpoint, so it is passed positionally
        # and also left in the payload (the rule body carries its own 'type').
        rule_type = _cloud_app_rule_type(rec.source_raw)
        if not rule_type:
            raise ValueError(
                f"cloud_app_control_rule '{rec.name}' has no rule type in its "
                "source config; cannot push"
            )
        if rec.operation == "create":
            target_client.create_cloud_app_rule(rule_type, payload)
        else:
            payload["id"] = rec.target_id
            target_client.update_cloud_app_rule(rule_type, rec.target_id, payload)
        return

    if rtype == "cloud_app_instance":
        # The PK is instance_id, not id: the generic tail below would read
        # result["id"], find nothing, and discard the new ID — leaving every rule
        # scoped to this instance unable to resolve it.  See
        # ZIAPushService._push_cloud_app_instance for the same reasoning.
        payload.pop("instance_id", None)
        if rec.operation == "create":
            result = target_client.create_cloud_app_instance(payload) or {}
            new_id = str(result.get("instance_id", "") or "")
            if not new_id:
                raise RuntimeError(
                    f"cloud app instance '{rec.name}' was created but the API "
                    "returned no instance_id; rule scoping cannot be resolved"
                )
            if created_ids is not None and rec.name:
                created_ids.setdefault(rtype, {})[rec.name.strip().lower()] = new_id
        else:
            target_client.update_cloud_app_instance(rec.target_id, payload)
        return

    create_method_name, update_method_name = _WRITE_METHODS[rtype]

    if rec.operation == "create":
        create_method = getattr(target_client, create_method_name)
        result = create_method(payload)
        # Record the new ID so a rule pushed later in this same run can resolve a
        # reference to it.  The target DB snapshot was imported before any write,
        # so without this an object and the rule that references it can only be
        # joined up on the *next* run — the rule is created with its reference
        # dropped, and _remap_refs reports it as unresolvable.
        if created_ids is not None and rec.name and isinstance(result, dict):
            new_id = result.get("id")
            if new_id is not None:
                created_ids.setdefault(rtype, {})[rec.name.strip().lower()] = str(new_id)
    else:
        # update / rename / reorder — inject the target's ID and call update
        payload["id"] = rec.target_id
        update_method = getattr(target_client, update_method_name)
        update_method(rec.target_id, payload)
