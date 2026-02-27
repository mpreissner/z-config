"""ZPA config import service.

Pulls the current configuration from ZPA via the API and stores each resource
as a ZPAResource row.  Unchanged resources (same config_hash) are skipped so
re-runs are fast.  A SyncLog row records the outcome of every run.

Usage:
    service = ZPAImportService(client, tenant_id=tenant.id)

    # With a progress callback (receives (resource_type, count, total_types)):
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
from db.models import SyncLog, TenantConfig, ZPAResource
from services import audit_service


@dataclass
class ResourceDef:
    """Describes one ZPA resource type to import."""
    resource_type: str          # key stored in zpa_resources.resource_type
    list_method: str            # name of ZPAClient method that returns a list
    id_field: str = "id"        # JSON field containing the ZPA resource ID
    name_field: str = "name"    # JSON field containing a human-readable name
    list_args: dict = field(default_factory=dict)  # extra kwargs for list_method


# All resource types we import.  Order doesn't matter.
RESOURCE_DEFINITIONS: List[ResourceDef] = [
    ResourceDef("application",          "list_applications"),
    ResourceDef("segment_group",        "list_segment_groups"),
    ResourceDef("server_group",         "list_server_groups"),
    ResourceDef("app_connector_group",  "list_connector_groups"),
    ResourceDef("app_connector",        "list_connectors"),
    ResourceDef("pra_portal",           "list_pra_portals"),
    ResourceDef("pra_credential",       "list_credentials"),
    ResourceDef("idp",                  "list_idp"),
    ResourceDef("saml_attribute",       "list_saml_attributes"),
    ResourceDef("scim_group",           "_scim_groups_all"),  # handled specially in _fetch
    ResourceDef("microtenant",          "list_microtenants"),
    ResourceDef("enrollment_cert",      "list_enrollment_certificates"),
    ResourceDef("policy_access",        "list_policy_rules", list_args={"policy_type": "access"}),
    ResourceDef("policy_timeout",       "list_policy_rules", list_args={"policy_type": "timeout"}),
    ResourceDef("policy_forwarding",    "list_policy_rules", list_args={"policy_type": "client_forwarding"}),
    ResourceDef("policy_inspection",    "list_policy_rules", list_args={"policy_type": "inspection"}),
    ResourceDef("policy_isolation",     "list_policy_rules", list_args={"policy_type": "isolation"}),
    ResourceDef("certificate",          "list_certificates"),
    ResourceDef("pra_console",          "list_pra_consoles"),
    ResourceDef("service_edge_group",   "list_service_edge_groups"),
    ResourceDef("service_edge",         "list_service_edges"),
    ResourceDef("server",               "list_servers"),
    ResourceDef("machine_group",        "list_machine_groups"),
    ResourceDef("trusted_network",      "list_trusted_networks"),
    ResourceDef("lss_config",           "list_lss_configs"),
]


def _hash(obj) -> str:
    """Return SHA-256 hex digest of a JSON-serialised object."""
    raw = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class ZPAImportService:
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
        """Import ZPA config into the database.

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

        # Resource types previously auto-disabled due to 401 — skip without calling API
        disabled_types = set(self._get_disabled_resource_types())

        with get_session() as session:
            sync = SyncLog(
                tenant_id=self.tenant_id,
                product="ZPA",
                status="RUNNING",
            )
            session.add(sync)
            session.flush()
            sync_id = sync.id

        # Capture run start once so _upsert and _mark_deleted use the same
        # timestamp — rows written this run get synced_at == run_start, and
        # _mark_deleted looks for synced_at < run_start to find stale rows.
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
                if "401" in str(exc):
                    self._disable_resource_type(defn.resource_type)
                    disabled_types.add(defn.resource_type)
                    newly_disabled.append(defn.resource_type)
                    audit_service.log(
                        product="ZPA",
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

        # Mark any resource no longer returned by the API as deleted
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

        # Write a FAILURE entry for each resource type that errored
        for error_msg in errors:
            # error format is "resource_type: exception message"
            rtype = error_msg.split(":", 1)[0].strip()
            audit_service.log(
                product="ZPA",
                operation="import_config",
                action="READ",
                status="FAILURE",
                tenant_id=self.tenant_id,
                resource_type=rtype,
                error_message=error_msg,
            )

        audit_service.log(
            product="ZPA",
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

        # Return a detached copy
        with get_session() as session:
            return session.get(SyncLog, sync_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_disabled_resource_types(self) -> list:
        with get_session() as session:
            tenant = session.get(TenantConfig, self.tenant_id)
            return list(tenant.zpa_disabled_resources or []) if tenant else []

    def _disable_resource_type(self, resource_type: str) -> None:
        with get_session() as session:
            tenant = session.get(TenantConfig, self.tenant_id)
            if tenant:
                disabled = list(tenant.zpa_disabled_resources or [])
                if resource_type not in disabled:
                    disabled.append(resource_type)
                    tenant.zpa_disabled_resources = disabled

    def clear_disabled_resource_types(self) -> None:
        with get_session() as session:
            tenant = session.get(TenantConfig, self.tenant_id)
            if tenant:
                tenant.zpa_disabled_resources = []

    def _fetch(self, defn: ResourceDef) -> list:
        """Call the appropriate ZPAClient list method."""
        if defn.list_method == "_scim_groups_all":
            return self._fetch_scim_groups_all()
        method = getattr(self.client, defn.list_method)
        result = method(**defn.list_args) if defn.list_args else method()
        return result or []

    def _fetch_scim_groups_all(self) -> list:
        """Fetch SCIM groups across all IdPs."""
        idps = self.client.list_idp()
        groups = []
        for idp in idps:
            idp_id = str(idp.get("id", ""))
            if not idp_id:
                continue
            try:
                groups.extend(self.client.list_scim_groups(idp_id) or [])
            except Exception:
                pass
        return groups

    def _upsert(self, defn: ResourceDef, records: list, run_start: datetime):
        """Insert or update ZPAResource rows for the fetched records.

        Returns (synced_count, updated_count, pending_audit_events).
        Audit events are returned rather than written inline so the caller can
        write them AFTER the session closes — writing inside the session would
        create a nested session that blocks on the SQLite write lock.
        """
        synced = updated = 0
        pending_audit: list = []

        with get_session() as session:
            for record in records:
                if not isinstance(record, dict):
                    continue
                zpa_id = str(record.get(defn.id_field, ""))
                if not zpa_id:
                    continue

                new_hash = _hash(record)
                name = record.get(defn.name_field) or ""

                existing = (
                    session.query(ZPAResource)
                    .filter_by(
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        zpa_id=zpa_id,
                    )
                    .first()
                )

                if existing is None:
                    session.add(ZPAResource(
                        tenant_id=self.tenant_id,
                        resource_type=defn.resource_type,
                        zpa_id=zpa_id,
                        name=name,
                        raw_config=record,
                        config_hash=new_hash,
                        synced_at=run_start,
                        is_deleted=False,
                    ))
                    pending_audit.append(dict(
                        action="CREATE", resource_type=defn.resource_type,
                        resource_id=zpa_id, resource_name=name,
                    ))
                    synced += 1
                else:
                    # Always update synced_at; only update data when changed
                    existing.synced_at = run_start
                    existing.is_deleted = False
                    if existing.config_hash != new_hash:
                        existing.name = name
                        existing.raw_config = record
                        existing.config_hash = new_hash
                        pending_audit.append(dict(
                            action="UPDATE", resource_type=defn.resource_type,
                            resource_id=zpa_id, resource_name=name,
                        ))
                        updated += 1
                    synced += 1

        # Session is closed — safe to write audit events now
        for evt in pending_audit:
            audit_service.log(
                product="ZPA",
                operation="import_config",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                **evt,
            )

        return synced, updated

    def _mark_deleted(self, resource_types: Optional[List[str]], run_start: datetime) -> int:
        """Mark rows not touched in this sync run as deleted.

        Rows written during this run have synced_at == run_start.  Any row
        with synced_at < run_start was not returned by the API this time.
        """
        deleted = 0
        type_filter = resource_types or [d.resource_type for d in RESOURCE_DEFINITIONS]
        pending_audit: list = []

        with get_session() as session:
            stale = (
                session.query(ZPAResource)
                .filter(
                    ZPAResource.tenant_id == self.tenant_id,
                    ZPAResource.resource_type.in_(type_filter),
                    ZPAResource.is_deleted == False,
                    ZPAResource.synced_at < run_start,
                )
                .all()
            )
            for row in stale:
                row.is_deleted = True
                pending_audit.append(dict(
                    resource_type=row.resource_type,
                    resource_id=row.zpa_id,
                    resource_name=row.name,
                ))
                deleted += 1

        # Session is closed — safe to write audit events now
        for evt in pending_audit:
            audit_service.log(
                product="ZPA",
                operation="import_config",
                action="DELETE",
                status="SUCCESS",
                tenant_id=self.tenant_id,
                **evt,
            )

        return deleted
