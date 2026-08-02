import base64
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from pydantic import BaseModel

from db.database import get_session, get_setting
from db.models import User, WebAuthnCredential
from api.auth_utils import (
    verify_password, hash_password, issue_access_token,
    issue_refresh_token, decode_token,
)
from api.dependencies import require_auth, AuthUser
from services.role_service import available_roles, resolve_active
from jose import JWTError

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

# ------------------------------------------------------------------
# WebAuthn challenge store
# Keyed by a string (str(user_id) for registration, username for authentication).
# Value: (challenge_bytes, expiry_datetime)
# ------------------------------------------------------------------

_challenge_store: Dict[str, tuple] = {}
_CHALLENGE_TTL_SECONDS = 60


def _sweep_challenges() -> None:
    now = datetime.utcnow()
    expired = [k for k, (_, exp) in _challenge_store.items() if exp <= now]
    for k in expired:
        del _challenge_store[k]


def _store_challenge(key: str, challenge: bytes) -> None:
    _sweep_challenges()
    _challenge_store[key] = (challenge, datetime.utcnow() + timedelta(seconds=_CHALLENGE_TTL_SECONDS))


def _pop_challenge(key: str) -> Optional[bytes]:
    _sweep_challenges()
    entry = _challenge_store.pop(key, None)
    if entry is None:
        return None
    challenge, expiry = entry
    if datetime.utcnow() > expiry:
        return None
    return challenge


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AssumeRoleRequest(BaseModel):
    role: str


def _set_refresh_cookie(response: Response, token: str):
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        samesite="strict",
        path="/api/v1/auth/refresh",
        secure=False,  # set ZS_SECURE_COOKIES=1 in production
    )


@router.post("/login")
def login(body: LoginRequest, response: Response):
    with get_session() as session:
        user = session.query(User).filter_by(username=body.username, is_active=True).first()
        if not user or not user.password_hash:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        roles = available_roles(user.id, user.role, session=session)
        if user.mfa_required:
            has_key = session.query(WebAuthnCredential).filter_by(user_id=user.id).first() is not None
            if has_key:
                raise HTTPException(status_code=401, detail="mfa_required")
            # No key enrolled — issue a restricted enrollment-only token
            access = issue_access_token(user, mfa_enroll=True, roles=roles)
            return {"access_token": access, "token_type": "bearer",
                    "force_password_change": False, "mfa_enrollment_required": True}
        user.last_login_at = datetime.utcnow()
        session.flush()
        session.refresh(user)
        # A session always starts at the least privilege the account has; an
        # admin who is also a user has to ask for admin before they get it.
        active = resolve_active(roles)
        access = issue_access_token(user, roles=roles, active_role=active)
        refresh = issue_refresh_token(user, active_role=active)
        fpc = user.force_password_change

    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer", "force_password_change": fpc,
            "active_role": active, "available_roles": roles}


@router.post("/refresh")
def refresh_token(refresh_token: Optional[str] = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    with get_session() as session:
        user = session.query(User).filter_by(id=int(payload["sub"]), is_active=True).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        roles = available_roles(user.id, user.role, session=session)
        # Land back on the role the session was holding. If it has since been
        # taken away, resolve_active drops to least privilege rather than
        # honouring a claim the account can no longer back up.
        active = resolve_active(roles, payload.get("role"))
        access = issue_access_token(user, roles=roles, active_role=active)

    return {"access_token": access, "token_type": "bearer",
            "active_role": active, "available_roles": roles}


@router.post("/assume-role")
def assume_role(body: AssumeRoleRequest, response: Response, user: AuthUser = Depends(require_auth)):
    """Switch the session to another of the account's roles.

    Reissues both tokens, so the change survives the next refresh. One role is
    live at a time — assuming `user` genuinely drops admin access until the
    account switches back.
    """
    with get_session() as session:
        db_user = session.query(User).filter_by(id=user.user_id, is_active=True).first()
        if not db_user:
            raise HTTPException(status_code=401, detail="User not found")
        roles = available_roles(db_user.id, db_user.role, session=session)
        if body.role not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{body.role}' is not available to this account")
        access = issue_access_token(db_user, roles=roles, active_role=body.role)
        refresh = issue_refresh_token(db_user, active_role=body.role)
        username = db_user.username

    from services import audit_service
    audit_service.log(
        product=None,
        operation="assume_role",
        action="UPDATE",
        status="SUCCESS",
        tenant_id=None,
        resource_type="user",
        resource_name=username,
        details={"from": user.role, "to": body.role},
    )

    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer",
            "active_role": body.role, "available_roles": roles}


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
        roles = available_roles(db_user.id, db_user.role, session=session)
        # Changing a password is not a reason to be dropped out of the role
        # the session was already holding.
        active = resolve_active(roles, user.role)
        access = issue_access_token(db_user, roles=roles, active_role=active)
        refresh = issue_refresh_token(db_user, active_role=active)

    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer", "force_password_change": False,
            "active_role": active, "available_roles": roles}


