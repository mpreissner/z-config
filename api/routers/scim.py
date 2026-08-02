"""Inbound SCIM 2.0 server.

An IdP (Okta, Entra, ZIdentity) calls these endpoints to provision and
deprovision zs-config's own web users. Nothing here talks to Zscaler.

Mounted at /scim/v2 rather than under /api/v1 because SCIM clients expect that
exact base path.
"""

import hashlib
import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from db.database import get_session
from db.models import ScimToken, User, UserGroup, UserGroupMember
from services import role_service

router = APIRouter(prefix="/scim/v2", tags=["SCIM"])

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"

SCIM_CONTENT_TYPE = "application/scim+json"


# ── Errors ────────────────────────────────────────────────────────────────────


class ScimError(Exception):
    """SCIM clients parse the SCIM error envelope, not FastAPI's {"detail": …}."""

    def __init__(self, status: int, detail: str, scim_type: Optional[str] = None):
        self.status = status
        self.detail = detail
        self.scim_type = scim_type
        super().__init__(detail)

    def response(self) -> JSONResponse:
        body: Dict[str, Any] = {
            "schemas": [ERROR_SCHEMA],
            "status": str(self.status),
            "detail": self.detail,
        }
        if self.scim_type:
            body["scimType"] = self.scim_type
        return JSONResponse(body, status_code=self.status, media_type=SCIM_CONTENT_TYPE)


def _scim_json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=SCIM_CONTENT_TYPE)


# ── Token auth ────────────────────────────────────────────────────────────────


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_token() -> Tuple[str, str, str]:
    """Return (plaintext, sha256 hash, display prefix)."""
    plaintext = secrets.token_urlsafe(36)
    return plaintext, hash_token(plaintext), plaintext[:8]


def require_scim_token(authorization: Optional[str] = Header(default=None)) -> int:
    """Authenticate the IdP by bearer token. Returns the token row id."""
    if not authorization or not authorization.startswith("Bearer "):
        raise ScimError(401, "Missing bearer token")
    presented = hash_token(authorization.removeprefix("Bearer ").strip())

    with get_session() as session:
        rows = session.query(ScimToken).filter_by(is_active=True).all()
        match = None
        for row in rows:
            # compare_digest over every active token so the comparison time
            # does not depend on which token was presented.
            if secrets.compare_digest(row.token_hash, presented):
                match = row
        if match is None:
            raise ScimError(401, "Invalid bearer token")
        match.last_used_at = datetime.utcnow()
        return match.id


# ── Serialisation ─────────────────────────────────────────────────────────────


def _meta(resource: str, obj_id: int, created: Optional[datetime], updated: Optional[datetime]) -> dict:
    meta = {"resourceType": resource, "location": f"/scim/v2/{resource}s/{obj_id}"}
    if created:
        meta["created"] = created.isoformat() + "Z"
    if updated:
        meta["lastModified"] = updated.isoformat() + "Z"
    return meta


def user_to_scim(u: User) -> dict:
    body: Dict[str, Any] = {
        "schemas": [USER_SCHEMA],
        "id": str(u.id),
        "userName": u.username,
        "active": bool(u.is_active),
        "meta": _meta("User", u.id, u.created_at, u.updated_at),
    }
    if u.scim_external_id:
        body["externalId"] = u.scim_external_id
    if u.given_name or u.family_name:
        body["name"] = {
            "givenName": u.given_name or "",
            "familyName": u.family_name or "",
            "formatted": " ".join(x for x in (u.given_name, u.family_name) if x),
        }
    if u.email:
        body["emails"] = [{"value": u.email, "primary": True, "type": "work"}]
    return body


def group_to_scim(g: UserGroup, member_rows: List[Tuple[int, str]]) -> dict:
    return {
        "schemas": [GROUP_SCHEMA],
        "id": str(g.id),
        "displayName": g.display_name,
        **({"externalId": g.external_id} if g.external_id else {}),
        "members": [
            {"value": str(uid), "display": uname, "$ref": f"/scim/v2/Users/{uid}"}
            for uid, uname in member_rows
        ],
        "meta": _meta("Group", g.id, g.created_at, g.updated_at),
    }


def _list_response(resources: List[dict], total: int, start_index: int) -> dict:
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


# ── Filter parsing ────────────────────────────────────────────────────────────

