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

    GovCloud note: the ZscalerClient SDK is not GovCloud-aware — it constructs the
    ZIdentity token URL as {vanityDomain}.zslogin.net which fails for GovCloud tenants.
    When self._govcloud is True, all SDK-backed methods fall back to direct HTTP using
    zia_get/zia_post/zia_put/zia_delete, which use self.auth.get_token() directly.
    """

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._oneapi_base_url = oneapi_base_url.rstrip("/")
        self._govcloud = auth.govcloud
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })

    @staticmethod
    def _raise_for_status(resp) -> None:
        """Like resp.raise_for_status() but includes the response body in the message.

        This ensures that ZIA error codes such as NOT_SUBSCRIBED survive as
        a substring of the exception string so callers (e.g. the import service)
        can inspect them without having to parse the response object.
        """
        if resp.ok:
            return
        try:
            body = resp.json()
            msg = f"{resp.status_code} Error: {body}"
        except Exception:
            msg = f"{resp.status_code} Error: {resp.text[:200]}"
        import requests as _req
        raise _req.HTTPError(msg, response=resp)

    def _zia_request(self, method: str, path: str, json=None, params=None) -> "requests.Response":
        """Authenticated direct HTTP request with automatic 429 retry/backoff.

        Retries up to 3 times on 429, honouring Retry-After when present and
        falling back to exponential backoff (2 / 4 / 8 s) otherwise.
        """
        import requests
        import time
        url = f"{self._oneapi_base_url}{path}"
        max_attempts = 4
        resp = None
        for attempt in range(max_attempts):
            token = self.auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            if json is not None:
                headers["Content-Type"] = "application/json"
            resp = requests.request(
                method, url,
                headers=headers, json=json, params=params, timeout=30,
            )
            if resp.status_code != 429 or attempt == max_attempts - 1:
                break
            try:
                delay = float(resp.headers.get("Retry-After", ""))
            except (ValueError, TypeError):
                delay = 2 ** (attempt + 1)  # 2, 4, 8 s
            time.sleep(delay)
        self._raise_for_status(resp)
        return resp

    def zia_get(self, path: str) -> dict:
        """Direct HTTP GET to the ZIA API — returns the raw camelCase JSON."""
        return self._zia_request("GET", path).json()

    def zia_put(self, path: str, payload: dict) -> dict:
        """Direct HTTP PUT to the ZIA API — bypasses the SDK's GET-merge-PUT behavior."""
        resp = self._zia_request("PUT", path, json=payload)
        return resp.json() if resp.content else {}

    def zia_post(self, path: str, payload) -> dict:
        """Direct HTTP POST to the ZIA API — bypasses SDK serialization."""
        resp = self._zia_request("POST", path, json=payload)
        return resp.json() if resp.content else {}

    def zia_delete(self, path: str) -> None:
        """Direct HTTP DELETE to the ZIA API."""
        self._zia_request("DELETE", path)

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def get_activation_status(self) -> Dict:
        if self._govcloud:
            return self.zia_get("/zia/api/v1/status")
        result, resp, err = self._sdk.zia.activate.status()
        return _to_dict(_unwrap(result, resp, err))

    def activate(self) -> Dict:
        """Commit all pending ZIA configuration changes."""
        if self._govcloud:
            return self.zia_post("/zia/api/v1/status/activate", {})
        result, resp, err = self._sdk.zia.activate.activate()
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # URL Categories
    # ------------------------------------------------------------------

    def list_url_categories(self, include_built_in: bool = False) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/urlCategories")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.url_categories.list_categories()
        return _to_dicts(_unwrap(result, resp, err))

    def list_url_categories_lite(self) -> List[Dict]:
        # SDK does not expose a lite endpoint — use direct HTTP for both paths.
        data = self.zia_get("/zia/api/v1/urlCategories/lite")
        return data if isinstance(data, list) else []

    def get_url_category(self, category_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/urlCategories/{category_id}")
        result, resp, err = self._sdk.zia.url_categories.get_category(category_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_url_category(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/urlCategories", config)
        result, resp, err = self._sdk.zia.url_categories.add_url_category(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_url_category(self, category_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/urlCategories/{category_id}", config)
        result, resp, err = self._sdk.zia.url_categories.update_url_category(category_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_url_category(self, category_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/urlCategories/{category_id}")
            return
        result, resp, err = self._sdk.zia.url_categories.delete_category(category_id)
        _unwrap(result, resp, err)

    def url_lookup(self, urls: List[str]) -> List[Dict]:
        if self._govcloud:
            data = self.zia_post("/zia/api/v1/urlLookup", urls)
            return data if isinstance(data, list) else []
        result, err = self._sdk.zia.url_categories.lookup(urls)
        if err:
            raise RuntimeError(err)
        return _to_dicts(result or [])

    # ------------------------------------------------------------------
    # URL Filtering Policies
    # ------------------------------------------------------------------

    def list_url_filtering_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/urlFilteringRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.url_filtering.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # User Management
    # ------------------------------------------------------------------

    def get_user(self, user_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/users/{user_id}")
        result, resp, err = self._sdk.zia.user_management.get_user(int(user_id))
        return _to_dict(_unwrap(result, resp, err))

    def create_user(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/users", config)
        result, resp, err = self._sdk.zia.user_management.add_user(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_user(self, user_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/users/{user_id}", config)
        result, resp, err = self._sdk.zia.user_management.update_user(int(user_id), **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_user(self, user_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/users/{user_id}")
            return
        result, resp, err = self._sdk.zia.user_management.delete_user(int(user_id))
        _unwrap(result, resp, err)

    def update_allowlist(self, urls: List[str]) -> Dict:
        """Replace the entire allowlist with the provided URL list."""
        if self._govcloud:
            return self.zia_put("/zia/api/v1/security", {"whitelistedUrls": urls})
        result, resp, err = self._sdk.zia.security_policy_settings.update_whitelist(whitelist_urls=urls)
        return _to_dict(_unwrap(result, resp, err))

    def update_denylist(self, urls: List[str]) -> Dict:
        """Replace the entire denylist with the provided URL list."""
        if self._govcloud:
            return self.zia_put("/zia/api/v1/security/advanced", {"blacklistedUrls": urls})
        result, resp, err = self._sdk.zia.security_policy_settings.update_blacklist(blacklist_urls=urls)
        return _to_dict(_unwrap(result, resp, err))

    def list_users(self, name: Optional[str] = None, group: Optional[str] = None, dept: Optional[str] = None) -> List[Dict]:
        if self._govcloud:
            params = {k: v for k, v in [("name", name), ("group", group), ("dept", dept)] if v}
            data = self._zia_request("GET", "/zia/api/v1/users", params=params or None).json()
            return data if isinstance(data, list) else []
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
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/departments")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.user_management.list_departments()
        return _to_dicts(_unwrap(result, resp, err))

    def list_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/groups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.user_management.list_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Browser Isolation
    # ------------------------------------------------------------------

    def list_browser_isolation_profiles(self) -> List[Dict]:
        # Always use direct HTTP — the SDK omits the profileSeq field which is
        # required to set smartIsolationProfileId when enabling Smart Isolation.
        data = self.zia_get("/zia/api/v1/browserIsolation/profiles")
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Location Management
    # ------------------------------------------------------------------

    def list_locations(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/locations")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.locations.list_locations()
        return _to_dicts(_unwrap(result, resp, err))

    def list_locations_lite(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/locations/lite")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.locations.list_locations_lite()
        return _to_dicts(_unwrap(result, resp, err))

    def get_location(self, location_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/locations/{location_id}")
        result, resp, err = self._sdk.zia.locations.get_location(location_id)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Security Policy (Allowlist / Denylist)
    # ------------------------------------------------------------------

    def get_allowlist(self) -> Dict:
        if self._govcloud:
            return self.zia_get("/zia/api/v1/security")
        result, resp, err = self._sdk.zia.security_policy_settings.get_whitelist()
        return _to_dict(_unwrap(result, resp, err))

    def get_denylist(self) -> Dict:
        if self._govcloud:
            return self.zia_get("/zia/api/v1/security/advanced")
        result, resp, err = self._sdk.zia.security_policy_settings.get_blacklist()
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Admin & Role Management
    # ------------------------------------------------------------------

    def list_admin_users(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/adminUsers")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.admin_users.list_admin_users()
        return _to_dicts(_unwrap(result, resp, err))

    def list_admin_roles(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/adminRoles/lite")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.admin_roles.list_roles()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Firewall Policy
    # ------------------------------------------------------------------

    def list_firewall_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/firewallFilteringRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def list_firewall_dns_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/firewallDnsRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall_dns.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def list_firewall_ips_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/firewallIpsRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall_ips.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def get_firewall_rule(self, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/firewallFilteringRules/{rule_id}")
        result, resp, err = self._sdk.zia.cloud_firewall_rules.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    def update_firewall_rule(self, rule_id: str, config: Dict) -> bool:
        if self._govcloud:
            self.zia_put(f"/zia/api/v1/firewallFilteringRules/{rule_id}", config)
            return True
        result, resp, err = self._sdk.zia.cloud_firewall_rules.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    def get_firewall_dns_rule(self, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/firewallDnsRules/{rule_id}")
        result, resp, err = self._sdk.zia.cloud_firewall_dns.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    def update_firewall_dns_rule(self, rule_id: str, config: Dict) -> bool:
        if self._govcloud:
            self.zia_put(f"/zia/api/v1/firewallDnsRules/{rule_id}", config)
            return True
        result, resp, err = self._sdk.zia.cloud_firewall_dns.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    def get_firewall_ips_rule(self, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/firewallIpsRules/{rule_id}")
        result, resp, err = self._sdk.zia.cloud_firewall_ips.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Firewall Supporting Objects
    # ------------------------------------------------------------------

    def list_ip_destination_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/ipDestinationGroups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall.list_ip_destination_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def list_ip_source_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/ipSourceGroups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall.list_ip_source_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def list_network_services(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/networkServices")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall.list_network_services()
        return _to_dicts(_unwrap(result, resp, err))

    def list_network_svc_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/networkServiceGroups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall.list_network_svc_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # SSL Inspection
    # ------------------------------------------------------------------

    def list_ssl_inspection_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/sslInspectionRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.ssl_inspection_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def get_ssl_inspection_rule(self, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/sslInspectionRules/{rule_id}")
        result, resp, err = self._sdk.zia.ssl_inspection_rules.get_rule(int(rule_id))
        return _to_dict(_unwrap(result, resp, err))

    def update_ssl_inspection_rule(self, rule_id: str, config: Dict) -> bool:
        if self._govcloud:
            self.zia_put(f"/zia/api/v1/sslInspectionRules/{rule_id}", config)
            return True
        result, resp, err = self._sdk.zia.ssl_inspection_rules.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Traffic Forwarding
    # ------------------------------------------------------------------

    def list_forwarding_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/forwardingRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.forwarding_control.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def get_forwarding_rule(self, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/forwardingRules/{rule_id}")
        result, resp, err = self._sdk.zia.forwarding_control.get_rule(rule_id)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Sandbox Policy
    # ------------------------------------------------------------------

    def list_sandbox_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/sandboxRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.sandbox_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def create_sandbox_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/sandboxRules", config)
        result, resp, err = self._sdk.zia.sandbox_rules.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_sandbox_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/sandboxRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.sandbox_rules.update_rule(int(rule_id), **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_sandbox_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/sandboxRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.sandbox_rules.delete_rule(int(rule_id))
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Device Groups
    # ------------------------------------------------------------------

    def list_device_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/deviceGroups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.device_management.list_device_groups(
            query_params={"includePseudoGroups": True}
        )
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Location Groups
    # ------------------------------------------------------------------

    def list_location_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/locations/groups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.locations.list_location_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Rule Labels & Time Intervals
    # ------------------------------------------------------------------

    def list_rule_labels(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/ruleLabels")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.rule_labels.list_labels()
        return _to_dicts(_unwrap(result, resp, err))

    def list_time_intervals(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/timeIntervals")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.time_intervals.list_time_intervals()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # DLP
    # ------------------------------------------------------------------

    def list_dlp_engines(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/dlpEngines")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.dlp_engine.list_dlp_engines()
        return _to_dicts(_unwrap(result, resp, err))

    def get_dlp_engine(self, engine_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/dlpEngines/{engine_id}")
        result, resp, err = self._sdk.zia.dlp_engine.get_dlp_engine(int(engine_id))
        return _to_dict(_unwrap(result, resp, err))

    def create_dlp_engine(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/dlpEngines", config)
        result, resp, err = self._sdk.zia.dlp_engine.add_dlp_engine(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_dlp_engine(self, engine_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/dlpEngines/{engine_id}", config)
        result, resp, err = self._sdk.zia.dlp_engine.update_dlp_engine(int(engine_id), **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_dlp_engine(self, engine_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/dlpEngines/{engine_id}")
            return
        result, resp, err = self._sdk.zia.dlp_engine.delete_dlp_engine(int(engine_id))
        _unwrap(result, resp, err)

    def list_dlp_dictionaries(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/dlpDictionaries")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.dlp_dictionary.list_dicts()
        return _to_dicts(_unwrap(result, resp, err))

    def get_dlp_dictionary(self, dict_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/dlpDictionaries/{dict_id}")
        result, resp, err = self._sdk.zia.dlp_dictionary.get_dict(int(dict_id))
        return _to_dict(_unwrap(result, resp, err))

    def create_dlp_dictionary(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/dlpDictionaries", config)
        result, resp, err = self._sdk.zia.dlp_dictionary.add_dict(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_dlp_dictionary(self, dict_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/dlpDictionaries/{dict_id}", config)
        result, resp, err = self._sdk.zia.dlp_dictionary.update_dict(int(dict_id), **config)
        return _to_dict(_unwrap(result, resp, err))

    def update_dlp_dictionary_confidence(self, dict_id: str, confidence_threshold: str) -> Dict:
        # Must use direct HTTP for both govcloud and SDK paths — the SDK doesn't
        # handle predefined dictionary updates; GET full camelCase payload, patch field, PUT back.
        current = self.zia_get(f"/zia/api/v1/dlpDictionaries/{dict_id}")
        current["confidenceThreshold"] = confidence_threshold
        return self.zia_put(f"/zia/api/v1/dlpDictionaries/{dict_id}", current)

    def delete_dlp_dictionary(self, dict_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/dlpDictionaries/{dict_id}")
            return
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
        if self._govcloud:
            current = self.get_allowlist()
            existing = current.get("whitelistedUrls") or []
            current["whitelistedUrls"] = list(set(existing) | set(url_list))
            return self.zia_put("/zia/api/v1/security", current)
        result, resp, err = self._sdk.zia.security_policy_settings.add_urls_to_whitelist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    def remove_from_allowlist(self, url_list: List[str]) -> Dict:
        if self._govcloud:
            current = self.get_allowlist()
            to_remove = set(url_list)
            current["whitelistedUrls"] = [u for u in (current.get("whitelistedUrls") or []) if u not in to_remove]
            return self.zia_put("/zia/api/v1/security", current)
        result, resp, err = self._sdk.zia.security_policy_settings.delete_urls_from_whitelist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    def add_to_denylist(self, url_list: List[str]) -> Dict:
        if self._govcloud:
            current = self.get_denylist()
            existing = current.get("blacklistedUrls") or []
            current["blacklistedUrls"] = list(set(existing) | set(url_list))
            return self.zia_put("/zia/api/v1/security/advanced", current)
        result, resp, err = self._sdk.zia.security_policy_settings.add_urls_to_blacklist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    def remove_from_denylist(self, url_list: List[str]) -> Dict:
        if self._govcloud:
            current = self.get_denylist()
            to_remove = set(url_list)
            current["blacklistedUrls"] = [u for u in (current.get("blacklistedUrls") or []) if u not in to_remove]
            return self.zia_put("/zia/api/v1/security/advanced", current)
        result, resp, err = self._sdk.zia.security_policy_settings.delete_urls_from_blacklist(url_list)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # URL Filtering — get/update for enable/disable
    # ------------------------------------------------------------------

    def get_url_filtering_rule(self, rule_id: str) -> Dict:
        # Always use direct HTTP — returns camelCase JSON from the API
        return self.zia_get(f"/zia/api/v1/urlFilteringRules/{rule_id}")

    def update_url_filtering_rule(self, rule_id: str, config: Dict) -> bool:
        if self._govcloud:
            self.zia_put(f"/zia/api/v1/urlFilteringRules/{rule_id}", config)
            return True
        result, resp, err = self._sdk.zia.url_filtering.update_rule(int(rule_id), **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # URL Categories — update for add/remove URLs
    # ------------------------------------------------------------------

    def add_urls_to_category(self, category_id: str, urls: List[str]) -> Dict:
        cat = self.get_url_category(category_id)
        existing = cat.get("urls") or []
        merged = list(set(existing) | set(urls))
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/urlCategories/{category_id}", {**cat, "urls": merged})
        result, resp, err = self._sdk.zia.url_categories.update_url_category(
            category_id, configured_name=cat.get("configured_name"), urls=merged
        )
        return _to_dict(_unwrap(result, resp, err))

    def remove_urls_from_category(self, category_id: str, urls: List[str]) -> Dict:
        cat = self.get_url_category(category_id)
        existing = cat.get("urls") or []
        to_remove = set(urls)
        updated = [u for u in existing if u not in to_remove]
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/urlCategories/{category_id}", {**cat, "urls": updated})
        result, resp, err = self._sdk.zia.url_categories.update_url_category(
            category_id, configured_name=cat.get("configured_name"), urls=updated
        )
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Cloud Applications (read-only catalog)
    # ------------------------------------------------------------------

    def list_cloud_app_policy(self, search: Optional[str] = None, app_class: Optional[str] = None) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/cloudApplications/policy")
            return data if isinstance(data, list) else []
        params = {}
        if search:
            params["search"] = search
        if app_class:
            params["app_class"] = app_class
        result, resp, err = self._sdk.zia.cloud_applications.list_cloud_app_policy(query_params=params)
        return _to_dicts(_unwrap(result, resp, err))

    def list_cloud_app_ssl_policy(self, search: Optional[str] = None, app_class: Optional[str] = None) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/cloudApplications/sslPolicy")
            return data if isinstance(data, list) else []
        params = {}
        if search:
            params["search"] = search
        if app_class:
            params["app_class"] = app_class
        result, resp, err = self._sdk.zia.cloud_applications.list_cloud_app_ssl_policy(query_params=params)
        return _to_dicts(_unwrap(result, resp, err))

    def list_cloud_app_instances(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/cloudApplicationInstances")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_app_instances.list_cloud_app_instances()
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
        if self._govcloud:
            return self.zia_get("/zia/api/v1/webApplicationRules/ruleTypeMapping")
        result, resp, err = self._sdk.zia.cloudappcontrol.get_rule_type_mapping()
        return _to_dict(_unwrap(result, resp, err))

    def list_cloud_app_rules(self, rule_type: str) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get(f"/zia/api/v1/webApplicationRules/{rule_type}")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloudappcontrol.list_rules(rule_type)
        return _to_dicts(_unwrap(result, resp, err))

    def get_cloud_app_rule(self, rule_type: str, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/webApplicationRules/{rule_type}/{rule_id}")
        result, resp, err = self._sdk.zia.cloudappcontrol.get_rule(rule_type, rule_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_cloud_app_rule(self, rule_type: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post(f"/zia/api/v1/webApplicationRules/{rule_type}", config)
        result, resp, err = self._sdk.zia.cloudappcontrol.add_rule(rule_type, **config)
        return _to_dict(_unwrap(result, resp, err))

    def update_cloud_app_rule(self, rule_type: str, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/webApplicationRules/{rule_type}/{rule_id}", config)
        result, resp, err = self._sdk.zia.cloudappcontrol.update_rule(rule_type, rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_cloud_app_rule(self, rule_type: str, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/webApplicationRules/{rule_type}/{rule_id}")
            return
        _, resp, err = self._sdk.zia.cloudappcontrol.delete_rule(rule_type, rule_id)
        if err:
            raise RuntimeError(str(err))

    def duplicate_cloud_app_rule(self, rule_type: str, rule_id: str, name: str) -> Dict:
        if self._govcloud:
            return self.zia_post(f"/zia/api/v1/webApplicationRules/{rule_type}/duplicate/{rule_id}", {"name": name})
        result, resp, err = self._sdk.zia.cloudappcontrol.add_duplicate_rule(rule_type, rule_id, name)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # DLP Web Rules
    # ------------------------------------------------------------------

    def list_dlp_web_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/webDlpRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.dlp_web_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def get_dlp_web_rule(self, rule_id: str) -> Dict:
        if self._govcloud:
            return self.zia_get(f"/zia/api/v1/webDlpRules/{rule_id}")
        result, resp, err = self._sdk.zia.dlp_web_rules.get_rule(rule_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_dlp_web_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/webDlpRules", config)
        result, resp, err = self._sdk.zia.dlp_web_rules.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_dlp_web_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/webDlpRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.dlp_web_rules.update_rule(rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_dlp_web_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/webDlpRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.dlp_web_rules.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # NAT Control Policy
    # ------------------------------------------------------------------

    def list_nat_control_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/dnatRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.nat_control_policy.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def create_nat_control_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/dnatRules", config)
        result, resp, err = self._sdk.zia.nat_control_policy.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_nat_control_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/dnatRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.nat_control_policy.update_rule(rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_nat_control_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/dnatRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.nat_control_policy.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Bandwidth Classes
    # ------------------------------------------------------------------

    def list_bandwidth_classes(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/bandwidthClasses")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.bandwidth_classes.list_classes()
        return _to_dicts(_unwrap(result, resp, err))

    def create_bandwidth_class(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/bandwidthClasses", config)
        result, resp, err = self._sdk.zia.bandwidth_classes.add_class(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_bandwidth_class(self, class_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/bandwidthClasses/{class_id}", config)
        result, resp, err = self._sdk.zia.bandwidth_classes.update_class(class_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_bandwidth_class(self, class_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/bandwidthClasses/{class_id}")
            return
        result, resp, err = self._sdk.zia.bandwidth_classes.delete_class(class_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Bandwidth Control Rules
    # ------------------------------------------------------------------

    def list_bandwidth_control_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/bandwidthControlRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.bandwidth_control_rules.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def create_bandwidth_control_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/bandwidthControlRules", config)
        result, resp, err = self._sdk.zia.bandwidth_control_rules.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_bandwidth_control_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/bandwidthControlRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.bandwidth_control_rules.update_rule(rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_bandwidth_control_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/bandwidthControlRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.bandwidth_control_rules.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Traffic Capture Rules
    # ------------------------------------------------------------------

    def list_traffic_capture_rules(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/trafficCaptureRules")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.traffic_capture.list_rules()
        return _to_dicts(_unwrap(result, resp, err))

    def create_traffic_capture_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/trafficCaptureRules", config)
        result, resp, err = self._sdk.zia.traffic_capture.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_traffic_capture_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/trafficCaptureRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.traffic_capture.update_rule(rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_traffic_capture_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/trafficCaptureRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.traffic_capture.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Workload Groups
    # ------------------------------------------------------------------

    def list_workload_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/workloadGroups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.workload_groups.list_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def create_workload_group(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/workloadGroups", config)
        result, resp, err = self._sdk.zia.workload_groups.add_group(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_workload_group(self, group_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/workloadGroups/{group_id}", config)
        result, resp, err = self._sdk.zia.workload_groups.update_group(group_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_workload_group(self, group_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/workloadGroups/{group_id}")
            return
        result, resp, err = self._sdk.zia.workload_groups.delete_group(group_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Network Apps (read-only) and Network App Groups
    # ------------------------------------------------------------------

    def list_network_apps(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/networkApplications")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall.list_network_apps()
        return _to_dicts(_unwrap(result, resp, err))

    def list_network_app_groups(self) -> List[Dict]:
        if self._govcloud:
            data = self.zia_get("/zia/api/v1/networkApplicationGroups")
            return data if isinstance(data, list) else []
        result, resp, err = self._sdk.zia.cloud_firewall.list_network_app_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def create_network_app_group(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/networkApplicationGroups", config)
        result, resp, err = self._sdk.zia.cloud_firewall.add_network_app_group(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_network_app_group(self, group_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/networkApplicationGroups/{group_id}", config)
        result, resp, err = self._sdk.zia.cloud_firewall.update_network_app_group(group_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_network_app_group(self, group_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/networkApplicationGroups/{group_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall.delete_network_app_group(group_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Rule Labels — write methods
    # ------------------------------------------------------------------

    def create_rule_label(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/ruleLabels", config)
        result, resp, err = self._sdk.zia.rule_labels.add_label(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_rule_label(self, label_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/ruleLabels/{label_id}", config)
        result, resp, err = self._sdk.zia.rule_labels.update_label(label_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_rule_label(self, label_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/ruleLabels/{label_id}")
            return
        result, resp, err = self._sdk.zia.rule_labels.delete_label(label_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Time Intervals — write methods
    # ------------------------------------------------------------------

    def create_time_interval(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/timeIntervals", config)
        result, resp, err = self._sdk.zia.time_intervals.add_time_interval(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_time_interval(self, interval_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/timeIntervals/{interval_id}", config)
        result, resp, err = self._sdk.zia.time_intervals.update_time_interval(interval_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_time_interval(self, interval_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/timeIntervals/{interval_id}")
            return
        result, resp, err = self._sdk.zia.time_intervals.delete_time_interval(interval_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # URL Filtering — create/delete (update already exists)
    # ------------------------------------------------------------------

    def create_url_filtering_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/urlFilteringRules", config)
        result, resp, err = self._sdk.zia.url_filtering.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_url_filtering_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/urlFilteringRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.url_filtering.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Firewall Rules — create/delete (update already exists)
    # ------------------------------------------------------------------

    def create_firewall_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/firewallFilteringRules", config)
        result, resp, err = self._sdk.zia.cloud_firewall_rules.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_firewall_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/firewallFilteringRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall_rules.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Firewall DNS Rules — create/delete (update already exists)
    # ------------------------------------------------------------------

    def create_firewall_dns_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/firewallDnsRules", config)
        result, resp, err = self._sdk.zia.cloud_firewall_dns.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_firewall_dns_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/firewallDnsRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall_dns.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Firewall IPS Rules — create/update/delete
    # ------------------------------------------------------------------

    def create_firewall_ips_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/firewallIpsRules", config)
        result, resp, err = self._sdk.zia.cloud_firewall_ips.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_firewall_ips_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/firewallIpsRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.cloud_firewall_ips.update_rule(rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_firewall_ips_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/firewallIpsRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall_ips.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # SSL Inspection Rules — create/delete (update already exists)
    # ------------------------------------------------------------------

    def create_ssl_inspection_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/sslInspectionRules", config)
        result, resp, err = self._sdk.zia.ssl_inspection_rules.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_ssl_inspection_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/sslInspectionRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.ssl_inspection_rules.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Forwarding Control — create/delete
    # ------------------------------------------------------------------

    def create_forwarding_rule(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/forwardingRules", config)
        result, resp, err = self._sdk.zia.forwarding_control.add_rule(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_forwarding_rule(self, rule_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/forwardingRules/{rule_id}", config)
        result, resp, err = self._sdk.zia.forwarding_control.update_rule(rule_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_forwarding_rule(self, rule_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/forwardingRules/{rule_id}")
            return
        result, resp, err = self._sdk.zia.forwarding_control.delete_rule(rule_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Firewall Supporting Objects — write methods
    # ------------------------------------------------------------------

    def create_ip_destination_group(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/ipDestinationGroups", config)
        result, resp, err = self._sdk.zia.cloud_firewall.add_ip_destination_group(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_ip_destination_group(self, group_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/ipDestinationGroups/{group_id}", config)
        result, resp, err = self._sdk.zia.cloud_firewall.update_ip_destination_group(group_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_ip_destination_group(self, group_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/ipDestinationGroups/{group_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall.delete_ip_destination_group(group_id)
        _unwrap(result, resp, err)

    def create_ip_source_group(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/ipSourceGroups", config)
        result, resp, err = self._sdk.zia.cloud_firewall.add_ip_source_group(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_ip_source_group(self, group_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/ipSourceGroups/{group_id}", config)
        result, resp, err = self._sdk.zia.cloud_firewall.update_ip_source_group(group_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_ip_source_group(self, group_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/ipSourceGroups/{group_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall.delete_ip_source_group(group_id)
        _unwrap(result, resp, err)

    def create_network_service(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/networkServices", config)
        result, resp, err = self._sdk.zia.cloud_firewall.add_network_service(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_network_service(self, service_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/networkServices/{service_id}", config)
        result, resp, err = self._sdk.zia.cloud_firewall.update_network_service(service_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_network_service(self, service_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/networkServices/{service_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall.delete_network_service(service_id)
        _unwrap(result, resp, err)

    def create_network_svc_group(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/networkServiceGroups", config)
        result, resp, err = self._sdk.zia.cloud_firewall.add_network_svc_group(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_network_svc_group(self, group_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/networkServiceGroups/{group_id}", config)
        result, resp, err = self._sdk.zia.cloud_firewall.update_network_svc_group(group_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_network_svc_group(self, group_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/networkServiceGroups/{group_id}")
            return
        result, resp, err = self._sdk.zia.cloud_firewall.delete_network_svc_group(group_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Locations — write methods
    # ------------------------------------------------------------------

    def create_location(self, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_post("/zia/api/v1/locations", config)
        result, resp, err = self._sdk.zia.locations.add_location(**config)
        return _to_dict(_unwrap(result, resp, err))

    def update_location(self, location_id: str, config: Dict) -> Dict:
        if self._govcloud:
            return self.zia_put(f"/zia/api/v1/locations/{location_id}", config)
        result, resp, err = self._sdk.zia.locations.update_location(location_id, **config)
        return _to_dict(_unwrap(result, resp, err))

    def delete_location(self, location_id: str) -> None:
        if self._govcloud:
            self.zia_delete(f"/zia/api/v1/locations/{location_id}")
            return
        result, resp, err = self._sdk.zia.locations.delete_location(location_id)
        _unwrap(result, resp, err)

    # ------------------------------------------------------------------
    # Advanced URL Filter & Cloud App Settings (singleton)
    # ------------------------------------------------------------------

    def list_url_filter_cloud_app_settings(self) -> List[Dict]:
        data = self.zia_get("/zia/api/v1/advancedUrlFilterAndCloudAppSettings")
        return [{"id": 1, "name": "url_filter_cloud_app_settings",
                  "access_control": "READ_WRITE", **data}]

    def update_url_filter_cloud_app_settings(self, rule_id: str, config: Dict) -> bool:
        """PUT singleton settings — rule_id is unused (singleton endpoint)."""
        payload = {k: v for k, v in config.items() if k not in ("id", "name")}
        self.zia_put("/zia/api/v1/advancedUrlFilterAndCloudAppSettings", payload)
        return True

    def list_advanced_settings(self) -> List[Dict]:
        """Return singleton advancedSettings wrapped in a one-element list for import compatibility."""
        data = self.zia_get("/zia/api/v1/advancedSettings")
        return [{"id": 1, "name": "advanced_settings",
                  "access_control": "READ_WRITE", **data}]

    def update_advanced_settings(self, rule_id: str, config: Dict) -> bool:
        """PUT singleton advancedSettings — rule_id is unused (singleton endpoint)."""
        payload = {k: v for k, v in config.items() if k not in ("id", "name")}
        self.zia_put("/zia/api/v1/advancedSettings", payload)
        return True

    def list_browser_control_settings(self) -> List[Dict]:
        """Return singleton browserControlSettings wrapped in a one-element list."""
        data = self.zia_get("/zia/api/v1/browserControlSettings")
        return [{"id": 1, "name": "browser_control_settings",
                  "access_control": "READ_WRITE", **data}]

    def update_browser_control_settings(self, rule_id: str, config: Dict) -> bool:
        """PUT singleton browserControlSettings — rule_id is unused (singleton endpoint)."""
        payload = {k: v for k, v in config.items() if k not in ("id", "name")}
        self.zia_put("/zia/api/v1/browserControlSettings", payload)
        return True

    # ------------------------------------------------------------------
    # Tenancy Restriction Profiles
    # ------------------------------------------------------------------

    _TENANCY_PATH = "/zia/api/v1/tenancyRestrictionProfile"

    def list_tenancy_restriction_profiles(self) -> List[Dict]:
        return self.zia_get(self._TENANCY_PATH)

    def create_tenancy_restriction_profile(self, config: Dict) -> Dict:
        return self.zia_post(self._TENANCY_PATH, config)

    def update_tenancy_restriction_profile(self, rule_id: str, config: Dict) -> Dict:
        return self.zia_put(f"{self._TENANCY_PATH}/{rule_id}", config)

    def delete_tenancy_restriction_profile(self, rule_id: str) -> None:
        self.zia_delete(f"{self._TENANCY_PATH}/{rule_id}")
