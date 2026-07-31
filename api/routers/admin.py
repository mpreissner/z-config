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
from db.database import dispose_engine, get_session, get_setting, init_db, get_db_url
from db.models import (
    AuditLog, RestorePoint, ScimGroup, ScimGroupMember, ScimToken, SyncLog,
    TenantConfig, User, UserTenantEntitlement, ZCCResource, ZIAResource,
    ZPAResource,
)

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
        # The UI disables local username/role edits on IdP-owned accounts —
        # a SCIM sync would overwrite them on the next cycle anyway.
        "scim_managed": bool(u.scim_managed),
        "sso_provider": u.sso_provider,
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


# ── Clear Data ───────────────────────────────────────────────────────────────

class ClearDataRequest(BaseModel):
    tenant_id: Optional[int] = None


@router.post("/clear-data")
def clear_data(body: ClearDataRequest, _: AuthUser = Depends(require_admin)):
    tenant_id = body.tenant_id
    if tenant_id is not None:
        with get_session() as session:
            if not session.query(TenantConfig).filter_by(id=tenant_id).first():
                raise HTTPException(status_code=404, detail="Tenant not found")

    with get_session() as session:
        q_zia   = session.query(ZIAResource)
        q_zpa   = session.query(ZPAResource)
        q_zcc   = session.query(ZCCResource)
        q_snap  = session.query(RestorePoint)
        q_sync  = session.query(SyncLog)
        q_audit = session.query(AuditLog)
        if tenant_id is not None:
            q_zia   = q_zia.filter_by(tenant_id=tenant_id)
            q_zpa   = q_zpa.filter_by(tenant_id=tenant_id)
            q_zcc   = q_zcc.filter_by(tenant_id=tenant_id)
            q_snap  = q_snap.filter_by(tenant_id=tenant_id)
            q_sync  = q_sync.filter_by(tenant_id=tenant_id)
            q_audit = q_audit.filter_by(tenant_id=tenant_id)
        zia_count   = q_zia.delete()
        zpa_count   = q_zpa.delete()
        zcc_count   = q_zcc.delete()
        snap_count  = q_snap.delete()
        sync_count  = q_sync.delete()
        audit_count = q_audit.delete()

    return {
        "zia": zia_count,
        "zpa": zpa_count,
        "zcc": zcc_count,
        "snapshots": snap_count,
        "sync_logs": sync_count,
        "audit_entries": audit_count,
    }


# ── Key Rotation ─────────────────────────────────────────────────────────────

class RotateKeyRequest(BaseModel):
    algorithm: Optional[str] = None