_FILTER_RE = re.compile(r'^\s*(\w+)\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE)


def parse_filter(expr: Optional[str], allowed: Tuple[str, ...]) -> Optional[Tuple[str, str]]:
    """Parse the `attr eq "value"` subset that provisioning clients actually send.

    Anything else is rejected outright rather than ignored — silently returning
    every user when the client asked for one is how duplicate accounts get made.
    """
    if not expr:
        return None
    m = _FILTER_RE.match(expr)
    if not m:
        raise ScimError(400, f"Unsupported filter: {expr}", scim_type="invalidFilter")
    attr, value = m.group(1), m.group(2)
    lowered = {a.lower(): a for a in allowed}
    if attr.lower() not in lowered:
        raise ScimError(400, f"Filtering on '{attr}' is not supported", scim_type="invalidFilter")
    return lowered[attr.lower()], value


# ── Payload helpers ───────────────────────────────────────────────────────────


def _primary_email(payload: dict) -> Optional[str]:
    emails = payload.get("emails") or []
    if isinstance(emails, dict):
        emails = [emails]
    for e in emails:
        if isinstance(e, dict) and e.get("primary"):
            return e.get("value")
    for e in emails:
        if isinstance(e, dict) and e.get("value"):
            return e["value"]
    return None


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _assert_admin_remains(session) -> None:
    """Refuse a change that has just left the install with no active admin.

    Called after the edit is flushed rather than before it is applied: the
    account being changed may hold admin through a group rather than through
    `User.role`, and a PATCH may carry several operations whose combined effect
    is not visible one at a time. Counting afterwards asks the question of the
    database instead of re-deriving it here, and `get_session` rolls the
    refused change back on the way out.

    A group mapping typo, or an IdP that deactivates the wrong account, should
    not be able to lock everyone out.
    """
    if role_service.active_admin_count(session) == 0:
        raise ScimError(400, role_service.LAST_ADMIN_MESSAGE, scim_type="mutability")


# A group's mapped_role is not written into User.role. It adds to the roles the
# account may assume, and role_service.available_roles() unions the two at
# token time — see services/role_service.py. Nothing here has to recompute a
# role when membership changes, because nothing here owns it.


def _default_role() -> str:
    from db.database import get_setting
    return get_setting("idp_default_role") or "user"


# ── Discovery documents ───────────────────────────────────────────────────────


@router.get("/ServiceProviderConfig")
def service_provider_config():
    return _scim_json({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://github.com/mpreissner/zs-config",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken",
            "name": "OAuth Bearer Token",
            "description": "Long-lived bearer token issued from Admin Settings",
            "primary": True,
        }],
        "meta": {"resourceType": "ServiceProviderConfig", "location": "/scim/v2/ServiceProviderConfig"},
    })


@router.get("/ResourceTypes")
def resource_types():
    return _scim_json(_list_response([
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "User", "name": "User", "endpoint": "/Users", "schema": USER_SCHEMA,
            "meta": {"resourceType": "ResourceType", "location": "/scim/v2/ResourceTypes/User"},
        },
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "Group", "name": "Group", "endpoint": "/Groups", "schema": GROUP_SCHEMA,
            "meta": {"resourceType": "ResourceType", "location": "/scim/v2/ResourceTypes/Group"},
        },
    ], 2, 1))


@router.get("/Schemas")
def schemas():
    return _scim_json(_list_response([
        {"id": USER_SCHEMA, "name": "User", "description": "zs-config web user"},
        {"id": GROUP_SCHEMA, "name": "Group", "description": "Role-mapping group"},
    ], 2, 1))


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/Users")
def list_users(
    filter: Optional[str] = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=200),
    _: int = Depends(require_scim_token),
):
    parsed = parse_filter(filter, ("userName", "externalId", "id"))
    with get_session() as session:
        q = session.query(User)
        if parsed:
            attr, value = parsed
            if attr == "userName":
                q = q.filter(User.username == value)
            elif attr == "externalId":
                q = q.filter(User.scim_external_id == value)
            else:
                q = q.filter(User.id == (int(value) if value.isdigit() else -1))
        total = q.count()
        rows = q.order_by(User.id).offset(startIndex - 1).limit(count).all()
        resources = [user_to_scim(u) for u in rows]
    return _scim_json(_list_response(resources, total, startIndex))


@router.get("/Users/{user_id}")
def get_user(user_id: int, _: int = Depends(require_scim_token)):
    with get_session() as session:
        u = session.query(User).filter_by(id=user_id).first()
        if not u:
            raise ScimError(404, f"User {user_id} not found")
        body = user_to_scim(u)
    return _scim_json(body)


