import time
from typing import Dict, List, Optional

import requests
from zscaler import ZscalerClient

from .auth import ZscalerAuth

# The FedRAMP OneAPI gateways (api.zscalergov.us / .net) authenticate the token
# but have no upstream for the /zcc service: every path under /zcc answers 500
# with a zero-length body, valid or not, while /zia and /zpa behave normally.
# There is nothing a client can do about it, so refuse to build one rather than
# emit a wall of opaque 500s. Remove this guard once Zscaler routes ZCC on gov.
ZCC_GOVCLOUD_UNAVAILABLE = (
    "ZCC is not available on GovCloud tenants — the FedRAMP OneAPI gateway "
    "does not serve the ZCC API. ZIA and ZPA are unaffected."
)


class ZCCUnavailableError(RuntimeError):
    """ZCC cannot be reached for this tenant's cloud."""


# Integer → human label (used by service layer and menus)
OS_TYPE_LABELS: Dict[int, str] = {
    1: "iOS",
    2: "Android",
    3: "Windows",
    4: "macOS",
    5: "Linux",
}

REGISTRATION_STATE_LABELS: Dict[int, str] = {
    0: "All (except Removed)",
    1: "Registered",
    3: "Removal Pending",
    4: "Unregistered",
    5: "Removed",
    6: "Quarantined",
}

# Integer → SDK string name (what the zcc_param_mapper expects)
_OS_TYPE_SDK: Dict[int, str] = {
    1: "ios",
    2: "android",
    3: "windows",
    4: "macos",
    5: "linux",
}

_REG_STATE_SDK: Dict[int, str] = {
    0: "all",
    1: "registered",
    3: "removal_pending",
    4: "unregistered",
    5: "removed",
    6: "quarantined",
}


def _unwrap(result, resp, err):
    if err:
        raise RuntimeError(str(err))
    return result


def _to_dicts(items) -> list:
    if not items:
        return []
    return [
        i if isinstance(i, dict) else (i.as_dict() if hasattr(i, "as_dict") else vars(i))
        for i in items
    ]


def _to_dict(item) -> dict:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if hasattr(item, "as_dict"):
        return item.as_dict()
    return vars(item)


