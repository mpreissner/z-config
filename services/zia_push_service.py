"""ZIA baseline push service — wipe-first redesign.

Baseline push strategy (wipe-first):
  1. IMPORT      — fresh import of target tenant state into DB
  2. EVALUATE    — classify every DB resource as user-created or Zscaler-managed
  3. WIPE        — delete all user-created resources in reverse-dependency order
  4. PUSH        — two passes:
                   a) Update Zscaler-managed READ_WRITE resources to match baseline
                   b) Create all user-defined baseline resources in dependency order
  5. ACTIVATE    — prompt to activate ZIA changes

The wipe-first approach eliminates rank conflicts, stale configVersions, and
ID mismatches by starting from a clean slate before pushing the baseline.

Legacy delta-mode (no wipe) is preserved for incremental pushes:

    service = ZIAPushService(client, tenant_id=tenant.id)
    dry_run = service.classify_baseline(baseline_dict)
    push_records = service.push_classified(dry_run)

Wipe-first mode:

    service = ZIAPushService(client, tenant_id=tenant.id)
    wipe_result = service.classify_wipe()
    wipe_records = service.execute_wipe(wipe_result, progress_callback=...)
    dry_run = service.classify_baseline(baseline_dict)
    push_records = service.push_classified(dry_run, progress_callback=...)

ID remapping: source→target IDs registered during classification and after
each successful create; applied to every outbound payload including flat
string url_category arrays.
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
    # Tier 0 — no deps
    "rule_label",
    "time_interval",
    "workload_group",
    "dlp_engine",
    "dlp_dictionary",
    "tenancy_restriction_profile",
    # Tier 1 — object building blocks
    "ip_source_group",
    "ip_destination_group",
    "network_service",
    "url_category",
    "bandwidth_class",
    # Tier 2 — aggregate objects
    "network_svc_group",
    "network_app_group",
    # Tier 2.5 — tenant-wide settings (before rules: provisions One-Click rules,
    # enables admin rank, and sets other policy toggles)
    "url_filter_cloud_app_settings",
    "advanced_settings",
    "browser_control_settings",
    # Tier 3 — rules (dependency order)
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
    "sandbox_rule",
    # Tier 4 — merge-only list resources
    "allowlist",
    "denylist",
]

# Wipe order — reverse of push (dependencies deleted before their dependents)
WIPE_ORDER: List[str] = [
    # Tier 4 first — clear URL lists (don't delete the objects themselves)
    "allowlist",
    "denylist",
    # Tier 3 — rules in reverse
    "sandbox_rule",
    "cloud_app_control_rule",
    "traffic_capture_rule",
    "bandwidth_control_rule",
    "dlp_web_rule",
    "forwarding_rule",
    "nat_control_rule",
    "ssl_inspection_rule",
    "firewall_ips_rule",
    "firewall_dns_rule",
    "firewall_rule",
    "url_filtering_rule",
    # Tier 2 — aggregate objects
    "network_app_group",
    "network_svc_group",
    # Tier 1 — object building blocks
    "bandwidth_class",
    "url_category",
    "network_service",
    "ip_destination_group",
    "ip_source_group",
    # Tier 0 — no deps
    "dlp_dictionary",
    "dlp_engine",
    "workload_group",
    "time_interval",
    "rule_label",
]

# Types that are env-specific or read-only in the SDK — skip entirely
SKIP_TYPES: set = {
    "user",
    "group",
    "department",
    "admin_user",
    "admin_role",
    "location_group",       # read-only in SDK
    "location",             # tenant-specific; public IPs and VPN credentials cannot be copied cross-tenant
    "location_lite",        # predefined/system locations (Road Warrior etc.) — imported for ID remapping only
    "device_group",         # predefined OS/platform groups (Windows, iOS, etc.) — imported for ID remapping only
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
    # Zscaler ships these DNS rules in every tenant but doesn't flag them as
    # predefined=True.  They can be managed/deleted by the user, but must never
    # be wiped during wipe-floor since they're Zscaler-provided defaults.
    "firewall_dns_rule":  {"Risky DNS categories", "Risky DNS tunnels"},
    # The SDK SandboxRules model omits default_rule, so _is_zscaler_managed can't
    # detect it via the boolean field.  Guard by name as a belt-and-suspenders fallback.
    "sandbox_rule":       {"Default BA Rule"},
    # "Smart Isolation One Click Rule" is auto-provisioned by the enableSmartIsolation
    # toggle in browser_control_settings.  The API does return predefined=True for it,
    # but guard by name as well so the rule is never accidentally wiped or re-created
    # from a baseline captured before predefined was present in raw_config.
    "ssl_inspection_rule": {"Smart Isolation One Click Rule"},
}

# Rule types that can be provisioned by one-click settings toggles.
# After pushing settings singletons, these types are re-fetched from the target
# so that newly provisioned rules can be matched and ID-remapped.
# Governing settings singletons:
#   url_filter_cloud_app_settings — O365/UCaaS/CIPA toggles
#   browser_control_settings      — Smart Isolation toggle (ssl_inspection_rule)
_ONE_CLICK_RULE_TYPES: set = {
    "url_filtering_rule",     # CIPA Compliance Rule  (enableCIPACompliance)
    "ssl_inspection_rule",    # O365 One Click, UCaaS One Click, Smart Isolation One Click Rule
    "firewall_rule",          # O365 One Click, UCaaS One Click, Block malicious IPs
    "firewall_dns_rule",      # O365 One Click, UCaaS One Click, DNS risk rules
}

# Fields always stripped from raw_config before comparison and before push.
# All keys are snake_case — the SDK returns snake_case from as_dict().
# NOTE: "rank" is intentionally NOT here — ZIA requires rank in POST/PUT for
# all rule types (url_filtering_rule, firewall_rule, etc.).
READONLY_FIELDS: set = {
    "id",
    "predefined",
    "last_modified_by",
    "last_modified_time",
    "created_by",
    "creation_time",
    "created_at",
    "updated_at",
    "modified_time",
    "modified_by",
    "last_modified_by_user",
    "is_deleted",
    "db_category_index",
    "deleted",
    "default_rule",
    "access_control",
    "managed_by",
}

# ---------------------------------------------------------------------------
# SDK method dispatch tables
# ---------------------------------------------------------------------------

# Resource types that can be deleted during wipe or baseline enforcement.
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
    "sandbox_rule":           "delete_sandbox_rule",
    "workload_group":                "delete_workload_group",
    "dlp_engine":                    "delete_dlp_engine",
    "dlp_dictionary":                "delete_dlp_dictionary",
    "tenancy_restriction_profile":   "delete_tenancy_restriction_profile",
    "location":                      "delete_location",
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
    "tenancy_restriction_profile":   ("create_tenancy_restriction_profile",
                                      "update_tenancy_restriction_profile"),
    "sandbox_rule":                  ("create_sandbox_rule",   "update_sandbox_rule"),
    # Singletons — no create path; use update method for both entries
    "url_filter_cloud_app_settings": ("update_url_filter_cloud_app_settings",
                                      "update_url_filter_cloud_app_settings"),
    "advanced_settings":             ("update_advanced_settings",
                                      "update_advanced_settings"),
    "browser_control_settings":      ("update_browser_control_settings",
                                      "update_browser_control_settings"),
}

# GET methods for live configVersion fetch before UPDATE.
# Only types with single-record GET endpoints are listed.
_GET_METHODS: Dict[str, str] = {
    "url_category":         "get_url_category",
    "url_filtering_rule":   "get_url_filtering_rule",
    "firewall_rule":        "get_firewall_rule",
    "firewall_dns_rule":    "get_firewall_dns_rule",
    "ssl_inspection_rule":  "get_ssl_inspection_rule",
    "dlp_engine":           "get_dlp_engine",
    "dlp_dictionary":       "get_dlp_dictionary",
    # cloud_app_control_rule requires rule_type — handled separately
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


@dataclass
class WipeRecord:
    resource_type: str
    name: str
    zia_id: str
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
    to_delete: List[WipeRecord]   # user-created resources to delete

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
    # Skipped records (predefined, identical config, SKIP_TYPES)
    skipped: List[PushRecord]
    # Entries queued to push, keyed by resource_type; each entry dict has
    # __action ("create"|"update"), __target_id, __display_name, __managed
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
        self._id_remap: Dict[str, str] = {}          # source_id (str) → target_id (str)
        self._target_known_ids: Dict[str, set] = {}  # resource_type → set of zia_ids in target
        self._usable_dlp_engine_ids: set = set()     # target DLP engine IDs that can be used in rules
        self._cbi_profile_map: Dict[str, dict] = {}  # profile name (lower) → {id, name, url, default}

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
        from services.zia_import_service import ZIAImportService
        import_svc = ZIAImportService(self._client, self._tenant_id)
        import_svc.run(progress_callback=import_progress_callback)

        existing = self._load_existing_from_db()
        to_delete: List[WipeRecord] = []

        for rtype in WIPE_ORDER:
            if rtype in SKIP_TYPES:
                continue
            if rtype not in _DELETE_METHODS:
                continue
            if rtype in ("allowlist", "denylist"):
                continue  # cleared differently — no individual resource deletion

            existing_for_type = existing.get(rtype) or {}
            for zia_id, entry in existing_for_type.items():
                name = entry.get("name", "")
                raw = entry.get("raw_config", {})
                if _is_zscaler_managed(rtype, raw):
                    continue
                if name in SKIP_NAMED.get(rtype, set()):
                    continue
                to_delete.append(WipeRecord(
                    resource_type=rtype,
                    name=name or zia_id,
                    zia_id=zia_id,
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

        Entries from Zscaler-managed READ_WRITE resources are tagged __managed=True
        so push_classified() can process them in the correct pass order.

        Args:
            baseline: Parsed snapshot export JSON dict (must have 'resources' key).
            import_progress_callback: Called during the fresh import phase.
                Signature: callback(resource_type: str, done: int, total: int)
        """
        from services.zia_import_service import ZIAImportService
        import_svc = ZIAImportService(self._client, self._tenant_id)
        import_svc.run(progress_callback=import_progress_callback)

        existing = self._load_existing_from_db()
        # Build a lookup of all IDs currently in the target so cross-tenant ref
        # filtering can strip IDs that don't exist in this environment.
        self._target_known_ids = {
            rtype: set(type_data.keys())
            for rtype, type_data in existing.items()
        }
        # DLP engine IDs present in the target tenant that can be referenced in rules.
        # All engine IDs are included — both named engines (custom_dlp_engine=True,
        # IDs 1–24) and predefined engines (custom_dlp_engine=False, IDs 60–64).
        # Predefined engines (e.g. id=61 "PCI") are used in default Zscaler rules and
        # are fully accepted by the API in user-created rule payloads.
        self._usable_dlp_engine_ids = set((existing.get("dlp_engine") or {}).keys())

        # Device group name → target ID map.
        # Device group IDs differ across tenants; remap by name so rules scoped to
        # predefined OS groups (Windows, iOS, etc.) carry over on push.
        # Source device_group entries come from the baseline; target from the DB.
        target_dg_name_map = {
            entry["name"].lower(): entry["id"]
            for entry in (existing.get("device_group") or {}).values()
            if entry.get("name")
        }
        for src_entry in (baseline.get("resources", {}).get("device_group") or []):
            src_id = str(src_entry.get("id", ""))
            src_name = (src_entry.get("name") or "").lower()
            if src_id and src_name and src_name in target_dg_name_map:
                self._register_remap(src_id, target_dg_name_map[src_name])

        # CBI profile map: profile name (lowercase) → profile dict.
        # Used to remap cbi_profile UUIDs on ISOLATE url_filtering_rules across tenants.
        try:
            profiles = self._client.list_browser_isolation_profiles()
            self._cbi_profile_map = {
                p.get("name", "").lower(): p for p in profiles if p.get("name")
            }
        except Exception:
            self._cbi_profile_map = {}

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

            if rtype in ("allowlist", "denylist"):
                new_urls = []
                for entry in entries:
                    raw = entry.get("raw_config", {})
                    new_urls.extend(
                        raw.get("whitelist_urls") or raw.get("whitelistUrls") or
                        raw.get("blacklist_urls") or raw.get("blacklistUrls") or []
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

                if _is_zscaler_managed(rtype, raw_config):
                    # Predefined cloud app control rules are provisioned by Zscaler via
                    # url_filter_cloud_app_settings (One-Click rules etc.).  Multiple rules
                    # share the same name across different types, so name-only lookup is
                    # ambiguous.  Skip them — the settings push handles their existence.
                    if rtype == "cloud_app_control_rule" and raw_config.get("predefined"):
                        skipped.append(PushRecord(rtype, display_name, "skipped:predefined"))
                        continue

                    existing_entry = self._find_existing(existing_for_type, source_id, name)
                    if existing_entry:
                        target_id = existing_entry["id"]
                        if source_id:
                            self._register_remap(source_id, target_id)
                        # Predefined DLP dictionaries (custom:false): the API rejects
                        # pattern/phrase edits but allows confidence_threshold updates
                        # via GET-then-PUT.  Queue an update when the threshold differs.
                        if (rtype == "dlp_dictionary"
                                and raw_config.get("custom") == False  # noqa: E712
                                and raw_config.get("confidence_threshold") is not None):
                            tgt_conf = existing_entry["raw_config"].get("confidence_threshold")
                            bl_conf = raw_config["confidence_threshold"]
                            if bl_conf != tgt_conf:
                                pending.setdefault(rtype, []).append(
                                    dict(entry,
                                         __action="update",
                                         __target_id=target_id,
                                         __display_name=display_name,
                                         __managed=True,
                                         __confidence_threshold=bl_conf)
                                )
                                continue

                        # READ_WRITE managed resources that differ from baseline are updated.
                        # Never created — they always exist in every tenant.
                        # For predefined rules in ordered types, positioning is
                        # handled by the reverse-insert mechanism — exclude order
                        # from comparison so order-only diffs don't trigger updates.
                        _ORDERED_MANAGED_TYPES = {
                            "ssl_inspection_rule", "url_filtering_rule", "forwarding_rule",
                            "firewall_rule", "firewall_dns_rule", "firewall_ips_rule",
                            "nat_control_rule", "sandbox_rule",
                        }
                        if raw_config.get("predefined") and rtype in _ORDERED_MANAGED_TYPES:
                            _bl = {k: v for k, v in raw_config.items() if k != "order"}
                            _ex = {k: v for k, v in existing_entry["raw_config"].items() if k != "order"}
                        else:
                            _bl, _ex = raw_config, existing_entry["raw_config"]
                        if (_is_writable(raw_config)
                                and not self._configs_match(rtype, _bl, _ex)):
                            pending.setdefault(rtype, []).append(
                                dict(entry,
                                     __action="update",
                                     __target_id=target_id,
                                     __display_name=display_name,
                                     __managed=True)
                            )
                            continue
                        # Found in target and configs match (or read-only): nothing to push.
                        skipped.append(PushRecord(rtype, display_name, "skipped"))
                        continue
                    # Rule not found in target. If it's a one-click governed rule that is
                    # ENABLED in the source, it may not exist yet because the toggle was
                    # never enabled on the target.  Tag it for re-matching after the
                    # settings push provisions it.  Disabled/absent rules are left as
                    # skipped — toggle=OFF / rule-absent is equivalent behaviour to
                    # toggle=OFF / rule-disabled; the settings push handles both.
                    if (rtype in _ONE_CLICK_RULE_TYPES
                            and raw_config.get("state") == "ENABLED"):
                        pending.setdefault(rtype, []).append(
                            dict(entry,
                                 __action="update",
                                 __display_name=display_name,
                                 __managed=True,
                                 __one_click_pending=True)
                        )
                        continue
                    # Settings singletons always exist in every tenant — queue an
                    # update even when the DB has no entry (e.g. first push before
                    # import, or stale DB).  Use the hardcoded singleton ID "1".
                    _SETTINGS_SINGLETONS = {
                        "url_filter_cloud_app_settings",
                        "advanced_settings",
                        "browser_control_settings",
                    }
                    if rtype in _SETTINGS_SINGLETONS and _is_writable(raw_config):
                        pending.setdefault(rtype, []).append(
                            dict(entry,
                                 __action="update",
                                 __target_id="1",
                                 __display_name=display_name,
                                 __managed=True)
                        )
                        continue
                    skipped.append(PushRecord(rtype, display_name, "skipped"))
                    continue

                # SIPA/ZPA forwarding rules reference ZPA app segments and gateways
                # that are provisioned per-tenant.  They cannot be copied cross-tenant.
                if rtype == "forwarding_rule" and raw_config.get("zpa_gateway", {}).get("id"):
                    rec = PushRecord(rtype, display_name, "skipped:zpa-forwarding")
                    rec.warnings.append(
                        "SIPA/ZPA forwarding rule skipped — references tenant-specific "
                        "ZPA app segments/gateway; recreate manually in target tenant"
                    )
                    skipped.append(rec)
                    continue

                # User-created resources: match by name only (no ID fallback).
                # IDs are tenant-specific and can collide with system resource IDs
                # in the target tenant (e.g. user DLP engine id=61 in source vs.
                # unnamed system engine id=61 in target).
                existing_entry = self._find_existing_user(existing_for_type, name)

                # Custom URL category slots (CUSTOM_01, CUSTOM_02, …) have a stable
                # string ID that is identical across tenants but often have an empty
                # display name.  _find_existing_user skips empty names, so fall back
                # to a direct slot-ID lookup when the name match fails.
                if (not existing_entry
                        and not name
                        and rtype == "url_category"
                        and source_id
                        and source_id in existing_for_type):
                    existing_entry = existing_for_type[source_id]

                if existing_entry:
                    target_id = existing_entry["id"]
                    if source_id:
                        self._register_remap(source_id, target_id)

                    if self._configs_match(rtype, raw_config, existing_entry["raw_config"]):
                        skipped.append(PushRecord(rtype, display_name, "skipped"))
                        continue

                    queued = dict(entry,
                                  __action="update",
                                  __target_id=target_id,
                                  __display_name=display_name,
                                  __managed=False,
                                  __target_order=existing_entry.get("raw_config", {}).get("order"))
                else:
                    queued = dict(entry,
                                  __action="create",
                                  __display_name=display_name,
                                  __managed=False)

                pending.setdefault(rtype, []).append(queued)

        # Identify extraneous resources present in the tenant but absent from baseline.
        # Only generate deletes for resource types that appear in the baseline file.
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

                if zia_id in baseline_ids or name in baseline_names:
                    continue
                if _is_zscaler_managed(rtype, raw):
                    continue
                if name in SKIP_NAMED.get(rtype, set()):
                    continue

                to_delete.append(PushRecord(
                    resource_type=rtype,
                    name=name or zia_id,
                    status=f"pending_delete:{zia_id}",
                ))

        # Rule ordering strategy:
        #
        # Creates (inserts) use a stacking approach: all are sent at insertion_point =
        # min(baseline create orders), processed in REVERSE baseline order.  Each
        # insert pushes the previous ones up by 1, so the last-processed entry (lowest
        # baseline order) lands at insertion_point with all others correctly above it.
        #
        # Updates (moves) use exact baseline orders and are processed ASCENDING after
        # all creates.  Because creates have already pushed existing rules to higher
        # positions, each ascending update moves a rule back to its exact target slot.
        #
        # Sequence: creates first (descending), then updates (ascending).
        _ORDERED_RULE_TYPES = (
            "ssl_inspection_rule", "url_filtering_rule", "forwarding_rule",
            "firewall_rule", "firewall_dns_rule", "firewall_ips_rule",
            "nat_control_rule", "dlp_web_rule", "bandwidth_control_rule",
            "traffic_capture_rule", "sandbox_rule",
        )
        for rtype in _ORDERED_RULE_TYPES:
            if rtype not in pending:
                continue
            creates = [e for e in pending[rtype] if e.get("__action") == "create"]
            updates = [e for e in pending[rtype] if e.get("__action") != "create"]

            if creates:
                create_orders = [
                    (e.get("raw_config", {}).get("order") or 0)
                    for e in creates
                    if (e.get("raw_config", {}).get("order") or 0) > 0
                ]
                if create_orders:
                    insertion_point = min(create_orders)
                else:
                    managed_positive_orders = [
                        e.get("raw_config", {}).get("order") or 0
                        for e in (existing.get(rtype) or {}).values()
                        if (e.get("raw_config", {}).get("order") or 0) > 0
                    ]
                    insertion_point = max(managed_positive_orders, default=0) + 1
                creates.sort(
                    key=lambda e: e.get("raw_config", {}).get("order") or 0, reverse=True
                )
                for entry in creates:
                    entry["raw_config"] = dict(entry["raw_config"], order=insertion_point)
                    entry["__set_order"] = True

            # Updates keep their exact baseline orders and are sorted ascending so each
            # move lands correctly without displacing already-placed creates.
            # Tag them so _push_one knows to include order in the update payload.
            updates.sort(key=lambda e: e.get("raw_config", {}).get("order") or 0)
            for entry in updates:
                entry["__set_order"] = True
            pending[rtype] = creates + updates

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

        Runs a fresh import of the target tenant then compares against the
        baseline.  Any remaining creates, updates, or deletes indicate that
        the push did not fully apply (e.g. ordering constraint, missed delete).

        Returns:
            A new DryRunResult.  An ideal post-push result has zero pending
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
          Pass 1 — Update Zscaler-managed READ_WRITE resources to match baseline.
                   These are processed first so managed objects are in the correct
                   state before user-defined resources reference them.
          Pass 2 — Create/update user-defined resources in dependency order,
                   with multi-pass retry for transient failures.

        Args:
            dry_run: Result from classify_baseline().
            progress_callback: Called after each push attempt.
                Signature: callback(pass_num: int, resource_type: str, record: PushRecord)
        """
        self._id_remap = dict(dry_run.id_remap)

        # Split pending into:
        #   settings_pending    — Tier-2.5 singletons that may provision one-click rules
        #   one_click_pending   — managed rules absent from target that need re-matching
        #                         after the settings push materialises them
        #   other_managed       — remaining managed resources (Pass 1b)
        #   user_pending        — user-defined resources (Pass 2+)
        _ALL_SINGLETONS = {"url_filter_cloud_app_settings", "advanced_settings",
                           "browser_control_settings"}
        settings_pending: Dict[str, List[dict]] = {}
        one_click_pending: Dict[str, List[dict]] = {}
        other_managed_pending: Dict[str, List[dict]] = {}
        user_pending: Dict[str, List[dict]] = {}

        for rtype, entries in dry_run.pending.items():
            for entry in entries:
                if entry.get("__managed"):
                    if rtype in _ALL_SINGLETONS:
                        settings_pending.setdefault(rtype, []).append(entry)
                    elif entry.get("__one_click_pending"):
                        one_click_pending.setdefault(rtype, []).append(entry)
                    else:
                        other_managed_pending.setdefault(rtype, []).append(entry)
                else:
                    user_pending.setdefault(rtype, []).append(entry)

        all_records: List[PushRecord] = []

        # Pass 1a — settings singletons (provisions one-click rules on the target)
        if settings_pending:
            _, pass1a_records = self._single_pass(settings_pending, 1, progress_callback)
            all_records.extend(pass1a_records)

        # Re-import one-click rule types so newly provisioned rules are visible,
        # then resolve __one_click_pending entries to real target IDs.
        if one_click_pending:
            from services.zia_import_service import ZIAImportService
            _reimport_svc = ZIAImportService(self._client, self._tenant_id)
            _reimport_svc.run(resource_types=list(one_click_pending.keys()))
            refreshed = self._load_existing_from_db()

            # Track orders of unprovisioned one-click rules per type so we can
            # collapse the gap they leave in the source order sequence.
            unprovisioned_orders_by_type: Dict[str, List[int]] = {}

            for rtype, entries in one_click_pending.items():
                refreshed_for_type = refreshed.get(rtype, {})
                for entry in entries:
                    name = entry.get("name") or entry.get("__display_name", "")
                    source_id = str(entry.get("id", ""))
                    found = self._find_existing(refreshed_for_type, source_id, name)
                    if found:
                        target_id = found["id"]
                        if source_id:
                            self._register_remap(source_id, target_id)
                        entry["__target_id"] = target_id
                        entry.pop("__one_click_pending", None)
                        other_managed_pending.setdefault(rtype, []).append(entry)
                    else:
                        dname = entry.get("__display_name") or name or "?"
                        all_records.append(PushRecord(
                            resource_type=rtype,
                            name=dname,
                            status="skipped:one_click_not_provisioned",
                        ))
                        order = (entry.get("raw_config") or {}).get("order") or 0
                        if order > 0:
                            unprovisioned_orders_by_type.setdefault(rtype, []).append(order)

            # Renumber ordered-rule entries whose source order sits above a gap
            # left by an unprovisioned one-click rule.  Each pending entry whose
            # order exceeds a skipped rule's position is decremented by the count
            # of skipped rules positioned strictly before it, so the target ends
            # up with a contiguous sequence starting at 1.
            for rtype, skipped_orders in unprovisioned_orders_by_type.items():
                skipped_sorted = sorted(skipped_orders)
                for pool in (other_managed_pending, user_pending):
                    for entry in pool.get(rtype, []):
                        if not entry.get("__set_order"):
                            continue
                        raw = entry.get("raw_config") or {}
                        current = raw.get("order") or 0
                        if current <= 0:
                            continue
                        gap = sum(1 for so in skipped_sorted if so < current)
                        if gap:
                            entry["raw_config"] = dict(raw, order=current - gap)

        # Pass 1b — remaining managed resources (including resolved one-click items)
        if other_managed_pending:
            _, pass1b_records = self._single_pass(other_managed_pending, 1, progress_callback)
            all_records.extend(pass1b_records)
            # Managed failures are logged but not retried

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
        # Sort by WIPE_ORDER so rules are deleted before the objects they reference
        # (e.g. url_filtering_rule before url_category, firewall_rule before ip_source_group).
        _order = {t: i for i, t in enumerate(WIPE_ORDER)}
        to_delete = sorted(to_delete, key=lambda r: _order.get(r.resource_type, len(WIPE_ORDER)))

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

    def apply_baseline(
        self,
        baseline: dict,
        wipe: bool = True,
        wipe_progress_callback: Optional[Callable] = None,
        import_progress_callback: Optional[Callable] = None,
        push_progress_callback: Optional[Callable] = None,
    ) -> Tuple[List[WipeRecord], List[PushRecord]]:
        """Full wipe-first pipeline: classify wipe, execute wipe, classify baseline, push.

        Args:
            baseline: Parsed snapshot export JSON dict.
            wipe: If True (default), delete user-created resources before pushing.
            wipe_progress_callback: Called during wipe execution.
                Signature: callback(resource_type: str, record: WipeRecord)
            import_progress_callback: Called during import phase.
            push_progress_callback: Called during push phase.

        Returns:
            (wipe_records, push_records)
        """
        wipe_records: List[WipeRecord] = []

        if wipe:
            wipe_result = self.classify_wipe(import_progress_callback)
            wipe_records = self.execute_wipe(wipe_result, wipe_progress_callback)
            # Fresh import happens inside classify_baseline below
        else:
            # Still need the import for classify_baseline — it'll run there
            pass

        dry_run = self.classify_baseline(baseline, import_progress_callback)
        push_records = self.push_classified(dry_run, push_progress_callback)
        return wipe_records, dry_run.skipped + push_records

    # ------------------------------------------------------------------
    # Wipe internals
    # ------------------------------------------------------------------

    def _wipe_delete_one(self, item: WipeRecord) -> WipeRecord:
        """Attempt to delete a single resource identified by classify_wipe()."""
        rtype = item.resource_type
        method_name = _DELETE_METHODS.get(rtype)

        try:
            if rtype == "cloud_app_control_rule":
                from db.database import get_session
                from db.models import ZIAResource
                with get_session() as session:
                    rec = (
                        session.query(ZIAResource)
                        .filter_by(tenant_id=self._tenant_id,
                                   resource_type=rtype,
                                   zia_id=item.zia_id)
                        .first()
                    )
                    rule_type = (rec.raw_config or {}).get("type") if rec else None
                if not rule_type:
                    return WipeRecord(rtype, item.name, item.zia_id,
                                      "failed:permanent:cloud_app_rule missing type in DB")
                self._client.delete_cloud_app_rule(rule_type, item.zia_id)
            elif method_name:
                getattr(self._client, method_name)(item.zia_id)
            else:
                return WipeRecord(rtype, item.name, item.zia_id, "skipped")
            return WipeRecord(rtype, item.name, item.zia_id, "deleted")
        except Exception as exc:
            exc_str = str(exc)
            permanent = bool(re.search(r'"status"\s*:\s*(400|403|404)', exc_str)) or \
                        any(s in exc_str for s in ("NOT_SUBSCRIBED", "not licensed"))
            prefix = "failed:permanent:" if permanent else "failed:"
            return WipeRecord(rtype, item.name, item.zia_id, f"{prefix}{exc_str[:150]}")

    # ------------------------------------------------------------------
    # Push internals
    # ------------------------------------------------------------------

    def _load_existing_from_db(self) -> Dict[str, Dict[str, dict]]:
        """Load all non-deleted resources for this tenant from the DB.

        Returns:
            {resource_type: {zia_id: {"id": str, "name": str, "raw_config": dict}}}
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

        Used for Zscaler-managed resources where system IDs are consistent
        across tenants (e.g. predefined rules, system categories).
        """
        if source_id and source_id in existing_for_type:
            return existing_for_type[source_id]
        if name:
            for entry in existing_for_type.values():
                if entry.get("name") == name:
                    return entry
        return None

    def _find_existing_user(
        self,
        existing_for_type: Dict[str, dict],
        name: str,
    ) -> Optional[dict]:
        """Locate a user-created resource by name only — no ID fallback.

        User-created resource IDs are tenant-specific and can collide with
        system resource IDs in the target tenant (e.g. a user DLP engine with
        id=61 in source vs. an unnamed system engine at id=61 in target).
        Matching by name prevents false cross-tenant ID collisions.
        """
        if name:
            for entry in existing_for_type.values():
                if entry.get("name") == name:
                    return entry
        return None

    def _configs_match(self, resource_type: str, baseline_config: dict, existing_config: dict) -> bool:
        """Return True if the push payloads for both configs are semantically identical.

        Compares _build_payload output rather than raw configs so that environment-specific
        refs (cross-tenant location IDs, ZPA segments, system DLP engines) that are stripped
        during push are also excluded from the comparison.  This prevents false positives
        where a baseline ref (e.g. system engine id=61) was already stripped in the target.

        Falls back to raw strip+normalize if _build_payload raises (e.g. during classify_wipe
        when _target_known_ids is not populated).
        """
        try:
            src = self._normalize(self._build_payload(resource_type, baseline_config))
            tgt = self._normalize(self._build_payload(resource_type, existing_config))
        except Exception:
            src = self._normalize(self._strip(baseline_config))
            tgt = self._normalize(self._strip(existing_config))
        return src == tgt

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

        # browser_control_settings: GET-then-merge to obtain the target's live
        # smartIsolationProfileId and smartIsolationProfile (profileSeq is only
        # available from this endpoint — /browserIsolation/profiles always returns 0).
        if resource_type == "browser_control_settings" and action == "update":
            try:
                current = self._client.zia_get("/zia/api/v1/browserControlSettings")
                payload = self._build_payload(resource_type, raw_config)
                warnings: List[str] = []
                norm_warning = payload.pop("__norm_warning", None)
                if norm_warning:
                    warnings.append(norm_warning)
                if payload.get("enableSmartBrowserIsolation"):
                    target_seq = current.get("smartIsolationProfileId")
                    target_profile = current.get("smartIsolationProfile")
                    if target_seq and target_profile:
                        # Inject the target's own profile reference so the API accepts
                        # the enableSmartBrowserIsolation flag.
                        payload["smartIsolationProfileId"] = target_seq
                        payload["smartIsolationProfile"] = target_profile
                    else:
                        # Smart Isolation has never been activated on this tenant.
                        # The API requires a valid profileSeq which only exists after
                        # the first manual activation — it cannot be bootstrapped via API.
                        payload.pop("enableSmartBrowserIsolation", None)
                        warnings.append(
                            "enableSmartBrowserIsolation not applied — Smart Isolation "
                            "has not been activated on this tenant; enable it once via "
                            "the web UI, then re-push to keep it in sync"
                        )
                self._client.update_browser_control_settings(target_id, payload)
                rec = PushRecord(resource_type=resource_type, name=name, status="updated")
                rec.warnings.extend(warnings)
                return rec
            except Exception as exc:
                return self._classify_error(resource_type, name, exc)

        # Predefined DLP dictionaries: only confidence_threshold can be synced.
        # GET the full camelCase payload, overwrite confidenceThreshold, PUT back.
        if (resource_type == "dlp_dictionary"
                and action == "update"
                and target_id
                and entry.get("__confidence_threshold")):
            conf = entry["__confidence_threshold"]
            try:
                current = self._client.zia_get(f"/zia/api/v1/dlpDictionaries/{target_id}")
                current["confidenceThreshold"] = conf
                self._client.zia_put(f"/zia/api/v1/dlpDictionaries/{target_id}", current)
                return PushRecord(resource_type=resource_type, name=name, status="updated")
            except Exception as exc:
                return self._classify_error(resource_type, name, exc)

        if resource_type not in _WRITE_METHODS:
            return PushRecord(resource_type=resource_type, name=name, status="skipped")

        create_method_name, update_method_name = _WRITE_METHODS[resource_type]
        create_method = getattr(self._client, create_method_name)
        update_method = getattr(self._client, update_method_name)

        # Predefined One-Click rules (ssl_inspection_rule, firewall_rule, etc.) only accept
        # order and rank on update — sending the full payload is rejected by the API.
        _ONE_CLICK_RULE_TYPES = {
            "ssl_inspection_rule", "url_filtering_rule", "firewall_rule",
            "forwarding_rule", "nat_control_rule", "dlp_web_rule",
        }
        if (resource_type in _ONE_CLICK_RULE_TYPES
                and action == "update"
                and target_id
                and raw_config.get("predefined")):
            full_payload = self._build_payload(resource_type, raw_config)
            # GET the raw camelCase payload from the API (SDK as_dict() returns
            # snake_case which the API rejects; also strip server-set read-only fields).
            # ssl_inspection_rule requires `order` in the payload — a restricted
            # {id, name} update fails with "order cannot be null".  Use GET-then-PUT
            # to preserve the target's current state while satisfying the API contract.
            _RULE_API_PATHS = {
                "firewall_rule":       "/zia/api/v1/firewallFilteringRules",
                "ssl_inspection_rule": "/zia/api/v1/sslInspectionRules",
            }
            _RO_FIELDS = {"lastModifiedTime", "lastModifiedBy", "accessControl",
                          "defaultDnsRuleNameUsed", "predefined", "defaultRule"}
            if resource_type in _RULE_API_PATHS:
                # GET raw camelCase, strip server-set RO fields, PUT back.
                # Order is NOT updated — handled by insertion_point mechanism.
                try:
                    current = self._client.zia_get(
                        f"{_RULE_API_PATHS[resource_type]}/{target_id}"
                    )
                    current = {k: v for k, v in current.items() if k not in _RO_FIELDS}
                    self._client.zia_put(
                        f"{_RULE_API_PATHS[resource_type]}/{target_id}", current
                    )
                    return PushRecord(resource_type=resource_type, name=name, status="updated")
                except Exception as exc:
                    return self._classify_error(resource_type, name, exc)
            else:
                # Preserve target's existing rank — admin rank may not be enabled.
                # Order is NOT updated — handled by insertion_point mechanism.
                restricted = {"id": target_id,
                              "name": full_payload.get("name")}
                try:
                    self._do_update(resource_type, target_id, update_method, restricted)
                    return PushRecord(resource_type=resource_type, name=name, status="updated")
                except Exception as exc:
                    return self._classify_error(resource_type, name, exc)

        # Predefined firewall DNS rules: GET the raw camelCase payload, strip
        # server-set read-only fields, PUT back unchanged except for any writable
        # non-order fields that differ.  Order is NOT updated here — it is handled
        # naturally by the reverse-insert mechanism (insertion_point).
        # Snake_case or minimal payloads cause 400/500 errors from the API.
        if (resource_type == "firewall_dns_rule"
                and action == "update"
                and target_id
                and raw_config.get("predefined")):
            _RO_FIELDS_DNS = {"lastModifiedTime", "lastModifiedBy", "accessControl",
                               "defaultDnsRuleNameUsed"}
            try:
                current = self._client.zia_get(f"/zia/api/v1/firewallDnsRules/{target_id}")
                current = {k: v for k, v in current.items() if k not in _RO_FIELDS_DNS}
                self._client.zia_put(
                    f"/zia/api/v1/firewallDnsRules/{target_id}", current
                )
                return PushRecord(resource_type=resource_type, name=name, status="updated")
            except Exception as exc:
                return self._classify_error(resource_type, name, exc)

        payload = self._build_payload(resource_type, raw_config)

        # Detect scope fields that were stripped during normalization because the
        # target tenant has no matching resources (locations, groups, departments,
        # users, ZPA segments are all tenant-specific and not pushed cross-tenant).
        # When ANY scope field is stripped on a create, insert the rule as DISABLED
        # so it cannot fire without its intended audience.  Always warn regardless of
        # action so the operator knows manual fixup is required.
        _SCOPE_CHECKS = [
            ("locations",       "location",          "create locations manually"),
            ("location_groups", "location_group",    "create location groups manually"),
            ("groups",          "group",             "create groups manually"),
            ("departments",     "department",        "create departments manually"),
            ("users",           "user",              "assign users manually"),
            ("devices",         "device",            "assign devices manually"),
            ("device_groups",   "device_group",      "assign device groups manually"),
            ("zpa_app_segments","zpa_app_segment",   "provision ZPA app segments, then re-enable"),
        ]
        record_warnings: List[str] = []
        # Extract warnings embedded by normalizers as __norm_warning sentinel keys.
        norm_warning = payload.pop("__norm_warning", None)
        if norm_warning:
            record_warnings.append(norm_warning)
        scope_was_stripped = False
        for field, rtype, hint in _SCOPE_CHECKS:
            baseline_vals = raw_config.get(field) or []
            if baseline_vals and not payload.get(field):
                scope_was_stripped = True
                names = [
                    v.get("name", str(v.get("id", "?"))) if isinstance(v, dict) else str(v)
                    for v in baseline_vals
                ]
                record_warnings.append(
                    f"{field} scope stripped — {hint}: {', '.join(names)}"
                )
        if scope_was_stripped:
            payload = dict(payload, state="DISABLED")
            if action == "create":
                record_warnings.insert(0, "rule inserted DISABLED — scope fields stripped (see below)")
            else:
                record_warnings.insert(0, "rule kept DISABLED — scope fields still stripped; resolve manually before enabling (see below)")

        # Detect cbi_profile remapped to a different profile (name mismatch or fallback to default).
        if resource_type == "url_filtering_rule":
            baseline_cbi = raw_config.get("cbi_profile")
            payload_cbi  = payload.get("cbi_profile")
            if isinstance(baseline_cbi, dict) and baseline_cbi.get("id"):
                baseline_cbi_name = baseline_cbi.get("name", "")
                if not payload_cbi:
                    record_warnings.append(
                        f"cbi_profile '{baseline_cbi_name}' not found in target and no default "
                        f"isolation profile available — rule created without isolation profile "
                        f"(update manually)"
                    )
                elif payload_cbi.get("name", "").lower() != baseline_cbi_name.lower():
                    record_warnings.append(
                        f"cbi_profile remapped: '{baseline_cbi_name}' → '{payload_cbi.get('name')}' "
                        f"(create matching profile in target to restore exact config)"
                    )

        if action == "update" and target_id:
            # For user-created ordered rules in delta mode, do not change the order.
            # Moving existing rules to their baseline position fails with ordering
            # constraint errors when other rules occupy intermediate positions.
            # In wipe-first mode this is moot (all rules are creates after wipe).
            _ORDERED_RULE_TYPES = {
                "url_filtering_rule", "ssl_inspection_rule", "firewall_rule",
                "firewall_dns_rule", "firewall_ips_rule", "forwarding_rule",
                "nat_control_rule", "dlp_web_rule", "bandwidth_control_rule",
                "traffic_capture_rule", "cloud_app_control_rule", "sandbox_rule",
            }
            update_payload = payload
            if resource_type in _ORDERED_RULE_TYPES and not entry.get("__managed"):
                if entry.get("__set_order"):
                    # Order was explicitly set by the ordering mechanism (creates-first
                    # stacking or ascending update sequence) — honor it in the payload.
                    pass  # update_payload already has the correct order from raw_config
                else:
                    # Legacy delta path: preserve the target's existing order to avoid
                    # ordering constraint failures when other rules are in the way.
                    target_order = entry.get("__target_order")
                    if target_order is not None:
                        update_payload = dict(payload, order=target_order)
                    else:
                        update_payload = {k: v for k, v in payload.items() if k != "order"}
            try:
                self._do_update(resource_type, target_id, update_method, update_payload)
                return PushRecord(resource_type=resource_type, name=name, status="updated",
                                  warnings=record_warnings)
            except Exception as exc:
                return self._classify_error(resource_type, name, exc)

        # action == "create"
        try:
            result = self._do_create_with_rank_fallback(create_method, payload)
            new_target_id = str(result.get("id", ""))
            if source_id and new_target_id:
                self._register_remap(source_id, new_target_id)
            return PushRecord(resource_type=resource_type, name=name, status="created",
                              warnings=record_warnings)
        except Exception as exc:
            exc_str = str(exc)
            if ("409" in exc_str or "DUPLICATE_ITEM" in exc_str
                    or "already exists" in exc_str.lower() or "conflict" in exc_str.lower()):
                found_id = self._find_by_name_live(resource_type, name)
                if found_id:
                    if source_id:
                        self._register_remap(source_id, found_id)
                    try:
                        self._do_update(resource_type, found_id, update_method, payload)
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
        rule_type = raw_config.get("type") or raw_config.get("rule_type")
        if not rule_type:
            return PushRecord(
                resource_type="cloud_app_control_rule",
                name=name,
                status="failed:permanent:missing rule type in config",
            )

        payload = self._build_payload("cloud_app_control_rule", raw_config)

        # Detect custom cloud apps in the rule's applications list.
        # Custom cloud apps cannot be created via the public API and must be created
        # manually in the target tenant's web UI before this rule will work correctly.
        # Detection: any app name not present in the target's imported cloud_app_policy set.
        record_warnings: List[str] = []
        known_apps = self._target_known_ids.get("cloud_app_policy", set())
        baseline_apps = raw_config.get("applications") or []
        unknown_apps = [a for a in baseline_apps if str(a) not in known_apps]
        if unknown_apps:
            record_warnings.append(
                f"applications may include custom cloud apps not in target "
                f"(create manually in web UI): {', '.join(str(a) for a in unknown_apps)}"
            )

        if action == "update" and target_id:
            try:
                self._client.update_cloud_app_rule(rule_type, target_id, payload)
                return PushRecord(resource_type="cloud_app_control_rule", name=name,
                                  status="updated", warnings=record_warnings)
            except Exception as exc:
                return self._classify_error("cloud_app_control_rule", name, exc)

        try:
            result = self._do_create_with_rank_fallback(
                lambda p: self._client.create_cloud_app_rule(rule_type, p),
                payload,
            )
            new_target_id = str(result.get("id", ""))
            if source_id and new_target_id:
                self._register_remap(source_id, new_target_id)
            return PushRecord(resource_type="cloud_app_control_rule", name=name,
                              status="created", warnings=record_warnings)
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
                            self._client.update_cloud_app_rule(rule_type, found_id, payload)
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
            urls = (raw_config.get("whitelist_urls") or raw_config.get("whitelistUrls") or
                    raw_config.get("blacklist_urls") or raw_config.get("blacklistUrls") or [])
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
        """Delete a single resource from the live tenant (legacy delta-mode path).

        A failed delete is returned as a skipped record with a warning rather than
        a hard failure — the push itself is unaffected and the user is informed via
        the manual-action warnings section.
        """
        method_name = _DELETE_METHODS.get(resource_type)

        try:
            if resource_type == "cloud_app_control_rule":
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
                    return PushRecord(resource_type, name, "skipped",
                                      warnings=["could not delete — rule type not found in DB"])
                self._client.delete_cloud_app_rule(rule_type, zia_id)
            elif method_name:
                getattr(self._client, method_name)(zia_id)
            else:
                return PushRecord(resource_type, name, "skipped")
            return PushRecord(resource_type, name, "deleted")
        except Exception as exc:
            reason = self._classify_error(resource_type, name, exc).failure_reason
            return PushRecord(resource_type, name, "skipped",
                              warnings=[f"could not delete — {reason} (may be Zscaler-managed or have active dependencies)"])

    def _classify_error(self, resource_type: str, name: str, exc: Exception) -> PushRecord:
        """Classify an exception as permanent (4xx) or transient."""
        exc_str = str(exc)
        permanent = bool(re.search(r'"status"\s*:\s*(400|403|404)', exc_str)) or \
                    any(s in exc_str for s in ("NOT_SUBSCRIBED", "not licensed"))
        prefix = "failed:permanent:" if permanent else "failed:"
        return PushRecord(
            resource_type=resource_type,
            name=name,
            status=f"{prefix}{exc_str[:150]}",
        )

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _build_payload(self, resource_type: str, raw_config: dict) -> dict:
        """Build normalized push payload: strip read-only fields, normalize embedded
        refs for API compatibility, then apply ID remapping."""
        cfg = self._strip(raw_config)
        cfg = self._type_normalize(resource_type, cfg)
        cfg = self._apply_id_remap(cfg)
        return cfg

    def _type_normalize(self, resource_type: str, cfg: dict) -> dict:
        """Apply per-type payload normalization (embed stripping, empty field handling,
        flat string array remapping)."""
        handlers = {
            "ssl_inspection_rule":    self._norm_ssl_inspection_rule,
            "firewall_rule":          self._norm_firewall_rule,
            "firewall_dns_rule":      self._norm_firewall_dns_rule,
            "firewall_ips_rule":      self._norm_firewall_ips_rule,
            "forwarding_rule":        self._norm_forwarding_rule,
            "nat_control_rule":       self._norm_nat_control_rule,
            "url_filtering_rule":     self._norm_url_filtering_rule,
            "dlp_web_rule":           self._norm_dlp_web_rule,
            "bandwidth_control_rule": self._norm_bandwidth_control_rule,
            "traffic_capture_rule":   self._norm_traffic_capture_rule,
            "cloud_app_control_rule": self._norm_cloud_app_control_rule,
            "location":               self._norm_location,
            "sandbox_rule":                  self._norm_sandbox_rule,
            "url_filter_cloud_app_settings": self._norm_url_filter_cloud_app_settings,
            "advanced_settings":             self._norm_advanced_settings,
            "browser_control_settings":      self._norm_browser_control_settings,
        }
        handler = handlers.get(resource_type)
        if handler:
            return handler(cfg)
        return cfg

    def _norm_ref_fields(
        self,
        cfg: dict,
        ref_fields: tuple = (),
        resolved_fields: tuple = (),
        empty_strip: tuple = (),
    ) -> dict:
        """Generic helper: normalize reference arrays and strip empty fields.

        ref_fields: apply _ref() — embed → [{id: X}].  Use for same-tenant or
                    non-env-specific references (nw_services, time_windows, etc.)
        resolved_fields: apply _ref_resolved() — also strip IDs not present in
                    the target tenant.  Use for env-specific references: locations,
                    location_groups, users, groups, departments, zpa_app_segments.
        empty_strip: remove the field entirely if falsy/empty.
        """
        for f in ref_fields:
            if cfg.get(f) is not None:
                cfg[f] = self._ref(cfg[f])
        for field_spec in resolved_fields:
            # field_spec is either "field_name" or ("field_name", "resource_type")
            if isinstance(field_spec, tuple):
                f, rtype = field_spec
            else:
                f, rtype = field_spec, field_spec  # best-effort: use field name as type
            if cfg.get(f) is not None:
                cfg[f] = self._ref_resolved(cfg[f], rtype)
                if not cfg[f]:
                    cfg.pop(f, None)
        for f in empty_strip:
            if not cfg.get(f):
                cfg.pop(f, None)
        return cfg

    def _norm_ssl_inspection_rule(self, cfg: dict) -> dict:
        # CRITICAL: locations contains full embedded objects — reduce to [{id: X}]
        # locations and location_groups are env-specific → filter to target's known IDs
        self._norm_ref_fields(cfg,
            ref_fields=("source_ip_groups", "dest_ip_groups", "workload_groups",
                        "proxy_gateways", "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
                ("devices",         "devices"),
                ("device_groups",   "device_groups"),
                ("zpa_app_segments", "zpa_app_segment"),
            ),
            empty_strip=("device_trust_levels", "platforms", "user_agent_types",
                         "cloud_applications", "proxy_gateways",
                         "url_categories", "time_windows"),
        )
        if cfg.get("url_categories"):
            cfg["url_categories"] = self._remap_str_list(cfg["url_categories"])
        # The SDK converts min_client_tls_version → minClientTlsVersion (wrong case).
        # Pre-rename to the correct camelCase so the SDK leaves them unchanged.
        action = cfg.get("action")
        if isinstance(action, dict):
            sub = action.get("decrypt_sub_actions")
            if isinstance(sub, dict):
                for old, new in (("min_client_tls_version", "minClientTLSVersion"),
                                 ("min_server_tls_version", "minServerTLSVersion")):
                    if old in sub:
                        sub[new] = sub.pop(old)
        return cfg

    def _norm_firewall_rule(self, cfg: dict) -> dict:
        # nw_services contains full embedded objects with port specs — reduce to [{id: X}]
        self._norm_ref_fields(cfg,
            ref_fields=("src_ip_groups", "src_ipv6_groups", "dest_ip_groups", "dest_ipv6_groups",
                        "nw_services", "nw_service_groups", "nw_applications",
                        "nw_application_groups", "workload_groups", "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
                ("zpa_app_segments", "zpa_app_segment"),
            ),
            empty_strip=("device_trust_levels", "src_ips", "dest_addresses",
                         "dest_countries", "source_countries"),
        )
        return cfg

    def _norm_firewall_dns_rule(self, cfg: dict) -> dict:
        # Strip server-computed fields that cause schema failures
        for f in ("default_dns_rule_name_used", "is_web_eun_enabled"):
            cfg.pop(f, None)
        self._norm_ref_fields(cfg,
            ref_fields=("src_ip_groups", "src_ipv6_groups", "dest_ip_groups", "dest_ipv6_groups",
                        "applications", "application_groups", "devices", "device_groups",
                        "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
            ),
            empty_strip=("src_ips", "dest_addresses", "dest_countries"),
        )
        return cfg

    def _norm_firewall_ips_rule(self, cfg: dict) -> dict:
        self._norm_ref_fields(cfg,
            ref_fields=("src_ip_groups", "src_ipv6_groups", "dest_ip_groups", "dest_ipv6_groups",
                        "nw_services", "nw_service_groups", "devices", "device_groups",
                        "time_windows", "labels", "threat_categories"),
            resolved_fields=(
                ("locations",        "location"),
                ("location_groups",  "location_group"),
                ("groups",           "group"),
                ("departments",      "department"),
                ("users",            "user"),
                ("zpa_app_segments", "zpa_app_segment"),
            ),
            empty_strip=("src_ips", "dest_addresses", "dest_countries", "source_countries",
                         "dest_ip_categories", "res_categories"),
        )
        return cfg

    def _norm_forwarding_rule(self, cfg: dict) -> dict:
        # zpa_gateway comes as a full embedded object — reduce to {id: X} so the
        # API doesn't reject unknown extension fields.
        if cfg.get("zpa_gateway") and isinstance(cfg["zpa_gateway"], dict):
            gw_id = cfg["zpa_gateway"].get("id")
            if gw_id:
                cfg["zpa_gateway"] = {"id": gw_id}
            else:
                cfg.pop("zpa_gateway", None)
        self._norm_ref_fields(cfg,
            ref_fields=("src_ip_groups", "src_ipv6_groups", "dest_ip_groups", "dest_ipv6_groups",
                        "nw_services", "nw_service_groups", "nw_applications",
                        "nw_application_groups", "ec_groups", "time_windows", "labels"),
            resolved_fields=(
                ("locations",                       "location"),
                ("location_groups",                 "location_group"),
                ("groups",                          "group"),
                ("departments",                     "department"),
                ("users",                           "user"),
                ("devices",                         "devices"),
                ("device_groups",                   "device_groups"),
                ("zpa_app_segments",                "zpa_app_segment"),
                ("zpa_application_segments",        "zpa_app_segment"),
                ("zpa_application_segment_groups",  "zpa_app_segment"),
            ),
            empty_strip=("src_ips", "dest_addresses", "dest_countries", "time_windows"),
        )
        return cfg

    def _norm_nat_control_rule(self, cfg: dict) -> dict:
        self._norm_ref_fields(cfg,
            ref_fields=("src_ip_groups", "src_ipv6_groups", "dest_ip_groups", "dest_ipv6_groups",
                        "nw_services", "nw_service_groups", "devices", "device_groups",
                        "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
            ),
            empty_strip=("src_ips", "dest_addresses", "dest_countries"),
        )
        return cfg

    def _norm_url_filtering_rule(self, cfg: dict) -> dict:
        self._norm_ref_fields(cfg,
            ref_fields=("source_ip_groups", "workload_groups", "override_users",
                        "override_groups", "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
                ("zpa_app_segments", "zpa_app_segment"),
            ),
            empty_strip=("device_trust_levels", "user_agent_types", "user_risk_score_levels",
                         "time_windows", "url_categories", "url_categories2"),
        )
        if cfg.get("url_categories"):
            cfg["url_categories"] = self._remap_str_list(cfg["url_categories"])
        # cbi_profile UUIDs are tenant-specific. Remap by name against target's profiles.
        # Fallback to the default isolation profile if no name match exists.
        # Strip entirely (with a note in _push_one warnings) if no profiles available.
        cbi = cfg.get("cbi_profile")
        if isinstance(cbi, dict) and cbi.get("id"):
            profile_name = (cbi.get("name") or "").lower()
            matched = self._cbi_profile_map.get(profile_name)
            if matched:
                cfg["cbi_profile"] = {"id": matched["id"], "name": matched.get("name", ""),
                                      "url": matched.get("url", "")}
            else:
                # Fall back to default profile if available.
                # Direct HTTP uses camelCase (defaultProfile); handle both just in case.
                default = next(
                    (p for p in self._cbi_profile_map.values()
                     if p.get("defaultProfile") or p.get("default_profile")),
                    None,
                )
                if default:
                    cfg["cbi_profile"] = {"id": default["id"], "name": default.get("name", ""),
                                          "url": default.get("url", "")}
                else:
                    cfg.pop("cbi_profile", None)
        return cfg

    def _norm_dlp_web_rule(self, cfg: dict) -> dict:
        # dlp_engines: reduce embedded objects to [{id: X}] then filter to IDs that
        # exist in the target tenant.  Both named (custom_dlp_engine=True, IDs 1-24)
        # and predefined (custom_dlp_engine=False, IDs 60-64) engines are usable.
        if cfg.get("dlp_engines"):
            remapped = [
                {"id": type(e["id"])(self._id_remap.get(str(e["id"]), e["id"]))}
                for e in cfg["dlp_engines"]
                if e.get("id") and self._id_remap.get(str(e["id"]), str(e["id"])) in self._usable_dlp_engine_ids
            ]
            if remapped:
                cfg["dlp_engines"] = remapped
            else:
                cfg.pop("dlp_engines", None)
        self._norm_ref_fields(cfg,
            ref_fields=("source_ip_groups", "workload_groups",
                        "time_windows", "labels"),
            resolved_fields=(
                ("locations",        "location"),
                ("location_groups",  "location_group"),
                ("groups",           "group"),
                ("departments",      "department"),
                ("users",            "user"),
                ("zpa_app_segments", "zpa_app_segment"),
            ),
            empty_strip=(
                "file_types", "user_risk_score_levels",
                # SDK returns empty arrays for unused fields — strip them to avoid API errors
                "dlp_content_locations_scopes",
                "excluded_groups", "excluded_departments", "excluded_users",
                "included_domain_profiles", "excluded_domain_profiles",
                "cloud_applications", "url_categories",
                "workload_groups", "source_ip_groups", "zpa_app_segments",
                # dlp_engines may be absent in source (after filtering system engines) or
                # empty-list in target — normalise both to absent for comparison.
                "dlp_engines",
            ),
        )
        # url_categories can be either a flat string list (Zscaler-defined names) or a
        # list of embedded objects [{id: X, ...}] (custom categories). Handle both forms.
        if cfg.get("url_categories"):
            cats = cfg["url_categories"]
            if cats and isinstance(cats[0], dict):
                cfg["url_categories"] = self._ref_resolved(cats, "url_category")
                if not cfg["url_categories"]:
                    cfg.pop("url_categories", None)
            else:
                cfg["url_categories"] = self._remap_str_list(cats)
        return cfg

    def _norm_sandbox_rule(self, cfg: dict) -> dict:
        # url_categories is a flat string list — remap CUSTOM_XX slots.
        if cfg.get("url_categories"):
            cfg["url_categories"] = self._remap_str_list(cfg["url_categories"])
        # Strip read-only / server-computed fields.
        for f in ("default_rule", "cbi_profile_id"):
            cfg.pop(f, None)
        self._norm_ref_fields(cfg,
            ref_fields=("time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
            ),
            empty_strip=("url_categories", "file_types", "protocols",
                         "ba_policy_categories", "zpa_app_segments",
                         "device_trust_levels", "user_agent_types"),
        )
        return cfg

    def _norm_bandwidth_control_rule(self, cfg: dict) -> dict:
        self._norm_ref_fields(cfg,
            ref_fields=("bandwidth_classes", "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
            ),
        )
        return cfg

    def _norm_traffic_capture_rule(self, cfg: dict) -> dict:
        self._norm_ref_fields(cfg,
            ref_fields=("src_ip_groups", "dest_ip_groups", "time_windows", "labels"),
            resolved_fields=(
                ("locations",       "location"),
                ("location_groups", "location_group"),
                ("groups",          "group"),
                ("departments",     "department"),
                ("users",           "user"),
            ),
        )
        return cfg

    def _norm_location(self, cfg: dict) -> dict:
        # Strip tenant-specific bindings that cannot/should not cross tenants.
        # vpn_credentials: UFQDN/IP credentials bound to this specific org.
        # ip_addresses: public IP associations — must be provisioned per-org by Zscaler.
        # dynamiclocation_groups: read-only, auto-assigned by dynamic group criteria.
        # static_location_groups: membership is managed from the group side, not writable here.
        # child_count: read-only counter.
        # extranet/extranet_ip_pool/extranet_dns with id=0: null references that the API rejects.
        for f in ("vpn_credentials", "ip_addresses", "dynamiclocation_groups",
                  "static_location_groups", "child_count"):
            cfg.pop(f, None)
        for f in ("extranet", "extranet_ip_pool", "extranet_dns"):
            val = cfg.get(f)
            if isinstance(val, dict) and val.get("id") == 0:
                cfg.pop(f, None)
        return cfg

    def _norm_url_filter_cloud_app_settings(self, cfg: dict) -> dict:
        # Strip the wrapper fields added for import compatibility — not part of the API payload.
        cfg.pop("name", None)
        return cfg

    def _norm_advanced_settings(self, cfg: dict) -> dict:
        cfg.pop("name", None)
        return cfg

    def _norm_browser_control_settings(self, cfg: dict) -> dict:
        cfg.pop("name", None)
        # browserControlSettings is stored from direct HTTP (zia_get), so all keys are
        # camelCase.  The API also expects camelCase on PUT.  Always use camelCase here.
        #
        # smartIsolationProfile / smartIsolationProfileId are tenant-specific.
        # The /browserIsolation/profiles endpoint always returns profileSeq=0 and is
        # therefore useless for resolving these values.  Strip all source profile fields
        # here; _push_one will inject the target's live values via GET-then-merge.
        cfg.pop("smartIsolationProfileId", None)
        cfg.pop("smartIsolationProfile", None)
        cfg.pop("smart_isolation_profile_id", None)
        cfg.pop("smart_isolation_profile", None)
        # smartIsolationUsers / smartIsolationGroups are env-specific references;
        # strip IDs that don't exist in the target.  The API uses camelCase.
        self._norm_ref_fields(cfg,
            resolved_fields=(
                ("smartIsolationUsers",  "user"),
                ("smartIsolationGroups", "group"),
            ),
        )
        return cfg

    def _norm_cloud_app_control_rule(self, cfg: dict) -> dict:
        # applications is a flat string list (app names), not [{id: X}] — leave as-is.
        # An empty list means "Any" in the ZIA UI; the API represents this by omitting
        # the field entirely (sending [] or ["ANY"] is rejected as invalid).
        if not cfg.get("applications"):
            cfg.pop("applications", None)
        self._norm_ref_fields(cfg,
            ref_fields=("time_windows", "labels"),
            resolved_fields=(
                ("locations",              "location"),
                ("location_groups",        "location_group"),
                ("groups",                 "group"),
                ("departments",            "department"),
                ("users",                  "user"),
                ("tenancy_profile_ids",    "tenancy_restriction_profile"),
            ),
            empty_strip=("device_trust_levels", "user_agent_types", "user_risk_score_levels",
                         "cloud_app_instances"),
        )
        return cfg

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
                    mapped = self._id_remap[id_str]
                    try:
                        value["id"] = int(mapped)
                    except (ValueError, TypeError):
                        value["id"] = mapped
            return {k: self._remap_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._remap_value(item) for item in value]
        return value

    def _register_remap(self, source_id, target_id) -> None:
        """Store source→target ID mapping (both coerced to str)."""
        self._id_remap[str(source_id)] = str(target_id)

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _ref(arr: list) -> list:
        """Reduce embedded object array to [{id: X}] — strips extra fields."""
        if not arr:
            return arr
        return [{"id": item["id"]} for item in arr if isinstance(item, dict) and item.get("id") is not None]

    @staticmethod
    def _ref_named(arr: list) -> list:
        """Reduce embedded object array to [{id: X, name: Y}]."""
        if not arr:
            return arr
        return [{"id": i["id"], "name": i.get("name", "")} for i in arr if isinstance(i, dict) and i.get("id") is not None]

    def _ref_resolved(self, arr: list, resource_type: str) -> list:
        """Like _ref() but strips IDs that can't be resolved in the target tenant.

        Used for reference fields that point to env-specific resources
        (locations, location_groups, zpa_app_segments, etc.) that may differ
        across tenants and are never pushed as part of a baseline.

        Kept:  negative IDs (Zscaler system constants, e.g. -3 = Mobile Users)
               IDs present in the target's imported data
               IDs registered in _id_remap from this session's creates

        Stripped: positive IDs from the source tenant not present in target
        """
        if not arr:
            return arr
        known = self._target_known_ids.get(resource_type, set())
        # Predefined locations (Road Warrior, Mobile Users, etc.) are stored under
        # location_lite rather than location — include both when resolving location refs.
        if resource_type == "location":
            known = known | self._target_known_ids.get("location_lite", set())
        result = []
        for item in arr:
            id_val = item.get("id")
            if id_val is None:
                continue
            # Negative IDs are Zscaler system constants (Mobile Users = -3, etc.)
            if isinstance(id_val, (int, float)) and id_val < 0:
                result.append({"id": id_val})
                continue
            id_str = str(id_val)
            if id_str in known or id_str in self._id_remap:
                mapped = self._id_remap.get(id_str, id_val)
                try:
                    result.append({"id": int(mapped)})
                except (ValueError, TypeError):
                    result.append({"id": mapped})
        return result

    def _remap_str_list(self, lst: list) -> list:
        """Remap flat string array through id_remap.

        Numeric strings are user-resource IDs and always remapped.
        Non-numeric strings are looked up too — CUSTOM_XX category IDs may differ
        between tenants if the assignment order differed.  Zscaler-defined names
        (e.g. "ADULT_SEX_EDUCATION") won't be in _id_remap, so they pass through
        unchanged via the dict .get() default.
        """
        return [self._id_remap.get(str(s), s) if isinstance(s, str) else s
                for s in lst]

    def _get_config_version(self, resource_type: str, target_id: str) -> Optional[int]:
        """Live GET a resource to retrieve its current configVersion.

        Returns the version as int if present, else None (e.g. tenants that
        don't expose configVersion in their API responses).
        """
        get_method_name = _GET_METHODS.get(resource_type)
        if not get_method_name:
            return None
        try:
            rec = getattr(self._client, get_method_name)(target_id)
            return rec.get("config_version") or rec.get("configVersion")
        except Exception:
            return None

    def _do_update(
        self,
        resource_type: str,
        target_id: str,
        update_method,
        payload: dict,
    ) -> None:
        """Execute an update with live configVersion re-fetch before PUT."""
        cv = self._get_config_version(resource_type, target_id)
        if cv is not None:
            payload["config_version"] = cv
        update_method(target_id, payload)

    def _do_create_with_rank_fallback(self, create_method, payload: dict) -> dict:
        """Try create; if rank/order rejected as invalid, retry without rank and order.

        If rank is *required* ("must have a rank specified"), we do NOT strip it —
        that error means rank is mandatory and should be investigated, not silently dropped.
        """
        try:
            return create_method(payload)
        except Exception as exc:
            exc_str = str(exc).lower()
            rank_required = "must have" in exc_str or ("rank" in exc_str and "required" in exc_str)
            rank_invalid = (
                "not allowed at order" in exc_str
                or ("rank" in exc_str and "400" in exc_str and not rank_required)
            )
            if rank_invalid:
                fallback = {k: v for k, v in payload.items() if k not in ("rank", "order")}
                return create_method(fallback)
            raise

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
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_zscaler_managed(resource_type: str, raw_config: dict) -> bool:
    """Return True if this resource is owned/managed by Zscaler across all tenants.

    All field names are snake_case — SDK as_dict() returns snake_case.

    Signals checked:
    - predefined:true  — dlp_engine, dlp_dictionary, network_service, url_filtering_rule, etc.
    - default_rule:true — firewall/forwarding/other rule types with a "default" Zscaler rule
    - network_service: type in ("PREDEFINED", "STANDARD") — STANDARD covers the 5 base services
    - bandwidth_class: name.startswith("BANDWIDTH_CAT_") — no type field; name is the signal
    - url_category: custom_category==False and non-numeric ID (Zscaler-defined categories)
    - dlp_engine: custom_dlp_engine==False
    - SKIP_NAMED: hardcoded names that are system-owned regardless of predefined flag
      Includes: "Smart Isolation One Click Rule" (ssl_inspection_rule, predefined=True in API
      but guarded by name as belt-and-suspenders in case raw_config was captured without it)
    """
    if resource_type in ("url_filter_cloud_app_settings", "advanced_settings",
                         "browser_control_settings"):
        return True  # singletons — always present in every tenant, never created/deleted
    if raw_config.get("predefined"):
        return True
    # ciparule:true — CIPA Compliance Rule; Zscaler-managed, toggled via enableCIPACompliance
    # in url_filter_cloud_app_settings.  Not flagged predefined by the API but equally
    # restricted: cannot be created/renamed manually.
    if raw_config.get("ciparule"):
        return True
    # Check both snake_case (SDK as_dict()) and camelCase (direct HTTP) forms.
    if raw_config.get("default_rule") or raw_config.get("defaultRule"):
        return True
    name = raw_config.get("name", "")
    if name and name in SKIP_NAMED.get(resource_type, set()):
        return True
    # network_service: PREDEFINED (protocol definitions) and STANDARD (5 base services)
    if resource_type == "network_service":
        svc_type = raw_config.get("type", "")
        if svc_type in ("PREDEFINED", "STANDARD"):
            return True
    # bandwidth_class: no type field — use name prefix as the detection signal
    if resource_type == "bandwidth_class":
        if name.startswith("BANDWIDTH_CAT_"):
            return True
    if resource_type == "url_category":
        if raw_config.get("type") == "ZSCALER_DEFINED":
            return True
        # custom_category == False → Zscaler-defined (handles SDK bool/int serialization)
        # custom_category == True  → user-created (CUSTOM_01 etc.), treat as user resource
        if raw_config.get("custom_category") == False:  # noqa: E712
            return True
        if raw_config.get("custom_category"):
            return False
        # Fallback: non-numeric IDs (e.g. "ADULT_SEX_EDUCATION") are Zscaler-defined
        cat_id = str(raw_config.get("id", ""))
        if cat_id and not cat_id.isdigit():
            return True
    # forwarding_rule: negative order means auto-created by ZPA/Client Connector — immutable
    if resource_type == "forwarding_rule":
        if (raw_config.get("order") or 0) < 0:
            return True
    if resource_type == "dlp_engine":
        # custom_dlp_engine:false → anonymous predefined engine (read-only, locked IDs)
        # custom_dlp_engine:true  → named engine (Zscaler-provided defaults OR user-created)
        #   These are handled via _find_existing_user (name lookup) in the user path so
        #   that Zscaler-provided named engines are matched by name AND user-created ones
        #   can be created in the target when not found.
        if raw_config.get("custom_dlp_engine") == False:  # noqa: E712
            return True
    if resource_type == "dlp_dictionary":
        # custom:false → Zscaler-predefined dictionary (SDK does not return a 'predefined' field)
        if raw_config.get("custom") == False:  # noqa: E712
            return True
    return False


def _is_writable(raw_config: dict) -> bool:
    """Return True if this Zscaler-managed resource allows modifications.

    Resources with access_control:"READ_WRITE" can be updated to match the baseline.
    Read-only managed resources are remapped but never modified.

    Field name is snake_case — SDK as_dict() converts accessControl → access_control.
    Note: access_control may be absent on some tenant configurations; when absent,
    the resource is treated as read-only.
    """
    return raw_config.get("access_control") == "READ_WRITE"
