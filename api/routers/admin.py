import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel

from api.dependencies import require_admin, AuthUser
from api.auth_utils import hash_password
from db.database import get_session, init_db, get_db_url
from db.models import User, UserTenantEntitlement, TenantConfig

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    force_password_change: bool
    created_at: str
    last_login_at: Optional[str]

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: str = "user"
    force_password_change: bool = True


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    force_password_change: Optional[bool] = None
    mfa_required: Optional[bool] = None
    password: Optional[str] = None


class EntitlementOut(BaseModel):
    id: int
    user_id: int
    username: str
    tenant_id: int
    tenant_name: str
    granted_at: str


class EntitlementCreate(BaseModel):
    user_id: int
    tenant_id: int


# ── Users ─────────────────────────────────────────────────────────────────────

def _user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "force_password_change": u.force_password_change,
        "mfa_required": bool(u.mfa_required),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/users")
def list_users(_: AuthUser = Depends(require_admin)):
    with get_session() as session:
        users = session.query(User).order_by(User.username).all()
        return [_user_out(u) for u in users]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, _: AuthUser = Depends(require_admin)):
    if body.role not in ("admin", "user"):
        raise HTTPException(status_code=422, detail="role must be 'admin' or 'user'")
    with get_session() as session:
        if session.query(User).filter_by(username=body.username).first():
            raise HTTPException(status_code=409, detail="Username already exists")
        user = User(
            username=body.username,
            email=body.email,
            role=body.role,
            password_hash=hash_password(body.password),
            force_password_change=body.force_password_change,
            is_active=True,
        )
        session.add(user)
        session.flush()
        session.refresh(user)
        return _user_out(user)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, current: AuthUser = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.id == current.user_id and body.role is not None and body.role != "admin":
            raise HTTPException(status_code=400, detail="Cannot remove admin role from yourself")
        if user.id == current.user_id and body.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        if body.role is not None:
            if body.role not in ("admin", "user"):
                raise HTTPException(status_code=422, detail="role must be 'admin' or 'user'")
            user.role = body.role
        if body.email is not None:
            user.email = body.email
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.force_password_change is not None:
            user.force_password_change = body.force_password_change
        if body.mfa_required is not None:
            user.mfa_required = body.mfa_required
        if body.password:
            user.password_hash = hash_password(body.password)
        user.updated_at = datetime.utcnow()
        session.flush()
        session.refresh(user)
        return _user_out(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, current: AuthUser = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.id == current.user_id:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        session.delete(user)


# ── Entitlements ──────────────────────────────────────────────────────────────

def _ent_out(e: UserTenantEntitlement) -> dict:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "username": e.user.username,
        "tenant_id": e.tenant_id,
        "tenant_name": e.tenant.name,
        "granted_at": e.granted_at.isoformat() if e.granted_at else None,
    }


@router.get("/entitlements")
def list_entitlements(_: AuthUser = Depends(require_admin)):
    with get_session() as session:
        ents = (
            session.query(UserTenantEntitlement)
            .join(UserTenantEntitlement.user)
            .join(UserTenantEntitlement.tenant)
            .order_by(User.username, TenantConfig.name)
            .all()
        )
        return [_ent_out(e) for e in ents]


@router.post("/entitlements", status_code=201)
def create_entitlement(body: EntitlementCreate, _: AuthUser = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter_by(id=body.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        tenant = session.query(TenantConfig).filter_by(id=body.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        existing = session.query(UserTenantEntitlement).filter_by(
            user_id=body.user_id, tenant_id=body.tenant_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Entitlement already exists")
        ent = UserTenantEntitlement(user_id=body.user_id, tenant_id=body.tenant_id)
        session.add(ent)
        session.flush()
        session.refresh(ent)
        return _ent_out(ent)


@router.delete("/entitlements/{entitlement_id}", status_code=204)
def delete_entitlement(entitlement_id: int, _: AuthUser = Depends(require_admin)):
    with get_session() as session:
        ent = session.query(UserTenantEntitlement).filter_by(id=entitlement_id).first()
        if not ent:
            raise HTTPException(status_code=404, detail="Entitlement not found")
        session.delete(ent)


# ── Database Import ───────────────────────────────────────────────────────────

_SQLITE_MAGIC = b"SQLite format 3\x00"


@router.post("/import-db")
async def import_database(
    db_file: UploadFile = File(...),
    key_file: UploadFile = File(default=None),
    _: AuthUser = Depends(require_admin),
):
    """Replace the running database and (optionally) the encryption key.

    Accepts multipart/form-data with:
      - db_file  — SQLite database exported from a TUI zs-config install
      - key_file — secret.key Fernet key file (optional; omit if tenant secrets
                   were not encrypted or you are importing into a fresh install
                   that has not yet encrypted anything)

    The endpoint writes the new files and reinitialises the SQLAlchemy engine.
    A page reload is required after import.
    """
    db_path_str = os.environ.get("ZSCALER_DB_PATH")
    if not db_path_str:
        raise HTTPException(status_code=400, detail="ZSCALER_DB_PATH is not set; cannot determine where to write the database")

    db_path = Path(db_path_str)
    key_dir = db_path.parent

    # Read and validate the SQLite file
    db_bytes = await db_file.read()
    if len(db_bytes) < 16 or db_bytes[:16] != _SQLITE_MAGIC:
        raise HTTPException(status_code=422, detail="Uploaded file is not a valid SQLite database")

    # Write atomically: write to a temp file first, then replace
    tmp_db = db_path.with_suffix(".tmp")
    try:
        tmp_db.write_bytes(db_bytes)
        if sys.platform != "win32":
            tmp_db.chmod(0o600)
        shutil.move(str(tmp_db), str(db_path))
    except Exception as exc:
        tmp_db.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to write database: {exc}")

    # Write key file if provided
    if key_file is not None:
        key_bytes = await key_file.read()
        key_str = key_bytes.decode().strip()
        # Validate — must be a 44-char base64url string (Fernet key)
        if len(key_str) != 44:
            raise HTTPException(status_code=422, detail="Key file does not look like a valid Fernet key (expected 44 characters)")
        key_out = key_dir / "secret.key"
        key_out.write_text(key_str)
        if sys.platform != "win32":
            key_out.chmod(0o600)

    # Reinitialise the database engine against the new file
    try:
        init_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database reinitialisation failed: {exc}")

    # Seed a default admin if the imported DB has no admin accounts (e.g. TUI export)
    from api.main import seed_admin_if_needed
    temp_password = seed_admin_if_needed()

    return {
        "ok": True,
        "message": "Database imported successfully. Reload the page to continue.",
        "seeded_admin": temp_password is not None,
        "temp_password": temp_password,
    }