def _to_camel_dict(obj) -> dict:
    """Recursively convert a SDK ZscalerObject to a camelCase plain dict.

    Uses request_format() (camelCase keys) rather than as_dict() (snake_case).
    This avoids the ZscalerCollection.form_list mutation side-effect that
    contaminates resp.get_body() with non-serialisable SDK model instances.
    """
    if hasattr(obj, "request_format"):
        return {
            k: _to_camel_dict(v)
            for k, v in obj.request_format().items()
            if v is not None
        }
    if isinstance(obj, dict):
        return {k: _to_camel_dict(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_to_camel_dict(i) for i in obj]
    return obj


class ZCCClient:
    """SDK adapter for the Zscaler Client Connector (ZCC) API.

    All query_params and kwargs use snake_case — the SDK's zcc_param_mapper
    decorator handles conversion to the camelCase names the API expects.
    """

    def __init__(
        self,
        auth: ZscalerAuth,
        oneapi_base_url: str = "https://api.zsapi.net",
        zia_cloud: Optional[str] = None,
        zia_tenant_id: Optional[str] = None,
    ):
        if auth.govcloud:
            raise ZCCUnavailableError(ZCC_GOVCLOUD_UNAVAILABLE)
        self.auth = auth
        sdk_config = {
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        }
        if auth.sdk_cloud:
            sdk_config["cloud"] = auth.sdk_cloud
        self._sdk = ZscalerClient(sdk_config)
        self._zcc_base = f"{oneapi_base_url}/zcc/papi/public/v1"
        self._zia_cloud = zia_cloud
        self._zia_tenant_id = zia_tenant_id
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Direct HTTP helpers (for SDK-missing endpoints)
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        resp = requests.post(
            f"{self.auth.zidentity_base_url}/oauth2/v1/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.auth.client_id,
                "client_secret": self.auth.client_secret,
                "audience": "https://api.zscaler.com",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def _direct_get(self, path: str, params: Optional[dict] = None) -> Dict:
        resp = requests.get(
            f"{self._zcc_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _direct_put(self, path: str, json: Optional[dict] = None) -> Dict:
        resp = requests.put(
            f"{self._zcc_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            json=json,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _direct_patch(self, path: str, json: Optional[dict] = None) -> Dict:
        resp = requests.patch(
            f"{self._zcc_base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            json=json,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(
        self,
        username: Optional[str] = None,
        os_type: Optional[int] = None,
        page_size: int = 500,
    ) -> List[Dict]:
        params: Dict = {"page_size": page_size}
        if username:
            params["username"] = username
        if os_type is not None:
            params["os_type"] = _OS_TYPE_SDK.get(os_type, str(os_type))
        result, resp, err = self._sdk.zcc.devices.list_devices(query_params=params)
        return _to_dicts(_unwrap(result, resp, err))

    def get_device_details(
        self,
        username: Optional[str] = None,
        udid: Optional[str] = None,
    ) -> Dict:
        params: Dict = {}
        if username:
            params["username"] = username
        if udid:
            params["udid"] = udid
        result, resp, err = self._sdk.zcc.devices.get_device_details(query_params=params)
        return _to_dict(_unwrap(result, resp, err))

    def remove_devices(
        self,
        username: Optional[str] = None,
        udids: Optional[List[str]] = None,
        os_type: Optional[int] = None,
        client_connector_version: Optional[List[str]] = None,
        page_size: int = 500,
    ) -> Dict:
        kwargs: Dict = {}
        if username:
            kwargs["user_name"] = username
        if udids:
            kwargs["udids"] = udids
        if os_type is not None:
            kwargs["os_type"] = _OS_TYPE_SDK.get(os_type, str(os_type))
        if client_connector_version:
            kwargs["client_connector_version"] = client_connector_version
        result, resp, err = self._sdk.zcc.devices.remove_devices(
            query_params={"page_size": page_size}, **kwargs
        )
        return _to_dict(_unwrap(result, resp, err))

    def force_remove_devices(
        self,
        username: Optional[str] = None,
        udids: Optional[List[str]] = None,
        os_type: Optional[int] = None,
        client_connector_version: Optional[List[str]] = None,
        page_size: int = 500,
    ) -> Dict:
        kwargs: Dict = {}
        if username:
            kwargs["user_name"] = username
        if udids:
            kwargs["udids"] = udids
        if os_type is not None:
            kwargs["os_type"] = _OS_TYPE_SDK.get(os_type, str(os_type))
        if client_connector_version:
            kwargs["client_connector_version"] = client_connector_version
        result, resp, err = self._sdk.zcc.devices.force_remove_devices(
            query_params={"page_size": page_size}, **kwargs
        )
        return _to_dict(_unwrap(result, resp, err))

    def download_devices(
        self,
        filename: str,
        os_types: Optional[List[int]] = None,
        registration_types: Optional[List[int]] = None,
    ):
        params: Dict = {}
        if os_types:
            params["os_types"] = [_OS_TYPE_SDK.get(t, str(t)) for t in os_types]
        if registration_types:
            params["registration_types"] = [_REG_STATE_SDK.get(t, str(t)) for t in registration_types]
        result, resp, err = self._sdk.zcc.devices.download_devices(
            query_params=params, filename=filename
        )
        return _unwrap(result, resp, err)

    def download_service_status(
        self,
        filename: str,
        os_types: Optional[List[int]] = None,
        registration_types: Optional[List[int]] = None,
    ):
        params: Dict = {}
        if os_types:
            params["os_types"] = [_OS_TYPE_SDK.get(t, str(t)) for t in os_types]
        if registration_types:
            params["registration_types"] = [_REG_STATE_SDK.get(t, str(t)) for t in registration_types]
        result, resp, err = self._sdk.zcc.devices.download_service_status(
            query_params=params, filename=filename
        )
        return _unwrap(result, resp, err)

    def download_disable_reasons(
        self,
        filename: str,
        start_date: str,
        end_date: str,
        os_type: Optional[int] = None,
        time_zone: Optional[str] = None,
    ) -> str:
        """Download disable-reasons CSV via direct HTTP.

        startDate and endDate (YYYY-MM-DD) are required by the API.
        The SDK wrapper for this endpoint is still broken (as of 1.9.21) — it
        raises if the Content-Type is not application/octet-stream AND the CSV
        header does not start with '"User","Device type"'. The actual response
        columns are: User, UDID, Platform, Service, Disable Time, Disable Reason.
        """
        params: Dict = {"startDate": start_date, "endDate": end_date}
        if os_type is not None:
            params["osType"] = os_type
        headers: Dict = {"Authorization": f"Bearer {self._get_token()}", "Accept": "*/*"}
        if time_zone:
            headers["Time-Zone"] = time_zone

        resp = requests.get(
            f"{self._zcc_base}/downloadDisableReasons",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()

        with open(filename, "wb") as f:
            f.write(resp.content)
        return filename

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    def get_otp(self, udid: str) -> Dict:
        result, resp, err = self._sdk.zcc.secrets.get_otp(query_params={"udid": udid})
        return _to_dict(_unwrap(result, resp, err))

    def get_passwords(self, username: str, os_type: int) -> Dict:
        result, resp, err = self._sdk.zcc.secrets.get_passwords(
            query_params={"username": username, "os_type": _OS_TYPE_SDK.get(os_type, str(os_type))}
        )
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Trusted Networks
    # ------------------------------------------------------------------

    def list_trusted_networks(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.trusted_networks.list_by_company()
        return _to_dicts(_unwrap(result, resp, err))

    # Trusted Networks (write)

    def create_trusted_network(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zcc.trusted_networks.add_trusted_network(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def update_trusted_network(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zcc.trusted_networks.update_trusted_network(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def delete_trusted_network(self, network_id: int) -> None:
        _, _, err = self._sdk.zcc.trusted_networks.delete_trusted_network(network_id)
        if err:
            raise RuntimeError(str(err))

    # ------------------------------------------------------------------
    # Forwarding Profiles
    # ------------------------------------------------------------------

    def list_forwarding_profiles(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.forwarding_profile.list_by_company()
        return _to_dicts(_unwrap(result, resp, err))

    # Forwarding Profiles (write)

    def update_forwarding_profile(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zcc.forwarding_profile.update_forwarding_profile(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def delete_forwarding_profile(self, profile_id: int) -> None:
        _, _, err = self._sdk.zcc.forwarding_profile.delete_forwarding_profile(profile_id)
        if err:
            raise RuntimeError(str(err))

    # ------------------------------------------------------------------
    # Admin Users
    # ------------------------------------------------------------------

    def list_admin_users(self) -> List[Dict]:
        # userType is mandatory (1=ZIA, 2=ZPA, 3=ZID, 4=ZDX); fetch all types and deduplicate
        seen: set = set()
        merged: List[Dict] = []
        for user_type in (1, 2, 3, 4):
            result, resp, err = self._sdk.zcc.admin_user.list_admin_users(
                query_params={"userType": user_type}
            )
            if err:
                continue
            for item in _to_dicts(_unwrap(result, resp, err)):
                uid = item.get("id") or item.get("userId") or str(item)
                if uid not in seen:
                    seen.add(uid)
                    merged.append(item)
        return merged

    # ------------------------------------------------------------------
    # Entitlements
    # ------------------------------------------------------------------

    def get_zpa_entitlements(self) -> Dict:
        return self._direct_get("getZpaGroupEntitlements")

    def get_zdx_entitlements(self) -> Dict:
        return self._direct_get("getZdxGroupEntitlements")

    def update_zpa_entitlements(self, payload: Dict) -> Dict:
        return self._direct_put("updateZpaGroupEntitlement", json=payload)

    def update_zdx_entitlements(self, payload: Dict) -> Dict:
        return self._direct_put("updateZdxGroupEntitlement", json=payload)

    # ------------------------------------------------------------------
    # Web App Services (Custom App Bypass definitions)
    # ------------------------------------------------------------------

    def list_web_app_services(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.web_app_service.list_by_company()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Web Policies (App Profiles)
    # ------------------------------------------------------------------

    def list_web_policies(self) -> List[Dict]:
        # Use the direct HTTP endpoint so that onNetPolicy (the embedded forwarding
        # profile object) is preserved in raw_config. The SDK's request_format()
        # strips onNetPolicy, making forwarding-profile lookup impossible.
        # Query only desktop OS types — iOS/Android use MDM-managed policies, not
        # ZCC Agent routing profiles, and those endpoints hang on unsupported tenants.
        _DESKTOP_TYPES = {3: "windows", 4: "macos", 5: "linux"}
        seen_ids: set = set()
        all_policies: List[Dict] = []
        for dt_int, dt_str in _DESKTOP_TYPES.items():
            try:
                data = self._direct_get(
                    "web/policy/listByCompany", params={"deviceType": dt_int}
                )
            except Exception:
                continue
            items = data if isinstance(data, list) else data.get("list", [])
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                pid = item.get("id")
                if pid is None or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                item["device_type"] = dt_str  # injected so the DB record is self-describing
                all_policies.append(item)
        return all_policies

    # ------------------------------------------------------------------
    # Fail Open Policy
    # ------------------------------------------------------------------

    def list_fail_open_policies(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.fail_open_policy.list_by_company()
        return _to_dicts(_unwrap(result, resp, err))

    # Fail Open Policy (write)

    def update_fail_open_policy(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zcc.fail_open_policy.update_failopen_policy(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Web Privacy
    # ------------------------------------------------------------------

    def get_web_privacy(self) -> Dict:
        result = self._sdk.zcc.web_privacy.get_web_privacy()
        if result is None:
            return {}
        return _to_dict(result)

    def get_web_privacy_singleton(self) -> List[Dict]:
        """Wraps get_web_privacy() as a list for uniform import service handling."""
        item = self.get_web_privacy()
        if not item:
            return []
        if "id" not in item:
            item = dict(item)
            item["id"] = "1"
        return [item]

    # Web Privacy (write)

    def set_web_privacy(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zcc.web_privacy.set_web_privacy_info(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Device Cleanup

    def get_device_cleanup(self) -> Dict:
        return self._direct_get("getDeviceCleanupInfo")

    def set_device_cleanup(self, **kwargs) -> Dict:
        return self._direct_put("setDeviceCleanupInfo", json=kwargs)

    def get_device_cleanup_singleton(self) -> List[Dict]:
        """Wraps get_device_cleanup() as a list for uniform import service handling."""
        item = self.get_device_cleanup()
        if not item:
            return []
        item = dict(item)
        item.setdefault("id", "1")
        return [item]

    # ------------------------------------------------------------------
    # Application Profiles

    def list_application_profiles(self) -> List[Dict]:
        data = self._direct_get("application-profiles")
        return data if isinstance(data, list) else (data.get("list", []) if isinstance(data, dict) else [])

    def update_application_profile(self, profile_id: str, **kwargs) -> Dict:
        return self._direct_patch(f"application-profiles/{profile_id}", json=kwargs)

    # ------------------------------------------------------------------
    # Entitlement singleton wrappers

    def get_zpa_entitlements_singleton(self) -> List[Dict]:
        """Wraps get_zpa_entitlements() as a list for uniform import service handling."""
        item = self.get_zpa_entitlements()
        if not item:
            return []
        item = dict(item) if isinstance(item, dict) else {"data": item}
        item.setdefault("id", "1")
        return [item]

    def get_zdx_entitlements_singleton(self) -> List[Dict]:
        """Wraps get_zdx_entitlements() as a list for uniform import service handling."""
        item = self.get_zdx_entitlements()
        if not item:
            return []
        item = dict(item) if isinstance(item, dict) else {"data": item}
        item.setdefault("id", "1")
        return [item]

    # ------------------------------------------------------------------
    # Company Info
    # ------------------------------------------------------------------

    def list_company_info(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.company.get_company_info()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Admin Roles
    # ------------------------------------------------------------------

    def list_admin_roles(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.admin_user.list_admin_roles()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # IP-based bypass apps (predefined + custom) and process-based apps
    # ------------------------------------------------------------------

    def list_ip_apps_predefined(self) -> List[Dict]:
        data = self._direct_get("predefined-ip-based-apps")
        return data if isinstance(data, list) else (data.get("list", []) if isinstance(data, dict) else [])

    def list_ip_apps_custom(self) -> List[Dict]:
        data = self._direct_get("custom-ip-based-apps")
        return data if isinstance(data, list) else (data.get("list", []) if isinstance(data, dict) else [])

    def list_process_apps(self) -> List[Dict]:
        data = self._direct_get("process-based-apps")
        return data if isinstance(data, list) else (data.get("list", []) if isinstance(data, dict) else [])

    def edit_web_policy(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zcc.web_policy.web_policy_edit(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def activate_web_policy(self, policy_id: int, device_type: str) -> Dict:
        result, resp, err = self._sdk.zcc.web_policy.activate_web_policy(
            policy_id=policy_id, device_type=device_type
        )
        return _to_dict(_unwrap(result, resp, err))

    def delete_web_policy(self, policy_id: int) -> None:
        _, _, err = self._sdk.zcc.web_policy.delete_web_policy(policy_id)
        if err:
            raise Exception(str(err))

