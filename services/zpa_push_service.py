"""ZPA baseline push service.

Baseline push strategy:
  1. IMPORT      — fresh import of target tenant state into DB
  2. EVALUATE    — classify every DB resource as user-created or Zscaler-managed
  3. WIPE        — (wipe-first only) delete all user-created resources in reverse order
  4. PUSH        — two passes:
                   a) Update Zscaler-managed resources (default rules) to match baseline
                   b) Create/update all user-defined baseline resources in dependency order

No activation step — ZPA changes take effect immediately.

Delta-only mode:

    service = ZPAPushService(client, tenant_id=tenant.id)
    dry_run = service.classify_baseline(baseline_dict)
    push_records = service.push_classified(dry_run)

Wipe-first mode:

    service = ZPAPushService(client, tenant_id=tenant.id)
    wipe_result = service.classify_wipe()
    wipe_records = service.execute_wipe(wipe_result, progress_callback=...)
    dry_run = service.classify_baseline(baseline_dict)
    push_records = service.push_classified(dry_run, progress_callback=...)

ID remapping: source→target IDs registered during classification and after
each successful create; applied to every outbound payload including nested
condition operand values in policy rules.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Push order — resources are attempted tier by tier within each pass
# ---------------------------------------------------------------------------

PUSH_ORDER: List[str] = [
    # Tier 1 — groups (no cross-type deps)
    "segment_group",
    "app_connector_group",
    "server_group",
    # Tier 2 — applications (reference segment_group, server_group, app_connector_group)
    "application",
    # Tier 3 — PRA (pra_portal references certificate; pra_console references pra_portal + app)
    "pra_portal",
    "pra_credential",
    "pra_console",
    # Tier 4 — policies (reference application, segment_group, app_connector_group,
    #           server_group, idp, saml_attribute, scim_group, posture_profile, etc.)
    "policy_access",
    "policy_timeout",
    "policy_forwarding",
    "policy_inspection",
    "policy_isolation",
    # Tier 5 — logging / auxiliary
    "lss_config",
]

# Wipe order is the exact reverse of push order
WIPE_ORDER: List[str] = list(reversed(PUSH_ORDER))

# Types that are env-specific or read-only — skip entirely (never create/update/delete)
SKIP_TYPES: set = {
    "idp",
    "saml_attribute",
    "scim_group",
    "scim_attribute",
    "posture_profile",
    "machine_group",
    "trusted_network",
    "enrollment_cert",
    "certificate",
    "microtenant",
    "server",
}

# Infrastructure types — skip with a warning message
SKIP_WITH_WARNING: set = {
    "app_connector",
    "service_edge",
    "service_edge_group",
}

SKIP_WITH_WARNING_MESSAGES: Dict[str, str] = {
    "app_connector": (
        "App Connectors represent physical infrastructure and cannot be migrated. "
        "Enroll new connectors manually in the target tenant."
    ),
    "service_edge": (
        "Service Edges represent physical infrastructure and cannot be migrated. "
        "Enroll new service edges manually in the target tenant."
    ),
    "service_edge_group": (
        "Service Edge Groups cannot be pushed without enrolled Service Edges. "
        "Create manually after enrolling edges in the target tenant."
    ),
}

# Read-only types used only for ID remapping (pre-pass)
REMAP_ONLY_TYPES: set = {
    "idp",
    "saml_attribute",
    "scim_group",
    "scim_attribute",
    "posture_profile",
    "machine_group",
    "trusted_network",
    "enrollment_cert",
}

# Fields always stripped from raw_config before comparison and before push.
# These are the camelCase field names as used in ZPA API responses.
READONLY_FIELDS: set = {
    "id",
    "predefined",
    "defaultRule",
    "isDefaultRule",
    "creationTime",
    "modifiedTime",
    "modifiedBy",
    "lastModifiedBy",
    "lastModifiedTime",
    "isDeleted",
    "deleted",
}

# ---------------------------------------------------------------------------
# SDK method dispatch tables
# ---------------------------------------------------------------------------

_WRITE_METHODS: Dict[str, Tuple[str, str]] = {
    # (create_method, update_method)
    "segment_group":       ("create_segment_group",    "update_segment_group"),
    "app_connector_group": ("create_connector_group",  "update_connector_group"),
    "server_group":        ("create_server_group",     "update_server_group"),
    "application":         ("create_application",      "update_application"),
    "pra_portal":          ("create_pra_portal",       "update_pra_portal"),
    "pra_credential":      ("create_pra_credential",   "update_pra_credential"),
    "pra_console":         ("create_pra_console",      "update_pra_console"),
    "policy_access":       ("create_access_rule",      "update_access_rule"),
    "policy_timeout":      ("create_timeout_rule",     "update_timeout_rule"),
    "policy_forwarding":   ("create_forwarding_rule",  "update_forwarding_rule"),
    "policy_inspection":   ("create_inspection_rule",  "update_inspection_rule"),
    "policy_isolation":    ("create_isolation_rule",   "update_isolation_rule"),
    "lss_config":          ("create_lss_config",       "update_lss_config"),
}

_DELETE_METHODS: Dict[str, str] = {
    "segment_group":       "delete_segment_group",
    "app_connector_group": "delete_connector_group",
    "server_group":        "delete_server_group",
    "application":         "delete_application",
    "pra_portal":          "delete_pra_portal",
    "pra_credential":      "delete_pra_credential",
    "pra_console":         "delete_pra_console",
    "policy_access":       "delete_access_rule",
    "policy_timeout":      "delete_timeout_rule",
    "policy_forwarding":   "delete_forwarding_rule",
    "policy_inspection":   "delete_inspection_rule",
    "policy_isolation":    "delete_isolation_rule",
    "lss_config":          "delete_lss_config",
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PushRecord:
    resource_type: str
    name: str
    status: str   # "created" | "updated" | "deleted" | "skipped" | "failed:<reason>"
    warnings: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

    @property
    def is_created(self) -> bool:
        return self.status == "created"

    @property
    def is_updated(self) -> bool:
        return self.status == "updated"

    @property
    def is_deleted(self) -> bool:
        return self.status == "deleted"

    @property
    def is_skipped(self) -> bool:
        return self.status == "skipped" or self.status.startswith("skipped:")

    @property
    def is_failed(self) -> bool:
        return self.status.startswith("failed:")

    @property
    def is_permanent_failure(self) -> bool:
        return self.status.startswith("failed:permanent:")

    @property
    def failure_reason(self) -> str:
        if self.is_failed:
            reason = self.status[len("failed:"):]
            return reason[len("permanent:"):] if reason.startswith("permanent:") else reason
        return ""


@dataclass
class WipeRecord:
    resource_type: str
    name: str
    zpa_id: str
    status: str  # "pending_delete" | "deleted" | "skipped" | "failed:<reason>"

    @property
    def is_deleted(self) -> bool:
        return self.status == "deleted"

    @property
    def is_skipped(self) -> bool:
        return self.status.startswith("skipped")

    @property
    def is_failed(self) -> bool:
        return self.status.startswith("failed:")


@dataclass
class WipeResult:
    """Classification output from classify_wipe() — no mutations made."""
    to_delete: List[WipeRecord]

    @property
    def delete_count(self) -> int:
        return len(self.to_delete)

    def type_summary(self) -> Dict[str, int]:
        """Return {resource_type: count} for the proposed deletions."""
        out: Dict[str, int] = {}
        for r in self.to_delete:
            out[r.resource_type] = out.get(r.resource_type, 0) + 1
        return out


# ---------------------------------------------------------------------------
# Dry-run result
# ---------------------------------------------------------------------------

@dataclass
class DryRunResult:
    """Classification output from classify_baseline() — no API writes made."""
    # Skipped records (predefined, identical config, SKIP_TYPES, infrastructure)
    skipped: List[PushRecord]
    # Entries queued to push, keyed by resource_type; each entry dict has
    # __action ("create"|"update"), __target_id, __display_name, __managed
    pending: Dict[str, List[dict]]
    # Resources present in the tenant but absent from the baseline — to be deleted
    to_delete: List[PushRecord]   # status = "pending_delete:<zpa_id>"
    # ID remap populated during classification (preserved for push_classified)
    id_remap: Dict[str, str]

    @property
    def create_count(self) -> int:
        return sum(1 for v in self.pending.values()
                   for e in v if e.get("__action") == "create")

    @property
    def update_count(self) -> int:
        return sum(1 for v in self.pending.values()
                   for e in v if e.get("__action") == "update")

    @property
    def skip_count(self) -> int:
        return len(self.skipped)

    @property
    def delete_count(self) -> int:
        return len(self.to_delete)

    def type_summary(self) -> Dict[str, Dict[str, int]]:
        """Return {rtype: {"create": N, "update": N, "skip": N, "delete": N}} across all types."""
        out: Dict[str, Dict[str, int]] = {}
        for r in self.skipped:
            out.setdefault(r.resource_type, {"create": 0, "update": 0, "skip": 0, "delete": 0})
            out[r.resource_type]["skip"] += 1
        for rtype, entries in self.pending.items():
            out.setdefault(rtype, {"create": 0, "update": 0, "skip": 0, "delete": 0})
            for e in entries:
                key = "create" if e.get("__action") == "create" else "update"
                out[rtype][key] += 1
        for r in self.to_delete:
            out.setdefault(r.resource_type, {"create": 0, "update": 0, "skip": 0, "delete": 0})
            out[r.resource_type]["delete"] += 1
        return out

    def changes_by_action(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str]]]:
        """Return (creates, updates, deletes) as lists of (resource_type, display_name) tuples."""
        creates, updates, deletes = [], [], []
        for rtype, entries in self.pending.items():
            for e in entries:
                dname = e.get("__display_name") or e.get("name") or "?"
                if e.get("__action") == "create":
                    creates.append((rtype, dname))
                else:
                    updates.append((rtype, dname))
        for r in self.to_delete:
            deletes.append((r.resource_type, r.name))
        return creates, updates, deletes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_zscaler_managed(rtype: str, raw_config: dict) -> bool:
    """Return True if this resource is Zscaler-managed (skip during create; remap ID only)."""
    if rtype in SKIP_TYPES:
        return True
    if raw_config.get("predefined"):
        return True
    if raw_config.get("isDefaultRule") or raw_config.get("defaultRule"):
        return True
    return False


# ---------------------------------------------------------------------------
# Push service
# ---------------------------------------------------------------------------

class ZPAPushService:
    def __init__(self, client, tenant_id: int):
        self._client = client
        self._tenant_id = tenant_id
        self._id_remap: Dict[str, str] = {}          # source_id (str) → target_id (str)
        self._target_known_ids: Dict[str, set] = {}  # resource_type → set of zpa_ids in target

    # ------------------------------------------------------------------
    # Public API — wipe phase
    # ------------------------------------------------------------------

    def classify_wipe(
        self,
        import_progress_callback: Optional[Callable] = None,
    ) -> WipeResult:
        """Identify all user-created resources on the target tenant for deletion.

        Performs a fresh import so the classification reflects current live state.
        No mutations are made — inspect WipeResult.to_delete before calling
        execute_wipe().

        Args:
            import_progress_callback: Called during import phase.
                Signature: callback(resource_type: str, done: int, total: int)
        """
        from services.zpa_import_service import ZPAImportService
        import_svc = ZPAImportService(self._client, self._tenant_id)
        import_svc.run(progress_callback=import_progress_callback)

        existing = self._load_existing_from_db()
        to_delete: List[WipeRecord] = []

        for rtype in WIPE_ORDER:
            if rtype in SKIP_TYPES:
                continue
            if rtype not in _DELETE_METHODS:
                continue

            existing_for_type = existing.get(rtype) or {}
            for zpa_id, entry in existing_for_type.items():
                name = entry.get("name", "")
                raw = entry.get("raw_config", {})
                if _is_zscaler_managed(rtype, raw):
                    continue
                to_delete.append(WipeRecord(
                    resource_type=rtype,
                    name=name or zpa_id,
                    zpa_id=zpa_id,
                    status="pending_delete",
                ))

        return WipeResult(to_delete=to_delete)

    def execute_wipe(
        self,
        wipe_result: WipeResult,
        progress_callback: Optional[Callable] = None,
    ) -> List[WipeRecord]:
        """Execute deletions identified by classify_wipe().

        Deletes user-created resources in reverse-dependency order (as listed in
        wipe_result.to_delete, which was already sorted by classify_wipe).
        A failed delete is logged and the wipe continues — it does not abort.

        Args:
            wipe_result: Result from classify_wipe().
            progress_callback: Called after each delete attempt.
                Signature: callback(resource_type: str, record: WipeRecord)

        Returns:
            List of WipeRecord with updated status ("deleted" | "failed:...").
        """
        records: List[WipeRecord] = []
        for item in wipe_result.to_delete:
            rec = self._wipe_delete_one(item)
            if progress_callback:
                progress_callback(item.resource_type, rec)
            records.append(rec)
        return records

    # ------------------------------------------------------------------
    # Public API — push phase
    # ------------------------------------------------------------------

    def classify_baseline(
        self,
        baseline: dict,
        import_progress_callback: Optional[Callable] = None,
    ) -> DryRunResult:
        """Import target state, load DB, classify each baseline entry.

        No API writes are made.  Returns a DryRunResult the caller can inspect
        before deciding whether to call push_classified().

        Args:
            baseline: Parsed snapshot export JSON dict (must have 'resources' key).
            import_progress_callback: Called during the fresh import phase.
                Signature: callback(resource_type: str, done: int, total: int)
        """
        from services.zpa_import_service import ZPAImportService
        import_svc = ZPAImportService(self._client, self._tenant_id)
        import_svc.run(progress_callback=import_progress_callback)

        existing = self._load_existing_from_db()
        self._target_known_ids = {
            rtype: set(type_data.keys())
            for rtype, type_data in existing.items()
        }

        resources = baseline.get("resources", {})

        # Pre-pass: register remaps for read-only types (idp, saml_attribute, etc.)
        # so that policy condition operand values can be remapped cross-tenant.
        for rtype in REMAP_ONLY_TYPES:
            if rtype not in resources:
                continue
            existing_for_type = existing.get(rtype) or {}
            # Build name → target_id map for this type
            target_name_map: Dict[str, str] = {}
            for entry in existing_for_type.values():
                n = entry.get("name", "")
                if n:
                    target_name_map[n] = entry["id"]

            for src_entry in (resources.get(rtype) or []):
                src_id = str(src_entry.get("id", ""))
                src_name = src_entry.get("name", "")
                if src_id and src_name and src_name in target_name_map:
                    self._register_remap(src_id, target_name_map[src_name])
                elif src_id and src_name:
                    # No name match — warn so the caller knows remapping will be incomplete
                    pass  # logged at push time when the value cannot be remapped

        ordered_types = [t for t in PUSH_ORDER if t in resources]
        extra_types = [t for t in resources if t not in PUSH_ORDER and t not in ordered_types]
        ordered_types.extend(extra_types)

        pending: Dict[str, List[dict]] = {}
        skipped: List[PushRecord] = []

        for rtype in ordered_types:
            if rtype in SKIP_TYPES:
                continue

            entries = resources.get(rtype) or []

            if rtype in SKIP_WITH_WARNING:
                warn_msg = SKIP_WITH_WARNING_MESSAGES.get(rtype, "Infrastructure resource; skip manually.")
                for entry in entries:
                    name = entry.get("name") or str(entry.get("id", "?"))
                    rec = PushRecord(rtype, name, "skipped:infrastructure")
                    rec.warnings.append(warn_msg)
                    skipped.append(rec)
                continue

            existing_for_type = existing.get(rtype) or {}

            for entry in entries:
                name = entry.get("name") or ""
                source_id = str(entry.get("id", ""))
                raw_config = entry.get("raw_config", {})
                display_name = name or source_id or "?"

                if _is_zscaler_managed(rtype, raw_config):
                    # Default rules (isDefaultRule / defaultRule) can be updated
                    # but never created or deleted.
                    existing_entry = self._find_existing_user(existing_for_type, name)
                    if existing_entry:
                        target_id = existing_entry["id"]
                        if source_id:
                            self._register_remap(source_id, target_id)
                        if not self._configs_match(raw_config, existing_entry["raw_config"]):
                            pending.setdefault(rtype, []).append(
                                dict(entry,
                                     __action="update",
                                     __target_id=target_id,
                                     __display_name=display_name,
                                     __managed=True)
                            )
                            continue
                    skipped.append(PushRecord(rtype, display_name, "skipped:managed"))
                    continue

                # User-created resources: match by name only (IDs are tenant-specific UUIDs)
                existing_entry = self._find_existing_user(existing_for_type, name)

                if existing_entry:
                    target_id = existing_entry["id"]
                    if source_id:
                        self._register_remap(source_id, target_id)

                    if self._configs_match(raw_config, existing_entry["raw_config"]):
                        skipped.append(PushRecord(rtype, display_name, "skipped"))
                        continue

                    queued = dict(entry,
                                  __action="update",
                                  __target_id=target_id,
                                  __display_name=display_name,
                                  __managed=False)
                else:
                    queued = dict(entry,
                                  __action="create",
                                  __display_name=display_name,
                                  __managed=False)

                pending.setdefault(rtype, []).append(queued)

        # Sort policy rules by ascending ruleOrder so lower-numbered rules are
        # processed first (ZPA accepts explicit ruleOrder values — no stacking needed).
        _POLICY_TYPES = {
            "policy_access", "policy_timeout", "policy_forwarding",
            "policy_inspection", "policy_isolation",
        }
        for rtype in _POLICY_TYPES:
            if rtype in pending:
                pending[rtype].sort(
                    key=lambda e: (e.get("raw_config") or {}).get("ruleOrder") or 0
                )

        # Identify extraneous resources present in the tenant but absent from baseline.
        # Only generate deletes for resource types that appear in the baseline file.
        to_delete: List[PushRecord] = []
        for rtype in ordered_types:
            if rtype in SKIP_TYPES or rtype in SKIP_WITH_WARNING:
                continue
            if rtype not in _DELETE_METHODS:
                continue

            baseline_entries = resources.get(rtype) or []
            baseline_names = {e.get("name", "") for e in baseline_entries if e.get("name")}

            for zpa_id, entry in (existing.get(rtype) or {}).items():
                name = entry.get("name", "")
                raw = entry.get("raw_config", {})

                if name in baseline_names:
                    continue
                if _is_zscaler_managed(rtype, raw):
                    continue

                to_delete.append(PushRecord(
                    resource_type=rtype,
                    name=name or zpa_id,
                    status=f"pending_delete:{zpa_id}",
                ))

        return DryRunResult(
            skipped=skipped,
            pending=pending,
            to_delete=to_delete,
            id_remap=dict(self._id_remap),
        )

    def verify_push(
        self,
        baseline: dict,
        import_progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> DryRunResult:
        """Re-classify the baseline against the current live state after a push.

        Returns a new DryRunResult.  An ideal post-push result has zero pending
        creates/updates and zero to_delete entries.
        """
        return self.classify_baseline(baseline, import_progress_callback=import_progress_callback)

    def push_classified(
        self,
        dry_run: DryRunResult,
        progress_callback: Optional[Callable] = None,
    ) -> List[PushRecord]:
        """Push the delta from a prior classify_baseline() call.

        Two-pass execution:
          Pass 1 — Update Zscaler-managed resources (default rules) to match baseline.
          Pass 2+ — Create/update user-defined resources with multi-pass retry.

        Args:
            dry_run: Result from classify_baseline().
            progress_callback: Called after each push attempt.
                Signature: callback(pass_num: int, resource_type: str, record: PushRecord)
        """
        self._id_remap = dict(dry_run.id_remap)

        managed_pending: Dict[str, List[dict]] = {}
        user_pending: Dict[str, List[dict]] = {}

        for rtype, entries in dry_run.pending.items():
            for entry in entries:
                if entry.get("__managed"):
                    managed_pending.setdefault(rtype, []).append(entry)
                else:
                    user_pending.setdefault(rtype, []).append(entry)

        all_records: List[PushRecord] = []

        # Pass 1 — managed resources (default rules: update only)
        if managed_pending:
            _, pass1_records = self._single_pass(managed_pending, 1, progress_callback)
            all_records.extend(pass1_records)

        # Pass 2+ — user-defined resources with multi-pass retry
        pending = user_pending
        pass_num = 1
        while pending:
            pass_num += 1
            prev_count = sum(len(v) for v in pending.values())

            new_pending, pass_records = self._single_pass(pending, pass_num, progress_callback)
            all_records.extend(pass_records)
            pending = new_pending

            if sum(len(v) for v in pending.values()) >= prev_count:
                for rtype, entries in pending.items():
                    for entry in entries:
                        last_err = entry.get("__last_error", "unknown error")
                        dname = entry.get("__display_name") or entry.get("name") or "?"
                        all_records.append(PushRecord(
                            resource_type=rtype,
                            name=dname,
                            status=f"failed:{last_err} (stable, no progress)",
                        ))
                break

        return all_records

    def execute_deletes(
        self,
        to_delete: List[PushRecord],
        progress_callback: Optional[Callable] = None,
    ) -> List[PushRecord]:
        """Execute a confirmed delete list from classify_baseline().

        Deletes are intentionally separated from push_classified so the caller
        can present the proposed deletes and require confirmation.
        """
        records: List[PushRecord] = []
        for rec in to_delete:
            zpa_id = rec.status.partition(":")[2]
            delete_rec = self._delete_one(rec.resource_type, rec.name, zpa_id)
            if progress_callback:
                progress_callback(0, rec.resource_type, delete_rec)
            records.append(delete_rec)
        return records

    # ------------------------------------------------------------------
    # Wipe internals
    # ------------------------------------------------------------------

    def _wipe_delete_one(self, item: WipeRecord) -> WipeRecord:
        """Attempt to delete a single resource identified by classify_wipe()."""
        rtype = item.resource_type
        method_name = _DELETE_METHODS.get(rtype)

        try:
            if method_name:
                getattr(self._client, method_name)(item.zpa_id)
            else:
                return WipeRecord(rtype, item.name, item.zpa_id, "skipped")
            return WipeRecord(rtype, item.name, item.zpa_id, "deleted")
        except Exception as exc:
            exc_str = str(exc)
            permanent = bool(re.search(r'"status"\s*:\s*(400|403|404)', exc_str)) or \
                        any(s in exc_str for s in ("NOT_SUBSCRIBED", "not licensed"))
            prefix = "failed:permanent:" if permanent else "failed:"
            return WipeRecord(rtype, item.name, item.zpa_id, f"{prefix}{exc_str[:150]}")

    # ------------------------------------------------------------------
    # Push internals
    # ------------------------------------------------------------------

    def _load_existing_from_db(self) -> Dict[str, Dict[str, dict]]:
        """Load all non-deleted ZPA resources for this tenant from the DB.

        Returns:
            {resource_type: {zpa_id: {"id": str, "name": str, "raw_config": dict}}}
        """
        from db.database import get_session
        from db.models import ZPAResource

        result: Dict[str, Dict[str, dict]] = {}
        with get_session() as session:
            rows = (
                session.query(ZPAResource)
                .filter_by(tenant_id=self._tenant_id, is_deleted=False)
                .all()
            )
            for row in rows:
                result.setdefault(row.resource_type, {})[row.zpa_id] = {
                    "id": row.zpa_id,
                    "name": row.name or "",
                    "raw_config": row.raw_config or {},
                }
        return result

    def _find_existing_user(
        self,
        existing_for_type: Dict[str, dict],
        name: str,
    ) -> Optional[dict]:
        """Locate a resource by name only — no ID fallback.

        ZPA resource IDs are tenant-specific UUIDs; matching by ID across tenants
        would produce false positives.
        """
        if name:
            for entry in existing_for_type.values():
                if entry.get("name") == name:
                    return entry
        return None

    def _configs_match(self, baseline_config: dict, existing_config: dict) -> bool:
        """Return True if the two configs are semantically identical after stripping read-only fields."""
        src = self._normalize(self._strip(baseline_config))
        tgt = self._normalize(self._strip(existing_config))
        return src == tgt

    def _strip(self, config: dict) -> dict:
        """Remove read-only fields from a config dict (shallow copy)."""
        return {k: v for k, v in config.items() if k not in READONLY_FIELDS}

    def _normalize(self, value):
        """Recursively normalize a config value for stable comparison."""
        if isinstance(value, dict):
            return {k: self._normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            normalized = [self._normalize(item) for item in value]
            try:
                return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True, default=str))
            except TypeError:
                return normalized
        return value

    def _register_remap(self, source_id: str, target_id: str) -> None:
        """Register a source→target ID mapping."""
        if source_id and target_id and source_id != target_id:
            self._id_remap[source_id] = target_id

    def _apply_id_remap(self, config: dict) -> dict:
        """Deep-walk config and replace any string value that exists in self._id_remap."""
        config = copy.deepcopy(config)
        return self._remap_recursive(config)

    def _remap_recursive(self, obj):
        """Recursively replace ID strings found in _id_remap."""
        if isinstance(obj, dict):
            return {k: self._remap_recursive(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._remap_recursive(i) for i in obj]
        if isinstance(obj, str) and obj in self._id_remap:
            return self._id_remap[obj]
        return obj

    def _single_pass(
        self,
        pending: Dict[str, List[dict]],
        pass_num: int,
        progress_callback=None,
    ) -> Tuple[Dict[str, List[dict]], List[PushRecord]]:
        """One iteration over pending resources.

        Returns (new_pending, records_this_pass).
        Permanent failures (4xx) are not retried.
        Transient failures are kept in new_pending with __last_error set.
        """
        new_pending: Dict[str, List[dict]] = {}
        records: List[PushRecord] = []

        # Process types in PUSH_ORDER, then any extras
        type_order = [t for t in PUSH_ORDER if t in pending]
        type_order += [t for t in pending if t not in type_order]

        for rtype in type_order:
            entries = pending.get(rtype, [])
            remaining = []

            for entry in entries:
                rec = self._push_one(rtype, entry)
                if progress_callback:
                    progress_callback(pass_num, rtype, rec)

                if rec.is_failed and not rec.is_permanent_failure:
                    entry["__last_error"] = rec.failure_reason
                    remaining.append(entry)
                else:
                    records.append(rec)

            if remaining:
                new_pending[rtype] = remaining

        return new_pending, records

    def _push_one(self, resource_type: str, entry: dict) -> PushRecord:
        """Push a single pre-classified resource entry."""
        name = entry.get("__display_name") or entry.get("name") or "?"
        source_id = str(entry.get("id", ""))
        raw_config = entry.get("raw_config", {})
        action = entry.get("__action", "create")
        target_id = entry.get("__target_id")

        try:
            payload = self._build_payload(resource_type, raw_config)
            payload = self._apply_id_remap(payload)
            warnings: List[str] = []
            extra_warnings = payload.pop("__warnings", [])
            warnings.extend(extra_warnings)

            methods = _WRITE_METHODS.get(resource_type)
            if not methods:
                rec = PushRecord(resource_type, name, "skipped:no_method")
                return rec

            create_method_name, update_method_name = methods

            if action == "update" and target_id:
                update_method = getattr(self._client, update_method_name)
                # For update_application, pass (app_id, config)
                if resource_type == "application":
                    update_method(target_id, payload)
                elif resource_type in ("pra_portal", "pra_console"):
                    update_method(target_id, payload)
                elif resource_type == "app_connector_group":
                    update_method(target_id, payload)
                elif resource_type in ("segment_group", "server_group"):
                    update_method(target_id, **payload)
                elif resource_type == "pra_credential":
                    # Only update non-secret fields
                    cred_payload = {k: v for k, v in payload.items()
                                    if k not in ("password", "sshPublicKey", "passphrase")}
                    update_method(target_id, **cred_payload)
                elif resource_type.startswith("policy_"):
                    # Policy updates use update_policy_rule(policy_type, rule_id, config)
                    # or type-specific update methods
                    if resource_type == "policy_access":
                        self._client.update_access_rule(target_id, **payload)
                    elif resource_type == "policy_timeout":
                        self._client.update_timeout_rule(target_id, **payload)
                    elif resource_type == "policy_forwarding":
                        self._client.update_forwarding_rule(target_id, **payload)
                    elif resource_type == "policy_inspection":
                        self._client.update_inspection_rule(target_id, **payload)
                    elif resource_type == "policy_isolation":
                        self._client.update_isolation_rule(target_id, **payload)
                else:
                    update_method(target_id, **payload)
                rec = PushRecord(resource_type, name, "updated")
                rec.warnings.extend(warnings)
                return rec

            else:
                # CREATE
                create_method = getattr(self._client, create_method_name)
                result = None
                try:
                    if resource_type == "application":
                        result = create_method(**payload)
                    elif resource_type in ("pra_portal", "pra_console"):
                        result = create_method(**payload)
                    elif resource_type == "app_connector_group":
                        result = create_method(**payload)
                    elif resource_type in ("segment_group", "server_group"):
                        result = create_method(**payload)
                    elif resource_type == "pra_credential":
                        result = create_method(**payload)
                        warnings.append(
                            "Credential secret was not exported — set password/SSH key "
                            "manually in target tenant after push"
                        )
                    elif resource_type.startswith("policy_"):
                        policy_name = payload.pop("name", name)
                        policy_action = payload.pop("action", "ALLOW")
                        result = create_method(name=policy_name, action=policy_action, **payload)
                    else:
                        result = create_method(**payload)
                except Exception as exc:
                    exc_str = str(exc)
                    # 409/DUPLICATE or 400 "already exists" → attempt update by name lookup
                    if "409" in exc_str or "already exists" in exc_str.lower() or "DUPLICATE" in exc_str:
                        existing = self._load_existing_from_db()
                        existing_entry = self._find_existing_user(existing.get(resource_type, {}), name)
                        if existing_entry:
                            target_id = existing_entry["id"]
                            if source_id:
                                self._register_remap(source_id, target_id)
                            update_method = getattr(self._client, _WRITE_METHODS[resource_type][1])
                            if resource_type == "application":
                                update_method(target_id, payload)
                            elif resource_type in ("segment_group", "server_group"):
                                update_method(target_id, **payload)
                            elif resource_type == "pra_credential":
                                cred_payload = {k: v for k, v in payload.items()
                                                if k not in ("password", "sshPublicKey", "passphrase")}
                                update_method(target_id, **cred_payload)
                            elif resource_type.startswith("policy_"):
                                policy_name = payload.get("name", name)
                                policy_action = payload.get("action", "ALLOW")
                                update_method(target_id, name=policy_name, action=policy_action,
                                              **{k: v for k, v in payload.items()
                                                 if k not in ("name", "action")})
                            else:
                                update_method(target_id, **payload)
                            rec = PushRecord(resource_type, name, "updated")
                            rec.warnings.extend(warnings)
                            return rec
                    raise

                # Register source→target ID remap after successful create
                if result and isinstance(result, dict):
                    new_id = str(result.get("id", ""))
                    if new_id and source_id:
                        self._register_remap(source_id, new_id)

                rec = PushRecord(resource_type, name, "created")
                rec.warnings.extend(warnings)

                # Audit logging — collected and written after session closes
                pending_audit = []
                pending_audit.append(dict(
                    product="ZPA",
                    operation="apply_baseline",
                    action="CREATE",
                    status="SUCCESS",
                    tenant_id=self._tenant_id,
                    resource_type=resource_type,
                    resource_name=name,
                ))
                self._write_audit_events(pending_audit)
                return rec

        except Exception as exc:
            exc_str = str(exc)
            permanent = bool(re.search(r'"status"\s*:\s*(400|403|404)', exc_str)) or \
                        any(s in exc_str for s in ("NOT_SUBSCRIBED", "not licensed"))
            prefix = "failed:permanent:" if permanent else "failed:"
            pending_audit = [dict(
                product="ZPA",
                operation="apply_baseline",
                action=action.upper(),
                status="FAILURE",
                tenant_id=self._tenant_id,
                resource_type=resource_type,
                resource_name=name,
                error_message=exc_str[:500],
            )]
            self._write_audit_events(pending_audit)
            return PushRecord(resource_type, name, f"{prefix}{exc_str[:200]}")

    def _delete_one(self, rtype: str, name: str, zpa_id: str) -> PushRecord:
        """Delete a single resource by type and ZPA ID."""
        method_name = _DELETE_METHODS.get(rtype)
        try:
            if method_name:
                getattr(self._client, method_name)(zpa_id)
            else:
                return PushRecord(rtype, name, "skipped:no_delete_method")
            rec = PushRecord(rtype, name, "deleted")
            pending_audit = [dict(
                product="ZPA",
                operation="apply_baseline",
                action="DELETE",
                status="SUCCESS",
                tenant_id=self._tenant_id,
                resource_type=rtype,
                resource_name=name,
            )]
            self._write_audit_events(pending_audit)
            return rec
        except Exception as exc:
            exc_str = str(exc)
            permanent = bool(re.search(r'"status"\s*:\s*(400|403|404)', exc_str)) or \
                        any(s in exc_str for s in ("NOT_SUBSCRIBED", "not licensed"))
            prefix = "failed:permanent:" if permanent else "failed:"
            rec = PushRecord(rtype, name, f"{prefix}{exc_str[:200]}")
            rec.warnings.append(f"Delete failed: {exc_str[:200]}")
            pending_audit = [dict(
                product="ZPA",
                operation="apply_baseline",
                action="DELETE",
                status="FAILURE",
                tenant_id=self._tenant_id,
                resource_type=rtype,
                resource_name=name,
                error_message=exc_str[:500],
            )]
            self._write_audit_events(pending_audit)
            return rec

    def _write_audit_events(self, events: list) -> None:
        """Write audit events after all session blocks have closed."""
        from services import audit_service
        for evt in events:
            try:
                audit_service.log(**evt)
            except Exception:
                pass  # Audit failures must not abort a push

    def _build_payload(self, resource_type: str, raw_config: dict) -> dict:
        """Build the API payload for a resource, stripping read-only fields and
        applying type-specific transformations.

        Returns a dict ready to be passed to the create/update method.
        A special key '__warnings' may be present — caller must pop and handle it.
        """
        payload = {k: v for k, v in raw_config.items() if k not in READONLY_FIELDS}
        warnings: List[str] = []

        if resource_type == "application":
            # Strip plural port range forms — SDK conflict (same as enable_application)
            payload.pop("tcpPortRanges", None)
            payload.pop("udpPortRanges", None)

        elif resource_type == "app_connector_group":
            # Individual connectors are not managed here
            payload.pop("connectors", None)

        elif resource_type == "pra_portal":
            # If certificateId cannot be remapped, null it and warn
            cert_id = payload.get("certificateId")
            if cert_id and cert_id not in self._id_remap:
                # Check if it exists in the target's known certificate IDs
                target_cert_ids = self._target_known_ids.get("certificate", set())
                if cert_id not in target_cert_ids:
                    payload["certificateId"] = None
                    warnings.append(
                        "PRA Portal certificate not found in target tenant; set manually"
                    )

        elif resource_type == "pra_credential":
            # Credentials are created with empty secret placeholder
            cred_type = payload.get("credentialType", "")
            if cred_type in ("USERNAME_PASSWORD", "KERBEROS_TICKET"):
                payload["password"] = ""
            elif cred_type == "SSH_PUBLIC_KEY":
                payload["sshPublicKey"] = ""
                payload.pop("password", None)

        elif resource_type.startswith("policy_"):
            # Strip policy-set-specific fields
            payload.pop("policySetId", None)
            payload.pop("policyType", None)
            # Strip operand values that cannot be remapped and are not known in target
            payload = self._strip_unknown_policy_refs(payload)

        elif resource_type == "lss_config":
            # connectorGroups uses the standard remap path
            pass

        if warnings:
            payload["__warnings"] = warnings
        return payload

    def _strip_unknown_policy_refs(self, payload: dict) -> dict:
        """Strip condition operand values that are not remappable and not in target.

        Returns the cleaned payload; also stores any warnings as __warnings.
        """
        warnings: List[str] = payload.pop("__warnings", [])
        conditions = payload.get("conditions")
        if not conditions:
            return payload

        cleaned_conditions = []
        for cond in conditions:
            cleaned_operands = []
            for operand in (cond.get("operands") or []):
                values = operand.get("values")
                if values is None:
                    cleaned_operands.append(operand)
                    continue
                cleaned_values = []
                for v in values:
                    if isinstance(v, str):
                        remapped = self._id_remap.get(v, v)
                        # Check if the (potentially remapped) value is known in target
                        # We do a best-effort check across all known IDs
                        all_known = set()
                        for s in self._target_known_ids.values():
                            all_known.update(s)
                        if remapped in all_known or remapped == v:
                            # Either remapped to a known target ID, or unchanged (may be OK)
                            cleaned_values.append(remapped)
                        else:
                            warnings.append(
                                f"Operand value {v!r} could not be remapped to target tenant"
                            )
                    else:
                        cleaned_values.append(v)
                if cleaned_values:
                    cleaned_operands.append(dict(operand, values=cleaned_values))
                elif not values:
                    cleaned_operands.append(operand)
                # If all values were stripped, drop this operand
            if cleaned_operands:
                cleaned_conditions.append(dict(cond, operands=cleaned_operands))
            elif not (cond.get("operands")):
                cleaned_conditions.append(cond)

        payload["conditions"] = cleaned_conditions
        if warnings:
            payload["__warnings"] = warnings
        return payload
