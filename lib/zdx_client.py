"""ZDX (Zscaler Digital Experience) API client.

Uses direct HTTP with an OAuth2 client_credentials token — no SDK module
exists for ZDX. Token is cached with a 30-second early-refresh buffer.
"""

import time
from typing import Dict, List, Optional

import requests

from .auth import ZscalerAuth


class ZDXClient:
    """Direct-HTTP client for the Zscaler Digital Experience (ZDX) API."""

    def __init__(self, auth: ZscalerAuth, oneapi_base_url: str = "https://api.zsapi.net"):
        self.auth = auth
        self._base = f"{oneapi_base_url}/zdx/api/v1"
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Auth helpers
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

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        resp = requests.get(
            f"{self._base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _post(self, path: str, json: Optional[dict] = None) -> dict:
        resp = requests.post(
            f"{self._base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            json=json,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _delete(self, path: str) -> None:
        resp = requests.delete(
            f"{self._base}/{path}",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            timeout=15,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Time range helper
    # ------------------------------------------------------------------

    def _time_range(self, hours: int) -> dict:
        """Return `from`/`to` query params as Unix timestamps."""
        now = int(time.time())
        return {"from": now - hours * 3600, "to": now}

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(self, search: Optional[str] = None, hours: int = 2) -> List[Dict]:
        params = self._time_range(hours)
        if search:
            params["q"] = search
        result = self._get("devices", params=params)
        return result.get("devices") or result if isinstance(result, list) else []

    def get_device(self, device_id: str) -> Dict:
        return self._get(f"devices/{device_id}")

    def get_device_health(self, device_id: str, hours: int) -> Dict:
        params = self._time_range(hours)
        return self._get(f"devices/{device_id}/healthmetrics", params=params)

    def get_device_events(self, device_id: str, hours: int) -> List[Dict]:
        params = self._time_range(hours)
        result = self._get(f"devices/{device_id}/events", params=params)
        return result.get("events") or result if isinstance(result, list) else []

    def list_device_apps(self, device_id: str, hours: int) -> List[Dict]:
        params = self._time_range(hours)
        result = self._get(f"devices/{device_id}/apps", params=params)
        return result.get("apps") or result if isinstance(result, list) else []

    def get_device_app(self, device_id: str, app_id: str, hours: int) -> Dict:
        params = self._time_range(hours)
        return self._get(f"devices/{device_id}/apps/{app_id}", params=params)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def list_users(self, search: Optional[str] = None) -> List[Dict]:
        params: dict = {}
        if search:
            params["q"] = search
        result = self._get("users", params=params)
        return result.get("users") or result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Apps (global)
    # ------------------------------------------------------------------

    def list_apps(self, hours: int = 2) -> List[Dict]:
        params = self._time_range(hours)
        result = self._get("apps", params=params)
        return result.get("apps") or result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Deep Trace
    # ------------------------------------------------------------------

    def list_deep_traces(self, device_id: str) -> List[Dict]:
        result = self._get(f"devices/{device_id}/deeptraces")
        return result.get("deeptraces") or result if isinstance(result, list) else []

    def start_deep_trace(
        self,
        device_id: str,
        session_name: str,
        app_id: Optional[str] = None,
    ) -> Dict:
        payload: dict = {"sessionName": session_name}
        if app_id:
            payload["appId"] = app_id
        return self._post(f"devices/{device_id}/deeptraces", json=payload)

    def get_deep_trace(self, device_id: str, trace_id: str) -> Dict:
        return self._get(f"devices/{device_id}/deeptraces/{trace_id}")

    def stop_deep_trace(self, device_id: str, trace_id: str) -> None:
        self._delete(f"devices/{device_id}/deeptraces/{trace_id}")
