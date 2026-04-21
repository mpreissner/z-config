from dataclasses import dataclass
from typing import Optional
from fastapi import Depends, HTTPException, Header
from api.auth_utils import decode_token
from jose import JWTError


@dataclass
class AuthUser:
    user_id: int
    username: str
    role: str
    force_password_change: bool


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
    )


def require_admin(user: AuthUser = Depends(require_auth)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
