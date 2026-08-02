"""Groups, their membership, and what a group grants.

A group is either pushed by the IdP over SCIM or created here by an admin —
`UserGroup.source` says which, and `UserGroupMember.source` says the same for
each individual membership. The split matters because a SCIM push is
authoritative only over its own rows: syncing a group replaces the members the
IdP put there and leaves hand-added ones alone, so an admin can top up a
provisioned group without the next sync undoing the work.

Two things hang off a group: a `mapped_role`, which SCIM already resolved into
each member's role, and tenant grants, which work exactly like
`UserTenantEntitlement` but for everyone in the group. Plugin grants live in
`plugin_entitlement_service` and reference the same groups.

Callers are responsible for auditing; this module only touches the database.
Every function opens its own session and returns plain dicts, so nothing here
may be called from inside an existing `with get_session()` block.
"""

from datetime import datetime
from typing import Iterable, Optional

from db.database import get_session
from db.models import (
    GroupTenantEntitlement,
    PluginEntitlement,
    TenantConfig,
    User,
    UserGroup,
    UserGroupMember,
    UserTenantEntitlement,
)


class GroupError(Exception):
    """Something the caller asked for cannot be done.

    `status` is the HTTP code the API layer should return, so routers can
    translate without re-deriving why the call failed.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _out(group: UserGroup, member_count: int = 0, tenant_count: int = 0) -> dict:
    return {
        "id": group.id,
        "display_name": group.display_name,
        "description": group.description,
        "external_id": group.external_id,
        "mapped_role": group.mapped_role,
        "source": group.source,
        "member_count": member_count,
        "tenant_count": tenant_count,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "updated_at": group.updated_at.isoformat() if group.updated_at else None,
    }


def _counts(session, table, column) -> dict:
    from sqlalchemy import func
    rows = session.query(column, func.count()).group_by(column).all()
    return {gid: n for gid, n in rows}


def list_groups() -> list[dict]:
    """Every group with its member and tenant-grant counts, by name."""
    with get_session() as session:
        groups = session.query(UserGroup).order_by(UserGroup.display_name).all()
        members = _counts(session, UserGroupMember, UserGroupMember.group_id)
        tenants = _counts(session, GroupTenantEntitlement, GroupTenantEntitlement.group_id)
        return [_out(g, members.get(g.id, 0), tenants.get(g.id, 0)) for g in groups]


def get_group(group_id: int) -> dict:
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise GroupError("Group not found", status=404)
        members = session.query(UserGroupMember).filter_by(group_id=group_id).count()
        tenants = session.query(GroupTenantEntitlement).filter_by(group_id=group_id).count()
        return _out(g, members, tenants)


def create_group(
    display_name: str,
    description: Optional[str] = None,
    mapped_role: Optional[str] = None,
) -> dict:
    """Create a local group. Raises GroupError(409) if the name is taken."""
    name = (display_name or "").strip()
    if not name:
        raise GroupError("Group name is required", status=422)
    _validate_role(mapped_role)

    with get_session() as session:
        if session.query(UserGroup).filter_by(display_name=name).first():
            raise GroupError(f"A group named '{name}' already exists", status=409)
        g = UserGroup(
            display_name=name,
            description=(description or None),
            mapped_role=(mapped_role or None),
            source="local",
        )
        session.add(g)
        session.flush()
        session.refresh(g)
        return _out(g)


def update_group(
    group_id: int,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    mapped_role: Optional[str] = None,
    set_role: bool = False,
) -> dict:
    """Edit a group.

    A SCIM group's name and description belong to the IdP — changing them here
    would be silently reverted on the next push, so they are refused. The role
    mapping is ours either way, and `set_role` distinguishes "clear the
    mapping" from "leave it alone", which a bare None cannot.
    """
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise GroupError("Group not found", status=404)

        if display_name is not None or description is not None:
            if g.source == "scim":
                raise GroupError(
                    "This group is provisioned over SCIM — rename it in the identity provider",
                    status=409,
                )
        if display_name is not None:
            name = display_name.strip()
            if not name:
                raise GroupError("Group name is required", status=422)
            clash = (
                session.query(UserGroup)
                .filter(UserGroup.display_name == name, UserGroup.id != group_id)
                .first()
            )
            if clash:
                raise GroupError(f"A group named '{name}' already exists", status=409)
            g.display_name = name
        if description is not None:
            g.description = description.strip() or None
        if set_role:
            _validate_role(mapped_role)
            g.mapped_role = mapped_role or None

        g.updated_at = datetime.utcnow()
        session.flush()

        # Members inherit a changed mapping now rather than at the IdP's next
        # sync — and for a local group there is no sync that would ever do it.
        if set_role:
            from api.routers.scim import _reconcile_roles
            _reconcile_roles(session, group_id)

        session.refresh(g)
        members = session.query(UserGroupMember).filter_by(group_id=group_id).count()
        tenants = session.query(GroupTenantEntitlement).filter_by(group_id=group_id).count()
        return _out(g, members, tenants)


def delete_group(group_id: int) -> str:
    """Delete a local group and everything it granted. Returns its name.

    SCIM groups are refused: the IdP would recreate the group on its next push
    while the grants attached to it stayed deleted.
    """
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise GroupError("Group not found", status=404)
        if g.source == "scim":
            raise GroupError(
                "This group is provisioned over SCIM — delete it in the identity provider",
                status=409,
            )
        name = g.display_name
        mapped_role = g.mapped_role
        member_ids = [
            uid for (uid,) in session.query(UserGroupMember.user_id).filter_by(group_id=group_id)
        ]
        session.query(UserGroupMember).filter_by(group_id=group_id).delete()
        session.query(GroupTenantEntitlement).filter_by(group_id=group_id).delete()
        session.query(PluginEntitlement).filter_by(group_id=group_id).delete()
        session.delete(g)
        session.flush()

        # The group may have been what made these people admins.
        if mapped_role:
            from api.routers.scim import _reconcile_roles
            _reconcile_roles(session, group_id, extra_user_ids=member_ids)
        return name


def _validate_role(role: Optional[str]) -> None:
    if role not in (None, "", "admin", "user"):
        raise GroupError("mapped_role must be 'admin', 'user' or null", status=422)


# ── Membership ────────────────────────────────────────────────────────────────


def list_members(group_id: int) -> list[dict]:
    with get_session() as session:
        if not session.query(UserGroup.id).filter_by(id=group_id).first():
            raise GroupError("Group not found", status=404)
        rows = (
            session.query(UserGroupMember, User)
            .join(User, User.id == UserGroupMember.user_id)
            .filter(UserGroupMember.group_id == group_id)
            .order_by(User.username)
            .all()
        )
        return [
            {
                "user_id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": bool(u.is_active),
                "source": m.source,
                "added_at": m.added_at.isoformat() if m.added_at else None,
                "added_by": m.added_by,
            }
            for m, u in rows
        ]


def add_members(group_id: int, user_ids: Iterable[int], added_by: Optional[str] = None) -> dict:
    """Add local memberships. Already-members are skipped, not rejected."""
    user_ids = [int(u) for u in user_ids]
    if not user_ids:
        raise GroupError("No users selected", status=400)

    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise GroupError("Group not found", status=404)
        found = {u for (u,) in session.query(User.id).filter(User.id.in_(user_ids))}
        missing = set(user_ids) - found
        if missing:
            raise GroupError(f"Unknown user id(s): {sorted(missing)}", status=404)

        already = {
            uid
            for (uid,) in session.query(UserGroupMember.user_id).filter(
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id.in_(user_ids),
            )
        }
        added = []
        for uid in user_ids:
            if uid in already:
                continue
            session.add(
                UserGroupMember(
                    group_id=group_id, user_id=uid, source="local", added_by=added_by
                )
            )
            added.append(uid)
        session.flush()

        if added and g.mapped_role:
            from api.routers.scim import _reconcile_roles
            _reconcile_roles(session, group_id)

        return {"added": added, "skipped": sorted(already), "group_name": g.display_name}


def remove_member(group_id: int, user_id: int) -> None:
    """Drop one membership.

    A SCIM-owned membership is refused — the IdP would put it straight back,
    and the admin needs to know the change belongs in the IdP instead.
    """
    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise GroupError("Group not found", status=404)
        m = session.query(UserGroupMember).filter_by(group_id=group_id, user_id=user_id).first()
        if not m:
            raise GroupError("Not a member of this group", status=404)
        if m.source == "scim":
            raise GroupError(
                "This membership comes from the identity provider — remove it there",
                status=409,
            )
        session.delete(m)
        session.flush()

        if g.mapped_role:
            from api.routers.scim import _reconcile_roles
            _reconcile_roles(session, group_id, extra_user_ids=[user_id])


def groups_for_user(user_id: int) -> list[dict]:
    """The groups one account belongs to, for the user detail view."""
    with get_session() as session:
        rows = (
            session.query(UserGroup, UserGroupMember.source)
            .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
            .filter(UserGroupMember.user_id == user_id)
            .order_by(UserGroup.display_name)
            .all()
        )
        return [
            {
                "id": g.id,
                "display_name": g.display_name,
                "mapped_role": g.mapped_role,
                "source": g.source,
                "membership_source": src,
            }
            for g, src in rows
        ]


# ── Tenant grants ─────────────────────────────────────────────────────────────


def list_tenant_grants(group_id: int) -> list[dict]:
    with get_session() as session:
        if not session.query(UserGroup.id).filter_by(id=group_id).first():
            raise GroupError("Group not found", status=404)
        rows = (
            session.query(GroupTenantEntitlement, TenantConfig)
            .join(TenantConfig, TenantConfig.id == GroupTenantEntitlement.tenant_id)
            .filter(GroupTenantEntitlement.group_id == group_id)
            .order_by(TenantConfig.name)
            .all()
        )
        return [
            {
                "id": e.id,
                "group_id": e.group_id,
                "tenant_id": e.tenant_id,
                "tenant_name": t.name,
                "granted_at": e.granted_at.isoformat() if e.granted_at else None,
                "granted_by": e.granted_by,
            }
            for e, t in rows
        ]


def grant_tenants(
    group_id: int, tenant_ids: Iterable[int], granted_by: Optional[str] = None
) -> dict:
    """Grant a group access to tenants, in one transaction like the user path."""
    tenant_ids = list(dict.fromkeys(int(t) for t in tenant_ids))
    if not tenant_ids:
        raise GroupError("No tenants selected", status=400)

    with get_session() as session:
        g = session.query(UserGroup).filter_by(id=group_id).first()
        if not g:
            raise GroupError("Group not found", status=404)
        found = {t for (t,) in session.query(TenantConfig.id).filter(TenantConfig.id.in_(tenant_ids))}
        missing = [t for t in tenant_ids if t not in found]
        if missing:
            raise GroupError(f"Tenant not found: {', '.join(str(t) for t in missing)}", status=404)

        already = {
            tid
            for (tid,) in session.query(GroupTenantEntitlement.tenant_id).filter(
                GroupTenantEntitlement.group_id == group_id,
                GroupTenantEntitlement.tenant_id.in_(tenant_ids),
            )
        }
        granted = [t for t in tenant_ids if t not in already]
        for tid in granted:
            session.add(
                GroupTenantEntitlement(group_id=group_id, tenant_id=tid, granted_by=granted_by)
            )
        session.flush()
        return {"granted": granted, "skipped": sorted(already), "group_name": g.display_name}


def revoke_tenant(group_id: int, tenant_id: int) -> None:
    with get_session() as session:
        row = (
            session.query(GroupTenantEntitlement)
            .filter_by(group_id=group_id, tenant_id=tenant_id)
            .first()
        )
        if not row:
            raise GroupError("Grant not found", status=404)
        session.delete(row)


def effective_tenant_ids(user_id: int) -> set[int]:
    """Every tenant this account can reach: its own grants plus its groups'.

    The single source of truth for non-admin tenant visibility. Both the
    listing and the per-tenant check go through here so a group grant cannot
    show a tenant the account is then refused entry to.
    """
    with get_session() as session:
        ids = {
            tid
            for (tid,) in session.query(UserTenantEntitlement.tenant_id).filter_by(user_id=user_id)
        }
        group_ids = [
            gid for (gid,) in session.query(UserGroupMember.group_id).filter_by(user_id=user_id)
        ]
        if group_ids:
            ids |= {
                tid
                for (tid,) in session.query(GroupTenantEntitlement.tenant_id).filter(
                    GroupTenantEntitlement.group_id.in_(group_ids)
                )
            }
    return ids
