from typing import Dict, List, Optional

from zscaler import ZscalerClient

from .auth import ZscalerAuth


def _unwrap(result, resp, err):
    if err:
        raise RuntimeError(str(err))
    return result


def _to_dicts(items) -> list:
    if not items:
        return []
    return [
        i if isinstance(i, dict) else (i.as_dict() if hasattr(i, 'as_dict') else vars(i))
        for i in items
    ]


def _to_dict(item) -> dict:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if hasattr(item, 'as_dict'):
        return item.as_dict()
    return vars(item)


class ZIAClient:
    """SDK adapter for the Zscaler Internet Access (ZIA) API.

    Wraps zscaler-sdk-python behind the same method signatures as the
    original hand-rolled HTTP client so all callers remain unchanged.

    NOTE: ZIA configuration changes do not take effect until you call activate().
    Always call activate() after making changes, or use the context manager pattern
    in services/zia_service.py which handles activation automatically.
    """

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def get_activation_status(self) -> Dict:
        result, resp, err = self._sdk.zia.activate.get_activation_status()
        return _to_dict(_unwrap(result, resp, err))

    def activate(self) -> Dict:
        """Commit all pending ZIA configuration changes."""
        result, resp, err = self._sdk.zia.activate.activate()
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # URL Categories
    # ------------------------------------------------------------------

    def list_url_categories(self, include_built_in: bool = False) -> List[Dict]:
        result, resp, err = self._sdk.zia.url_categories.list_categories()
        return _to_dicts(_unwrap(result, resp, err))

    def list_url_categories_lite(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.url_categories.list_url_categories_lite()
        return _to_dicts(_unwrap(result, resp, err))

    def get_url_category(self, category_id: str) -> Dict:
        result, resp, err = self._sdk.zia.url_categories.get_url_category(category_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_url_category(self, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.url_categories.add_url_category(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_url_category(self, category_id: str, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.url_categories.update_url_category(category_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def url_lookup(self, urls: List[str]) -> List[Dict]:
        result, err = self._sdk.zia.url_categories.lookup(urls)
        if err:
            raise RuntimeError(err)
        return _to_dicts(result or [])

    # ------------------------------------------------------------------
    # URL Filtering Policies
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.url_filtering.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------

    def list_users(self, name: Optional[str] = None, group: Optional[str] = None, dept: Optional[str] = None) -> List[Dict]:
        params = {}
        if name:
            params["name"] = name
        if group:
            params["group"] = group
        if dept:
            params["dept"] = dept
        result, resp, err = self._sdk.zia.user_management.list_users(params)
        return _to_dicts(_unwrap(result, resp, err))

    def list_departments(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.user_management.list_departments()
        return _to_dicts(_unwrap(result, resp, err))

    def list_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.user_management.list_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Location Management
    # ------------------------------------------------------------------

    def list_locations(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.locations.list_locations()
        return _to_dicts(_unwrap(result, resp, err))

    def list_locations_lite(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.locations.list_locations_lite()
        return _to_dicts(_unwrap(result, resp, err))

    def get_location(self, location_id: str) -> Dict:
        result, resp, err = self._sdk.zia.locations.get_location(location_id)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Security Policy (Allowlist / Denylist)
    # ------------------------------------------------------------------

    def get_allowlist(self) -> Dict:
        result, resp, err = self._sdk.zia.security_policy_settings.get_whitelist()
        return _to_dict(_unwrap(result, resp, err))

    def get_denylist(self) -> Dict:
        result, resp, err = self._sdk.zia.security_policy_settings.get_blacklist()
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Admin & Role Management
    # ------------------------------------------------------------------

    def list_admin_users(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.admin_users.list_admin_users()
        return _to_dicts(_unwrap(result, resp, err))

    def list_admin_roles(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.admin_roles.list_roles()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Firewall Policy
    # ------------------------------------------------------------------

    def list_firewall_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def list_firewall_dns_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall_dns.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def list_firewall_ips_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall_ips.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def get_firewall_rule(self, rule_id: str) -> Dict:
        result, resp, err = self._sdk.zia.cloud_firewall_rules.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    def update_firewall_rule(self, rule_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zia.cloud_firewall_rules.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    def get_firewall_dns_rule(self, rule_id: str) -> Dict:
        result, resp, err = self._sdk.zia.cloud_firewall_dns.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    def update_firewall_dns_rule(self, rule_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zia.cloud_firewall_dns.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Firewall Supporting Objects
    # ------------------------------------------------------------------

    def list_ip_destination_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall.list_ip_destination_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def list_ip_source_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall.list_ip_source_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def list_network_services(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall.list_network_services()
        return _to_dicts(_unwrap(result, resp, err))

    def list_network_svc_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloud_firewall.list_network_svc_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # SSL Inspection
    # ------------------------------------------------------------------

    def list_ssl_inspection_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.ssl_inspection_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def get_ssl_inspection_rule(self, rule_id: str) -> Dict:
        result, resp, err = self._sdk.zia.ssl_inspection_rules.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    def update_ssl_inspection_rule(self, rule_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zia.ssl_inspection_rules.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Traffic Forwarding
    # ------------------------------------------------------------------

    def list_forwarding_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.forwarding_control.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Location Groups
    # ------------------------------------------------------------------

    def list_location_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.locations.list_location_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Rule Labels & Time Intervals
    # ------------------------------------------------------------------

    def list_rule_labels(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.rule_labels.list_labels()
        return _to_dicts(_unwrap(result, resp, err))

    def list_time_intervals(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.time_intervals.list_time_intervals()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # DLP
    # ------------------------------------------------------------------

    def list_dlp_engines(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.dlp_engine.list_dlp_engines()
        return _to_dicts(_unwrap(result, resp, err))

    def get_dlp_engine(self, engine_id: str) -> Dict:
        result, resp, err = self._sdk.zia.dlp_engine.get_dlp_engine(int(engine_id))
        return _to_dict(_unwrap(result, resp, err))

    def create_dlp_engine(self, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.dlp_engine.add_dlp_engine(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_dlp_engine(self, engine_id: str, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.dlp_engine.update_dlp_engine(int(engine_id), **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_dlp_engine(self, engine_id: str) -> None:
        result, resp, err = self._sdk.zia.dlp_engine.delete_dlp_engine(int(engine_id))
        _unwrap(result, resp, err)

    def list_dlp_dictionaries(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.dlp_dictionary.list_dicts()
        return _to_dicts(_unwrap(result, resp, err))

    def get_dlp_dictionary(self, dict_id: str) -> Dict:
        result, resp, err = self._sdk.zia.dlp_dictionary.get_dict(int(dict_id))
        return _to_dict(_unwrap(result, resp, err))

    def create_dlp_dictionary(self, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.dlp_dictionary.add_dict(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_dlp_dictionary(self, dict_id: str, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.dlp_dictionary.update_dict(int(dict_id), **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_dlp_dictionary(self, dict_id: str) -> None:
        result, resp, err = self._sdk.zia.dlp_dictionary.delete_dict(int(dict_id))
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Security Policy (singleton list wrappers for import)
    # ------------------------------------------------------------------

    def list_allowlist(self) -> List[Dict]:
        """Wrap allowlist singleton as a single-element list for the import service."""
        data = self.get_allowlist()
        return [{"id": "allowlist", "name": "allowlist", **data}]

    def list_denylist(self) -> List[Dict]:
        """Wrap denylist singleton as a single-element list for the import service."""
        data = self.get_denylist()
        return [{"id": "denylist", "name": "denylist", **data}]

    def add_to_allowlist(self, url_list: List[str]) -> Dict:
        result, resp, err = self._sdk.zia.security_policy_settings.add_urls_to_whitelist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    def remove_from_allowlist(self, url_list: List[str]) -> Dict:
        result, resp, err = self._sdk.zia.security_policy_settings.delete_urls_from_whitelist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    def add_to_denylist(self, url_list: List[str]) -> Dict:
        result, resp, err = self._sdk.zia.security_policy_settings.add_urls_to_blacklist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    def remove_from_denylist(self, url_list: List[str]) -> Dict:
        result, resp, err = self._sdk.zia.security_policy_settings.delete_urls_from_blacklist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # URL Filtering — get/update for enable/disable
    # ------------------------------------------------------------------

    def get_url_filtering_rule(self, rule_id: str) -> Dict:
        result, resp, err = self._sdk.zia.url_filtering.get_rule(rule_id)
        return _to_dict(_unwrap(result, resp, err))

    def update_url_filtering_rule(self, rule_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zia.url_filtering.update_rule(rule_id, **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # URL Categories — update for add/remove URLs
    # ------------------------------------------------------------------

    def add_urls_to_category(self, category_id: str, urls: List[str]) -> Dict:
        cat = self.get_url_category(category_id)
        existing = cat.get("urls") or []
        merged = list(set(existing) | set(urls))
        result, resp, err = self._sdk.zia.url_categories.update_url_category(
            category_id, urls=merged
        )
        return _to_dict(_unwrap(result, resp, err))

    def remove_urls_from_category(self, category_id: str, urls: List[str]) -> Dict:
        cat = self.get_url_category(category_id)
        existing = cat.get("urls") or []
        to_remove = set(urls)
        updated = [u for u in existing if u not in to_remove]
        result, resp, err = self._sdk.zia.url_categories.update_url_category(
            category_id, urls=updated
        )
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Cloud Applications (read-only catalog)
    # ------------------------------------------------------------------

    def list_cloud_app_policy(self, search: Optional[str] = None, app_class: Optional[str] = None) -> List[Dict]:
        params = {}
        if search:
            params["search"] = search
        if app_class:
            params["app_class"] = app_class
        result, resp, err = self._sdk.zia.cloud_applications.list_cloud_app_policy(query_params=params)
        return _to_dicts(_unwrap(result, resp, err))

    def list_cloud_app_ssl_policy(self, search: Optional[str] = None, app_class: Optional[str] = None) -> List[Dict]:
        params = {}
        if search:
            params["search"] = search
        if app_class:
            params["app_class"] = app_class
        result, resp, err = self._sdk.zia.cloud_applications.list_cloud_app_ssl_policy(query_params=params)
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Cloud App Control
    # ------------------------------------------------------------------

    # SDK's form_response_body mangles UPPER_SNAKE keys via pydash.camel_case
    # (e.g. AI_ML → aiMl), so get_rule_type_mapping() can't be used to drive
    # the import loop.  Use the canonical type list from the SDK docs instead.
    _CLOUD_APP_RULE_TYPES: List[str] = [
        "AI_ML", "BUSINESS_PRODUCTIVITY", "CONSUMER", "DNS_OVER_HTTPS",
        "ENTERPRISE_COLLABORATION", "FILE_SHARE", "FINANCE", "HEALTH_CARE",
        "HOSTING_PROVIDER", "HUMAN_RESOURCES", "INSTANT_MESSAGING", "IT_SERVICES",
        "LEGAL", "SALES_AND_MARKETING", "SOCIAL_NETWORKING", "STREAMING_MEDIA",
        "SYSTEM_AND_DEVELOPMENT", "WEBMAIL",
    ]

    def list_all_cloud_app_rules(self) -> List[Dict]:
        """Fetch rules for every rule type and return combined list (for import)."""
        all_rules: List[Dict] = []
        for rule_type in self._CLOUD_APP_RULE_TYPES:
            try:
                all_rules.extend(self.list_cloud_app_rules(rule_type))
            except Exception:
                pass
        return all_rules

    def get_cloud_app_rule_types(self) -> Dict:
        result, resp, err = self._sdk.zia.cloudappcontrol.get_rule_type_mapping()
        return _to_dict(_unwrap(result, resp, err))

    def list_cloud_app_rules(self, rule_type: str) -> List[Dict]:
        result, resp, err = self._sdk.zia.cloudappcontrol.list_rules(rule_type)
        return _to_dicts(_unwrap(result, resp, err))

    def get_cloud_app_rule(self, rule_type: str, rule_id: str) -> Dict:
        result, resp, err = self._sdk.zia.cloudappcontrol.get_rule(rule_type, rule_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_cloud_app_rule(self, rule_type: str, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.cloudappcontrol.add_rule(rule_type, **config)
        return _to_dict(_unwrap(result, resp, err))

    def update_cloud_app_rule(self, rule_type: str, rule_id: str, config: Dict) -> Dict:
        result, resp, err = self._sdk.zia.cloudappcontrol.update_rule(rule_type, rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_cloud_app_rule(self, rule_type: str, rule_id: str) -> None:
        _, resp, err = self._sdk.zia.cloudappcontrol.delete_rule(rule_type, rule_id)
        if err:
            raise RuntimeError(str(err))

    def duplicate_cloud_app_rule(self, rule_type: str, rule_id: str, name: str) -> Dict:
        result, resp, err = self._sdk.zia.cloudappcontrol.add_duplicate_rule(rule_type, rule_id, name)
        return _to_dict(_unwrap(result, resp, err))
