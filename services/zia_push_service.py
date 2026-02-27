"""ZIA baseline push service.

Reads an exported snapshot JSON (produced by Config Snapshots → Export) and
pushes only the delta to a live ZIA tenant via the API.

Strategy:
  - Fresh import: ZIAImportService runs against the target tenant first, so we
    have an accurate picture of its current state.
  - Delta detection: each baseline entry is compared (after stripping read-only
    fields) against the freshly imported state. Resources whose stripped config
    matches are skipped entirely — no API call is made.
  - Predefined/system resources (dlp_engine, dlp_dictionary, url_category,
    network_service) are always skipped regardless of content. Zscaler manages
    these and they differ across tenants.
  - Resources absent in the target are created; changed resources are updated
    directly (no speculative create → 409 loop).
  - Multi-pass retry for transient failures until the error set stabilises.
  - ID remapping: source→target ID pairs are registered during classification
    (name-matched resources) and after each successful create, then applied to
    every outbound payload so cross-environment references resolve correctly.

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
from typing import Callable, Dict, List, Optional

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
# Zscaler periodically updates its own predefined resources independently;
# pushing them cross-tenant would overwrite Zscaler's managed versions.
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

# Maps resource_type → (create_method_name, update_method_name)
_WRITE_METHODS: Dict[str, tuple] = {
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
    def failure_reason(self) -> str:
        if self.is_failed:
            return self.status[len("failed:"):]
        return ""


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

    def push_baseline(
        self,
        baseline: dict,
        progress_callback: Optional[Callable] = None,
        import_progress_callback: Optional[Callable] = None,
    ) -> List[PushRecord]:
        """Main entry point. Imports target state, diffs, then pushes only deltas.

        Args:
            baseline: Parsed snapshot export JSON dict (must have 'resources' key).
            progress_callback: Called after each push attempt.
                Signature: callback(pass_num: int, resource_type: str, record: PushRecord)
            import_progress_callback: Called during the fresh import phase.
                Signature: callback(resource_type: str, done: int, total: int)

        Returns:
            All PushRecord objects (created + updated + skipped + failed).
        """
        # ------------------------------------------------------------------
        # Step 1: Fresh import — get current state of target tenant into DB
        # ------------------------------------------------------------------
        from services.zia_import_service import ZIAImportService
        import_svc = ZIAImportService(self._client, self._tenant_id)
        import_svc.run(progress_callback=import_progress_callback)

        # ------------------------------------------------------------------
        # Step 2: Load freshly imported state from DB
        # ------------------------------------------------------------------
        existing = self._load_existing_from_db()
        # existing: {resource_type: {name: {"id": str, "raw_config": dict}}}

        # ------------------------------------------------------------------
        # Step 3: Classify each baseline entry — skip / create / update
        # ------------------------------------------------------------------
        resources = baseline.get("resources", {})
        ordered_types = [t for t in PUSH_ORDER if t in resources]
        extra_types = [t for t in resources if t not in PUSH_ORDER]
        ordered_types.extend(extra_types)

        pending: Dict[str, List[dict]] = {}
        all_records: List[PushRecord] = []

        for rtype in ordered_types:
            if rtype in SKIP_TYPES:
                continue

            entries = resources.get(rtype) or []

            # Allowlist/denylist bypass delta check — always merge
            if rtype in ("allowlist", "denylist"):
                if entries:
                    pending[rtype] = list(entries)
                continue

            for entry in entries:
                name = entry.get("name") or ""
                source_id = str(entry.get("id", ""))
                raw_config = entry.get("raw_config", {})

                # Always skip predefined resources for managed types
                if rtype in SKIP_IF_PREDEFINED and raw_config.get("predefined"):
                    # Still register remap so downstream rules can reference them
                    existing_entry = (existing.get(rtype) or {}).get(name)
                    if existing_entry and source_id:
                        self._register_remap(source_id, existing_entry["id"])
                    all_records.append(PushRecord(rtype, name, "skipped"))
                    continue

                existing_entry = (existing.get(rtype) or {}).get(name)

                if existing_entry:
                    target_id = existing_entry["id"]
                    # Pre-populate remap — downstream entries can use this ID
                    if source_id:
                        self._register_remap(source_id, target_id)

                    # Delta check: compare stripped configs
                    if self._configs_match(raw_config, existing_entry["raw_config"]):
                        # Identical — nothing to do
                        all_records.append(PushRecord(rtype, name, "skipped"))
                        continue

                    # Config differs — queue for update
                    queued = dict(entry, __action="update", __target_id=target_id)
                else:
                    # Not found in target — queue for create
                    queued = dict(entry, __action="create")

                pending.setdefault(rtype, []).append(queued)

        # ------------------------------------------------------------------
        # Step 4: Push deltas — multi-pass retry until stable
        # ------------------------------------------------------------------
        pass_num = 0
        while pending:
            pass_num += 1
            prev_count = sum(len(v) for v in pending.values())

            new_pending, pass_records = self._single_pass(pending, pass_num, progress_callback)
            all_records.extend(pass_records)
            pending = new_pending

            if sum(len(v) for v in pending.values()) >= prev_count:
                # No progress — stable failure set
                for rtype, entries in pending.items():
                    for entry in entries:
                        all_records.append(PushRecord(
                            resource_type=rtype,
                            name=entry.get("name", "?"),
                            status="failed:stable — no progress after retry",
                        ))
                break

        return all_records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_existing_from_db(self) -> Dict[str, Dict[str, dict]]:
        """Load all non-deleted resources for this tenant from the DB.

        Returns:
            {resource_type: {name: {"id": str, "raw_config": dict}}}
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
                if not row.name:
                    continue
                result.setdefault(row.resource_type, {})[row.name] = {
                    "id": row.zia_id,
                    "raw_config": row.raw_config or {},
                }
        return result

    def _configs_match(self, baseline_config: dict, existing_config: dict) -> bool:
        """Return True if both configs are identical after stripping read-only fields."""
        return self._strip(baseline_config) == self._strip(existing_config)

    def _single_pass(
        self,
        pending: Dict[str, List[dict]],
        pass_num: int,
        progress_callback=None,
    ) -> tuple[Dict[str, List[dict]], List[PushRecord]]:
        """One iteration over pending resources.

        Returns (new_pending, records_this_pass).
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

                if rec.is_failed and "stable" not in rec.failure_reason:
                    # Transient failure — keep for retry
                    remaining.append(entry)
                else:
                    records.append(rec)

            if remaining:
                new_pending[rtype] = remaining

        return new_pending, records

    def _push_one(self, resource_type: str, entry: dict) -> PushRecord:
        """Push a single pre-classified resource entry."""
        name = entry.get("name", "?")
        source_id = str(entry.get("id", ""))
        raw_config = entry.get("raw_config", {})
        action = entry.get("__action", "create")
        target_id = entry.get("__target_id")

        if resource_type == "cloud_app_control_rule":
            return self._push_cloud_app_rule(name, source_id, raw_config, action, target_id)

        if resource_type not in _WRITE_METHODS:
            return PushRecord(resource_type=resource_type, name=name, status="skipped")

        _, update_method_name = _WRITE_METHODS[resource_type]
        create_method_name, _ = _WRITE_METHODS[resource_type]
        create_method = getattr(self._client, create_method_name)
        update_method = getattr(self._client, update_method_name)

        config = self._strip(raw_config)
        config = self._apply_id_remap(config)

        if action == "update" and target_id:
            try:
                update_method(target_id, config)
                return PushRecord(resource_type=resource_type, name=name, status="updated")
            except Exception as exc:
                exc_str = str(exc)
                permanent = any(c in exc_str for c in ("400", "403", "NOT_SUBSCRIBED", "not licensed"))
                return PushRecord(
                    resource_type=resource_type,
                    name=name,
                    status=f"failed:{exc_str[:120]}",
                ) if permanent else PushRecord(
                    resource_type=resource_type,
                    name=name,
                    status=f"failed:{exc_str[:120]}",
                )

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
                found_id = self._find_by_name(resource_type, name)
                if found_id:
                    if source_id:
                        self._register_remap(source_id, found_id)
                    try:
                        update_method(found_id, config)
                        return PushRecord(resource_type=resource_type, name=name, status="updated")
                    except Exception as upd_exc:
                        return PushRecord(
                            resource_type=resource_type,
                            name=name,
                            status=f"failed:{upd_exc}",
                        )
                return PushRecord(
                    resource_type=resource_type,
                    name=name,
                    status="failed:409 — could not locate existing resource by name",
                )
            return PushRecord(
                resource_type=resource_type,
                name=name,
                status=f"failed:{exc_str[:120]}",
            )

    def _push_cloud_app_rule(
        self,
        name: str,
        source_id: str,
        raw_config: dict,
        action: str,
        target_id: Optional[str],
    ) -> PushRecord:
        """Push a cloud app control rule (requires rule_type embedded in config)."""
        rule_type = raw_config.get("type") or raw_config.get("ruleType")
        if not rule_type:
            return PushRecord(
                resource_type="cloud_app_control_rule",
                name=name,
                status="failed:missing rule type in config",
            )

        config = self._strip(raw_config)
        config = self._apply_id_remap(config)

        if action == "update" and target_id:
            try:
                self._client.update_cloud_app_rule(rule_type, target_id, config)
                return PushRecord(resource_type="cloud_app_control_rule", name=name, status="updated")
            except Exception as exc:
                return PushRecord(
                    resource_type="cloud_app_control_rule",
                    name=name,
                    status=f"failed:{exc}",
                )

        # create
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
                            return PushRecord(
                                resource_type="cloud_app_control_rule",
                                name=name,
                                status=f"failed:{upd_exc}",
                            )
                except Exception:
                    pass
                return PushRecord(
                    resource_type="cloud_app_control_rule",
                    name=name,
                    status="failed:409 — could not locate existing rule by name",
                )
            return PushRecord(
                resource_type="cloud_app_control_rule",
                name=name,
                status=f"failed:{exc_str[:120]}",
            )

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
                    status=f"failed:{exc}",
                ))
        return records

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

    def _find_by_name(self, resource_type: str, name: str) -> Optional[str]:
        """Safety-net lookup: return target ID of existing resource matching name, or None.
        Only called when a create unexpectedly 409s (import snapshot was stale/incomplete).
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
