import time
from typing import Dict, List, Optional

import requests
from zscaler import ZscalerClient

from .auth import ZscalerAuth

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
        self.auth = auth
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })
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
        The SDK wrapper for this endpoint is still broken (as of 1.9.20) — it
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

    # ------------------------------------------------------------------
    # Forwarding Profiles
    # ------------------------------------------------------------------

    def list_forwarding_profiles(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.forwarding_profile.list_by_company()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Admin Users
    # ------------------------------------------------------------------

    def list_admin_users(self) -> List[Dict]:
        result, resp, err = self._sdk.zcc.admin_user.list_admin_users()
        return _to_dicts(_unwrap(result, resp, err))

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
        # The API returns nothing without device_type; fetch per-OS and combine.
        # Use _to_camel_dict(wp) on each WebPolicy result object to get a
        # camelCase plain dict — avoids the ZscalerCollection.form_list mutation
        # side-effect that makes resp.get_body() non-JSON-serialisable.
        device_types = ["windows", "macos", "ios", "android", "linux"]
        seen_ids: set = set()
        all_policies: List[Dict] = []
        for dt in device_types:
            result, _, err = self._sdk.zcc.web_policy.list_by_company(
                query_params={"device_type": dt}
            )
            if err:
                continue
            for wp in (result or []):
                item = _to_camel_dict(wp)
                pid = item.get("id")
                if pid is None or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                item["device_type"] = dt  # injected so the DB record is self-describing
                all_policies.append(item)
        return all_policies

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

