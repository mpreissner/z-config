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
        result, resp, err = self._sdk.zia.url_categories.list_url_categories()
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
        result, resp, err = self._sdk.zia.url_categories.url_lookup(urls)
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # URL Filtering Policies
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        result, resp, err = self._sdk.zia.url_filtering.list_url_filtering_rules()
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
