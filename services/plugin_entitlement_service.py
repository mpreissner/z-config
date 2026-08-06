"""Who may use an installed plugin.

Installing a plugin makes it available to the deployment, not to its users.
zs-config can run as a shared service, so a plugin an admin installs for one
team must not appear for everyone with an account; this module is the grant
list that decides.

A grant names either a user or a group. Group grants are resolved through
current membership at read time rather than expanded into user rows, so an
account that leaves the group — whether the IdP moved it or an admin did —
loses the plugin on its next request with nothing to clean up here.

Admins are not checked against the list — they install the plugins, and
`UserTenantEntitlement` already sets that precedent for tenant access.
"""

from datetime import datetime
from typing import Iterable, Optional

from db.database import get_session
from db.models import PluginEntitlement, UserGroup, UserGroupMember, User


def _out(row: PluginEntitlement, username: Optional[str], group_name: Optional[str]) -> dict:
    return {
        "id": row.id,
        "package": row.package,
        "user_id": row.user_id,
        "username": username,
        "group_id": row.group_id,
        "group_name": group_name,
        "granted_at": row.granted_at.isoformat() if row.granted_at else None,
        "granted_by": row.granted_by,
    }


def list_entitlements(package: Optional[str] = None) -> list[dict]:
    """Every grant, or only those for one package, newest last."""
    with get_session() as session:
        query = session.query(PluginEntitlement)
        if package:
            query = query.filter(PluginEntitlement.package == package)
        rows = query.order_by(PluginEntitlement.package, PluginEntitlement.id).all()

        user_names = dict(session.query(User.id, User.username).all())
        group_names = dict(session.query(UserGroup.id, UserGroup.display_name).all())

        return [
            _out(r, user_names.get(r.user_id), group_names.get(r.group_id))
            for r in rows
        ]


def grant(
    package: str,
    user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    granted_by: Optional[str] = None,
) -> dict:
    """Grant a package to users and/or groups in one transaction.

    Subjects that already hold the package are reported as skipped rather than
    failing the whole request — the UI grants from a checkbox list, and a
    stale checkbox should not undo the rest of the selection.

    Returns {"granted": [...], "skipped_user_ids": [...], "skipped_group_ids": [...]}.
    Raises ValueError for an unknown user or group.
    """
    user_ids = [int(u) for u in user_ids]
    group_ids = [int(g) for g in group_ids]
    if not user_ids and not group_ids:
        raise ValueError("Provide at least one user or group")

    with get_session() as session:
        if user_ids:
            found = {u for (u,) in session.query(User.id).filter(User.id.in_(user_ids))}
            missing = set(user_ids) - found
            if missing:
                raise ValueError(f"Unknown user id(s): {sorted(missing)}")
        if group_ids:
            found = {g for (g,) in session.query(UserGroup.id).filter(UserGroup.id.in_(group_ids))}
            missing = set(group_ids) - found
            if missing:
                raise ValueError(f"Unknown group id(s): {sorted(missing)}")

        existing = session.query(PluginEntitlement).filter_by(package=package).all()
        have_users = {e.user_id for e in existing if e.user_id is not None}
        have_groups = {e.group_id for e in existing if e.group_id is not None}

        created: list[PluginEntitlement] = []
        now = datetime.utcnow()
        for uid in user_ids:
            if uid in have_users:
                continue
            row = PluginEntitlement(
                package=package, user_id=uid, granted_at=now, granted_by=granted_by
            )
            session.add(row)
            created.append(row)
        for gid in group_ids:
            if gid in have_groups:
                continue
            row = PluginEntitlement(
                package=package, group_id=gid, granted_at=now, granted_by=granted_by
            )
            session.add(row)
            created.append(row)

        session.flush()

        user_names = dict(session.query(User.id, User.username).all())
        group_names = dict(session.query(UserGroup.id, UserGroup.display_name).all())
        granted = [
            _out(r, user_names.get(r.user_id), group_names.get(r.group_id))
            for r in created
        ]

    return {
        "granted": granted,
        "skipped_user_ids": sorted(set(user_ids) & have_users),
        "skipped_group_ids": sorted(set(group_ids) & have_groups),
    }


def revoke(entitlement_id: int) -> bool:
    """Drop one grant. Returns False if it was already gone."""
    with get_session() as session:
        row = session.query(PluginEntitlement).filter_by(id=entitlement_id).first()
        if not row:
            return False
        session.delete(row)
    return True


def revoke_package(package: str) -> int:
    """Drop every grant for a package. Returns how many were removed.

    Called when a plugin is uninstalled with its data purged: keeping grants
    for a package whose tables are gone would silently re-authorize everyone
    if it were ever reinstalled.
    """
    with get_session() as session:
        rows = session.query(PluginEntitlement).filter_by(package=package).all()
        count = len(rows)
        for row in rows:
            session.delete(row)
    return count


def entitled_packages(user_id: int, role: str = "user") -> Optional[list[str]]:
    """Packages this account may use, or None when the account may use any.

    None means "no restriction" (admin) and is deliberately distinct from an
    empty list, so a caller cannot mistake an admin for someone with nothing
    granted.
    """
    if role == "admin":
        return None

    with get_session() as session:
        group_ids = [
            g for (g,) in session.query(UserGroupMember.group_id).filter_by(user_id=user_id)
        ]
        query = session.query(PluginEntitlement.package).filter(
            PluginEntitlement.user_id == user_id
        )
        rows = {p for (p,) in query}
        if group_ids:
            rows |= {
                p for (p,) in session.query(PluginEntitlement.package).filter(
                    PluginEntitlement.group_id.in_(group_ids)
                )
            }
    return sorted(rows)


def may_use(user_id: int, role: str, package: str) -> bool:
    """Whether this account is allowed to use a plugin."""
    allowed = entitled_packages(user_id, role)
    return allowed is None or package in allowed
