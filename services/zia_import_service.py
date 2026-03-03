"""ZIA config import service.

Pulls the current configuration from ZIA via the API and stores each resource
as a ZIAResource row.  Unchanged resources (same config_hash) are skipped so
re-runs are fast.  A SyncLog row records the outcome of every run.

Usage:
    service = ZIAImportService(client, tenant_id=tenant.id)

    def on_progress(resource_type, count, total):
        print(f"{resource_type}: {count}/{total}")

    service.run(progress_callback=on_progress)
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional

from db.database import get_session
from db.models import SyncLog, TenantConfig, ZIAResource
from services import audit_service


@dataclass
class ResourceDef:
    """Describes one ZIA resource type to import."""
    resource_type: str          # key stored in zia_resources.resource_type
    list_method: str            # name of ZIAClient method that returns a list
    id_field: str = "id"        # JSON field containing the ZIA resource ID
    name_field: str = "name"    # JSON field containing a human-readable name
    list_args: dict = field(default_factory=dict)


# All resource types we import.  Order doesn't matter.
RESOURCE_DEFINITIONS: List[ResourceDef] = [
    ResourceDef("url_category",          "list_url_categories"),
    ResourceDef("url_filtering_rule",    "list_url_filtering_rules"),
    ResourceDef("firewall_rule",         "list_firewall_rules"),
    ResourceDef("firewall_dns_rule",     "list_firewall_dns_rules"),
    ResourceDef("firewall_ips_rule",     "list_firewall_ips_rules"),
    ResourceDef("ssl_inspection_rule",   "list_ssl_inspection_rules"),
    ResourceDef("forwarding_rule",       "list_forwarding_rules"),
    ResourceDef("ip_destination_group",  "list_ip_destination_groups"),
    ResourceDef("ip_source_group",       "list_ip_source_groups"),
    ResourceDef("network_service",       "list_network_services"),
    ResourceDef("network_svc_group",     "list_network_svc_groups"),
    ResourceDef("rule_label",            "list_rule_labels"),
    ResourceDef("time_interval",         "list_time_intervals"),
    ResourceDef("location",              "list_locations"),
    ResourceDef("location_group",        "list_location_groups"),
    ResourceDef("admin_user",            "list_admin_users"),
    ResourceDef("admin_role",            "list_admin_roles"),
    ResourceDef("department",            "list_departments"),
    ResourceDef("group",                 "list_groups"),
    ResourceDef("user",                  "list_users"),
    ResourceDef("dlp_engine",            "list_dlp_engines"),
    ResourceDef("dlp_dictionary",        "list_dlp_dictionaries"),
    ResourceDef("cloud_app_policy",      "list_cloud_app_policy",     id_field="app",  name_field="app_name"),
    ResourceDef("cloud_app_ssl_policy",  "list_cloud_app_ssl_policy", id_field="app",  name_field="app_name"),
    ResourceDef("cloud_app_control_rule","list_all_cloud_app_rules",  id_field="id",   name_field="name"),
    ResourceDef("allowlist",             "list_allowlist",      id_field="id", name_field="name"),
    ResourceDef("denylist",             "list_denylist",       id_field="id", name_field="name"),
    ResourceDef("dlp_web_rule",          "list_dlp_web_rules"),
    ResourceDef("nat_control_rule",      "list_nat_control_rules"),
    ResourceDef("bandwidth_class",       "list_bandwidth_classes"),
    ResourceDef("bandwidth_control_rule","list_bandwidth_control_rules"),
    ResourceDef("traffic_capture_rule",  "list_traffic_capture_rules"),
    ResourceDef("workload_group",        "list_workload_groups"),
    ResourceDef("network_app",           "list_network_apps"),
    ResourceDef("network_app_group",     "list_network_app_groups"),
]


def _hash(obj) -> str:
    """Return SHA-256 hex digest of a JSON-serialised object."""
    raw = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class ZIAImportService:
    def __init__(self, client, tenant_id: int):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        resource_types: Optional[List[str]] = None,
    ) -> SyncLog:
        """Import ZIA config into the database.

        Args:
            progress_callback: Called after each resource type is fetched.
                Signature: callback(resource_type: str, done: int, total: int)
            resource_types: If given, only import these resource_type values.

        Returns:
            The completed SyncLog ORM object.
        """
        all_defs = [d for d in RESOURCE_DEFINITIONS
                    if resource_types is None or d.resource_type in resource_types]
        total = len(all_defs)

        disabled_types = set(self._get_disabled_resource_types())

        with get_session() as session:
            sync = SyncLog(
                tenant_id=self.tenant_id,
                product="ZIA",
                status="RUNNING",
            )
            session.add(sync)
            session.flush()
            sync_id = sync.id

        run_start = datetime.utcnow()

        synced = updated = deleted = 0
        errors = []
        newly_disabled = []

        for idx, defn in enumerate(all_defs, start=1):
            if defn.resource_type in disabled_types:
                if progress_callback:
                    progress_callback(defn.resource_type, idx, total)
                continue

            try:
                records = self._fetch(defn)
            except Exception as exc:
                if "401" in str(exc) or "NOT_SUBSCRIBED" in str(exc):
                    self._disable_resource_type(defn.resource_type)
                    disabled_types.add(defn.resource_type)
                    newly_disabled.append(defn.resource_type)
                    audit_service.log(
                        product="ZIA",
                        operation="import_config",
                        action="DISABLE",
                        status="N/A",
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        resource_name="marked as N/A — not entitled",
                    )
                else:
                    errors.append(f"{defn.resource_type}: {exc}")
                if progress_callback:
                    progress_callback(defn.resource_type, idx, total)
                continue

            s, u = self._upsert(defn, records, run_start)
            synced += s
            updated += u

            if progress_callback:
                progress_callback(defn.resource_type, idx, total)

        deleted = self._mark_deleted(resource_types, run_start)

        all_skipped = sorted(disabled_types)
        attempted = total - len([d for d in all_defs if d.resource_type in disabled_types and d.resource_type not in newly_disabled])
        final_status = "FAILED" if (errors and len(errors) == attempted) else (
            "PARTIAL" if errors else "SUCCESS"
        )

        with get_session() as session:
            sync = session.get(SyncLog, sync_id)
            sync.completed_at = datetime.utcnow()
            sync.status = final_status
            sync.resources_synced = synced
            sync.resources_updated = updated
            sync.resources_deleted = deleted
            sync.error_message = "\n".join(errors) if errors else None
            sync.details = {"skipped_na": all_skipped} if all_skipped else None

        for error_msg in errors:
            rtype = error_msg.split(":", 1)[0].strip()
            audit_service.log(
                product="ZIA",
                operation="import_config",
                action="READ",
                status="FAILURE",
                tenant_id=self.tenant_id,
                resource_type=rtype,
                error_message=error_msg,
            )

        audit_service.log(
            product="ZIA",
            operation="import_config",
            action="READ",
            status=final_status,
            tenant_id=self.tenant_id,
            resource_type="sync_log",
            resource_id=str(sync_id),
            details={
                "resources_synced": synced,
                "resources_updated": updated,
                "resources_deleted": deleted,
                "errors": errors or None,
            },
        )

        with get_session() as session:
            return session.get(SyncLog, sync_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_disabled_resource_types(self) -> list:
        with get_session() as session:
            tenant = session.get(TenantConfig, self.tenant_id)
            return list(tenant.zia_disabled_resources or []) if tenant else []

    def _disable_resource_type(self, resource_type: str) -> None:
        with get_session() as session:
            tenant = session.get(TenantConfig, self.tenant_id)
            if tenant:
                disabled = list(tenant.zia_disabled_resources or [])
                if resource_type not in disabled:
                    disabled.append(resource_type)
                    tenant.zia_disabled_resources = disabled

    def clear_disabled_resource_types(self) -> None:
        with get_session() as session:
            tenant = session.get(TenantConfig, self.tenant_id)
            if tenant:
                tenant.zia_disabled_resources = []

    def _fetch(self, defn: ResourceDef) -> list:
        method = getattr(self.client, defn.list_method)
        result = method(**defn.list_args) if defn.list_args else method()
        return result or []

    def _upsert(self, defn: ResourceDef, records: list, run_start: datetime):
        synced = updated = 0
        pending_audit: list = []

        with get_session() as session:
            for record in records:
                if not isinstance(record, dict):
                    continue
                zia_id = str(record.get(defn.id_field, ""))
                if not zia_id:
                    continue

                new_hash = _hash(record)
                name = record.get(defn.name_field) or ""

                existing = (
                    session.query(ZIAResource)
                    .filter_by(
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        zia_id=zia_id,
                    )
                    .first()
                )

                if existing is None:
                    session.add(ZIAResource(
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        zia_id=zia_id,
                        name=name,
                        raw_config=record,
                        config_hash=new_hash,
                        synced_at=run_start,
                        is_deleted=False,
                    ))
                    pending_audit.append(dict(
                        action="CREATE", resource_type=defn.resource_type,
                        resource_id=zia_id, resource_name=name,
                    ))
                    synced += 1
                else:
                    existing.synced_at = run_start
                    existing.is_deleted = False
                    if existing.config_hash != new_hash:
                        existing.name = name
                        existing.raw_config = record
                        existing.config_hash = new_hash
                        pending_audit.append(dict(
                            action="UPDATE", resource_type=defn.resource_type,
                            resource_id=zia_id, resource_name=name,
                        ))
                        updated += 1
                    synced += 1

        for evt in pending_audit:
            audit_service.log(
                product="ZIA",
                operation="import_config",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                **evt,
            )

        return synced, updated

    def _mark_deleted(self, resource_types: Optional[List[str]], run_start: datetime) -> int:
        deleted = 0
        type_filter = resource_types or [d.resource_type for d in RESOURCE_DEFINITIONS]
        pending_audit: list = []

        with get_session() as session:
            stale = (
                session.query(ZIAResource)
                .filter(
                    ZIAResource.tenant_id == self.tenant_id,
                    ZIAResource.resource_type.in_(type_filter),
                    ZIAResource.is_deleted == False,
                    ZIAResource.synced_at < run_start,
                )
                .all()
            )
            for row in stale:
                row.is_deleted = True
                pending_audit.append(dict(
                    resource_type=row.resource_type,
                    resource_id=row.zia_id,
                    resource_name=row.name,
                ))
                deleted += 1

        for evt in pending_audit:
            audit_service.log(
                product="ZIA",
                operation="import_config",
                action="DELETE",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                **evt,
            )

        return deleted
