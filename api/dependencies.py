from dataclasses import dataclass, field
from typing import List, Optional
from fastapi import Depends, HTTPException, Header, Query
from api.auth_utils import decode_token
from jose import JWTError


@dataclass
class AuthUser:
    user_id: int
    username: str
    #: The role this session is holding. Every authorisation check reads this
    #: and only this — a role the account has but has not assumed grants
    #: nothing, which is what keeps admin and user from ever being live at once.
    role: str
    force_password_change: bool
    mfa_enroll: bool = False
    #: Everything the account could switch to, for the role picker.
    roles: List[str] = field(default_factory=list)


def _auth_user(payload: dict) -> AuthUser:
    return AuthUser(
        user_id=int(payload["sub"]),
        username=payload["username"],
        role=payload["role"],
        force_password_change=payload.get("fpc", False),
        mfa_enroll=payload.get("mfa_enroll", False),
        # Tokens minted before roles existed carry only the active one.
        roles=payload.get("roles") or [payload["role"]],
    )


def require_auth(authorization: Optional[str] = Header(default=None)) -> AuthUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(authorization.removeprefix("Bearer "))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return _auth_user(payload)


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
    return _auth_user(payload)


def require_admin(user: AuthUser = Depends(require_auth)) -> AuthUser:
    """Admin-only. Deliberately checks the assumed role, not what is available:
    an account that could be an admin but is holding `user` is refused until it
    assumes the role, and the switch is audited."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def check_tenant_access(tenant_id: int, user: AuthUser) -> None:
    """Raise 404 if user has no entitlement for tenant_id.

    A grant to any group the account belongs to counts, exactly as a direct
    grant does — group_service.effective_tenant_ids() is the one place that
    union is computed, so this and the tenant listing can never disagree.

    Always enforced regardless of role — admins are not exempt.
    Use an explicit `if user.role != "admin"` guard before calling this
    for endpoints that intentionally allow admins through.
    Uses 404 (not 403) to avoid leaking tenant existence to unauthorized users.
    Must never be called from inside an existing with get_session() block.
    """
    from services.group_service import effective_tenant_ids
    if tenant_id not in effective_tenant_ids(user.user_id):
        raise HTTPException(status_code=404, detail="Tenant not found")
