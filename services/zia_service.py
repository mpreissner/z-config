"""ZIA business logic layer.

Wraps ZIAClient with audit logging and higher-level workflows.

Read operations serve from the local `zia_resources` DB table for speed.
Write operations go to the ZIA API; on success, the affected resource type
is reimported from the API into the DB so the local cache stays current.

IMPORTANT: ZIA requires explicit activation after config changes.
Use the auto_activate=True parameter (default) to activate automatically,
or call activate() manually when batching multiple changes.
"""

from typing import Dict, List, Optional

from lib.zia_client import ZIAClient
from services import audit_service


class ZIAService:
    def __init__(self, client: ZIAClient, tenant_id: Optional[int] = None):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _list_from_db(self, resource_type: str) -> List[Dict]:
        """Return raw_config dicts for live resources of the given type."""
        if not self.tenant_id:
            return []
        from db.database import get_session
        from db.models import ZIAResource
        from sqlalchemy import select
        with get_session() as session:
            rows = session.execute(
                select(ZIAResource).where(
                    ZIAResource.tenant_id == self.tenant_id,
                    ZIAResource.resource_type == resource_type,
                    ZIAResource.is_deleted == False,
                    ZIAResource.candidate_status == None,
                )
            ).scalars().all()
            return [row.raw_config for row in rows]

    def _get_from_db(self, resource_type: str, zia_id: str) -> Optional[Dict]:
        """Return raw_config for a single live resource, or None."""
        if not self.tenant_id:
            return None
        from db.database import get_session
        from db.models import ZIAResource
        from sqlalchemy import select
        with get_session() as session:
            row = session.execute(
                select(ZIAResource).where(
                    ZIAResource.tenant_id == self.tenant_id,
                    ZIAResource.resource_type == resource_type,
                    ZIAResource.zia_id == str(zia_id),
                    ZIAResource.is_deleted == False,
                )
            ).scalar_one_or_none()
            return row.raw_config if row else None

    def _reimport(self, resource_types: List[str]) -> None:
        """Partial reimport — fetch only the listed resource types from ZIA API and upsert into DB."""
        if not self.tenant_id:
            return
        from services.zia_import_service import ZIAImportService
        try:
            svc = ZIAImportService(self.client, self.tenant_id)
            svc.run(resource_types=resource_types)
        except Exception:
            pass  # best-effort; don't let reimport failure mask the successful mutation

    def _upsert_one(self, resource_type: str, zia_id: str, record: dict, name_field: str = "name") -> None:
        """Write a single resource record into the DB without fetching the full list."""
        if not self.tenant_id or not record:
            return
        import hashlib, json
        from db.database import get_session
        from db.models import ZIAResource
        from datetime import datetime

        def _hash(obj):
            return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

        new_hash = _hash(record)
        name = record.get(name_field) or ""
        now = datetime.utcnow()
        try:
            with get_session() as session:
                existing = (
                    session.query(ZIAResource)
                    .filter_by(tenant_id=self.tenant_id, resource_type=resource_type, zia_id=str(zia_id))
                    .first()
                )
                if existing is None:
                    session.add(ZIAResource(
                        tenant_id=self.tenant_id,
                        resource_type=resource_type,
                        zia_id=str(zia_id),
                        name=name,
                        raw_config=record,
                        config_hash=new_hash,
                        synced_at=now,
                        is_deleted=False,
                    ))
                else:
                    existing.name = name
                    existing.raw_config = record
                    existing.config_hash = new_hash
                    existing.synced_at = now
                    existing.is_deleted = False
        except Exception:
            pass  # best-effort

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def get_activation_status(self) -> Dict:
        result = self.client.get_activation_status()
        audit_service.log(
            product="ZIA", operation="get_activation_status", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="configuration",
            details={"status": result.get("status")},
        )
        return result

    def activate(self) -> Dict:
        """Commit all pending ZIA configuration changes."""
        result = self.client.activate()
        audit_service.log(
            product="ZIA",
            operation="activate",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="configuration",
            details=result,
        )
        return result

    # ------------------------------------------------------------------
    # URL Categories
    # ------------------------------------------------------------------

    def list_url_categories(self) -> List[Dict]:
        rows = self._list_from_db("url_category")
        if rows:
            for cat in rows:
                # Normalize snake_case DB field to camelCase for frontend consumers
                if cat.get("configured_name") and not cat.get("configuredName"):
                    cat["configuredName"] = cat["configured_name"]
                if not cat.get("name") and cat.get("configured_name"):
                    cat["name"] = cat["configured_name"]
            audit_service.log(
                product="ZIA", operation="list_url_categories", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="url_category",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        # Fallback to API if DB is empty (e.g. first run before import)
        result = self.client.list_url_categories_lite()
        for cat in result:
            if not cat.get("name") and cat.get("configuredName"):
                cat["name"] = cat["configuredName"]
        audit_service.log(
            product="ZIA", operation="list_url_categories", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_category",
            details={"count": len(result), "source": "api"},
        )
        return result

    def add_urls_to_category(self, category_id: str, urls: List[str]) -> Dict:
        result = self.client.add_urls_to_category(category_id, urls)
        audit_service.log(
            product="ZIA", operation="add_urls_to_category", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_category",
            resource_id=category_id, details={"urls_added": urls},
        )
        self.activate()
        self._upsert_one("url_category", category_id, result, name_field="configured_name")
        return result

    def remove_urls_from_category(self, category_id: str, urls: List[str]) -> Dict:
        result = self.client.remove_urls_from_category(category_id, urls)
        audit_service.log(
            product="ZIA", operation="remove_urls_from_category", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_category",
            resource_id=category_id, details={"urls_removed": urls},
        )
        self.activate()
        self._upsert_one("url_category", category_id, result, name_field="configured_name")
        return result

    def get_url_category(self, category_id: str) -> Dict:
        db_row = self._get_from_db("url_category", category_id)
        if db_row:
            audit_service.log(
                product="ZIA", operation="get_url_category", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="url_category",
                resource_id=category_id, resource_name=db_row.get("configured_name") or db_row.get("name"),
            )
            return db_row
        result = self.client.get_url_category(category_id)
        audit_service.log(
            product="ZIA", operation="get_url_category", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_category",
            resource_id=category_id, resource_name=result.get("name"),
        )
        return result

    def create_url_category(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_url_category(config)
        audit_service.log(
            product="ZIA",
            operation="create_url_category",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_category",
            resource_id=result.get("id"),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._reimport(["url_category"])
        return result

    def update_url_category(self, category_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.update_url_category(category_id, config)
        audit_service.log(
            product="ZIA",
            operation="update_url_category",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_category",
            resource_id=category_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        self._reimport(["url_category"])
        return result

    def url_lookup(self, urls: List[str]) -> List[Dict]:
        """Look up the category classifications for a list of URLs."""
        result = self.client.url_lookup(urls)
        audit_service.log(
            product="ZIA", operation="url_lookup", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url",
            details={"urls": urls},
        )
        return result

    # ------------------------------------------------------------------
    # URL Filtering Rules
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        rows = self._list_from_db("url_filtering_rule")
        if rows:
            rows.sort(key=lambda r: r.get("order") or 0)
            audit_service.log(
                product="ZIA", operation="list_url_filtering_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="url_filtering_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_url_filtering_rules()
        audit_service.log(
            product="ZIA", operation="list_url_filtering_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_filtering_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def update_url_filtering_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        self.client.update_url_filtering_rule(rule_id, config)
        audit_service.log(
            product="ZIA",
            operation="update_url_filtering_rule",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_filtering_rule",
            resource_id=rule_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        # Fetch the updated rule from the API and upsert just this one row
        updated = self.client.get_url_filtering_rule(rule_id)
        self._upsert_one("url_filtering_rule", rule_id, updated)
        return updated

    def delete_url_filtering_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None:
        self.client.delete_url_filtering_rule(rule_id)
        audit_service.log(
            product="ZIA",
            operation="delete_url_filtering_rule",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_filtering_rule",
            resource_id=rule_id,
            resource_name=rule_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["url_filtering_rule"])

    def create_url_filtering_rule(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_url_filtering_rule(config)
        audit_service.log(
            product="ZIA",
            operation="create_url_filtering_rule",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_filtering_rule",
            resource_id=result.get("id"),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._reimport(["url_filtering_rule"])
        return result

    # ------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------

    def get_user(self, user_id: str) -> Dict:
        result = self.client.get_user(user_id)
        audit_service.log(
            product="ZIA", operation="get_user", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="user",
            resource_id=user_id, resource_name=result.get("name"),
        )
        return result

    def create_user(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_user(config)
        audit_service.log(
            product="ZIA",
            operation="create_user",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            resource_id=str(result.get("id", "")),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._reimport(["user"])
        return result

    def update_user(self, user_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.update_user(user_id, config)
        audit_service.log(
            product="ZIA",
            operation="update_user",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            resource_id=user_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        self._reimport(["user"])
        return result

    def delete_user(self, user_id: str, auto_activate: bool = True) -> None:
        self.client.delete_user(user_id)
        audit_service.log(
            product="ZIA",
            operation="delete_user",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="user",
            resource_id=user_id,
        )
        if auto_activate:
            self.activate()
        self._reimport(["user"])

    def list_users(self, name: Optional[str] = None) -> List[Dict]:
        rows = self._list_from_db("user")
        if rows:
            if name:
                name_lower = name.lower()
                rows = [r for r in rows if name_lower in (r.get("name") or "").lower()]
            audit_service.log(
                product="ZIA", operation="list_users", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="user",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_users(name=name)
        audit_service.log(
            product="ZIA", operation="list_users", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="user",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_departments(self) -> List[Dict]:
        rows = self._list_from_db("department")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_departments", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="department",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_departments()
        audit_service.log(
            product="ZIA", operation="list_departments", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="department",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_groups(self) -> List[Dict]:
        rows = self._list_from_db("group")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_groups", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="group",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_groups()
        audit_service.log(
            product="ZIA", operation="list_groups", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="group",
            details={"count": len(result), "source": "api"},
        )
        return result

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    def list_locations(self) -> List[Dict]:
        rows = self._list_from_db("location_lite")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_locations", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="location_lite",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_locations_lite()
        audit_service.log(
            product="ZIA", operation="list_locations", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="location",
            details={"count": len(result), "source": "api"},
        )
        return result

    def get_location(self, location_id: str) -> Dict:
        result = self.client.get_location(location_id)
        audit_service.log(
            product="ZIA", operation="get_location", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="location",
            resource_id=location_id, resource_name=result.get("name"),
        )
        return result

    # ------------------------------------------------------------------
    # Security Policy
    # ------------------------------------------------------------------

    def get_allowlist(self) -> Dict:
        result = self.client.get_allowlist()
        audit_service.log(
            product="ZIA", operation="get_allowlist", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="allowlist",
        )
        return result

    def get_denylist(self) -> Dict:
        result = self.client.get_denylist()
        audit_service.log(
            product="ZIA", operation="get_denylist", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="denylist",
        )
        return result

    def update_allowlist(self, urls: List[str]) -> Dict:
        result = self.client.update_allowlist(urls)
        audit_service.log(
            product="ZIA",
            operation="update_allowlist",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="allowlist",
            details={"url_count": len(urls)},
        )
        return result

    def update_denylist(self, urls: List[str]) -> Dict:
        result = self.client.update_denylist(urls)
        audit_service.log(
            product="ZIA",
            operation="update_denylist",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="denylist",
            details={"url_count": len(urls)},
        )
        return result

    # ------------------------------------------------------------------
    # Firewall Policy
    # ------------------------------------------------------------------

    def list_firewall_rules(self) -> List[Dict]:
        rows = self._list_from_db("firewall_rule")
        if rows:
            rows.sort(key=lambda r: r.get("order") or 0)
            audit_service.log(
                product="ZIA", operation="list_firewall_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="firewall_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_firewall_rules()
        audit_service.log(
            product="ZIA", operation="list_firewall_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def toggle_firewall_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_firewall_rule(rule_id)
        rule["state"] = state
        self.client.update_firewall_rule(rule_id, rule)
        audit_service.log(
            product="ZIA", operation="toggle_firewall_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_rule",
            resource_id=rule_id, details={"state": state},
        )
        self._upsert_one("firewall_rule", rule_id, rule)
        return rule

    # ------------------------------------------------------------------
    # SSL Inspection
    # ------------------------------------------------------------------

    def list_ssl_inspection_rules(self) -> List[Dict]:
        rows = self._list_from_db("ssl_inspection_rule")
        if rows:
            rows.sort(key=lambda r: r.get("order") or 0)
            audit_service.log(
                product="ZIA", operation="list_ssl_inspection_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_ssl_inspection_rules()
        audit_service.log(
            product="ZIA", operation="list_ssl_inspection_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def toggle_ssl_inspection_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_ssl_inspection_rule(rule_id)
        rule["state"] = state
        self.client.update_ssl_inspection_rule(rule_id, rule)
        audit_service.log(
            product="ZIA", operation="toggle_ssl_inspection_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
            resource_id=rule_id, details={"state": state},
        )
        self._upsert_one("ssl_inspection_rule", rule_id, rule)
        return rule

    # ------------------------------------------------------------------
    # Traffic Forwarding
    # ------------------------------------------------------------------

    def list_forwarding_rules(self) -> List[Dict]:
        rows = self._list_from_db("forwarding_rule")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_forwarding_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="forwarding_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_forwarding_rules()
        audit_service.log(
            product="ZIA", operation="list_forwarding_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="forwarding_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    # ------------------------------------------------------------------
    # DLP
    # ------------------------------------------------------------------

    def list_dlp_engines(self) -> List[Dict]:
        rows = self._list_from_db("dlp_engine")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_dlp_engines", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_engine",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_dlp_engines()
        audit_service.log(
            product="ZIA", operation="list_dlp_engines", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_engine",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_dlp_dictionaries(self) -> List[Dict]:
        rows = self._list_from_db("dlp_dictionary")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_dlp_dictionaries", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_dictionary",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_dlp_dictionaries()
        audit_service.log(
            product="ZIA", operation="list_dlp_dictionaries", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_dictionary",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_dlp_web_rules(self) -> List[Dict]:
        rows = self._list_from_db("dlp_web_rule")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_dlp_web_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_web_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_dlp_web_rules()
        audit_service.log(
            product="ZIA", operation="list_dlp_web_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_web_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    # ------------------------------------------------------------------
    # Cloud App Controls
    # ------------------------------------------------------------------

    def list_cloud_app_settings(self) -> List[Dict]:
        result = self.client.list_url_filter_cloud_app_settings()
        audit_service.log(
            product="ZIA", operation="list_cloud_app_settings", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="cloud_app_setting",
            details={"count": len(result)},
        )
        return result