@router.post("/Users", status_code=201)
async def create_user(request: Request, _: int = Depends(require_scim_token)):
    payload = await request.json()
    username = (payload.get("userName") or "").strip()
    if not username:
        raise ScimError(400, "userName is required", scim_type="invalidValue")

    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        existing = session.query(User).filter_by(username=username).first()
        if existing:
            if existing.is_active:
                raise ScimError(409, f"User {username} already exists", scim_type="uniqueness")
            # A previously deprovisioned account comes back rather than
            # colliding — entitlements and audit history stay attached.
            existing.is_active = True
            existing.scim_managed = True
            existing.scim_external_id = payload.get("externalId") or existing.scim_external_id
            session.flush()
            session.refresh(existing)
            body = user_to_scim(existing)
            audit.append({"operation": "scim_reactivate_user", "action": "UPDATE", "name": username})
        else:
            name = payload.get("name") or {}
            user = User(
                username=username,
                email=_primary_email(payload),
                role=_default_role(),
                password_hash=None,
                force_password_change=False,
                scim_external_id=payload.get("externalId"),
                scim_managed=True,
                given_name=name.get("givenName"),
                family_name=name.get("familyName"),
                is_active=_truthy(payload.get("active"), True),
            )
            session.add(user)
            session.flush()
            session.refresh(user)
            body = user_to_scim(user)
            audit.append({"operation": "scim_create_user", "action": "CREATE", "name": username})

    _audit(audit)
    return _scim_json(body, 201)


@router.put("/Users/{user_id}")
async def replace_user(user_id: int, request: Request, _: int = Depends(require_scim_token)):
    payload = await request.json()
    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        u = session.query(User).filter_by(id=user_id).first()
        if not u:
            raise ScimError(404, f"User {user_id} not found")

        active = _truthy(payload.get("active"), u.is_active)

        name = payload.get("name") or {}
        if payload.get("userName"):
            u.username = payload["userName"].strip()
        u.email = _primary_email(payload) or u.email
        u.given_name = name.get("givenName", u.given_name)
        u.family_name = name.get("familyName", u.family_name)
        if "externalId" in payload:
            u.scim_external_id = payload["externalId"]
        u.is_active = active
        session.flush()
        _assert_admin_remains(session)
        session.refresh(u)
        body = user_to_scim(u)
        audit.append({"operation": "scim_replace_user", "action": "UPDATE", "name": u.username})

    _audit(audit)
    return _scim_json(body)


@router.patch("/Users/{user_id}")
async def patch_user(user_id: int, request: Request, _: int = Depends(require_scim_token)):
    payload = await request.json()
    ops = payload.get("Operations") or []
    if not isinstance(ops, list):
        raise ScimError(400, "Operations must be a list", scim_type="invalidValue")

    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        u = session.query(User).filter_by(id=user_id).first()
        if not u:
            raise ScimError(404, f"User {user_id} not found")

        for op in ops:
            if not isinstance(op, dict):
                continue
            action = (op.get("op") or "").lower()
            path = (op.get("path") or "").strip()
            value = op.get("value")

            # Entra sends {"op":"replace","value":{"active":false}} with no path.
            if not path and isinstance(value, dict):
                for k, v in value.items():
                    _apply_user_field(u, k, v, action)
                continue
            if action == "remove" and not path:
                continue
            _apply_user_field(u, path, value, action)

        session.flush()
        # After the whole batch: a PATCH that deactivates and reactivates in one
        # body has no net effect, and checking per-operation would refuse it.
        _assert_admin_remains(session)
        session.refresh(u)
        body = user_to_scim(u)
        audit.append({"operation": "scim_patch_user", "action": "UPDATE", "name": u.username})

    _audit(audit)
    return _scim_json(body)


def _apply_user_field(u: User, path: str, value: Any, action: str) -> None:
    """Apply one PATCH operation. Unknown paths are ignored on purpose.

    Entra in particular sends operations for attributes we do not store; 400ing
    on those would fail the whole provisioning cycle over nothing.
    """
    key = path.split("[", 1)[0].strip().lower()

    if key == "active":
        u.is_active = _truthy(value, True) if action != "remove" else False
    elif key == "username":
        if isinstance(value, str) and value.strip():
            u.username = value.strip()
    elif key == "externalid":
        u.scim_external_id = value if isinstance(value, str) else None
    elif key in ("emails", "emails.value") or key.startswith("emails"):
        if isinstance(value, str):
            u.email = value
        elif isinstance(value, list) and value:
            first = value[0]
            u.email = first.get("value") if isinstance(first, dict) else str(first)
        elif isinstance(value, dict):
            u.email = value.get("value")
    elif key == "name.givenname":
        u.given_name = value if isinstance(value, str) else None
    elif key == "name.familyname":
        u.family_name = value if isinstance(value, str) else None
    elif key == "name" and isinstance(value, dict):
        u.given_name = value.get("givenName", u.given_name)
        u.family_name = value.get("familyName", u.family_name)


