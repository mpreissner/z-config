"""ZCC business logic layer.

Wraps ZCCClient with:
  - Audit logging for every mutating operation
  - OS type and registration state label helpers
"""

from typing import Dict, List, Optional

from lib.zcc_client import OS_TYPE_LABELS, REGISTRATION_STATE_LABELS, ZCCClient
from services import audit_service


class ZCCService:
    def __init__(self, client: ZCCClient, tenant_id: Optional[int] = None):
        self.client = client
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(
        self,
        username: Optional[str] = None,
        os_type: Optional[int] = None,
        page_size: int = 500,
    ) -> List[Dict]:
        result = self.client.list_devices(
            username=username, os_type=os_type, page_size=page_size
        )
        audit_service.log(
            product="ZCC",
            operation="list_devices",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="device",
            details={"count": len(result), "username_filter": username, "os_type": os_type},
        )
        return result

    def get_device_details(
        self,
        username: Optional[str] = None,
        udid: Optional[str] = None,
    ) -> Dict:
        return self.client.get_device_details(username=username, udid=udid)

    def remove_device(
        self,
        username: Optional[str] = None,
        udids: Optional[List[str]] = None,
        os_type: Optional[int] = None,
    ) -> Dict:
        result = self.client.remove_devices(username=username, udids=udids, os_type=os_type)
        audit_service.log(
            product="ZCC",
            operation="remove_device",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="device",
            details={"username": username, "udids": udids, "os_type": os_type},
        )
        return result

    def force_remove_device(
        self,
        username: Optional[str] = None,
        udids: Optional[List[str]] = None,
        os_type: Optional[int] = None,
    ) -> Dict:
        result = self.client.force_remove_devices(
            username=username, udids=udids, os_type=os_type
        )
        audit_service.log(
            product="ZCC",
            operation="force_remove_device",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="device",
            details={"username": username, "udids": udids, "os_type": os_type},
        )
        return result

    # ------------------------------------------------------------------
    # Secrets / credentials
    # ------------------------------------------------------------------

    def get_otp(self, udid: str) -> Dict:
        result = self.client.get_otp(udid=udid)
        audit_service.log(
            product="ZCC",
            operation="get_otp",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="device",
            details={"udid": udid},
        )
        return result

    def get_passwords(self, username: str, os_type: int) -> Dict:
        result = self.client.get_passwords(username=username, os_type=os_type)
        audit_service.log(
            product="ZCC",
            operation="get_passwords",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="device",
            details={"username": username, "os_type": self.os_label(os_type)},
        )
        return result

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def download_devices_csv(
        self,
        filename: str,
        os_types: Optional[List[int]] = None,
        registration_types: Optional[List[int]] = None,
    ):
        return self.client.download_devices(
            filename=filename,
            os_types=os_types,
            registration_types=registration_types,
        )

    def download_service_status_csv(
        self,
        filename: str,
        os_types: Optional[List[int]] = None,
        registration_types: Optional[List[int]] = None,
    ):
        return self.client.download_service_status(
            filename=filename,
            os_types=os_types,
            registration_types=registration_types,
        )

    # ------------------------------------------------------------------
    # Label helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Web App Services (Custom App Bypass definitions)
    # ------------------------------------------------------------------

    def list_web_app_services(self) -> List[Dict]:
        result = self.client.list_web_app_services()
        audit_service.log(
            product="ZCC",
            operation="list_web_app_services",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="web_app_service",
            details={"count": len(result)},
        )
        return result

    # ------------------------------------------------------------------
    # Web Policies (App Profiles)
    # ------------------------------------------------------------------

    def list_web_policies(self) -> List[Dict]:
        result = self.client.list_web_policies()
        audit_service.log(
            product="ZCC",
            operation="list_web_policies",
            action="READ",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="web_policy",
            details={"count": len(result)},
        )
        return result

    def edit_web_policy(self, **kwargs) -> Dict:
        result = self.client.edit_web_policy(**kwargs)
        policy_id = kwargs.get("id") or kwargs.get("policy_id")
        policy_name = kwargs.get("name", "")
        audit_service.log(
            product="ZCC",
            operation="edit_web_policy",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="web_policy",
            resource_id=str(policy_id) if policy_id else None,
            resource_name=policy_name,
        )
        return result

    def activate_web_policy(self, policy_id: int, device_type: str, name: str = "") -> Dict:
        result = self.client.activate_web_policy(policy_id=policy_id, device_type=device_type)
        audit_service.log(
            product="ZCC",
            operation="activate_web_policy",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="web_policy",
            resource_id=str(policy_id),
            resource_name=name,
            details={"device_type": device_type},
        )
        return result

    def delete_web_policy(self, policy_id: int, name: str = "") -> None:
        self.client.delete_web_policy(policy_id=policy_id)
        audit_service.log(
            product="ZCC",
            operation="delete_web_policy",
            action="DELETE",
            status="SUCCESS",
            tenant_id=self.tenant_id,
            resource_type="web_policy",
            resource_id=str(policy_id),
            resource_name=name,
        )

    # ------------------------------------------------------------------
    # Label helpers
    # ------------------------------------------------------------------

    @staticmethod
    def os_label(os_type: int) -> str:
        return OS_TYPE_LABELS.get(os_type, str(os_type))

    @staticmethod
    def registration_label(state: int) -> str:
        return REGISTRATION_STATE_LABELS.get(state, str(state))