# ------------------------------------------------------------------
# WebAuthn — Registration
# ------------------------------------------------------------------

class WebAuthnRegisterBeginRequest(BaseModel):
    label: Optional[str] = None


class WebAuthnRegisterCompleteRequest(BaseModel):
    label: Optional[str] = None
    credential: Dict[str, Any]


@router.post("/webauthn/register/begin")
def webauthn_register_begin(
    body: WebAuthnRegisterBeginRequest,
    user: AuthUser = Depends(require_auth),
):
    """Begin FIDO2 registration ceremony. Returns PublicKeyCredentialCreationOptions."""
    try:
        import webauthn
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            UserVerificationRequirement,
            AttestationConveyancePreference,
            PublicKeyCredentialDescriptor,
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="WebAuthn not available (py-webauthn not installed)")

    rp_id = get_setting("webauthn_rp_id") or os.environ.get("WEBAUTHN_RP_ID", "localhost")

    with get_session() as session:
        existing_creds = session.query(WebAuthnCredential).filter_by(user_id=user.user_id).all()
        exclude_credentials = [
            PublicKeyCredentialDescriptor(id=_b64url_decode(c.credential_id))
            for c in existing_creds
        ]

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name="zs-config",
        user_id=str(user.user_id).encode(),
        user_name=user.username,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        attestation=AttestationConveyancePreference.NONE,
    )

    _store_challenge(f"reg:{user.user_id}", options.challenge)

    import json
    return json.loads(webauthn.options_to_json(options))


@router.post("/webauthn/register/complete")
def webauthn_register_complete(
    body: WebAuthnRegisterCompleteRequest,
    user: AuthUser = Depends(require_auth),
):
    """Complete FIDO2 registration ceremony. Saves the credential."""
    try:
        import webauthn
        from webauthn.helpers import parse_registration_credential_json
    except ImportError:
        raise HTTPException(status_code=501, detail="WebAuthn not available (py-webauthn not installed)")

    rp_id = get_setting("webauthn_rp_id") or os.environ.get("WEBAUTHN_RP_ID", "localhost")
    origin = get_setting("webauthn_origin") or os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")

    challenge = _pop_challenge(f"reg:{user.user_id}")
    if challenge is None:
        raise HTTPException(status_code=400, detail="No pending registration challenge or challenge expired")

    try:
        import json
        credential_json = json.dumps(body.credential)
        registration_credential = parse_registration_credential_json(credential_json)
        verified = webauthn.verify_registration_response(
            credential=registration_credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Registration verification failed: {exc}")

    credential_id_b64 = _b64url_encode(verified.credential_id)
    public_key_b64 = _b64url_encode(verified.credential_public_key)
    label = (body.label or "")[:255] or None
    aaguid_str = str(verified.aaguid) if verified.aaguid else None

    pending_audit: List[Dict] = []

    with get_session() as session:
        cred = WebAuthnCredential(
            user_id=user.user_id,
            credential_id=credential_id_b64,
            public_key=public_key_b64,
            sign_count=verified.sign_count,
            aaguid=aaguid_str,
            label=label,
            created_at=datetime.utcnow(),
        )
        session.add(cred)
        pending_audit.append({
            "product": None,
            "operation": "register_webauthn",
            "action": "CREATE",
            "status": "SUCCESS",
            "tenant_id": None,
            "resource_type": "webauthn_credential",
            "resource_name": label,
        })

    from services import audit_service
    for ev in pending_audit:
        audit_service.log(**ev)

    return {"ok": True, "credential_id": credential_id_b64}


# ------------------------------------------------------------------
# WebAuthn — Authentication
# ------------------------------------------------------------------

class WebAuthnAuthBeginRequest(BaseModel):
    username: str


class WebAuthnAuthCompleteRequest(BaseModel):
    username: str
    credential: Dict[str, Any]


@router.post("/webauthn/authenticate/begin")
def webauthn_authenticate_begin(body: WebAuthnAuthBeginRequest):
    """Begin FIDO2 authentication ceremony. No auth header required."""
    try:
        import webauthn
        from webauthn.helpers.structs import (
            UserVerificationRequirement,
            PublicKeyCredentialDescriptor,
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="WebAuthn not available (py-webauthn not installed)")

    rp_id = get_setting("webauthn_rp_id") or os.environ.get("WEBAUTHN_RP_ID", "localhost")

    with get_session() as session:
        db_user = session.query(User).filter_by(username=body.username, is_active=True).first()
        if not db_user:
            raise HTTPException(status_code=400, detail="No credentials found")
        creds = session.query(WebAuthnCredential).filter_by(user_id=db_user.id).all()
        if not creds:
            raise HTTPException(status_code=400, detail="No security keys registered")
        allow_credentials = [
            PublicKeyCredentialDescriptor(id=_b64url_decode(c.credential_id))
            for c in creds
        ]

    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    _store_challenge(f"auth:{body.username}", options.challenge)

    import json
    return json.loads(webauthn.options_to_json(options))


@router.post("/webauthn/authenticate/complete")
def webauthn_authenticate_complete(body: WebAuthnAuthCompleteRequest, response: Response):
    """Complete FIDO2 authentication ceremony. Returns JWT tokens."""
    try:
        import webauthn
        from webauthn.helpers import parse_authentication_credential_json
    except ImportError:
        raise HTTPException(status_code=501, detail="WebAuthn not available (py-webauthn not installed)")

    rp_id = get_setting("webauthn_rp_id") or os.environ.get("WEBAUTHN_RP_ID", "localhost")
    origin = get_setting("webauthn_origin") or os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")

    challenge = _pop_challenge(f"auth:{body.username}")
    if challenge is None:
        raise HTTPException(status_code=401, detail="Authentication failed")

    import json
    credential_json = json.dumps(body.credential)

    with get_session() as session:
        db_user = session.query(User).filter_by(username=body.username, is_active=True).first()
        if not db_user:
            raise HTTPException(status_code=401, detail="Authentication failed")

        cred_id_from_request = body.credential.get("id", "")
        stored_cred = session.query(WebAuthnCredential).filter_by(
            user_id=db_user.id, credential_id=cred_id_from_request
        ).first()
        if not stored_cred:
            raise HTTPException(status_code=401, detail="Authentication failed")

        try:
            authentication_credential = parse_authentication_credential_json(credential_json)
            verified = webauthn.verify_authentication_response(
                credential=authentication_credential,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=_b64url_decode(stored_cred.public_key),
                credential_current_sign_count=stored_cred.sign_count,
                require_user_verification=False,
            )
        except Exception:
            raise HTTPException(status_code=401, detail="Authentication failed")

        stored_cred.sign_count = verified.new_sign_count
        stored_cred.last_used_at = datetime.utcnow()
        db_user.last_login_at = datetime.utcnow()
        session.flush()
        session.refresh(db_user)
        roles = available_roles(db_user.id, db_user.role, session=session)
        active = resolve_active(roles)
        access = issue_access_token(db_user, roles=roles, active_role=active)
        refresh = issue_refresh_token(db_user, active_role=active)
        fpc = db_user.force_password_change

    from services import audit_service
    audit_service.log(
        product=None,
        operation="webauthn_login",
        action="READ",
        status="SUCCESS",
        tenant_id=None,
        resource_type="user",
        resource_name=body.username,
    )

    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer", "force_password_change": fpc,
            "active_role": active, "available_roles": roles}


