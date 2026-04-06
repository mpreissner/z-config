"""ZDX (Zscaler Digital Experience) API client — SDK-backed.

Uses the zscaler-sdk-python ZDXService via the same ZscalerClient instance
pattern as ZIAClient/ZPAClient.  No separate token management required.

OneAPI endpoint base: /zdx/v1  (confirmed against Postman collection and
live tenant — NOT /zdx/api/v1 which returns 404).
"""

from typing import Dict, List, Optional

from zscaler import ZscalerClient

from .auth import ZscalerAuth


def _unwrap(result, resp, err):
    if err:
        raise RuntimeError(str(err))
    return result


def _to_dict(obj) -> dict:
    """Convert an SDK model object to a plain dict.

    Falls back to vars() when as_dict() returns an empty dict — works around
    a known SDK bug in DeviceActiveApplications where as_dict() is a no-op.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "as_dict"):
        d = obj.as_dict()
        if d:
            return d
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {}


def _to_dicts(items) -> List[Dict]:
    if not items:
        return []
    return [_to_dict(i) for i in items]


class ZDXClient:
    """SDK-backed client for the Zscaler Digital Experience (ZDX) API."""

    def __init__(self, auth: ZscalerAuth):
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
        })

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(self, search: Optional[str] = None, hours: int = 2) -> List[Dict]:
        params: dict = {"since": hours}
        if search:
            params["q"] = search
        result, resp, err = self._sdk.zdx.devices.list_devices(query_params=params)
        wrapper = _unwrap(result, resp, err)
        # SDK returns [Devices({devices: [...], next_offset: ...})]
        devices = wrapper[0].devices if wrapper else []
        return _to_dicts(devices)

    def get_device(self, device_id: str) -> Dict:
        result, resp, err = self._sdk.zdx.devices.get_device(device_id)
        items = _unwrap(result, resp, err)
        return _to_dict(items[0]) if items else {}

    def get_device_health(self, device_id: str, hours: int) -> Dict:
        """Return health data as {metrics: [{metric, value, unit}]}.

        The SDK returns a list of {category, instances:[{metrics:[{metric, unit,
        datapoints:[{timestamp, value}]}]}]}.  We flatten it to the most recent
        non-negative value per series so the menu table renders cleanly.
        The full SDK payload is preserved under 'raw' for the JSON fallback view.
        """
        result, resp, err = self._sdk.zdx.devices.get_health_metrics(
            device_id, query_params={"since": hours}
        )
        categories = _unwrap(result, resp, err) or []
        flat: List[Dict] = []
        raw = []
        for cat in categories:
            cat_dict = _to_dict(cat)
            raw.append(cat_dict)
            category = cat_dict.get("category") or ""
            for inst in cat_dict.get("instances") or []:
                for m in inst.get("metrics") or []:
                    metric_name = f"{category}.{m.get('metric', '')}"
                    unit = m.get("unit") or ""
                    datapoints = m.get("datapoints") or []
                    # Most recent non-negative value
                    value = next(
                        (dp["value"] for dp in reversed(datapoints)
                         if dp.get("value", -1) >= 0),
                        None,
                    )
                    flat.append({"metric": metric_name, "value": value, "unit": unit})
        return {"metrics": flat, "raw": raw}

    def get_device_events(self, device_id: str, hours: int) -> List[Dict]:
        result, resp, err = self._sdk.zdx.devices.get_events(
            device_id, query_params={"since": hours}
        )
        return _to_dicts(_unwrap(result, resp, err))

    def list_device_apps(self, device_id: str, hours: int) -> List[Dict]:
        # SDK bug: DeviceActiveApplications deserializes the plain-array response
        # as a single object, yielding all-None fields.  Use resp.get_body() directly.
        _, resp, err = self._sdk.zdx.devices.get_device_apps(
            device_id, query_params={"since": hours}
        )
        if err:
            raise RuntimeError(str(err))
        body = resp.get_body()
        return body if isinstance(body, list) else []

    def get_device_app(self, device_id: str, app_id: str, hours: int) -> List[Dict]:
        # Same plain-array response pattern — use resp.get_body() for correctness.
        _, resp, err = self._sdk.zdx.devices.get_device_app(
            device_id, app_id, query_params={"since": hours}
        )
        if err:
            raise RuntimeError(str(err))
        body = resp.get_body()
        return body if isinstance(body, list) else ([body] if body else [])

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def list_users(self, search: Optional[str] = None) -> List[Dict]:
        params: dict = {}
        if search:
            params["q"] = search
        result, resp, err = self._sdk.zdx.users.list_users(query_params=params)
        wrapper = _unwrap(result, resp, err)
        # SDK returns [ActiveUsers({users: [...]})]
        users = wrapper[0].users if wrapper else []
        return _to_dicts(users)

    # ------------------------------------------------------------------
    # Apps (global)
    # ------------------------------------------------------------------

    def list_apps(self, hours: int = 2) -> List[Dict]:
        result, resp, err = self._sdk.zdx.apps.list_apps(query_params={"since": hours})
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Deep Trace
    # ------------------------------------------------------------------

    def list_deep_traces(self, device_id: str) -> List[Dict]:
        result, resp, err = self._sdk.zdx.troubleshooting.list_deeptraces(device_id)
        return _to_dicts(_unwrap(result, resp, err))

    def start_deep_trace(
        self,
        device_id: str,
        session_name: str,
        app_id: Optional[str] = None,
    ) -> Dict:
        kwargs: dict = {"session_name": session_name}
        if app_id:
            kwargs["app_id"] = app_id
        result, resp, err = self._sdk.zdx.troubleshooting.start_deeptrace(
            device_id, **kwargs
        )
        return _to_dict(_unwrap(result, resp, err))

    def get_deep_trace(self, device_id: str, trace_id: str) -> Dict:
        result, resp, err = self._sdk.zdx.troubleshooting.get_deeptrace(
            device_id, trace_id
        )
        return _to_dict(_unwrap(result, resp, err))

    def stop_deep_trace(self, device_id: str, trace_id: str) -> None:
        result, resp, err = self._sdk.zdx.troubleshooting.delete_deeptrace(
            device_id, trace_id
        )
        _unwrap(result, resp, err)
