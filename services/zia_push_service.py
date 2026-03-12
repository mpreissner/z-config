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
  - Zscaler-managed resources (predefined:true, defaultRule:true, type:PREDEFINED,
    url_category ZSCALER_DEFINED, etc.) are handled universally regardless of type:
      - ID-remapped so cross-tenant references resolve correctly.
      - If access_control is READ_WRITE and config differs → UPDATE only (never CREATE).
      - Otherwise (read-only or config identical) → remapped and skipped.
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
import json
import re
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
    "location",             # tenant-specific; IPs must be provisioned by Zscaler per-org
    "network_app",          # system-defined, read-only
    "cloud_app_policy",     # reference data, not policy
    "cloud_app_ssl_policy",
}

# Specific resource names that are system-managed and must never be pushed,
# even when the 'predefined' flag is absent from the API response.
SKIP_NAMED: dict = {
    "network_service":    {"ZSCALER_PROXY_NW_SERVICES"},
    # "CIPA Compliance Rule" is a Zscaler-reserved name; the API rejects any
    # attempt to create or rename a custom rule with this name.
    "url_filtering_rule": {"CIPA Compliance Rule"},
}

# Fields stripped from raw_config before comparison and before push.
# NOTE: "rank" is intentionally NOT here — ZIA requires rank in POST/PUT for
# all rule types (url_filtering_rule, firewall_rule, etc.).
# NOTE: "configVersion" is intentionally NOT here — it is injected from the
# target's existing record at push time (see __target_config_version).
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
    "defaultRule",
    "accessControl",
    "managedBy",
}

# ---------------------------------------------------------------------------
# SDK method dispatch tables
# ---------------------------------------------------------------------------