@router.delete("/Users/{user_id}", status_code=204)
def delete_user(user_id: int, _: int = Depends(require_scim_token)):
    """Soft delete. Rows stay so audit references and entitlements survive."""
    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        u = session.query(User).filter_by(id=user_id).first()
        if not u:
            raise ScimError(404, f"User {user_id} not found")
        u.is_active = False
        session.flush()
        _assert_admin_remains(session)
        audit.append({"operation": "scim_delete_user", "action": "DELETE", "name": u.username})

    _audit(audit)
    return Response(status_code=204)


# ── Groups ────────────────────────────────────────────────────────────────────


def _members_of(session, group_id: int) -> List[Tuple[int, str]]:
    rows = (
        session.query(User.id, User.username)
        .join(UserGroupMember, UserGroupMember.user_id == User.id)
        .filter(UserGroupMember.group_id == group_id)
        .all()
    )
    return [(r[0], r[1]) for r in rows]


@router.get("/Groups")
def list_groups(
    filter: Optional[str] = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=200),
    _: int = Depends(require_scim_token),
):
    parsed = parse_filter(filter, ("displayName", "externalId", "id"))
    with get_session() as session:
        q = session.query(UserGroup)
        if parsed:
            attr, value = parsed
            if attr == "displayName":
                q = q.filter(UserGroup.display_name == value)
            elif attr == "externalId":
                q = q.filter(UserGroup.external_id == value)
            else:
                q = q.filter(UserGroup.id == (int(value) if value.isdigit() else -1))
        total = q.count()
        rows = q.order_by(UserGroup.id).offset(startIndex - 1).limit(count).all()
        resources = [group_to_scim(g, _members_of(session, g.id)) for g in rows]
    return _scim_json(_list_response(resources, total, startIndex))


@router.get("/Groups/{group_id}")
def get_group(group_id: int, _: int = Depends(require_scim_token)):
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise ScimError(404, f"Group {group_id} not found")
        body = group_to_scim(g, _members_of(session, g.id))
    return _scim_json(body)


@router.post("/Groups", status_code=201)
async def create_group(request: Request, _: int = Depends(require_scim_token)):
    payload = await request.json()
    display = (payload.get("displayName") or "").strip()
    if not display:
        raise ScimError(400, "displayName is required", scim_type="invalidValue")

    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        existing = session.query(UserGroup).filter_by(display_name=display).first()
        if existing and existing.source == "scim":
            raise ScimError(409, f"Group {display} already exists", scim_type="uniqueness")
        if existing:
            # A local group of the same name is adopted rather than rejected: the
            # IdP has no way to resolve a 409 it did not cause, and refusing would
            # wedge provisioning for good. Membership the admin added by hand
            # stays — only rows marked 'scim' are ever replaced from here.
            g = existing
            g.source = "scim"
            g.external_id = payload.get("externalId") or g.external_id
        else:
            g = UserGroup(display_name=display, external_id=payload.get("externalId"),
                          source="scim")
            session.add(g)
        session.flush()
        _set_members(session, g.id, payload.get("members") or [])
        session.flush()
        session.refresh(g)
        body = group_to_scim(g, _members_of(session, g.id))
        audit.append({"operation": "scim_create_group", "action": "CREATE", "name": display})

    _audit(audit)
    return _scim_json(body, 201)


@router.put("/Groups/{group_id}")
async def replace_group(group_id: int, request: Request, _: int = Depends(require_scim_token)):
    payload = await request.json()
    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise ScimError(404, f"Group {group_id} not found")
        if payload.get("displayName"):
            g.display_name = payload["displayName"].strip()
        if "externalId" in payload:
            g.external_id = payload["externalId"]
        if "members" in payload:
            _set_members(session, g.id, payload.get("members") or [], replace=True)
        session.flush()
        _assert_admin_remains(session)
        session.refresh(g)
        body = group_to_scim(g, _members_of(session, g.id))
        audit.append({"operation": "scim_replace_group", "action": "UPDATE", "name": g.display_name})

    _audit(audit)
    return _scim_json(body)


