"""Which roles an account may hold, and which one it holds right now.

`User.role` is the account's own role. Any group it belongs to can map to a
role as well, and those add to what the account may assume rather than
overwriting the base — someone can be a plain user in their own right and an
admin through a group without the two fighting over one column.

Only one of them is ever active. A token carries the whole set in `roles` and
the active one in `role`, and every authorisation check in the app reads the
active one, so holding admin in reserve grants nothing at all until it is
assumed. Sessions start at the least privilege on offer and the account has to
ask for more, which is why `resolve_active` falls back down rather than up.
"""

from typing import List, Optional, Sequence, Set

# Least privileged first. This is the order a session defaults through, so
# adding a role here means deciding where it sits relative to the others.
ROLE_ORDER = ("user", "admin")


def _group_roles(session, user_id: int) -> Set[str]:
    from db.models import UserGroup, UserGroupMember

    rows = (
        session.query(UserGroup.mapped_role)
        .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .filter(UserGroupMember.user_id == user_id)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def available_roles(user_id: int, base_role: str, *, session=None) -> List[str]:
    """Every role this account may assume, least privileged first.

    Pass `session` when calling from inside an open one — a second session
    against the same SQLite file is exactly what the project rule forbids.
    """
    if session is not None:
        roles = _group_roles(session, user_id)
    else:
        from db.database import get_session

        with get_session() as s:
            roles = _group_roles(s, user_id)
    if base_role:
        roles.add(base_role)
    return _order(roles)


def _order(roles: Set[str]) -> List[str]:
    ordered = [r for r in ROLE_ORDER if r in roles]
    # A role this module has never heard of still belongs to the account; it
    # sorts after the known ones rather than being silently dropped.
    return ordered + sorted(r for r in roles if r not in ROLE_ORDER)


def roles_for_users(session, users) -> dict:
    """`{user_id: [roles]}` for a whole list of accounts in one query.

    The per-account form would be one round trip each, which the admin user
    list would pay on every render. `users` is anything with `.id` and `.role`.
    """
    from db.models import UserGroup, UserGroupMember

    ids = [u.id for u in users]
    out = {u.id: ({u.role} if u.role else set()) for u in users}
    if not ids:
        return {}
    rows = (
        session.query(UserGroupMember.user_id, UserGroup.mapped_role)
        .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
        .filter(UserGroupMember.user_id.in_(ids))
        .all()
    )
    for user_id, role in rows:
        if role:
            out[user_id].add(role)
    return {uid: _order(roles) for uid, roles in out.items()}


LAST_ADMIN_MESSAGE = (
    "This change would leave the install with no active administrator"
)


def active_admin_count(session) -> int:
    """How many accounts can administer this install *right now*.

    Base role or group mapping — the same union `available_roles` performs, so
    an account that is only an admin through a group counts, and demoting the
    last `User.role == "admin"` is not by itself a lockout.

    Meant to be called *after* a change has been flushed and *before* its
    session commits. `get_session` rolls back on the way out, so a caller that
    sees zero here refuses by raising and the change is undone. Measuring the
    result beats predicting it: every write path asks the same question of the
    same data, and no caller has to model what its own edit was about to do.
    """
    from db.models import User, UserGroup, UserGroupMember

    admins = {
        uid
        for (uid,) in session.query(User.id).filter(
            User.role == "admin", User.is_active.is_(True)
        )
    }
    # "admin" is hardcoded where ROLE_ORDER is not: this counts who can still
    # unlock the deployment, and only one role does that.
    admins |= {
        uid
        for (uid,) in session.query(UserGroupMember.user_id)
        .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
        .join(User, User.id == UserGroupMember.user_id)
        .filter(UserGroup.mapped_role == "admin", User.is_active.is_(True))
    }
    return len(admins)


def resolve_active(roles: Sequence[str], requested: Optional[str] = None) -> str:
    """The role a session should hold.

    The requested one if it is still on offer — a role can be revoked while a
    refresh token that names it is still valid — otherwise least privilege.
    """
    if requested and requested in roles:
        return requested
    return roles[0] if roles else "user"
