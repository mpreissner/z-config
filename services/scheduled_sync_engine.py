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

        # 8. Split diff into phases returned by _compute_diff:
        #    phase 1 — create / update / rename / delete  (content operations)
        #    phase 2 — reorder  (positional, after all rules exist on target)
        phase1 = [r for r in diff if r.operation != "reorder"]
        phase2 = [r for r in diff if r.operation == "reorder"]

        def _apply_batch(batch):
            nonlocal synced
            for rec in batch:
                try:
                    _apply_one(target_client, t_target, t_source, rec, source_zia_id=t_source_zia_id)
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

        _apply_batch(phase1)
        _apply_batch(phase2)

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
        # This makes the next run's diff and _next_order accurate without any
        # in-memory offset tricks.
        try:
            ZIAImportService(target_client, tenant_id=t_target).run(
                resource_types=resource_types
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

    # 11. Write audit entries — all sessions from import/push are already closed
    from services import audit_service
    for entry in pending_audit:
        audit_service.log(**entry)

    # 12. Update run record
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
                if r.name and not _is_zscaler_managed(rtype, r.raw_config or {}):
                    src_by_name[r.name] = r

            # Target: name → [all rows]  and  content_fingerprint → [all rows]
            tgt_by_name_all: Dict[str, List[ZIAResource]] = {}
            tgt_by_content: Dict[str, List[ZIAResource]] = {}
            for r in tgt_rows:
                if r.name and not _is_zscaler_managed(rtype, r.raw_config or {}):
                    tgt_by_name_all.setdefault(r.name, []).append(r)
                    ck = _content_fingerprint(r.raw_config or {})
                    tgt_by_content.setdefault(ck, []).append(r)

            # Label filtering: restrict source to labelled rules; deletes are
            # scoped to labelled target rules only (tgt_labelled_names).
            if label_name is not None:
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
                        target_id=name_match.zia_id,
                    ))
                    continue

                # 4. No match → create
                content_diff.append(_DiffRecord(
                    resource_type=rtype, name=name, operation="create",
                    source_raw=copy.deepcopy(src.raw_config or {}),
                ))

            # DELETE — unclaimed labelled target rows not matched by any source rule
            if sync_deletes:
                for del_name in tgt_labelled_names:
                    for r in tgt_by_name_all.get(del_name, []):
                        if r.zia_id not in claimed:
                            content_diff.append(_DiffRecord(
                                resource_type=rtype, name=del_name, operation="delete",
                                target_id=r.zia_id,
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
    "nw_applications", "nw_application_groups",
    "ec_groups", "zpa_app_segments",
    "zpa_application_segments", "zpa_application_segment_groups",
    "threat_categories",
    "applications", "application_groups",
})


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
    "proxy_gateways",
})


def _slim_payload(rtype: str, payload: Dict) -> Dict:
    """Reduce ref-array fields to [{id}] and apply per-type fixups.

    Lightweight equivalent of ZIAPushService._norm_*() — no ID remapping,
    just strips extra embedded fields so the API accepts the payload.
    """
    # Strip null values from the entire payload (null enum sub-fields cause 400s)
    payload = _drop_nulls(payload)

    for f in _REF_FIELDS:
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


def _remap_label_ids(payload: Dict, source_tenant_id: int, target_tenant_id: int) -> Dict:
    """Replace source-tenant label IDs with corresponding target-tenant IDs (matched by name).

    Labels are tenant-specific resources — the same label name has a different
    numeric ID on each tenant.  Sending the source ID causes a referential
    integrity 500.  Labels absent in the target are dropped from the payload.
    """
    labels = payload.get("labels")
    if not labels:
        return payload

    with get_session() as session:
        src_rows = (
            session.query(ZIAResource)
            .filter_by(tenant_id=source_tenant_id, resource_type="rule_label", is_deleted=False)
            .all()
        )
        tgt_rows = (
            session.query(ZIAResource)
            .filter_by(tenant_id=target_tenant_id, resource_type="rule_label", is_deleted=False)
            .all()
        )

    src_id_to_name: Dict[str, str] = {r.zia_id: r.name for r in src_rows}
    tgt_name_to_id: Dict[str, str] = {r.name: r.zia_id for r in tgt_rows}

    remapped = []
    for lbl in labels:
        if not isinstance(lbl, dict):
            continue
        src_id = str(lbl.get("id", ""))
        name = src_id_to_name.get(src_id)
        if name:
            tgt_id = tgt_name_to_id.get(name)
            if tgt_id:
                try:
                    remapped.append({"id": int(tgt_id)})
                except (ValueError, TypeError):
                    remapped.append({"id": tgt_id})

    if remapped:
        payload["labels"] = remapped
    else:
        payload.pop("labels", None)

    return payload


# ---------------------------------------------------------------------------
# Apply a single diff record to the target
# ---------------------------------------------------------------------------

def _apply_one(
    target_client,
    target_tenant_id: int,
    source_tenant_id: int,
    rec: _DiffRecord,
    source_zia_id: Optional[str] = None,
) -> None:
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
        # Set order to target rule count + 1 — source order often exceeds target count
        payload["order"] = _next_order(target_tenant_id, rtype)
        if source_zia_id:
            payload["description"] = f"Sync'd from {source_zia_id}"

    # Reduce embedded ref objects to [{id}] and apply per-type fixups
    payload = _slim_payload(rtype, payload)

    # Remap label IDs: source tenant IDs differ from target tenant IDs
    payload = _remap_label_ids(payload, source_tenant_id, target_tenant_id)

    if rec.operation == "create":
        create_method = getattr(target_client, create_method_name)
        create_method(payload)
    else:
        # update / rename / reorder — inject the target's ID and call update
        payload["id"] = rec.target_id
        update_method = getattr(target_client, update_method_name)
        update_method(rec.target_id, payload)