# Resource types that can be deleted during baseline enforcement.
# Only types listed here will ever have DELETE actions generated.
# cloud_app_control_rule is handled specially (needs rule_type from raw_config).
_DELETE_METHODS: Dict[str, str] = {
    "rule_label":             "delete_rule_label",
    "time_interval":          "delete_time_interval",
    "bandwidth_class":        "delete_bandwidth_class",
    "url_category":           "delete_url_category",
    "ip_destination_group":   "delete_ip_destination_group",
    "ip_source_group":        "delete_ip_source_group",
    "network_service":        "delete_network_service",
    "network_svc_group":      "delete_network_svc_group",
    "network_app_group":      "delete_network_app_group",
    "url_filtering_rule":     "delete_url_filtering_rule",
    "firewall_rule":          "delete_firewall_rule",
    "firewall_dns_rule":      "delete_firewall_dns_rule",
    "firewall_ips_rule":      "delete_firewall_ips_rule",
    "ssl_inspection_rule":    "delete_ssl_inspection_rule",
    "nat_control_rule":       "delete_nat_control_rule",
    "forwarding_rule":        "delete_forwarding_rule",
    "dlp_web_rule":           "delete_dlp_web_rule",
    "bandwidth_control_rule": "delete_bandwidth_control_rule",
    "traffic_capture_rule":   "delete_traffic_capture_rule",
    "cloud_app_control_rule": None,   # handled via delete_cloud_app_rule(rule_type, id)
    "workload_group":         "delete_workload_group",
    "location":               "delete_location",
}

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
    status: str   # "created" | "updated" | "deleted" | "skipped" | "failed:<reason>"

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
    # Resources present in the tenant but absent from the baseline — to be deleted
    to_delete: List[PushRecord]
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

            # Allowlist/denylist: only queue if there are URLs to add
            if rtype in ("allowlist", "denylist"):
                new_urls = []
                for entry in entries:
                    raw = entry.get("raw_config", {})
                    # SDK may return snake_case or camelCase keys
                    new_urls.extend(
                        raw.get("whitelistUrls") or raw.get("whitelist_urls") or
                        raw.get("blacklistUrls") or raw.get("blacklist_urls") or []
                    )
                if new_urls:
                    pending[rtype] = list(entries)
                else:
                    skipped.append(PushRecord(rtype, rtype, "skipped"))
                continue

            existing_for_type = existing.get(rtype) or {}

            for entry in entries:
                name = entry.get("name") or ""
                source_id = str(entry.get("id", ""))
                raw_config = entry.get("raw_config", {})
                display_name = name or source_id or "?"

                # Universal Zscaler-managed detection (predefined, defaultRule, PREDEFINED type, etc.)
                if _is_zscaler_managed(rtype, raw_config):
                    existing_entry = self._find_existing(existing_for_type, source_id, name)
                    if existing_entry:
                        target_id = existing_entry["id"]
                        if source_id:
                            self._register_remap(source_id, target_id)
                        # Writable managed resources (access_control:READ_WRITE) that differ
                        # from the baseline are updated. Never created — they always exist.
                        # Exception: predefined dlp_dictionary entries appear READ_WRITE but
                        # the API refuses pattern edits — treat them as read-only.
                        if (_is_writable(raw_config)
                                and not (rtype == "dlp_dictionary" and raw_config.get("predefined"))
                                and not self._configs_match(raw_config, existing_entry["raw_config"])):
                            pending.setdefault(rtype, []).append(
                                dict(entry, __action="update", __target_id=target_id,
                                     __display_name=display_name,
                                     __target_config_version=existing_entry["raw_config"].get("configVersion"))
                            )
                            continue
                    skipped.append(PushRecord(rtype, display_name, "skipped"))
                    continue

                # User-defined resource — normal create/update logic
                existing_entry = self._find_existing(existing_for_type, source_id, name)

                if existing_entry:
                    target_id = existing_entry["id"]
                    if source_id:
                        self._register_remap(source_id, target_id)

                    if self._configs_match(raw_config, existing_entry["raw_config"]):
                        skipped.append(PushRecord(rtype, display_name, "skipped"))
                        continue

                    queued = dict(entry, __action="update", __target_id=target_id,
                                  __display_name=display_name,
                                  __target_config_version=existing_entry["raw_config"].get("configVersion"))
                else:
                    queued = dict(entry, __action="create", __display_name=display_name)

                pending.setdefault(rtype, []).append(queued)

        # Step 4: Identify extraneous resources — present in tenant but absent from baseline.
        # Only generate deletes for resource types that appear in the baseline file;
        # types not covered by the snapshot are left untouched.
        to_delete: List[PushRecord] = []
        for rtype in ordered_types:
            if rtype in SKIP_TYPES or rtype not in _DELETE_METHODS:
                continue
            if rtype in ("allowlist", "denylist"):
                continue

            baseline_entries = resources.get(rtype) or []
            baseline_ids = {str(e.get("id", "")) for e in baseline_entries if e.get("id")}
            baseline_names = {e.get("name", "") for e in baseline_entries if e.get("name")}

            for zia_id, entry in (existing.get(rtype) or {}).items():
                name = entry.get("name", "")
                raw = entry.get("raw_config", {})

                # Skip if this entry was matched during classification
                if zia_id in baseline_ids or name in baseline_names:
                    continue
                # Skip predefined/system resources
                if _is_zscaler_managed(rtype, raw):
                    continue
                if name in SKIP_NAMED.get(rtype, set()):
                    continue

                to_delete.append(PushRecord(
                    resource_type=rtype,
                    name=name or zia_id,
                    status=f"pending_delete:{zia_id}",
                ))

        return DryRunResult(
            skipped=skipped,
            pending=pending,
            to_delete=to_delete,
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

    def execute_deletes(
        self,
        to_delete: List[PushRecord],
        progress_callback: Optional[Callable] = None,
    ) -> List[PushRecord]:
        """Execute a confirmed delete list. Called from the menu after explicit user approval.

        Deletes are intentionally separated from push_classified so the caller
        can present the proposed deletes and require confirmation before any
        destructive action is taken.
        """
        records: List[PushRecord] = []
        for rec in to_delete:
            zia_id = rec.status.partition(":")[2]
            delete_rec = self._delete_one(rec.resource_type, rec.name, zia_id)
            if progress_callback:
                progress_callback(0, rec.resource_type, delete_rec)
            records.append(delete_rec)
        return records

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
        """Return True if both configs are semantically identical after stripping
        read-only fields and normalizing list ordering (ZIA returns arrays like
        port ranges in non-deterministic order between API calls)."""
        return self._normalize(self._strip(baseline_config)) == self._normalize(self._strip(existing_config))

    def _normalize(self, value):
        """Recursively normalize a config value for stable comparison.

        Lists are sorted by their canonical JSON representation so that
        semantically equivalent configs with differently-ordered arrays
        (e.g. port range lists) compare as equal.
        """
        if isinstance(value, dict):
            return {k: self._normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            normalized = [self._normalize(item) for item in value]
            try:
                return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True, default=str))
            except TypeError:
                return normalized
        return value

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
            # Inject the target's configVersion for optimistic-locking checks
            # (e.g. bandwidth_control_rule requires it; harmless for others).
            target_cv = entry.get("__target_config_version")
            if target_cv is not None:
                config["configVersion"] = target_cv
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
            # Safety net: resource already exists (ZIA may return 409 or 400/DUPLICATE_ITEM)
            if ("409" in exc_str or "DUPLICATE_ITEM" in exc_str
                    or "already exists" in exc_str.lower() or "conflict" in exc_str.lower()):
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
                    status="failed:permanent:duplicate — resource exists but name lookup failed",
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
            if ("409" in exc_str or "DUPLICATE_ITEM" in exc_str
                    or "already exists" in exc_str.lower() or "conflict" in exc_str.lower()):
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
                    status="failed:permanent:duplicate — rule exists but name lookup failed",
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

    def _delete_one(self, resource_type: str, name: str, zia_id: str) -> PushRecord:
        """Delete a single resource from the live tenant."""
        method_name = _DELETE_METHODS.get(resource_type)

        try:
            if resource_type == "cloud_app_control_rule":
                # Need rule_type — look it up from DB raw_config
                from db.database import get_session
                from db.models import ZIAResource
                with get_session() as session:
                    rec = (
                        session.query(ZIAResource)
                        .filter_by(tenant_id=self._tenant_id,
                                   resource_type=resource_type,
                                   zia_id=zia_id)
                        .first()
                    )
                    rule_type = (rec.raw_config or {}).get("type") if rec else None
                if not rule_type:
                    return PushRecord(resource_type, name,
                                      "failed:permanent:cloud_app_rule missing type in DB")
                self._client.delete_cloud_app_rule(rule_type, zia_id)
            elif method_name:
                getattr(self._client, method_name)(zia_id)
            else:
                return PushRecord(resource_type, name, "skipped")
            return PushRecord(resource_type, name, "deleted")
        except Exception as exc:
            return self._classify_error(resource_type, name, exc)

    def _classify_error(self, resource_type: str, name: str, exc: Exception) -> PushRecord:
        """Classify an exception as permanent (4xx) or transient.

        Uses the JSON "status" field ZIA returns (e.g. ``"status": 400``) rather
        than a bare substring search, which would false-positive on resource IDs
        that happen to contain "400", "403", or "404" (e.g. /rules/326403).
        Non-HTTP errors (SSLError, connection reset) are always transient.
        """
        exc_str = str(exc)
        # ZIA error payloads contain: {"status": 400, ...}
        permanent = bool(re.search(r'"status"\s*:\s*(400|403|404)', exc_str)) or \
                    any(s in exc_str for s in ("NOT_SUBSCRIBED", "not licensed"))
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

