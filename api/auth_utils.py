import os
import time
import bcrypt
from jose import jwt

_ALGORITHM = "HS256"


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())


def issue_access_token(user) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user.id), "username": user.username, "role": user.role,
         "fpc": user.force_password_change, "iat": now, "exp": now + 900},
        _secret(), algorithm=_ALGORITHM,
    )


def issue_refresh_token(user) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user.id), "type": "refresh", "iat": now, "exp": now + 604800},
        _secret(), algorithm=_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
