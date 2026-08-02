"""ZPA push service.

Extracted from the `restore_zpa_snapshot` request handler in `api/routers/zpa.py`,
which held the only ZPA write engine in the codebase — dependency ordering, ID
remapping, payload cleaning and per-type capability rules — as nested closures
inside an HTTP handler.

Two modes:

  restore — diff-driven reconciliation against a snapshot.  Deletes resources
            the snapshot does not contain.  Matches by id, because snapshot ids
            came from this same tenant.

  merge   — additive push of a desired-state resource dict.  Never deletes.
            Matches by name, because candidate sets (e.g. migration output) carry
            synthetic ids that exist in no tenant.

`merge` is the default.  A caller that forgets the argument cannot delete
anything: the delete phase of a merge plan is always empty and no delete call is
reachable from it.

Usage:

    push = ZPAPushService(client, tenant_id)
    plan = push.classify_restore(snapshot["resources"])   # no API writes
    records = push.push_classified(plan, progress_callback=cb)
    push.sync_after_push(plan)
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.push_types import (
    APPLIED,
    CREATE,
    DELETE,
    FAILED,
    MANUAL,
    UPDATE,
    PushPlan,
    PushPlanEntry,
    PushRecord,
)

# ---------------------------------------------------------------------------
# Ordering and capability tables
#
# Moved verbatim from api/routers/zpa.py.  The capability sets encode real API
# constraints — app_connector and service_edge are provisioned, not declared, so
# they cannot be created; only policy_access supports create among policy types.
# Do not "fix" these.
# ---------------------------------------------------------------------------

# Dependency order — creates run forward, deletes run in reverse.
RTYPE_ORDER: List[str] = [
    "segment_group", "app_connector_group", "server_group",
    "pra_portal", "user_portal", "application", "pra_console",
    "app_connector", "service_edge",
    "policy_access", "policy_timeout", "policy_forwarding",
    "policy_inspection", "policy_isolation",
]

# Volatile fields stripped from all payloads before sending to the API.
PAYLOAD_META = frozenset({
    "id", "creation_time", "modified_time", "modified_by",
    "creationTime", "modifiedTime", "modifiedBy",
    "modifiedAt", "createdAt", "modified_at", "created_at",
})

# Extra fields to strip per resource type (beyond meta).
TYPE_EXTRA_STRIP: Dict[str, frozenset] = {
    "application":       frozenset({"tcp_port_ranges", "udp_port_ranges"}),
    "policy_access":     frozenset({"policy_set_id"}),
    "policy_timeout":    frozenset({"policy_set_id"}),
    "policy_forwarding": frozenset({"policy_set_id"}),
    "policy_inspection": frozenset({"policy_set_id"}),
    "policy_isolation":  frozenset({"policy_set_id"}),
}

POLICY_TYPE_MAP = {
    "policy_access":     "access",
    "policy_timeout":    "timeout",
    "policy_forwarding": "client_forwarding",
    "policy_inspection": "inspection",
    "policy_isolation":  "isolation",
}

CAN_CREATE = frozenset({
    "segment_group", "server_group", "app_connector_group",
    "application", "pra_portal", "user_portal", "pra_console",
    "policy_access",
})
CAN_UPDATE = frozenset({
    "segment_group", "server_group", "app_connector_group",
    "application", "pra_portal", "user_portal", "pra_console",
    "app_connector", "service_edge",
    "policy_access", "policy_timeout", "policy_forwarding",
    "policy_inspection", "policy_isolation",
})
CAN_DELETE = frozenset({
    "segment_group", "server_group", "app_connector_group",
    "application", "pra_portal", "user_portal", "pra_console",
    "app_connector",
    "policy_access", "policy_timeout", "policy_forwarding",
    "policy_inspection", "policy_isolation",
})

# Skip reasons — wire format, surfaced in the job payload.
_UNSUPPORTED = {
    CREATE: "create not supported for this resource type",
    UPDATE: "update not supported for this resource type",
    DELETE: "delete not supported for this resource type",
}

MODE_RESTORE = "restore"
MODE_MERGE = "merge"

# PRA console/portal payloads can carry credential material.  API errors
# sometimes echo the offending payload, so error text is redacted before it
# reaches an audit row or a job payload.
_SECRET_PATTERN = re.compile(
    r'("?(?:client_secret|clientSecret|password|passphrase|private_key|privateKey|'
    r'secret|token)"?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,}\]]+)',
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    """Mask secret-looking values in free-form error text."""
    return _SECRET_PATTERN.sub(r"\1***", text or "")


class ZPAPushCancelled(Exception):
    """Raised by push_classified() when stop_fn signals cancellation."""

    def __init__(self, pushed_records: List[PushRecord]):
        super().__init__("Push cancelled")
        self.pushed_records = pushed_records


class ZPAPushService:
    def __init__(self, client, tenant_id: int):
        self._client = client
        self._tenant_id = tenant_id
        self._id_map: Dict[str, str] = {}                       # source id → target id
        self._executed: List[Tuple[PushPlanEntry, PushRecord]] = []

    # ------------------------------------------------------------------
    # Classification — no API writes
    # ------------------------------------------------------------------

    def classify_restore(
        self,
        snapshot_resources: Dict[str, List[dict]],
        refresh_from_tenant: bool = False,
        import_progress_callback: Optional[Callable] = None,
    ) -> PushPlan:
        """Diff a snapshot against current tenant state.

        Args:
            snapshot_resources: the `resources` mapping of a RestorePoint.
            refresh_from_tenant: re-import from the tenant before diffing.
                Defaults False, matching the behaviour of the original restore
                endpoint, which diffs against local DB state as-is.
        """
        from services.snapshot_service import compute_diff

        current = self._current_state(refresh_from_tenant, import_progress_callback)
        diff = compute_diff(snapshot_resources, current)
        by_type = {rd.resource_type: rd for rd in diff.resource_diffs}

        plan = PushPlan(mode=MODE_RESTORE)

        # Deletes — reverse dependency order.  rd.added is present in the tenant
        # but absent from the snapshot.
        for rtype in reversed(RTYPE_ORDER):
            rd = by_type.get(rtype)
            if not rd:
                continue
            for item in rd.added:
                plan.deletes.append(self._entry(
                    rtype, DELETE, item.get("name") or item["id"],
                    supported=rtype in CAN_DELETE,
                    target_id=item["id"],
                ))

        # Creates — forward order.  rd.removed is in the snapshot but not the tenant.
        for rtype in RTYPE_ORDER:
            rd = by_type.get(rtype)
            if not rd:
                continue
            for item in rd.removed:
                plan.creates.append(self._entry(
                    rtype, CREATE, item.get("name") or item["id"],
                    supported=rtype in CAN_CREATE,
                    source_id=item["id"],
                    desired_config=item.get("raw_config") or {},
                ))

        # Updates — forward order.  Restore to the snapshot's config; the
        # tenant's current config is retained as the rollback target.
        for rtype in RTYPE_ORDER:
            rd = by_type.get(rtype)
            if not rd:
                continue
            for item in rd.modified:
                plan.updates.append(self._entry(
                    rtype, UPDATE, item.get("name") or item["id"],
                    supported=rtype in CAN_UPDATE,
                    target_id=item["id"],
                    desired_config=item.get("old_config") or {},
                    pre_config=item.get("new_config") or {},
                ))

        return plan

    def classify_merge(
        self,
        target: Dict[str, Any],
        refresh_from_tenant: bool = False,
        import_progress_callback: Optional[Callable] = None,
    ) -> PushPlan:
        """Classify a desired-state resource dict additively.  Never deletes.

        Matching is by name within resource type, because inputs such as
        migration candidates carry synthetic ids (`palo:<name>`) that exist in
        no tenant.  A name already present classifies as update; a novel name
        classifies as create.

        Ids of matched resources are seeded into the plan's remap so that a
        candidate referencing another candidate that already exists resolves to
        the real tenant id at push time.
        """
        resources = target.get("resources", target) if isinstance(target, dict) else {}
        current = self._current_state(refresh_from_tenant, import_progress_callback)

        plan = PushPlan(mode=MODE_MERGE)

        for rtype in self._ordered_types(resources.keys()):
            existing_by_name = {
                (item.get("name") or "").casefold(): item
                for item in current.get(rtype, [])
                if item.get("name")
            }
            for item in resources.get(rtype) or []:
                source_id = item.get("id")
                name = item.get("name") or source_id or ""
                match = existing_by_name.get(name.casefold()) if name else None

                if match:
                    if source_id and match["id"] and source_id != match["id"]:
                        plan.id_remap[str(source_id)] = str(match["id"])
                    plan.updates.append(self._entry(
                        rtype, UPDATE, name,
                        supported=rtype in CAN_UPDATE,
                        target_id=match["id"],
                        source_id=source_id,
                        desired_config=item.get("raw_config") or {},
                        pre_config=match.get("raw_config") or {},
                    ))
                else:
                    plan.creates.append(self._entry(
                        rtype, CREATE, name,
                        supported=rtype in CAN_CREATE,
                        source_id=source_id,
                        desired_config=item.get("raw_config") or {},
                    ))

        return plan

    # Convenience wrapper mirroring ZIAPushService.classify_baseline naming.
    def classify(
        self,
        target: Dict[str, Any],
        mode: str = MODE_MERGE,
        refresh_from_tenant: bool = False,
        import_progress_callback: Optional[Callable] = None,
    ) -> PushPlan:
        if mode == MODE_RESTORE:
            resources = target.get("resources", target) if isinstance(target, dict) else {}
            return self.classify_restore(resources, refresh_from_tenant, import_progress_callback)
        if mode == MODE_MERGE:
            return self.classify_merge(target, refresh_from_tenant, import_progress_callback)
        raise ValueError(f"Unknown push mode: {mode!r}")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def push_classified(
        self,
        plan: PushPlan,
        progress_callback: Optional[Callable] = None,
        stop_fn: Optional[Callable[[], bool]] = None,
        audit_operation: str = "push",
        audit_details: Optional[dict] = None,
    ) -> List[PushRecord]:
        """Execute a plan: deletes, then creates, then updates.

        Entries the API cannot service are reported as `manual` records in the
        position they occupy in the plan, so the emitted record sequence matches
        a straight walk of the classification.

        Args:
            progress_callback: called after every record with a dict of
                {action, resource_type, name, status, reason, done, total}.
            stop_fn: polled between records; when it returns True, raises
                ZPAPushCancelled carrying the records applied so far.
        """
        self._id_map = dict(plan.id_remap)
        self._executed = []

        records: List[PushRecord] = []
        total = plan.total
        details = dict(audit_details or {})

        def emit(record: PushRecord, entry: PushPlanEntry) -> None:
            records.append(record)
            self._executed.append((entry, record))
            if progress_callback:
                event = record.to_item()
                event["done"] = len(records)
                event["total"] = total
                progress_callback(event)

        for entry in plan.entries:
            if stop_fn and stop_fn():
                raise ZPAPushCancelled(records)

            if not entry.supported:
                emit(PushRecord(
                    resource_type=entry.resource_type, name=entry.name,
                    action=entry.action, status=MANUAL,
                    reason=entry.skip_reason,
                ), entry)
                continue

            if entry.action == DELETE:
                emit(self._do_delete(entry, audit_operation, details), entry)
            elif entry.action == CREATE:
                emit(self._do_create(entry, audit_operation, details), entry)
            else:
                emit(self._do_update(entry, audit_operation, details), entry)

        return records

    def rollback_pushed(
        self,
        audit_operation: str = "push_rollback",
    ) -> List[PushRecord]:
        """Undo the writes made by the last push_classified() call.

        Creates are deleted; updates are restored from the config captured at
        classification time.  Deletes cannot be undone and are reported as
        `manual`.  Walks in reverse so dependents unwind before dependencies.

        ID remapping is suppressed for the duration: `pre_config` holds state
        that already existed in the tenant under live tenant ids, and every
        entry in the map points at a resource this rollback is about to delete.
        Restoring must write back the captured bytes, not rewrite them.
        """
        out: List[PushRecord] = []
        saved_id_map, self._id_map = self._id_map, {}
        try:
            out = self._rollback_entries(audit_operation)
        finally:
            self._id_map = saved_id_map
        return out

    def _rollback_entries(self, audit_operation: str) -> List[PushRecord]:
        out: List[PushRecord] = []
        for entry, record in reversed(self._executed):
            if not record.is_applied:
                continue
            if record.action == CREATE and record.resource_id:
                undo = PushPlanEntry(
                    resource_type=entry.resource_type, name=entry.name,
                    action=DELETE, supported=entry.resource_type in CAN_DELETE,
                    target_id=record.resource_id,
                    skip_reason=_UNSUPPORTED[DELETE],
                )
                out.append(
                    self._do_delete(undo, audit_operation, {})
                    if undo.supported else
                    PushRecord(entry.resource_type, entry.name, DELETE, MANUAL,
                               reason=_UNSUPPORTED[DELETE])
                )
            elif record.action == UPDATE and entry.pre_config:
                undo = PushPlanEntry(
                    resource_type=entry.resource_type, name=entry.name,
                    action=UPDATE, supported=True,
                    target_id=entry.target_id, desired_config=entry.pre_config,
                )
                out.append(self._do_update(undo, audit_operation, {}))
        return out

    @staticmethod
    def affected_types(plan: PushPlan) -> List[str]:
        """Resource types the plan touches, in dependency order."""
        present = set(plan.affected_types)
        return [rt for rt in RTYPE_ORDER if rt in present]

    def sync_after_push(self, plan: PushPlan) -> None:
        """Best-effort re-import of the resource types the plan touched."""
        affected = self.affected_types(plan)
        if not affected:
            return
        try:
            from services.zpa_import_service import ZPAImportService
            ZPAImportService(self._client, self._tenant_id).run(resource_types=affected)
        except Exception:
            pass  # the push result is already recorded; sync is advisory

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _current_state(
        self,
        refresh_from_tenant: bool,
        import_progress_callback: Optional[Callable],
    ) -> Dict[str, List[dict]]:
        from db.database import get_session
        from services.snapshot_service import get_snapshot_data_current

        if refresh_from_tenant:
            from services.zpa_import_service import ZPAImportService
            ZPAImportService(self._client, self._tenant_id).run(
                progress_callback=import_progress_callback
            )

        with get_session() as session:
            return get_snapshot_data_current(self._tenant_id, "ZPA", session)

    def _ordered_types(self, present) -> List[str]:
        present = list(present)
        ordered = [rt for rt in RTYPE_ORDER if rt in present]
        return ordered + sorted(rt for rt in present if rt not in RTYPE_ORDER)

    @staticmethod
    def _entry(
        rtype: str,
        action: str,
        name: str,
        supported: bool,
        target_id: Optional[str] = None,
        source_id: Optional[str] = None,
        desired_config: Optional[dict] = None,
        pre_config: Optional[dict] = None,
    ) -> PushPlanEntry:
        return PushPlanEntry(
            resource_type=rtype, name=name, action=action, supported=supported,
            target_id=target_id, source_id=source_id,
            desired_config=desired_config or {}, pre_config=pre_config or {},
            skip_reason="" if supported else _UNSUPPORTED[action],
        )

    def _remap_ids(self, obj: Any) -> Any:
        """Rewrite known source ids to target ids anywhere in a payload."""
        if not self._id_map:
            return obj
        if isinstance(obj, dict):
            return {k: self._remap_ids(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._remap_ids(i) for i in obj]
        if isinstance(obj, str) and obj in self._id_map:
            return self._id_map[obj]
        return obj

    def _clean_payload(self, rtype: str, raw: dict, is_create: bool) -> dict:
        strip = set(PAYLOAD_META)
        if is_create:
            strip.add("id")
        strip |= TYPE_EXTRA_STRIP.get(rtype, frozenset())
        return self._remap_ids({k: v for k, v in raw.items() if k not in strip})

    def _audit(self, action: str, status: str, entry: PushPlanEntry,
               operation: str, details: dict,
               resource_id: Optional[str] = None, error: str = "") -> None:
        from services import audit_service

        kwargs: Dict[str, Any] = {
            "product": "ZPA", "operation": operation, "action": action.upper(),
            "status": status, "tenant_id": self._tenant_id,
            "resource_type": entry.resource_type, "resource_name": entry.name,
        }
        if resource_id:
            kwargs["resource_id"] = resource_id
        if error:
            kwargs["error_message"] = error
        elif details:
            kwargs["details"] = dict(details)
        audit_service.log(**kwargs)

    def _do_create(self, entry: PushPlanEntry, operation: str, details: dict) -> PushRecord:
        rtype, name = entry.resource_type, entry.name
        payload = self._clean_payload(rtype, entry.desired_config, is_create=True)
        client = self._client
        try:
            if rtype == "segment_group":
                result = client.create_segment_group_full(**payload)
            elif rtype == "server_group":
                result = client.create_server_group_full(**payload)
            elif rtype == "app_connector_group":
                result = client.create_connector_group(**payload)
            elif rtype == "application":
                result = client.create_application(**payload)
            elif rtype == "pra_portal":
                result = client.create_pra_portal(**payload)
            elif rtype == "user_portal":
                result = client.create_user_portal(**payload)
            elif rtype == "pra_console":
                result = client.create_pra_console(**payload)
            elif rtype == "policy_access":
                kw = dict(payload)
                ac_name = kw.pop("name", name)
                ac_action = kw.pop("action", "ALLOW")
                result = client.create_access_rule(name=ac_name, action=ac_action, **kw)
            else:
                raise ValueError("unsupported")

            new_id = str(result.get("id", ""))
            if entry.source_id and new_id:
                self._id_map[str(entry.source_id)] = new_id
            self._audit("CREATE", "SUCCESS", entry, operation, details, resource_id=new_id)
            return PushRecord(rtype, name, CREATE, APPLIED, resource_id=new_id or None)
        except Exception as exc:
            reason = _redact(str(exc))
            self._audit("CREATE", "FAILURE", entry, operation, details, error=reason)
            return PushRecord(rtype, name, CREATE, FAILED, reason=reason)

    def _do_update(self, entry: PushPlanEntry, operation: str, details: dict) -> PushRecord:
        rtype, name, rid = entry.resource_type, entry.name, entry.target_id
        payload = self._clean_payload(rtype, entry.desired_config, is_create=False)
        client = self._client
        try:
            if rtype == "segment_group":
                client.update_segment_group(rid, payload)
            elif rtype == "server_group":
                client.update_server_group(rid, payload)
            elif rtype == "app_connector_group":
                client.update_connector_group(rid, payload)
            elif rtype == "application":
                client.update_application(rid, payload)
            elif rtype == "pra_portal":
                client.update_pra_portal(rid, payload)
            elif rtype == "user_portal":
                client.update_user_portal(rid, payload)
            elif rtype == "pra_console":
                client.update_pra_console(rid, payload)
            elif rtype == "app_connector":
                client.update_connector(rid, payload)
            elif rtype == "service_edge":
                client.update_service_edge(rid, payload)
            elif rtype in POLICY_TYPE_MAP:
                client.update_policy_rule(POLICY_TYPE_MAP[rtype], rid, payload)
            else:
                raise ValueError("unsupported")

            self._audit("UPDATE", "SUCCESS", entry, operation, details, resource_id=rid)
            return PushRecord(rtype, name, UPDATE, APPLIED, resource_id=rid)
        except Exception as exc:
            reason = _redact(str(exc))
            self._audit("UPDATE", "FAILURE", entry, operation, details,
                        resource_id=rid, error=reason)
            return PushRecord(rtype, name, UPDATE, FAILED, reason=reason, resource_id=rid)

    def _do_delete(self, entry: PushPlanEntry, operation: str, details: dict) -> PushRecord:
        rtype, name, rid = entry.resource_type, entry.name, entry.target_id
        client = self._client
        try:
            if rtype == "segment_group":
                client.delete_segment_group(rid)
            elif rtype == "server_group":
                client.delete_server_group(rid)
            elif rtype == "app_connector_group":
                client.delete_connector_group(rid)
            elif rtype == "application":
                client.delete_application(rid)
            elif rtype == "pra_portal":
                client.delete_pra_portal(rid)
            elif rtype == "user_portal":
                client.delete_user_portal(rid)
            elif rtype == "pra_console":
                client.delete_pra_console(rid)
            elif rtype == "app_connector":
                client.delete_connector(rid)
            elif rtype in POLICY_TYPE_MAP:
                client.delete_policy_rule(POLICY_TYPE_MAP[rtype], rid)
            else:
                raise ValueError("unsupported")

            self._audit("DELETE", "SUCCESS", entry, operation, details, resource_id=rid)
            return PushRecord(rtype, name, DELETE, APPLIED, resource_id=rid)
        except Exception as exc:
            reason = _redact(str(exc))
            self._audit("DELETE", "FAILURE", entry, operation, details,
                        resource_id=rid, error=reason)
            return PushRecord(rtype, name, DELETE, FAILED, reason=reason, resource_id=rid)