@router.post("/rotate-key")
def rotate_encryption_key(body: RotateKeyRequest, _: AuthUser = Depends(require_admin)):
    from services.encryption_service import rotate_key
    from lib.crypto import CryptoAlgorithm

    algorithm = body.algorithm or get_setting("encryption_algorithm") or CryptoAlgorithm.FERNET
    try:
        result = rotate_key(algorithm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


# ── Database Import ───────────────────────────────────────────────────────────

_SQLITE_MAGIC = b"SQLite format 3\x00"

# SQLite writes these next to the main file in WAL mode. They describe the
# database being replaced, so they must not survive a swap — SQLite would try
# to replay a stale WAL against the incoming file.
_SIDECAR_SUFFIXES = ("-wal", "-shm")


def _sqlcipher_key_from_material(raw: bytes) -> bytes:
    """Derive the 32-byte SQLCipher key from raw secret.key file content.

    Mirrors db.database._derive_sqlcipher_key(), but takes the material
    explicitly so an uploaded key can be tested before it is installed.
    """
    import base64

    from lib.crypto import CryptoAlgorithm, get_active_algorithm

    if get_active_algorithm() == CryptoAlgorithm.FERNET:
        return base64.urlsafe_b64decode(raw)[:32]
    return base64.b64decode(raw)[:32]


def _probe_database(path: Path, key_material: Optional[bytes]) -> Optional[str]:
    """Return None if the file is a usable database, else a reason string.

    A plaintext SQLite file is accepted on its header — init_db() converts it
    to SQLCipher on first open. Anything else is treated as already encrypted,
    where the header is ciphertext and there is no magic number to match; the
    only way to distinguish a real SQLCipher database from arbitrary bytes is
    to decrypt it, which also verifies the key actually fits the data.
    """
    with open(path, "rb") as fh:
        header = fh.read(16)
    if len(header) < 16:
        return "the file is too small to be a database"
    if header == _SQLITE_MAGIC:
        return None

    if not key_material:
        return (
            "the file is not plaintext SQLite, and no encryption key is available "
            "to decrypt it — upload the matching secret.key alongside it"
        )

    try:
        import binascii

        import sqlcipher3.dbapi2 as sqlcipher

        hex_key = binascii.hexlify(_sqlcipher_key_from_material(key_material)).decode()
        conn = sqlcipher.connect(str(path))
        try:
            conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
            conn.execute("SELECT count(*) FROM sqlite_master")
        finally:
            conn.close()
    except Exception:
        # Deliberately not surfacing the driver error — it varies by failure
        # mode and adds nothing an operator can act on.
        return (
            "the file could not be opened — it is neither a plaintext SQLite "
            "database nor a SQLCipher database matching the supplied key"
        )
    return None


@router.post("/import-db")
async def import_database(
    db_file: UploadFile = File(...),
    key_file: UploadFile = File(default=None),
    _: AuthUser = Depends(require_admin),
):
    """Replace the running database and (optionally) the encryption key.

    Accepts multipart/form-data with:
      - db_file  — a zs-config database, either plaintext SQLite (older TUI
                   exports) or SQLCipher-encrypted (anything current)
      - key_file — secret.key material. Required when db_file is encrypted,
                   unless this install already holds the matching key.

    The upload is staged and opened before anything live is touched, and the
    previous database and key are restored if the swap or the reinitialisation
    fails. A page reload is required after a successful import.
    """
    db_path_str = os.environ.get("ZSCALER_DB_PATH")
    if not db_path_str:
        raise HTTPException(status_code=400, detail="ZSCALER_DB_PATH is not set; cannot determine where to write the database")

    db_path = Path(db_path_str)
    key_dir = db_path.parent
    key_path = key_dir / "secret.key"

    db_bytes = await db_file.read()

    new_key: Optional[str] = None
    if key_file is not None:
        key_bytes = await key_file.read()
        try:
            new_key = key_bytes.decode().strip()
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="Key file is not valid text")
        # Fernet keys are 44 base64url chars; the raw-byte algorithms store
        # base64 of 32 bytes, which is also 44.
        if len(new_key) != 44:
            raise HTTPException(status_code=422, detail="Key file does not look like a valid key (expected 44 characters)")

    # The candidate is opened with the uploaded key when one was supplied,
    # otherwise with whatever this install already uses.
    if new_key is not None:
        probe_key: Optional[bytes] = new_key.encode()
    elif os.environ.get("ZSCALER_SECRET_KEY"):
        probe_key = os.environ["ZSCALER_SECRET_KEY"].encode()
    elif key_path.exists():
        probe_key = key_path.read_bytes().strip()
    else:
        probe_key = None

    staged = db_path.with_suffix(".import.tmp")
    try:
        staged.write_bytes(db_bytes)
        if sys.platform != "win32":
            staged.chmod(0o600)
    except Exception as exc:
        staged.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to write database: {exc}")

    reason = _probe_database(staged, probe_key)
    if reason is not None:
        staged.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Uploaded file rejected — {reason}.")

    # Past this point live files change, so keep restorable copies of each.
    backup_dir = Path(tempfile.mkdtemp(prefix=".zs-import-", dir=str(key_dir)))
    saved: dict = {}

    def _save(src: Path) -> None:
        if src.exists():
            dest = backup_dir / src.name
            shutil.copy2(src, dest)
            saved[src] = dest

    try:
        # Drop handles on the outgoing file before it is replaced.
        dispose_engine()

        _save(db_path)
        _save(key_path)
        for suffix in _SIDECAR_SUFFIXES:
            _save(Path(str(db_path) + suffix))
        for suffix in _SIDECAR_SUFFIXES:
            Path(str(db_path) + suffix).unlink(missing_ok=True)

        shutil.move(str(staged), str(db_path))

        if new_key is not None:
            key_path.write_text(new_key)
            if sys.platform != "win32":
                key_path.chmod(0o600)

        init_db()
    except Exception as exc:
        for src, dest in saved.items():
            try:
                shutil.copy2(dest, src)
            except Exception:
                pass
        staged.unlink(missing_ok=True)
        try:
            init_db()  # bring the previous database back online
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Import failed and the previous database was restored: {exc}",
        )
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)

    # Seed a default admin if the imported DB has no admin accounts (e.g. TUI export)
    from api.main import seed_admin_if_needed
    temp_password = seed_admin_if_needed()

    return {
        "ok": True,
        "message": "Database imported successfully. Reload the page to continue.",
        "seeded_admin": temp_password is not None,
        "temp_password": temp_password,
    }



