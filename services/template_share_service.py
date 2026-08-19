"""Who may see, apply, and manage a ZIA template.

A template is owned by whoever created it.  From there it is private, shared
with named users and groups, or published org-wide — `ZIATemplate.visibility`
decides which, and this module is the only place that decision is read.

Two grades of permission, not three.  `can_read` and `can_apply` are the same
check: applying is already gated on `check_tenant_access`, so a read-only share
would protect nothing — the holder can list the template's contents either way,
and without tenant access they cannot push it anywhere.  `can_manage` (rename,
re-share, delete) is the elevated grade, and it belongs to the owner and to
admins.

Group grants resolve through current membership at read time rather than being
expanded into user rows, so an account that leaves a group loses the template on
its next request with nothing to clean up here — the same shape
`plugin_entitlement_service` uses.
"""

from datetime import datetime
from typing import Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from db.models import (
    TemplateShare, User, UserGroup, UserGroupMember, ZIATemplate,
)


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

def _group_ids_for(user_id: int, session: Session) -> List[int]:
    """Groups this account belongs to — the same source GroupTenantEntitlement reads."""
    return [
        g for (g,) in session.query(UserGroupMember.group_id).filter_by(user_id=user_id)
    ]


def visible_template_ids(user_id: int, role: str, session: Session) -> Optional[Set[int]]:
    """Return the set of template IDs this account may see, or None for 'all'.

    None is the admin sentinel, and is deliberately distinct from an empty set:
    it lets the caller drop the IN-clause entirely instead of building one over
    every row in the table, and it cannot be mistaken for "an admin who has been
    granted nothing".

    `role` is the role the session has *assumed*, not every role the account
    holds — an account that could be an admin but is sitting in `user` sees only
    its own and shared templates, which is how every other check in the app
    behaves.
    """
    if role == "admin":
        return None

    ids: Set[int] = {
        t for (t,) in session.query(ZIATemplate.id).filter(ZIATemplate.visibility == "org")
    }
    ids |= {
        t for (t,) in session.query(ZIATemplate.id).filter(
            ZIATemplate.owner_user_id == user_id
        )
    }
    ids |= {
        t for (t,) in session.query(TemplateShare.template_id).filter(
            TemplateShare.user_id == user_id
        )
    }
    group_ids = _group_ids_for(user_id, session)
    if group_ids:
        ids |= {
            t for (t,) in session.query(TemplateShare.template_id).filter(
                TemplateShare.group_id.in_(group_ids)
            )
        }
    return ids


def can_read(template: ZIATemplate, user_id: int, role: str, session: Session) -> bool:
    """Whether this account may see the template at all."""
    if role == "admin":
        return True
    if template.visibility == "org":
        return True
    if template.owner_user_id is not None and template.owner_user_id == user_id:
        return True
    if template.visibility != "shared":
        return False

    shares = session.query(TemplateShare).filter_by(template_id=template.id).all()
    if any(s.user_id == user_id for s in shares):
        return True
    group_ids = set(_group_ids_for(user_id, session))
    return any(s.group_id in group_ids for s in shares if s.group_id is not None)


#: Applying is the same permission as reading — see the module docstring.
can_apply = can_read


def can_manage(template: ZIATemplate, user_id: int, role: str) -> bool:
    """Whether this account may rename, re-share, or delete the template.

    A legacy template (`owner_user_id IS NULL`) is admin-only: nobody can be
    handed ownership of one without guessing, and guessing wrong gives one user
    unilateral delete rights over an object the whole org can see.  An admin can
    adopt one explicitly through PATCH.
    """
    if role == "admin":
        return True
    return template.owner_user_id is not None and template.owner_user_id == user_id


# ---------------------------------------------------------------------------
# Share CRUD
# ---------------------------------------------------------------------------

def _out(row: TemplateShare, username: Optional[str], group_name: Optional[str]) -> dict:
    return {
        "id": row.id,
        "template_id": row.template_id,
        "user_id": row.user_id,
        "username": username,
        "group_id": row.group_id,
        "group_name": group_name,
        "shared_at": row.shared_at.isoformat() + "Z" if row.shared_at else None,
        "shared_by": row.shared_by,
    }


