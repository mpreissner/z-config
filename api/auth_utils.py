import os
import time
from jose import jwt
from passlib.context import CryptContext

_ALGORITHM = "HS256"
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(plaintext: str) -> str:
    return _pwd_ctx.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plaintext, hashed)


def issue_access_token(user) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user.id, "username": user.username, "role": user.role,
         "fpc": user.force_password_change, "iat": now, "exp": now + 900},
        _secret(), algorithm=_ALGORITHM,
    )


def issue_refresh_token(user) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user.id, "type": "refresh", "iat": now, "exp": now + 604800},
        _secret(), algorithm=_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