# ------------------------------------------------------------------
# WebAuthn — Credential Management
# ------------------------------------------------------------------

class WebAuthnPatchRequest(BaseModel):
    label: str


@router.get("/webauthn/credentials")
def list_webauthn_credentials(user: AuthUser = Depends(require_auth)):
    """List registered security keys for the current user."""
    with get_session() as session:
        creds = session.query(WebAuthnCredential).filter_by(user_id=user.user_id).all()
        result = [
            {
                "credential_id": c.credential_id,
                "label": c.label,
                "aaguid": c.aaguid,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
            }
            for c in creds
        ]
    return result


@router.delete("/webauthn/credentials/{credential_id}", status_code=204)
def delete_webauthn_credential(
    credential_id: str,
    user: AuthUser = Depends(require_auth),
):
    """Delete a registered security key. Prevents deletion of last key for passwordless accounts."""
    with get_session() as session:
        cred = session.query(WebAuthnCredential).filter_by(
            credential_id=credential_id, user_id=user.user_id
        ).first()
        if not cred:
            raise HTTPException(status_code=404, detail="Credential not found")

        total = session.query(WebAuthnCredential).filter_by(user_id=user.user_id).count()
        db_user = session.query(User).filter_by(id=user.user_id).first()
        if total == 1 and (not db_user or not db_user.password_hash):
            raise HTTPException(
                status_code=400,
                detail="Cannot remove last credential for a passwordless account",
            )

        session.delete(cred)


@router.patch("/webauthn/credentials/{credential_id}")
def patch_webauthn_credential(
    credential_id: str,
    body: WebAuthnPatchRequest,
    user: AuthUser = Depends(require_auth),
):
    """Update the label of a registered security key."""
    with get_session() as session:
        cred = session.query(WebAuthnCredential).filter_by(
            credential_id=credential_id, user_id=user.user_id
        ).first()
        if not cred:
            raise HTTPException(status_code=404, detail="Credential not found")
        cred.label = body.label[:255]
        session.flush()
        result = {"credential_id": cred.credential_id, "label": cred.label}
    return result
