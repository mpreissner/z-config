from dataclasses import dataclass
from typing import Optional
from fastapi import Depends, HTTPException, Header, Query
from api.auth_utils import decode_token
from jose import JWTError


@dataclass
class AuthUser:
    user_id: int
    username: str
    role: str
    force_password_change: bool
    mfa_enroll: bool = False


def require_auth(authorization: Optional[str] = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(authorization.removeprefix("Bearer "))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return AuthUser(
        user_id=int(payload["sub"]),
        username=payload["username"],
        role=payload["role"],
        force_password_change=payload.get("fpc", False),
        mfa_enroll=payload.get("mfa_enroll", False),
    )


def require_auth_sse(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
) -> AuthUser:
    """Auth dependency for SSE endpoints — accepts token via query param or Authorization header.

    EventSource cannot send custom headers, so the JWT is passed as ?token=<jwt>.
    """
    raw = token
    if raw is None and authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ")
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(raw)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return AuthUser(
        user_id=int(payload["sub"]),
        username=payload["username"],
        role=payload["role"],
        force_password_change=payload.get("fpc", False),
        mfa_enroll=payload.get("mfa_enroll", False),
    )


def require_admin(user: AuthUser = Depends(require_auth)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def check_tenant_access(tenant_id: int, user: AuthUser) -> None:
    """Raise 404 if user has no entitlement for tenant_id.

    Always enforced regardless of role — admins are not exempt.
    Use an explicit `if user.role != "admin"` guard before calling this
    for endpoints that intentionally allow admins through.
    Uses 404 (not 403) to avoid leaking tenant existence to unauthorized users.
    Must never be called from inside an existing with get_session() block.
    """
    from db.database import get_session
    from db.models import UserTenantEntitlement
    with get_session() as session:
        row = session.query(UserTenantEntitlement).filter_by(
            user_id=user.user_id, tenant_id=tenant_id
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
