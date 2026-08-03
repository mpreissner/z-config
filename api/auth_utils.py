import os
import secrets as _secrets_mod
import time
import bcrypt
from jose import jwt

_ALGORITHM = "HS256"
_ACCESS_TTL_DEFAULT = 300    # 5 minutes; not configurable via UI
_REFRESH_TTL_DEFAULT = 3600  # 60 minutes; configurable via admin settings

# Generated fresh on every container start. All refresh tokens signed with a
# previous nonce are rejected, preventing session re-use across restarts.
_STARTUP_NONCE = _secrets_mod.token_hex(16)


def _secret() -> str:
    return os.environ["JWT_SECRET"] + _STARTUP_NONCE


def _access_ttl() -> int:
    try:
        from db.database import get_setting
        v = get_setting("access_token_ttl")
        return int(v) if v else _ACCESS_TTL_DEFAULT
    except Exception:
        return _ACCESS_TTL_DEFAULT


def _refresh_ttl() -> int:
    try:
        from db.database import get_setting
        v = get_setting("refresh_token_ttl")
        return int(v) if v else _REFRESH_TTL_DEFAULT
    except Exception:
        return _REFRESH_TTL_DEFAULT


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())


def issue_access_token(user, *, mfa_enroll: bool = False, roles=None, active_role=None) -> str:
    """Mint an access token for one active role.

    `role` is the role this session is actually holding and the only thing any
    authorisation check reads; `roles` is everything the account could switch
    to. Callers already inside a session must pass `roles` themselves —
    working it out here would open a second one.
    """
    from services.role_service import available_roles, resolve_active

    if roles is None:
        roles = available_roles(user.id, user.role)
    active = resolve_active(roles, active_role)

    now = int(time.time())
    ttl = _access_ttl()
    payload: dict = {"sub": str(user.id), "username": user.username, "role": active,
                     "roles": list(roles),
                     "fpc": user.force_password_change, "iat": now, "exp": now + ttl}
    if mfa_enroll:
        payload["mfa_enroll"] = True
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def issue_refresh_token(user, *, active_role=None) -> str:
    """Mint a refresh token.

    It carries the active role so a refresh lands the session back where it
    was — without it, every five-minute refresh would silently drop an
    assumed admin back to least privilege.
    """
    now = int(time.time())
    ttl = _refresh_ttl()
    payload: dict = {"sub": str(user.id), "type": "refresh", "iat": now, "exp": now + ttl}
    if active_role:
        payload["role"] = active_role
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
