import secrets
from datetime import datetime
from fastapi import APIRouter, HTTPException, Response, Cookie
from pydantic import BaseModel
from typing import Optional
from db.database import get_session
from db.models import User
from api.auth_utils import (
    verify_password, hash_password, issue_access_token,
    issue_refresh_token, decode_token,
)
from api.dependencies import require_auth, AuthUser
from fastapi import Depends
from jose import JWTError

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _set_refresh_cookie(response: Response, token: str):
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        samesite="strict",
        path="/api/v1/auth/refresh",
        secure=False,  # set ZS_SECURE_COOKIES=1 in production
    )


def _token_response(user: User) -> dict:
    return {
        "access_token": issue_access_token(user),
        "token_type": "bearer",
        "force_password_change": user.force_password_change,
    }


@router.post("/login")
def login(body: LoginRequest, response: Response):
    with get_session() as session:
        user = session.query(User).filter_by(username=body.username, is_active=True).first()
        if not user or not user.password_hash:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        user.last_login_at = datetime.utcnow()
        session.flush()
        session.refresh(user)
        access = issue_access_token(user)
        refresh = issue_refresh_token(user)
        fpc = user.force_password_change

    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer", "force_password_change": fpc}


@router.post("/refresh")
def refresh_token(response: Response, refresh_token: Optional[str] = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    with get_session() as session:
        user = session.query(User).filter_by(id=payload["sub"], is_active=True).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access = issue_access_token(user)
        new_refresh = issue_refresh_token(user)

    _set_refresh_cookie(response, new_refresh)
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="refresh_token", path="/api/v1/auth/refresh")
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, response: Response, user: AuthUser = Depends(require_auth)):
    with get_session() as session:
        db_user = session.query(User).filter_by(id=user.user_id, is_active=True).first()
        if not db_user or not verify_password(body.current_password, db_user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid current password")
        db_user.password_hash = hash_password(body.new_password)
        db_user.force_password_change = False
        session.flush()
        session.refresh(db_user)
        access = issue_access_token(db_user)
        refresh = issue_refresh_token(db_user)

    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer", "force_password_change": False}
