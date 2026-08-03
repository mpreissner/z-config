"""Admin API for groups, their members, and the tenants they grant.

Everything here is admin-only. The service layer holds the rules about what a
SCIM-provisioned group will and will not allow; this module translates its
GroupError into an HTTP status and writes the audit trail.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import require_admin, AuthUser
from services import group_service
from services.group_service import GroupError

router = APIRouter(prefix="/api/v1/admin/groups", tags=["Groups"])


def _audit(operation: str, action: str, name: Optional[str], details: Optional[dict] = None) -> None:
    from services import audit_service
    audit_service.log(
        product=None,
        operation=operation,
        action=action,
        status="SUCCESS",
        resource_type="group",
        resource_name=name,
        details=details,
    )


def _http(err: GroupError) -> HTTPException:
    return HTTPException(status_code=err.status, detail=str(err))


class GroupCreate(BaseModel):
    display_name: str
    description: Optional[str] = None
    mapped_role: Optional[str] = None


class GroupUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    # Sent as an explicit null to clear the mapping, so the field's presence is
    # what matters — see `fields_set` below.
    mapped_role: Optional[str] = None


class MemberAdd(BaseModel):
    user_ids: List[int]


class TenantGrant(BaseModel):
    tenant_ids: List[int]


@router.get("")
def list_groups(_: AuthUser = Depends(require_admin)):
    return group_service.list_groups()


@router.post("", status_code=201)
def create_group(body: GroupCreate, current: AuthUser = Depends(require_admin)):
    try:
        group = group_service.create_group(
            display_name=body.display_name,
            description=body.description,
            mapped_role=body.mapped_role,
        )
    except GroupError as e:
        raise _http(e)
    _audit("create_group", "CREATE", group["display_name"], {"by": current.username})
    return group


@router.get("/{group_id}")
def get_group(group_id: int, _: AuthUser = Depends(require_admin)):
    try:
        return group_service.get_group(group_id)
    except GroupError as e:
        raise _http(e)


@router.patch("/{group_id}")
def update_group(group_id: int, body: GroupUpdate, current: AuthUser = Depends(require_admin)):
    try:
        group = group_service.update_group(
            group_id,
            display_name=body.display_name,
            description=body.description,
            mapped_role=body.mapped_role,
            set_role="mapped_role" in body.model_fields_set,
        )
    except GroupError as e:
        raise _http(e)
    _audit(
        "update_group",
        "UPDATE",
        group["display_name"],
        {"by": current.username, "mapped_role": group["mapped_role"]},
    )
    return group


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int, current: AuthUser = Depends(require_admin)):
    try:
        name = group_service.delete_group(group_id)
    except GroupError as e:
        raise _http(e)
    _audit("delete_group", "DELETE", name, {"by": current.username})


@router.get("/{group_id}/members")
def list_members(group_id: int, _: AuthUser = Depends(require_admin)):
    try:
        return group_service.list_members(group_id)
    except GroupError as e:
        raise _http(e)


@router.post("/{group_id}/members", status_code=201)
def add_members(group_id: int, body: MemberAdd, current: AuthUser = Depends(require_admin)):
    try:
        result = group_service.add_members(group_id, body.user_ids, added_by=current.username)
    except GroupError as e:
        raise _http(e)
    if result["added"]:
        _audit(
            "add_group_members",
            "UPDATE",
            result["group_name"],
            {"by": current.username, "user_ids": result["added"]},
        )
    return result


@router.delete("/{group_id}/members/{user_id}", status_code=204)
def remove_member(group_id: int, user_id: int, current: AuthUser = Depends(require_admin)):
    try:
        group_service.remove_member(group_id, user_id)
    except GroupError as e:
        raise _http(e)
    _audit(
        "remove_group_member",
        "UPDATE",
        None,
        {"by": current.username, "group_id": group_id, "user_id": user_id},
    )


@router.get("/{group_id}/tenants")
def list_tenant_grants(group_id: int, _: AuthUser = Depends(require_admin)):
    try:
        return group_service.list_tenant_grants(group_id)
    except GroupError as e:
        raise _http(e)


@router.post("/{group_id}/tenants", status_code=201)
def grant_tenants(group_id: int, body: TenantGrant, current: AuthUser = Depends(require_admin)):
    try:
        result = group_service.grant_tenants(group_id, body.tenant_ids, granted_by=current.username)
    except GroupError as e:
        raise _http(e)
    if result["granted"]:
        _audit(
            "grant_group_tenants",
            "CREATE",
            result["group_name"],
            {"by": current.username, "tenant_ids": result["granted"]},
        )
    return result


@router.delete("/{group_id}/tenants/{tenant_id}", status_code=204)
def revoke_tenant(group_id: int, tenant_id: int, current: AuthUser = Depends(require_admin)):
    try:
        group_service.revoke_tenant(group_id, tenant_id)
    except GroupError as e:
        raise _http(e)
    _audit(
        "revoke_group_tenant",
        "DELETE",
        None,
        {"by": current.username, "group_id": group_id, "tenant_id": tenant_id},
    )
