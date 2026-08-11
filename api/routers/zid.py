"""ZIdentity (ZID) API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zidentity_client import ZIdentityClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zidentity_service import ZIdentityService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
        govcloud=bool(tenant.govcloud),
        gov_tier=tenant.gov_cloud_tier,
    )
    client = ZIdentityClient(auth, tenant.oneapi_base_url)
    return ZIdentityService(client, tenant_id=tenant.id)


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------

@router.get("/{tenant}/users")
def list_users(
    tenant: str,
    login_name: Optional[str] = None,
    display_name: Optional[str] = None,
    primary_email: Optional[str] = None,
    domain_name: Optional[str] = None,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_service(tenant, user)
    return svc.list_users(
        login_name=login_name,
        display_name=display_name,
        primary_email=primary_email,
        domain_name=domain_name,
    )


@router.get("/{tenant}/users/{user_id}")
def get_user(tenant: str, user_id: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.get_user(user_id)


@router.post("/{tenant}/users", status_code=201)
def create_user(tenant: str, body: dict, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    return svc.create_user(body)


@router.put("/{tenant}/users/{user_id}")
def update_user(tenant: str, user_id: str, body: dict, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    username = body.get("loginName") or body.get("login_name") or user_id
    return svc.update_user(user_id, username, body)


@router.delete("/{tenant}/users/{user_id}", status_code=204)
def delete_user(tenant: str, user_id: str, body: dict = None, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    username = (body or {}).get("username") or user_id
    svc.delete_user(user_id, username)
    return Response(status_code=204)


@router.post("/{tenant}/users/{user_id}/reset-password")
def reset_password(tenant: str, user_id: str, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    result = svc.reset_password(user_id, username=user_id)
    return {"temporary_password": result.get("temporaryPassword") or result.get("temporary_password", "")}


class SetPasswordRequest(BaseModel):
    password: str
    reset_on_login: bool = False


@router.put("/{tenant}/users/{user_id}/password")
def set_password(tenant: str, user_id: str, body: SetPasswordRequest, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    svc.update_password(user_id, username=user_id, new_password=body.password, reset_on_login=body.reset_on_login)
    return {"ok": True}


class SkipMfaRequest(BaseModel):
    until_timestamp: int


@router.post("/{tenant}/users/{user_id}/skip-mfa")
def skip_mfa(tenant: str, user_id: str, body: SkipMfaRequest, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    svc.skip_mfa(user_id, username=user_id, until_timestamp=body.until_timestamp)
    return {"ok": True}


# ------------------------------------------------------------------
# Groups
# ------------------------------------------------------------------

@router.get("/{tenant}/groups")
def list_groups(
    tenant: str,
    name: Optional[str] = None,
    exclude_dynamic: bool = False,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_service(tenant, user)
    return svc.list_groups(name=name, exclude_dynamic=exclude_dynamic)


@router.get("/{tenant}/groups/{group_id}")
def get_group(tenant: str, group_id: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.get_group(group_id)


@router.get("/{tenant}/groups/{group_id}/members")
def list_group_members(tenant: str, group_id: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.list_group_members(group_id)


class GroupMemberRequest(BaseModel):
    user_id: str
    username: str


@router.post("/{tenant}/groups/{group_id}/members")
def add_group_member(
    tenant: str,
    group_id: str,
    body: GroupMemberRequest,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    svc.add_user_to_group(group_id, group_name=group_id, user_id=body.user_id, username=body.username)
    return {"ok": True}


@router.delete("/{tenant}/groups/{group_id}/members/{member_user_id}", status_code=204)
def remove_group_member(
    tenant: str,
    group_id: str,
    member_user_id: str,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    svc.remove_user_from_group(group_id, group_name=group_id, user_id=member_user_id, username=member_user_id)
    return Response(status_code=204)


# ------------------------------------------------------------------
# API Clients
# ------------------------------------------------------------------

@router.get("/{tenant}/api-clients")
def list_api_clients(tenant: str, name: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.list_api_clients(name=name)


@router.get("/{tenant}/api-clients/{client_id}")
def get_api_client(tenant: str, client_id: str, user: AuthUser = Depends(require_auth)):
    svc = _get_service(tenant, user)
    return svc.get_api_client(client_id)


@router.get("/{tenant}/api-clients/{client_id}/secrets")
def get_api_client_secrets(tenant: str, client_id: str, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    return svc.get_api_client_secrets(client_id)


class AddSecretRequest(BaseModel):
    expires_at: Optional[str] = None


@router.post("/{tenant}/api-clients/{client_id}/secrets")
def add_api_client_secret(
    tenant: str,
    client_id: str,
    body: AddSecretRequest,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.add_api_client_secret(client_id, client_name=client_id, expires_at=body.expires_at)


@router.delete("/{tenant}/api-clients/{client_id}/secrets/{secret_id}", status_code=204)
def delete_api_client_secret(
    tenant: str,
    client_id: str,
    secret_id: str,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    svc.delete_api_client_secret(client_id, client_name=client_id, secret_id=secret_id)
    return Response(status_code=204)


@router.delete("/{tenant}/api-clients/{client_id}", status_code=204)
def delete_api_client(tenant: str, client_id: str, user: AuthUser = Depends(require_admin)):
    svc = _get_service(tenant, user)
    svc.delete_api_client(client_id, client_name=client_id)
    return Response(status_code=204)
