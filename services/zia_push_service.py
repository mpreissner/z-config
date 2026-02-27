"""ZIA baseline push service.

Reads an exported snapshot JSON (produced by Config Snapshots → Export) and
pushes only the delta to a live ZIA tenant via the API.

Strategy:
  - Fresh import: ZIAImportService runs against the target tenant first so we
    have an accurate picture of its current state.
  - Delta detection via ID-first lookup:
      1. Match baseline entry against target by source ID (zia_id).
         Works for same-tenant pushes and for Zscaler-system resources whose
         IDs are constants across all tenants (e.g. "ADULT_DATING", predefined
         DLP engines).
      2. Fall back to name-based match for cross-tenant pushes of user-defined
         resources where the numeric ID differs between environments.
      Matched resources whose stripped configs are identical → skipped (no API
      call).  Changed → updated directly.  Not found → created.
  - Predefined/system resources are always skipped:
      dlp_engine, dlp_dictionary, network_service  — flagged by predefined:true
      url_category — flagged by type:"ZSCALER_DEFINED" (no predefined field)
  - Multi-pass retry for transient failures; permanent errors (4xx) are not
    retried.  The last actual error is preserved in the "stable" failure message
    so the cause is always visible.
  - ID remapping: source→target IDs registered during classification and after
    each successful create; applied to every outbound payload.

Usage:
    service = ZIAPushService(client, tenant_id=tenant.id)
    records = service.push_baseline(
        baseline_dict,
        import_progress_callback=lambda rtype, done, total: ...,
        progress_callback=lambda pass_num, rtype, record: ...,
    )
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Push order — resources are attempted tier by tier within each pass
# ---------------------------------------------------------------------------

PUSH_ORDER: List[str] = [
    # Tier 1 — no deps
    "rule_label",
    "time_interval",
    "workload_group",
    "bandwidth_class",
    # Tier 2 — objects
    "url_category",
    "ip_destination_group",
    "ip_source_group",
    "network_service",
    "network_svc_group",
    "network_app_group",
    "dlp_engine",
    "dlp_dictionary",
    # Tier 3 — locations
    "location",
    # Tier 4 — rules
    "url_filtering_rule",
    "firewall_rule",
    "firewall_dns_rule",
    "firewall_ips_rule",
    "ssl_inspection_rule",
    "nat_control_rule",
    "forwarding_rule",
    "dlp_web_rule",
    "bandwidth_control_rule",
    "traffic_capture_rule",
    "cloud_app_control_rule",
    # Tier 5 — merge-only list resources
    "allowlist",
    "denylist",
]

# Types that are env-specific or read-only in the SDK — skip entirely
SKIP_TYPES: set = {
    "user",
    "group",
    "department",
    "admin_user",
    "admin_role",
    "location_group",       # read-only in SDK
    "network_app",          # system-defined, read-only
    "cloud_app_policy",     # reference data, not policy
    "cloud_app_ssl_policy",
}

# Types where only user-defined (non-predefined) resources are pushed.
# Zscaler manages predefined entries in these types independently across tenants.
SKIP_IF_PREDEFINED: set = {
    "url_category",
    "dlp_engine",
    "dlp_dictionary",
    "network_service",
}

# Fields stripped from raw_config before comparison and before push
READONLY_FIELDS: set = {
    "id",
    "predefined",
    "lastModifiedBy",
    "lastModifiedTime",
    "createdBy",
    "creationTime",
    "createdAt",
    "updatedAt",
    "modifiedTime",
    "modifiedBy",
    "lastModifiedByUser",
    "isDeleted",
    "dbCategoryIndex",
    "deleted",
}

# ---------------------------------------------------------------------------
# SDK method dispatch tables
# ---------------------------------------------------------------------------

_WRITE_METHODS: Dict[str, Tuple[str, str]] = {
    "rule_label":             ("create_rule_label",             "update_rule_label"),
    "time_interval":          ("create_time_interval",          "update_time_interval"),
    "workload_group":         ("create_workload_group",         "update_workload_group"),
    "bandwidth_class":        ("create_bandwidth_class",        "update_bandwidth_class"),
    "url_category":           ("create_url_category",          "update_url_category"),
    "ip_destination_group":   ("create_ip_destination_group",  "update_ip_destination_group"),
    "ip_source_group":        ("create_ip_source_group",       "update_ip_source_group"),
    "network_service":        ("create_network_service",       "update_network_service"),
    "network_svc_group":      ("create_network_svc_group",     "update_network_svc_group"),
    "network_app_group":      ("create_network_app_group",     "update_network_app_group"),
    "dlp_engine":             ("create_dlp_engine",            "update_dlp_engine"),
    "dlp_dictionary":         ("create_dlp_dictionary",        "update_dlp_dictionary"),
    "location":               ("create_location",              "update_location"),
    "url_filtering_rule":     ("create_url_filtering_rule",    "update_url_filtering_rule"),
    "firewall_rule":          ("create_firewall_rule",         "update_firewall_rule"),
    "firewall_dns_rule":      ("create_firewall_dns_rule",     "update_firewall_dns_rule"),
    "firewall_ips_rule":      ("create_firewall_ips_rule",     "update_firewall_ips_rule"),
    "ssl_inspection_rule":    ("create_ssl_inspection_rule",   "update_ssl_inspection_rule"),
    "nat_control_rule":       ("create_nat_control_rule",      "update_nat_control_rule"),
    "forwarding_rule":        ("create_forwarding_rule",       "update_forwarding_rule"),
    "dlp_web_rule":           ("create_dlp_web_rule",         "update_dlp_web_rule"),
    "bandwidth_control_rule": ("create_bandwidth_control_rule","update_bandwidth_control_rule"),
    "traffic_capture_rule":   ("create_traffic_capture_rule",  "update_traffic_capture_rule"),
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PushRecord:
    resource_type: str
    name: str
    status: str   # "created" | "updated" | "skipped" | "failed:<reason>"

    @property
    def is_created(self) -> bool:
        return self.status == "created"

    @property
    def is_updated(self) -> bool:
        return self.status == "updated"

    @property
    def is_skipped(self) -> bool:
        return self.status == "skipped"

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


# ---------------------------------------------------------------------------
# Dry-run result
# ---------------------------------------------------------------------------

@dataclass
class DryRunResult:
    """Classification output from classify_baseline() — no API writes made."""
    # Skipped records (predefined, identical config, SKIP_TYPES)
    skipped: List[PushRecord]
    # Entries queued to push, keyed by resource_type; each entry dict has
    # __action ("create"|"update"), __target_id, __display_name
    pending: Dict[str, List[dict]]
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

    def type_summary(self) -> Dict[str, Dict[str, int]]:
        """Return {rtype: {"create": N, "update": N, "skip": N}} across all types."""
        out: Dict[str, Dict[str, int]] = {}
        for r in self.skipped:
            out.setdefault(r.resource_type, {"create": 0, "update": 0, "skip": 0})
            out[r.resource_type]["skip"] += 1
        for rtype, entries in self.pending.items():
            out.setdefault(rtype, {"create": 0, "update": 0, "skip": 0})
            for e in entries:
                key = "create" if e.get("__action") == "create" else "update"
                out[rtype][key] += 1
        return out

    def changes_by_action(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """Return (creates, updates) as lists of (resource_type, display_name) tuples."""
        creates, updates = [], []
        for rtype, entries in self.pending.items():
            for e in entries:
                dname = e.get("__display_name") or e.get("name") or "?"
                if e.get("__action") == "create":
                    creates.append((rtype, dname))
                else:
                    updates.append((rtype, dname))
        return creates, updates


# ---------------------------------------------------------------------------
# Push service
# ---------------------------------------------------------------------------

class ZIAPushService:
    def __init__(self, client, tenant_id: int):
        self._client = client
        self._tenant_id = tenant_id
        self._id_remap: Dict[str, str] = {}   # source_id (str) → target_id (str)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_baseline(
        self,
        baseline: dict,
        import_progress_callback: Optional[Callable] = None,
    ) -> DryRunResult:
        """Step 1 + 2 + 3: import target state, load DB, classify each entry.

        No API writes are made.  Returns a DryRunResult the caller can inspect
        before deciding whether to call push_classified().

        Args:
            baseline: Parsed snapshot export JSON dict (must have 'resources' key).
            import_progress_callback: Called during the fresh import phase.
                Signature: callback(resource_type: str, done: int, total: int)

        Returns:
            DryRunResult with .pending (to push) and .skipped (no-op entries).
        """
        # Step 1: Fresh import
        from services.zia_import_service import ZIAImportService
        import_svc = ZIAImportService(self._client, self._tenant_id)
        import_svc.run(progress_callback=import_progress_callback)

        # Step 2: Load freshly imported state, keyed by zia_id
        existing = self._load_existing_from_db()

        # Step 3: Classify
        resources = baseline.get("resources", {})
        ordered_types = [t for t in PUSH_ORDER if t in resources]
        extra_types = [t for t in resources if t not in PUSH_ORDER]
        ordered_types.extend(extra_types)

        pending: Dict[str, List[dict]] = {}
        skipped: List[PushRecord] = []

        for rtype in ordered_types:
            if rtype in SKIP_TYPES:
                continue

            entries = resources.get(rtype) or []

            # Allowlist/denylist bypass delta check — always merge
            if rtype in ("allowlist", "denylist"):
                if entries:
                    pending[rtype] = list(entries)
                continue

            existing_for_type = existing.get(rtype) or {}

            for entry in entries:
                name = entry.get("name") or ""
                source_id = str(entry.get("id", ""))
                raw_config = entry.get("raw_config", {})
                display_name = name or source_id or "?"

                # Skip predefined/system resources for managed types
                if rtype in SKIP_IF_PREDEFINED and _is_predefined(rtype, raw_config):
                    existing_entry = self._find_existing(existing_for_type, source_id, name)
                    if existing_entry and source_id:
                        self._register_remap(source_id, existing_entry["id"])
                    skipped.append(PushRecord(rtype, display_name, "skipped"))
                    continue

                existing_entry = self._find_existing(existing_for_type, source_id, name)

                if existing_entry:
                    target_id = existing_entry["id"]
                    if source_id:
                        self._register_remap(source_id, target_id)

                    if self._configs_match(raw_config, existing_entry["raw_config"]):
                        skipped.append(PushRecord(rtype, display_name, "skipped"))
                        continue

                    queued = dict(entry, __action="update", __target_id=target_id,
                                  __display_name=display_name)
                else:
                    queued = dict(entry, __action="create", __display_name=display_name)

                pending.setdefault(rtype, []).append(queued)

        return DryRunResult(
            skipped=skipped,
            pending=pending,
            id_remap=dict(self._id_remap),
        )

    def push_classified(
        self,
        dry_run: DryRunResult,
        progress_callback: Optional[Callable] = None,
    ) -> List[PushRecord]:
        """Step 4: push the delta from a prior classify_baseline() call.

        Restores the ID remap populated during classification so references
        resolve correctly, then runs multi-pass push until stable.

        Args:
            dry_run: Result from classify_baseline().
            progress_callback: Called after each push attempt.
                Signature: callback(pass_num: int, resource_type: str, record: PushRecord)

        Returns:
            PushRecord list for the pushed entries (created / updated / failed).
            Combine with dry_run.skipped for the full picture.
        """
        # Restore remap state from classification
        self._id_remap = dict(dry_run.id_remap)

        pending = {rtype: list(entries) for rtype, entries in dry_run.pending.items()}
        all_records: List[PushRecord] = []
        pass_num = 0

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

    def push_baseline(
        self,
        baseline: dict,
        progress_callback: Optional[Callable] = None,
        import_progress_callback: Optional[Callable] = None,
    ) -> List[PushRecord]:
        """Convenience wrapper: classify then push, returning all records."""
        dry_run = self.classify_baseline(baseline, import_progress_callback)
        push_records = self.push_classified(dry_run, progress_callback)
        return dry_run.skipped + push_records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_existing_from_db(self) -> Dict[str, Dict[str, dict]]:
        """Load all non-deleted resources for this tenant from the DB.

        Returns:
            {resource_type: {zia_id: {"id": str, "name": str, "raw_config": dict}}}

        Keyed by zia_id (not name) so same-tenant lookups always hit by ID,
        and Zscaler-system resources (whose IDs are constant across tenants)
        also match by ID in cross-tenant scenarios.
        """
        from db.database import get_session
        from db.models import ZIAResource

        result: Dict[str, Dict[str, dict]] = {}
        with get_session() as session:
            rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=self._tenant_id, is_deleted=False)
                .all()
            )
            for row in rows:
                result.setdefault(row.resource_type, {})[row.zia_id] = {
                    "id": row.zia_id,
                    "name": row.name or "",
                    "raw_config": row.raw_config or {},
                }
        return result

    def _find_existing(
        self,
        existing_for_type: Dict[str, dict],
        source_id: str,
        name: str,
    ) -> Optional[dict]:
        """Locate an existing target resource by ID first, then name.

        ID-first handles same-tenant pushes and Zscaler-system resources whose
        IDs are constants across all tenants.  Name fallback handles cross-tenant
        pushes of user-defined resources where numeric IDs differ.
        """
        # Primary: exact ID match
        if source_id and source_id in existing_for_type:
            return existing_for_type[source_id]

        # Fallback: name match (cross-tenant, user-defined resources)
        if name:
            for entry in existing_for_type.values():
                if entry.get("name") == name:
                    return entry

        return None

    def _configs_match(self, baseline_config: dict, existing_config: dict) -> bool:
        """Return True if both configs are identical after stripping read-only fields."""
        return self._strip(baseline_config) == self._strip(existing_config)

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

        for rtype in list(pending.keys()):
            entries = pending[rtype]
            remaining = []

            if rtype in ("allowlist", "denylist"):
                list_records = self._push_list_resource(rtype, entries)
                records.extend(list_records)
                if progress_callback:
                    for r in list_records:
                        progress_callback(pass_num, rtype, r)
                continue

            for entry in entries:
                rec = self._push_one(rtype, entry)
                if progress_callback:
                    progress_callback(pass_num, rtype, rec)

                if rec.is_failed and not rec.is_permanent_failure:
                    # Transient — keep for retry, preserve the error
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

        if resource_type == "cloud_app_control_rule":
            return self._push_cloud_app_rule(name, source_id, raw_config, action, target_id)

        if resource_type not in _WRITE_METHODS:
            return PushRecord(resource_type=resource_type, name=name, status="skipped")

        create_method_name, update_method_name = _WRITE_METHODS[resource_type]
        create_method = getattr(self._client, create_method_name)
        update_method = getattr(self._client, update_method_name)

        config = self._strip(raw_config)
        config = self._apply_id_remap(config)

        if action == "update" and target_id:
            try:
                update_method(target_id, config)
                return PushRecord(resource_type=resource_type, name=name, status="updated")
            except Exception as exc:
                return self._classify_error(resource_type, name, exc)

        # action == "create"
        try:
            result = create_method(config)
            new_target_id = str(result.get("id", ""))
            if source_id and new_target_id:
                self._register_remap(source_id, new_target_id)
            return PushRecord(resource_type=resource_type, name=name, status="created")
        except Exception as exc:
            exc_str = str(exc)
            # Safety net: 409 means it exists but wasn't in our import snapshot
            if "409" in exc_str or "already exists" in exc_str.lower() or "conflict" in exc_str.lower():
                found_id = self._find_by_name_live(resource_type, name)
                if found_id:
                    if source_id:
                        self._register_remap(source_id, found_id)
                    try:
                        update_method(found_id, config)
                        return PushRecord(resource_type=resource_type, name=name, status="updated")
                    except Exception as upd_exc:
                        return self._classify_error(resource_type, name, upd_exc)
                return PushRecord(
                    resource_type=resource_type,
                    name=name,
                    status="failed:permanent:409 — resource exists but name lookup failed",
                )
            return self._classify_error(resource_type, name, exc)

    def _push_cloud_app_rule(
        self,
        name: str,
        source_id: str,
        raw_config: dict,
        action: str,
        target_id: Optional[str],
    ) -> PushRecord:
        """Push a cloud app control rule (rule_type embedded in config)."""
        rule_type = raw_config.get("type") or raw_config.get("ruleType")
        if not rule_type:
            return PushRecord(
                resource_type="cloud_app_control_rule",
                name=name,
                status="failed:permanent:missing rule type in config",
            )

        config = self._strip(raw_config)
        config = self._apply_id_remap(config)

        if action == "update" and target_id:
            try:
                self._client.update_cloud_app_rule(rule_type, target_id, config)
                return PushRecord(resource_type="cloud_app_control_rule", name=name, status="updated")
            except Exception as exc:
                return self._classify_error("cloud_app_control_rule", name, exc)

        try:
            result = self._client.create_cloud_app_rule(rule_type, config)
            new_target_id = str(result.get("id", ""))
            if source_id and new_target_id:
                self._register_remap(source_id, new_target_id)
            return PushRecord(resource_type="cloud_app_control_rule", name=name, status="created")
        except Exception as exc:
            exc_str = str(exc)
            if "409" in exc_str or "already exists" in exc_str.lower() or "conflict" in exc_str.lower():
                try:
                    existing_rules = self._client.list_cloud_app_rules(rule_type)
                    found = next((r for r in existing_rules if r.get("name") == name), None)
                    if found:
                        found_id = str(found.get("id", ""))
                        if source_id and found_id:
                            self._register_remap(source_id, found_id)
                        try:
                            self._client.update_cloud_app_rule(rule_type, found_id, config)
                            return PushRecord(resource_type="cloud_app_control_rule", name=name, status="updated")
                        except Exception as upd_exc:
                            return self._classify_error("cloud_app_control_rule", name, upd_exc)
                except Exception:
                    pass
                return PushRecord(
                    resource_type="cloud_app_control_rule",
                    name=name,
                    status="failed:permanent:409 — rule exists but name lookup failed",
                )
            return self._classify_error("cloud_app_control_rule", name, exc)

    def _push_list_resource(self, resource_type: str, entries: List[dict]) -> List[PushRecord]:
        """Special handler for allowlist / denylist — merge only (add new URLs)."""
        records = []
        for entry in entries:
            raw_config = entry.get("raw_config", {})
            urls = raw_config.get("whitelistUrls") or raw_config.get("blacklistUrls") or []
            if not urls:
                records.append(PushRecord(resource_type=resource_type, name=resource_type, status="skipped"))
                continue
            try:
                if resource_type == "allowlist":
                    self._client.add_to_allowlist(urls)
                else:
                    self._client.add_to_denylist(urls)
                records.append(PushRecord(resource_type=resource_type, name=resource_type, status="updated"))
            except Exception as exc:
                records.append(PushRecord(
                    resource_type=resource_type,
                    name=resource_type,
                    status=f"failed:permanent:{exc}",
                ))
        return records

    def _classify_error(self, resource_type: str, name: str, exc: Exception) -> PushRecord:
        """Classify an exception as permanent (4xx) or transient."""
        exc_str = str(exc)
        permanent = any(code in exc_str for code in ("400", "403", "NOT_SUBSCRIBED", "not licensed", "404"))
        prefix = "failed:permanent:" if permanent else "failed:"
        return PushRecord(
            resource_type=resource_type,
            name=name,
            status=f"{prefix}{exc_str[:150]}",
        )

    def _strip(self, config: dict) -> dict:
        """Return a shallow copy of config with READONLY_FIELDS removed."""
        return {k: v for k, v in config.items() if k not in READONLY_FIELDS}

    def _apply_id_remap(self, config: dict) -> dict:
        """Walk config recursively. For any sub-dict with an 'id' key whose value
        (coerced to str) is in _id_remap, replace it with the mapped target ID."""
        return self._remap_value(copy.deepcopy(config))

    def _remap_value(self, value):
        if isinstance(value, dict):
            if "id" in value:
                id_str = str(value["id"])
                if id_str in self._id_remap:
                    value["id"] = type(value["id"])(self._id_remap[id_str])
            return {k: self._remap_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._remap_value(item) for item in value]
        return value

    def _register_remap(self, source_id, target_id) -> None:
        """Store source→target ID mapping (both coerced to str)."""
        self._id_remap[str(source_id)] = str(target_id)

    def _find_by_name_live(self, resource_type: str, name: str) -> Optional[str]:
        """Safety-net: query the live API for a resource by name.
        Only called when a create unexpectedly 409s (snapshot was stale).
        """
        from services.zia_import_service import RESOURCE_DEFINITIONS
        list_method_name = next(
            (d.list_method for d in RESOURCE_DEFINITIONS if d.resource_type == resource_type),
            None,
        )
        if not list_method_name:
            return None
        try:
            items = getattr(self._client, list_method_name)()
            for item in items:
                if item.get("name") == name:
                    return str(item.get("id", ""))
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _is_predefined(resource_type: str, raw_config: dict) -> bool:
    """Return True if this resource is predefined/system-managed.

    Different resource types use different fields to signal predefined status:
    - dlp_engine, dlp_dictionary, network_service: predefined:true boolean
    - url_category: type:"ZSCALER_DEFINED" (no predefined field)
    """
    if raw_config.get("predefined"):
        return True
    if resource_type == "url_category":
        if raw_config.get("type") == "ZSCALER_DEFINED":
            return True
        if raw_config.get("customCategory") is False:
            return True
    return False