@router.patch("/Groups/{group_id}")
async def patch_group(group_id: int, request: Request, _: int = Depends(require_scim_token)):
    payload = await request.json()
    ops = payload.get("Operations") or []
    audit: List[Dict[str, Any]] = []

    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise ScimError(404, f"Group {group_id} not found")

        for op in ops:
            if not isinstance(op, dict):
                continue
            action = (op.get("op") or "").lower()
            path = (op.get("path") or "").strip().lower()
            value = op.get("value")

            if path.startswith("members"):
                if action == "add":
                    _set_members(session, g.id, value or [])
                elif action == "replace":
                    _set_members(session, g.id, value or [], replace=True)
                elif action == "remove":
                    _remove_members(session, g.id, value, path)
            elif path == "displayname" and isinstance(value, str):
                g.display_name = value.strip()
            elif path == "externalid":
                g.external_id = value if isinstance(value, str) else None
            elif not path and isinstance(value, dict):
                if isinstance(value.get("displayName"), str):
                    g.display_name = value["displayName"].strip()
                if "members" in value:
                    _set_members(session, g.id, value["members"] or [], replace=(action == "replace"))

        session.flush()
        _assert_admin_remains(session)
        session.refresh(g)
        body = group_to_scim(g, _members_of(session, g.id))
        audit.append({"operation": "scim_patch_group", "action": "UPDATE", "name": g.display_name})

    _audit(audit)
    return _scim_json(body)


@router.delete("/Groups/{group_id}", status_code=204)
def delete_group(group_id: int, _: int = Depends(require_scim_token)):
    audit: List[Dict[str, Any]] = []
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise ScimError(404, f"Group {group_id} not found")
        name = g.display_name
        session.query(UserGroupMember).filter_by(group_id=g.id).delete()
        session.delete(g)
        session.flush()
        _assert_admin_remains(session)
        # Members lose whatever role this group offered on their next token —
        # nothing to rewrite, because User.role was never it.
        audit.append({"operation": "scim_delete_group", "action": "DELETE", "name": name})

    _audit(audit)
    return Response(status_code=204)


def _member_ids(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    ids: List[int] = []
    for m in value:
        raw = m.get("value") if isinstance(m, dict) else m
        if raw is None:
            continue
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def _set_members(session, group_id: int, value: Any, replace: bool = False) -> None:
    """Apply the IdP's membership list.

    A replace clears only the memberships SCIM itself created. Anyone an admin
    added to the group by hand keeps their place — the IdP does not know about
    them, so its list is not evidence they should be gone.
    """
    ids = _member_ids(value)
    if replace:
        session.query(UserGroupMember).filter_by(group_id=group_id, source="scim").delete()
        session.flush()
    existing = {
        r.user_id for r in session.query(UserGroupMember).filter_by(group_id=group_id).all()
    }
    for uid in ids:
        if uid in existing:
            continue
        if session.query(User).filter_by(id=uid).first() is None:
            continue
        session.add(UserGroupMember(group_id=group_id, user_id=uid, source="scim"))
    session.flush()


_MEMBER_FILTER_RE = re.compile(r'value\s+eq\s+"([^"]+)"', re.IGNORECASE)


def _remove_members(session, group_id: int, value: Any, path: str) -> None:
    """Handle both `members` with a value list and `members[value eq "x"]`."""
    ids = _member_ids(value)
    ids.extend(int(m) for m in _MEMBER_FILTER_RE.findall(path) if m.isdigit())
    if not ids:
        # `remove` on the whole `members` path clears what SCIM put there.
        session.query(UserGroupMember).filter_by(group_id=group_id, source="scim").delete()
    else:
        # Naming a member explicitly does remove them, however they were added:
        # the IdP is stating that this person is not in the group.
        session.query(UserGroupMember).filter(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id.in_(ids),
        ).delete(synchronize_session=False)
    session.flush()


# ── Audit ─────────────────────────────────────────────────────────────────────


def _audit(entries: List[Dict[str, Any]]) -> None:
    """Written after the session closes, per the project's SQLite rule."""
    if not entries:
        return
    from services import audit_service
    for e in entries:
        audit_service.log(
            product=None,
            operation=e["operation"],
            action=e["action"],
            status="SUCCESS",
            tenant_id=None,
            resource_type="user" if "user" in e["operation"] else "scim_group",
            resource_name=e.get("name"),
        )