def list_shares(template_id: int, session: Session) -> List[dict]:
    """Every grant on one template, users before groups, each by name."""
    rows = (
        session.query(TemplateShare)
        .filter_by(template_id=template_id)
        .order_by(TemplateShare.id)
        .all()
    )
    if not rows:
        return []
    user_names = dict(session.query(User.id, User.username).all())
    group_names = dict(session.query(UserGroup.id, UserGroup.display_name).all())
    return [_out(r, user_names.get(r.user_id), group_names.get(r.group_id)) for r in rows]


def share_counts(template_ids: Iterable[int], session: Session) -> dict:
    """template_id → number of grants, for the list view's "Shared with N" chip."""
    counts: dict = {}
    ids = list(template_ids)
    if not ids:
        return counts
    rows = session.query(TemplateShare.template_id).filter(
        TemplateShare.template_id.in_(ids)
    ).all()
    for (tid,) in rows:
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def add_shares(
    template: ZIATemplate,
    user_ids: Iterable[int],
    group_ids: Iterable[int],
    shared_by: Optional[str],
    session: Session,
) -> List[dict]:
    """Grant a template to users and/or groups.  Returns the rows created.

    Idempotent: re-posting a grant that already exists is a no-op rather than a
    conflict, because the UI grants from a checkbox list and a stale checkbox
    should not undo the rest of the selection.  The partial unique indexes are
    the backstop; this checks first so the common case never depends on catching
    an IntegrityError.

    Raises ValueError (→ 422) for an unknown or inactive user, an unknown group,
    or the owner's own account — the last would render as a redundant chip
    granting nothing.
    """
    user_ids = [int(u) for u in user_ids]
    group_ids = [int(g) for g in group_ids]
    if not user_ids and not group_ids:
        raise ValueError("Provide at least one user or group")

    if template.owner_user_id is not None and template.owner_user_id in user_ids:
        raise ValueError("The owner already has access and cannot be shared with")

    if user_ids:
        found = {
            u for (u,) in session.query(User.id).filter(
                User.id.in_(user_ids), User.is_active.is_(True)
            )
        }
        missing = set(user_ids) - found
        if missing:
            raise ValueError(f"Unknown or inactive user id(s): {sorted(missing)}")
    if group_ids:
        found = {
            g for (g,) in session.query(UserGroup.id).filter(UserGroup.id.in_(group_ids))
        }
        missing = set(group_ids) - found
        if missing:
            raise ValueError(f"Unknown group id(s): {sorted(missing)}")

    existing = session.query(TemplateShare).filter_by(template_id=template.id).all()
    have_users = {e.user_id for e in existing if e.user_id is not None}
    have_groups = {e.group_id for e in existing if e.group_id is not None}

    created: List[TemplateShare] = []
    now = datetime.utcnow()
    for uid in user_ids:
        if uid in have_users:
            continue
        row = TemplateShare(template_id=template.id, user_id=uid,
                            shared_at=now, shared_by=shared_by)
        session.add(row)
        created.append(row)
    for gid in group_ids:
        if gid in have_groups:
            continue
        row = TemplateShare(template_id=template.id, group_id=gid,
                            shared_at=now, shared_by=shared_by)
        session.add(row)
        created.append(row)

    session.flush()
    if not created:
        return []
    user_names = dict(session.query(User.id, User.username).all())
    group_names = dict(session.query(UserGroup.id, UserGroup.display_name).all())
    return [_out(r, user_names.get(r.user_id), group_names.get(r.group_id)) for r in created]


def remove_share(template_id: int, share_id: int, session: Session) -> Optional[dict]:
    """Drop one grant.  Returns what was removed, or None if it was already gone."""
    row = session.query(TemplateShare).filter_by(
        id=share_id, template_id=template_id
    ).first()
    if row is None:
        return None
    user_name = None
    group_name = None
    if row.user_id is not None:
        user_name = session.query(User.username).filter_by(id=row.user_id).scalar()
    if row.group_id is not None:
        group_name = session.query(UserGroup.display_name).filter_by(id=row.group_id).scalar()
    out = _out(row, user_name, group_name)
    session.delete(row)
    return out
