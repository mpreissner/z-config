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


def _rule_order_key(n):
    """Positive integers ascending first, then negative integers descending.
    e.g. 1, 2, 3, ..., -1, -2, -3, ...
    """
    return (0, n) if n >= 0 else (1, -n)


def _normalize_ssl_rules(rules: List[Dict]) -> None:
    """Flatten the action field in-place: {type: "INSPECT"} → "INSPECT"."""
    for r in rules:
        action = r.get("action")
        if isinstance(action, dict):
            r["action"] = action.get("type") or action.get("name") or str(action)


_CAMEL_RO_FIELDS = frozenset({
    "lastModifiedTime", "lastModifiedBy", "createdBy", "creationTime",
    "accessControl", "predefined", "defaultRule", "defaultDnsRuleNameUsed",
})

_SNAKE_RO_FIELDS = frozenset({
    "last_modified_time", "last_modified_by", "created_by", "creation_time",
    "access_control", "predefined", "default_rule",
})


def _prepare_rule_for_update(config: Dict) -> Dict:
    """Strip read-only and empty-collection fields before a PUT to the ZIA API.

    Zscaler rejects: (a) server-set read-only fields (both camelCase from direct
    API and snake_case from the SDK), (b) empty arrays, (c) ZPA segment objects
    with extra extension fields.
    """
    out = {
        k: v for k, v in config.items()
        if k not in _CAMEL_RO_FIELDS
        and k not in _SNAKE_RO_FIELDS
        and v is not None
        and not (isinstance(v, list) and len(v) == 0)
    }
    # ZPA app segment refs: keep {id, name, external_id} — extensions cause rejection
    for field in ("zpa_app_segments", "zpa_application_segments", "zpa_application_segment_groups"):
        if field in out and isinstance(out[field], list):
            reduced = [
                {k2: v2 for k2, v2 in seg.items() if k2 in ("id", "name", "external_id")}
                for seg in out[field]
                if isinstance(seg, dict) and "id" in seg
            ]
            if reduced:
                out[field] = reduced
            else:
                del out[field]
    if "zpa_gateway" in out and isinstance(out["zpa_gateway"], dict):
        gw = out["zpa_gateway"]
        if gw.get("id"):
            out["zpa_gateway"] = {k2: v2 for k2, v2 in gw.items() if k2 in ("id", "name")}
        else:
            del out["zpa_gateway"]
    return out


# Forwarding rule list-ref fields that take [{id, name}] stubs (no extensions).
_FORWARDING_REF_FIELDS = frozenset({
    "locations", "location_groups", "groups", "departments", "users",
    "devices", "device_groups", "nw_services", "nw_service_groups",
    "nw_applications", "nw_application_groups", "src_ip_groups", "src_ipv6_groups",
    "dest_ip_groups", "dest_ipv6_groups", "ec_groups", "time_windows", "labels",
})


