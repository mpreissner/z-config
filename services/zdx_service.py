"""ZDX service — thin wrapper with audit logging."""

from typing import Dict, List, Optional

from lib.zdx_client import ZDXClient
from services import audit_service


class ZDXService:
    def __init__(self, client: ZDXClient, tenant_id: int):
        self.client = client
        self.tenant_id = tenant_id

    def search_devices(self, query: Optional[str] = None, hours: int = 2) -> List[Dict]:
        result = self.client.list_devices(search=query, hours=hours)
        audit_service.log(
            product="ZDX",
            operation="list_devices",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            details={"query": query, "hours": hours},
        )
        return result

    def get_device_summary(self, device_id: str, hours: int) -> Dict:
        health = {}
        events: List[Dict] = []
        try:
            health = self.client.get_device_health(device_id, hours)
        except Exception:
            pass
        try:
            events = self.client.get_device_events(device_id, hours)
        except Exception:
            pass
        audit_service.log(
            product="ZDX",
            operation="get_device_summary",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="device",
            resource_id=device_id,
            details={"hours": hours},
        )
        return {"health": health, "events": events}

    def lookup_user(self, query: str) -> List[Dict]:
        result = self.client.list_users(search=query)
        audit_service.log(
            product="ZDX",
            operation="lookup_user",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            details={"query": query},
        )
        return result