def _is_zscaler_managed(resource_type: str, raw_config: dict) -> bool:
    """Return True if this resource is owned/managed by Zscaler across all tenants.

    Managed resources exist in every fresh tenant with the same name but potentially
    different numeric IDs. They must never be created — only remapped and optionally
    updated (if access_control is READ_WRITE and config differs).

    Signals checked (applied universally, not gated by resource type):
    - predefined:true  — dlp_engine, dlp_dictionary, network_service, bandwidth_class, etc.
    - defaultRule:true — firewall/forwarding/other rule types with a "default" Zscaler rule
    - type:"PREDEFINED" — network_service and bandwidth_class predefined entries
    - url_category-specific: type:"ZSCALER_DEFINED", customCategory==False, non-numeric id
    - SKIP_NAMED: hardcoded names that lack the predefined flag but are still system-owned
    """
    if raw_config.get("predefined"):
        return True
    if raw_config.get("defaultRule"):
        return True
    name = raw_config.get("name", "")
    if name and name in SKIP_NAMED.get(resource_type, set()):
        return True
    # network_service and bandwidth_class predefined entries carry type:"PREDEFINED"
    # rather than a predefined:true boolean field.
    if raw_config.get("type") == "PREDEFINED":
        return True
    if resource_type == "url_category":
        if raw_config.get("type") == "ZSCALER_DEFINED":
            return True
        # customCategory == False (not 'is False') handles SDK serializing as 0/False
        if raw_config.get("customCategory") == False:  # noqa: E712
            return True
        # Zscaler-defined categories have string IDs (e.g. "ADULT_SEX_EDUCATION");
        # user-created custom categories always have numeric IDs.
        cat_id = str(raw_config.get("id", ""))
        if cat_id and not cat_id.isdigit():
            return True
    return False


def _is_writable(raw_config: dict) -> bool:
    """Return True if this Zscaler-managed resource allows modifications.

    Resources with accessControl:"READ_WRITE" can be updated to match the baseline
    even though they are predefined/system-managed. Read-only managed resources
    are remapped but never modified.
    """
    return raw_config.get("accessControl") == "READ_WRITE"