# ── SCIM provisioning ─────────────────────────────────────────────────────────

class ScimTokenCreate(BaseModel):
    label: Optional[str] = None


class ScimGroupMapping(BaseModel):
    mapped_role: Optional[str] = None   # 'admin' | 'user' | null to unmap


def _scim_token_out(t: ScimToken) -> dict:
    return {
        "id": t.id,
        "label": t.label,
        # Only ever the first few characters, so an admin can tell two tokens
        # apart without the value being usable.
        "token_prefix": t.token_prefix,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "created_by": t.created_by,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "is_active": bool(t.is_active),
    }


@router.get("/scim/tokens")
def list_scim_tokens(_: AuthUser = Depends(require_admin)):
    with get_session() as session:
        rows = session.query(ScimToken).order_by(ScimToken.created_at.desc()).all()
        return [_scim_token_out(t) for t in rows]


@router.post("/scim/tokens", status_code=201)
def create_scim_token(body: ScimTokenCreate, current: AuthUser = Depends(require_admin)):
    """Issue a bearer token. The plaintext is returned once and never stored."""
    from api.routers.scim import generate_token

    plaintext, token_hash, prefix = generate_token()
    with get_session() as session:
        token = ScimToken(
            label=body.label or None,
            token_hash=token_hash,
            token_prefix=prefix,
            created_by=current.username,
            is_active=True,
        )
        session.add(token)
        session.flush()
        session.refresh(token)
        out = _scim_token_out(token)
    out["token"] = plaintext
    return out


@router.delete("/scim/tokens/{token_id}", status_code=204)
def revoke_scim_token(token_id: int, _: AuthUser = Depends(require_admin)):
    with get_session() as session:
        token = session.query(ScimToken).filter_by(id=token_id).first()
        if not token:
            raise HTTPException(status_code=404, detail="Token not found")
        session.delete(token)


@router.get("/scim/groups")
def list_scim_groups(_: AuthUser = Depends(require_admin)):
    with get_session() as session:
        rows = session.query(ScimGroup).order_by(ScimGroup.display_name).all()
        out = []
        for g in rows:
            count = session.query(ScimGroupMember).filter_by(group_id=g.id).count()
            out.append({
                "id": g.id,
                "display_name": g.display_name,
                "external_id": g.external_id,
                "mapped_role": g.mapped_role,
                "member_count": count,
                "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            })
        return out


@router.put("/scim/groups/{group_id}")
def map_scim_group(group_id: int, body: ScimGroupMapping, _: AuthUser = Depends(require_admin)):
    """Point a provisioned group at a zs-config role, then re-apply it."""
    if body.mapped_role not in (None, "", "admin", "user"):
        raise HTTPException(status_code=422, detail="mapped_role must be 'admin', 'user' or null")

    with get_session() as session:
        group = session.query(ScimGroup).filter_by(id=group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        group.mapped_role = body.mapped_role or None
        group.updated_at = datetime.utcnow()
        session.flush()

        # Members inherit the new mapping immediately rather than waiting for
        # the IdP's next sync cycle.
        from api.routers.scim import _reconcile_roles
        _reconcile_roles(session, group_id)

        count = session.query(ScimGroupMember).filter_by(group_id=group_id).count()
        return {
            "id": group.id,
            "display_name": group.display_name,
            "external_id": group.external_id,
            "mapped_role": group.mapped_role,
            "member_count": count,
            "updated_at": group.updated_at.isoformat() if group.updated_at else None,
        }
