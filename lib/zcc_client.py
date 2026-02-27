from typing import Dict, List, Optional

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


class ZCCClient:
    """SDK adapter for the Zscaler Client Connector (ZCC) API.

    All query_params and kwargs use snake_case — the SDK's zcc_param_mapper
    decorator handles conversion to the camelCase names the API expects.
    """

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })

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