def _prepare_forwarding_rule_for_update(config: Dict) -> Dict:
    """Normalise a forwarding rule payload for PUT.

    Verified empirically against the ZIA API:
    - Strip snake_case read-only fields and empty arrays.
    - zpa_app_segments: keep {id, name, external_id}, drop extensions.
    - zpa_gateway: keep {id, name}, drop extensions/external_id.
    - Other ref-list fields: reduce to [{id, name}] stubs.
    """
    out = {
        k: v for k, v in config.items()
        if k not in _SNAKE_RO_FIELDS
        and k not in _CAMEL_RO_FIELDS
        and v is not None
        and not (isinstance(v, list) and len(v) == 0)
    }

    # zpa_app_segments: {id, name, external_id} — extensions causes rejection
    if "zpa_app_segments" in out and isinstance(out["zpa_app_segments"], list):
        out["zpa_app_segments"] = [
            {k2: v2 for k2, v2 in seg.items() if k2 in ("id", "name", "external_id")}
            for seg in out["zpa_app_segments"]
            if isinstance(seg, dict) and "id" in seg
        ]

    # zpa_application_segments / zpa_application_segment_groups: same shape
    for field in ("zpa_application_segments", "zpa_application_segment_groups"):
        if field in out and isinstance(out[field], list):
            out[field] = [
                {k2: v2 for k2, v2 in seg.items() if k2 in ("id", "name", "external_id")}
                for seg in out[field]
                if isinstance(seg, dict) and "id" in seg
            ]
            if not out[field]:
                del out[field]

    # zpa_gateway: {id, name} only
    if out.get("zpa_gateway") and isinstance(out["zpa_gateway"], dict):
        gw = out["zpa_gateway"]
        if gw.get("id"):
            out["zpa_gateway"] = {k2: v2 for k2, v2 in gw.items() if k2 in ("id", "name")}
        else:
            del out["zpa_gateway"]

    # Standard ref-list fields: [{id, name}]
    for field in _FORWARDING_REF_FIELDS:
        if field in out and isinstance(out[field], list):
            reduced = [
                {k2: v2 for k2, v2 in item.items() if k2 in ("id", "name")}
                for item in out[field]
                if isinstance(item, dict) and "id" in item
            ]
            if reduced:
                out[field] = reduced
            else:
                del out[field]

    return out


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

    def delete_url_category(self, category_id: str, category_name: str = "", auto_activate: bool = True) -> None:
        self.client.delete_url_category(category_id)
        audit_service.log(
            product="ZIA",
            operation="delete_url_category",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="url_category",
            resource_id=category_id,
            resource_name=category_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["url_category"])

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
        rows = self._list_from_db("allowlist")
        if rows:
            return rows[0]
        result = self.client.get_allowlist()
        audit_service.log(
            product="ZIA", operation="get_allowlist", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="allowlist",
        )
        return result

    def get_denylist(self) -> Dict:
        rows = self._list_from_db("denylist")
        if rows:
            return rows[0]
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
            rows.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
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

    def get_firewall_rule(self, rule_id: str) -> Dict:
        db_row = self._get_from_db("firewall_rule", rule_id)
        if db_row:
            audit_service.log(
                product="ZIA", operation="get_firewall_rule", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="firewall_rule",
                resource_id=rule_id, resource_name=db_row.get("name"),
            )
            return db_row
        result = self.client.get_firewall_rule(rule_id)
        audit_service.log(
            product="ZIA", operation="get_firewall_rule", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_rule",
            resource_id=rule_id, resource_name=result.get("name"),
        )
        return result

    def create_firewall_rule(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_firewall_rule(config)
        audit_service.log(
            product="ZIA",
            operation="create_firewall_rule",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="firewall_rule",
            resource_id=str(result.get("id", "")),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("firewall_rule", str(result.get("id", "")), result)
        return result

    def update_firewall_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        cleaned = _prepare_rule_for_update(config)
        self.client.update_firewall_rule(rule_id, cleaned)
        audit_service.log(
            product="ZIA",
            operation="update_firewall_rule",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="firewall_rule",
            resource_id=rule_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        updated = self.client.get_firewall_rule(rule_id)
        self._upsert_one("firewall_rule", rule_id, updated)
        return updated

    def delete_firewall_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None:
        self.client.delete_firewall_rule(rule_id)
        audit_service.log(
            product="ZIA",
            operation="delete_firewall_rule",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="firewall_rule",
            resource_id=rule_id,
            resource_name=rule_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["firewall_rule"])

    def toggle_firewall_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_firewall_rule(rule_id)
        rule["state"] = state
        self.client.update_firewall_rule(rule_id, _prepare_rule_for_update(rule))
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
            rows.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
            _normalize_ssl_rules(rows)
            audit_service.log(
                product="ZIA", operation="list_ssl_inspection_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_ssl_inspection_rules()
        result.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
        _normalize_ssl_rules(result)
        audit_service.log(
            product="ZIA", operation="list_ssl_inspection_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def get_ssl_inspection_rule(self, rule_id: str) -> Dict:
        db_row = self._get_from_db("ssl_inspection_rule", rule_id)
        if db_row:
            _normalize_ssl_rules([db_row])
            audit_service.log(
                product="ZIA", operation="get_ssl_inspection_rule", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
                resource_id=rule_id, resource_name=db_row.get("name"),
            )
            return db_row
        result = self.client.get_ssl_inspection_rule(rule_id)
        _normalize_ssl_rules([result])
        audit_service.log(
            product="ZIA", operation="get_ssl_inspection_rule", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="ssl_inspection_rule",
            resource_id=rule_id, resource_name=result.get("name"),
        )
        return result

    def create_ssl_inspection_rule(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_ssl_inspection_rule(config)
        _normalize_ssl_rules([result])
        audit_service.log(
            product="ZIA",
            operation="create_ssl_inspection_rule",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="ssl_inspection_rule",
            resource_id=str(result.get("id", "")),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("ssl_inspection_rule", str(result.get("id", "")), result)
        return result

    def update_ssl_inspection_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        cleaned = _prepare_rule_for_update(config)
        self.client.update_ssl_inspection_rule(rule_id, cleaned)
        audit_service.log(
            product="ZIA",
            operation="update_ssl_inspection_rule",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="ssl_inspection_rule",
            resource_id=rule_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        updated = self.client.get_ssl_inspection_rule(rule_id)
        _normalize_ssl_rules([updated])
        self._upsert_one("ssl_inspection_rule", rule_id, updated)
        return updated

    def delete_ssl_inspection_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None:
        self.client.delete_ssl_inspection_rule(rule_id)
        audit_service.log(
            product="ZIA",
            operation="delete_ssl_inspection_rule",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="ssl_inspection_rule",
            resource_id=rule_id,
            resource_name=rule_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["ssl_inspection_rule"])

    def toggle_ssl_inspection_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_ssl_inspection_rule(rule_id)
        rule["state"] = state
        self.client.update_ssl_inspection_rule(rule_id, _prepare_rule_for_update(rule))
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
            rows.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
            audit_service.log(
                product="ZIA", operation="list_forwarding_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="forwarding_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_forwarding_rules()
        result.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
        audit_service.log(
            product="ZIA", operation="list_forwarding_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="forwarding_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def get_forwarding_rule(self, rule_id: str) -> Dict:
        db_row = self._get_from_db("forwarding_rule", rule_id)
        if db_row:
            audit_service.log(
                product="ZIA", operation="get_forwarding_rule", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="forwarding_rule",
                resource_id=rule_id, resource_name=db_row.get("name"),
            )
            return db_row
        result = self.client.get_forwarding_rule(rule_id)
        audit_service.log(
            product="ZIA", operation="get_forwarding_rule", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="forwarding_rule",
            resource_id=rule_id, resource_name=result.get("name"),
        )
        return result

    def create_forwarding_rule(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_forwarding_rule(config)
        audit_service.log(
            product="ZIA",
            operation="create_forwarding_rule",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="forwarding_rule",
            resource_id=str(result.get("id", "")),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("forwarding_rule", str(result.get("id", "")), result)
        return result

    def update_forwarding_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        cleaned = _prepare_forwarding_rule_for_update(config)
        result = self.client.update_forwarding_rule(rule_id, cleaned)
        audit_service.log(
            product="ZIA",
            operation="update_forwarding_rule",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="forwarding_rule",
            resource_id=rule_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("forwarding_rule", rule_id, result)
        return result

    def delete_forwarding_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None:
        self.client.delete_forwarding_rule(rule_id)
        audit_service.log(
            product="ZIA",
            operation="delete_forwarding_rule",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="forwarding_rule",
            resource_id=rule_id,
            resource_name=rule_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["forwarding_rule"])

    def toggle_forwarding_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_forwarding_rule(rule_id)
        rule["state"] = state
        self.client.update_forwarding_rule(rule_id, _prepare_forwarding_rule_for_update(rule))
        audit_service.log(
            product="ZIA", operation="toggle_forwarding_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="forwarding_rule",
            resource_id=rule_id, details={"state": state},
        )
        self._upsert_one("forwarding_rule", rule_id, rule)
        return rule

    # ------------------------------------------------------------------
    # Firewall DNS Filter Rules
    # ------------------------------------------------------------------

    def list_firewall_dns_rules(self) -> List[Dict]:
        rows = self._list_from_db("firewall_dns_rule")
        if rows:
            rows.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
            audit_service.log(
                product="ZIA", operation="list_firewall_dns_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="firewall_dns_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_firewall_dns_rules()
        result.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
        audit_service.log(
            product="ZIA", operation="list_firewall_dns_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_dns_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def toggle_firewall_dns_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_firewall_dns_rule(rule_id)
        rule["state"] = state
        self.client.update_firewall_dns_rule(rule_id, _prepare_rule_for_update(rule))
        audit_service.log(
            product="ZIA", operation="toggle_firewall_dns_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_dns_rule",
            resource_id=rule_id, details={"state": state},
        )
        self._upsert_one("firewall_dns_rule", rule_id, rule)
        return rule

    # ------------------------------------------------------------------
    # Firewall IPS Rules
    # ------------------------------------------------------------------

    def list_firewall_ips_rules(self) -> List[Dict]:
        rows = self._list_from_db("firewall_ips_rule")
        if rows:
            rows.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
            audit_service.log(
                product="ZIA", operation="list_firewall_ips_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="firewall_ips_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_firewall_ips_rules()
        result.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
        audit_service.log(
            product="ZIA", operation="list_firewall_ips_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_ips_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def toggle_firewall_ips_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_firewall_ips_rule(rule_id)
        rule["state"] = state
        self.client.update_firewall_ips_rule(rule_id, _prepare_rule_for_update(rule))
        audit_service.log(
            product="ZIA", operation="toggle_firewall_ips_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="firewall_ips_rule",
            resource_id=rule_id, details={"state": state},
        )
        self._upsert_one("firewall_ips_rule", rule_id, rule)
        return rule

    # ------------------------------------------------------------------
    # DLP
    # ------------------------------------------------------------------

    def get_dlp_engine(self, engine_id: str) -> Dict:
        db_row = self._get_from_db("dlp_engine", engine_id)
        if db_row:
            audit_service.log(
                product="ZIA", operation="get_dlp_engine", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_engine",
                resource_id=engine_id, resource_name=db_row.get("name"),
            )
            return db_row
        result = self.client.get_dlp_engine(engine_id)
        audit_service.log(
            product="ZIA", operation="get_dlp_engine", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_engine",
            resource_id=engine_id, resource_name=result.get("name"),
        )
        return result

    def create_dlp_engine(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_dlp_engine(config)
        audit_service.log(
            product="ZIA",
            operation="create_dlp_engine",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="dlp_engine",
            resource_id=str(result.get("id", "")),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("dlp_engine", str(result.get("id", "")), result)
        return result

    def update_dlp_engine(self, engine_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.update_dlp_engine(engine_id, config)
        audit_service.log(
            product="ZIA",
            operation="update_dlp_engine",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="dlp_engine",
            resource_id=engine_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("dlp_engine", engine_id, result)
        return result

    def delete_dlp_engine(self, engine_id: str, engine_name: str, auto_activate: bool = True) -> None:
        self.client.delete_dlp_engine(engine_id)
        audit_service.log(
            product="ZIA",
            operation="delete_dlp_engine",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="dlp_engine",
            resource_id=engine_id,
            resource_name=engine_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["dlp_engine"])

    def list_dlp_engines(self) -> List[Dict]:
        rows = self._list_from_db("dlp_engine")
        if rows:
            rows.sort(key=lambda r: r.get("id") or 0)
            audit_service.log(
                product="ZIA", operation="list_dlp_engines", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_engine",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_dlp_engines()
        result.sort(key=lambda r: r.get("id") or 0)
        audit_service.log(
            product="ZIA", operation="list_dlp_engines", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_engine",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_dlp_dictionaries(self) -> List[Dict]:
        rows = self._list_from_db("dlp_dictionary")
        if rows:
            rows.sort(key=lambda r: r.get("id") or 0)
            audit_service.log(
                product="ZIA", operation="list_dlp_dictionaries", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_dictionary",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_dlp_dictionaries()
        result.sort(key=lambda r: r.get("id") or 0)
        audit_service.log(
            product="ZIA", operation="list_dlp_dictionaries", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_dictionary",
            details={"count": len(result), "source": "api"},
        )
        return result

    def update_dlp_dictionary_confidence(self, dict_id: str, confidence_threshold: str) -> Dict:
        result = self.client.update_dlp_dictionary_confidence(dict_id, confidence_threshold)
        audit_service.log(
            product="ZIA", operation="update_dlp_dictionary_confidence", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_dictionary",
            resource_id=dict_id, details={"confidence_threshold": confidence_threshold},
        )
        self._upsert_one("dlp_dictionary", dict_id, result)
        return result

    def get_dlp_web_rule(self, rule_id: str) -> Dict:
        db_row = self._get_from_db("dlp_web_rule", rule_id)
        if db_row:
            audit_service.log(
                product="ZIA", operation="get_dlp_web_rule", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_web_rule",
                resource_id=rule_id, resource_name=db_row.get("name"),
            )
            return db_row
        result = self.client.get_dlp_web_rule(rule_id)
        audit_service.log(
            product="ZIA", operation="get_dlp_web_rule", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_web_rule",
            resource_id=rule_id, resource_name=result.get("name"),
        )
        return result

    def create_dlp_web_rule(self, config: Dict, auto_activate: bool = True) -> Dict:
        result = self.client.create_dlp_web_rule(config)
        audit_service.log(
            product="ZIA",
            operation="create_dlp_web_rule",
            action="CREATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="dlp_web_rule",
            resource_id=str(result.get("id", "")),
            resource_name=result.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("dlp_web_rule", str(result.get("id", "")), result)
        return result

    def update_dlp_web_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict:
        cleaned = _prepare_rule_for_update(config)
        result = self.client.update_dlp_web_rule(rule_id, cleaned)
        audit_service.log(
            product="ZIA",
            operation="update_dlp_web_rule",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="dlp_web_rule",
            resource_id=rule_id,
            resource_name=config.get("name"),
        )
        if auto_activate:
            self.activate()
        self._upsert_one("dlp_web_rule", rule_id, result)
        return result

    def delete_dlp_web_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None:
        self.client.delete_dlp_web_rule(rule_id)
        audit_service.log(
            product="ZIA",
            operation="delete_dlp_web_rule",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="dlp_web_rule",
            resource_id=rule_id,
            resource_name=rule_name,
        )
        if auto_activate:
            self.activate()
        self._reimport(["dlp_web_rule"])

    def toggle_dlp_web_rule(self, rule_id: str, state: str) -> Dict:
        rule = self.client.get_dlp_web_rule(rule_id)
        rule["state"] = state
        self.client.update_dlp_web_rule(rule_id, _prepare_rule_for_update(rule))
        audit_service.log(
            product="ZIA", operation="toggle_dlp_web_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="dlp_web_rule",
            resource_id=rule_id, details={"state": state},
        )
        self._upsert_one("dlp_web_rule", rule_id, rule)
        return rule

    def list_dlp_web_rules(self) -> List[Dict]:
        rows = self._list_from_db("dlp_web_rule")
        if rows:
            rows.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
            audit_service.log(
                product="ZIA", operation="list_dlp_web_rules", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="dlp_web_rule",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_dlp_web_rules()
        result.sort(key=lambda r: _rule_order_key(r.get("order") or 0))
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
        rows = self._list_from_db("url_filter_cloud_app_settings")
        if rows:
            audit_service.log(
                product="ZIA", operation="list_cloud_app_settings", action="READ", status="SUCCESS",
                tenant_id=self.tenant_id, resource_type="url_filter_cloud_app_settings",
                details={"count": len(rows), "source": "db"},
            )
            return rows
        result = self.client.list_url_filter_cloud_app_settings()
        audit_service.log(
            product="ZIA", operation="list_cloud_app_settings", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="url_filter_cloud_app_settings",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_cloud_app_policies(self) -> List[Dict]:
        rows = self._list_from_db("cloud_app_policy")
        if rows:
            rows.sort(key=lambda r: (r.get("app_class") or "", r.get("app_name") or ""))
            return rows
        result = self.client.list_cloud_app_policy()
        audit_service.log(
            product="ZIA", operation="list_cloud_app_policies", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="cloud_app_policy",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_cloud_app_control_rules(self) -> List[Dict]:
        rows = self._list_from_db("cloud_app_control_rule")
        if rows:
            rows.sort(key=lambda r: r.get("order") or 0)
            return rows
        result = self.client.list_all_cloud_app_rules()
        audit_service.log(
            product="ZIA", operation="list_cloud_app_control_rules", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="cloud_app_control_rule",
            details={"count": len(result), "source": "api"},
        )
        return result

    def toggle_cloud_app_rule(self, rule_type: str, rule_id: str, state: str) -> Dict:
        rule = self.client.get_cloud_app_rule(rule_type, rule_id)
        rule["state"] = state
        self.client.update_cloud_app_rule(rule_type, rule_id, _prepare_rule_for_update(rule))
        audit_service.log(
            product="ZIA", operation="toggle_cloud_app_rule", action="UPDATE", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="cloud_app_control_rule",
            resource_id=rule_id, details={"state": state, "rule_type": rule_type},
        )
        self._upsert_one("cloud_app_control_rule", rule_id, rule)
        return rule

    def list_tenancy_restriction_profiles(self) -> List[Dict]:
        rows = self._list_from_db("tenancy_restriction_profile")
        if rows:
            return rows
        result = self.client.list_tenancy_restriction_profiles()
        audit_service.log(
            product="ZIA", operation="list_tenancy_restriction_profiles", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="tenancy_restriction_profile",
            details={"count": len(result), "source": "api"},
        )
        return result

    def list_cloud_app_instances(self) -> List[Dict]:
        rows = self._list_from_db("cloud_app_instance")
        if rows:
            rows.sort(key=lambda r: (r.get("instance_type") or "", r.get("instance_name") or ""))
            return rows
        result = self.client.list_cloud_app_instances()
        audit_service.log(
            product="ZIA", operation="list_cloud_app_instances", action="READ", status="SUCCESS",
            tenant_id=self.tenant_id, resource_type="cloud_app_instance",
            details={"count": len(result), "source": "api"},
        )
        return result
