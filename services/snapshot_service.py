"""Snapshot (restore point) service.

DB-only — no API calls.  Captures point-in-time snapshots of a tenant's
local resource cache, computes field-level diffs between any two snapshots
(or a snapshot vs. the current DB state), and persists/deletes snapshot rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db.models import RestorePoint, ZIAResource, ZPAResource

# Fields that carry no meaningful configuration signal — excluded from diffs.
IGNORED_FIELDS = frozenset({
    "modifiedBy", "modifiedTime", "creationTime", "modifiedAt",
    "createdAt", "lastModifiedTime", "modifiedByUser", "createdByUser",
})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FieldChange:
    field: str
    old: Any
    new: Any


@dataclass
class ResourceDiff:
    resource_type: str
    added: List[dict] = field(default_factory=list)    # {"id", "name", "raw_config"}
    removed: List[dict] = field(default_factory=list)
    modified: List[dict] = field(default_factory=list) # {"id","name","field_changes","old_config","new_config"}


@dataclass
class DiffResult:
    resource_diffs: List[ResourceDiff] = field(default_factory=list)

    @property
    def total_added(self) -> int:
        return sum(len(rd.added) for rd in self.resource_diffs)

    @property
    def total_removed(self) -> int:
        return sum(len(rd.removed) for rd in self.resource_diffs)

    @property
    def total_modified(self) -> int:
        return sum(len(rd.modified) for rd in self.resource_diffs)

    @property
    def is_empty(self) -> bool:
        return self.total_added == 0 and self.total_removed == 0 and self.total_modified == 0


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_snapshot_data_current(tenant_id: int, product: str, session: Session) -> Dict[str, List[dict]]:
    """Return the current (non-deleted) resource inventory for a tenant+product.

    Result shape: {"resource_type": [{"id": <api_id>, "name": ..., "raw_config": {...}}, ...]}
    """
    result: Dict[str, List[dict]] = {}

    if product.upper() == "ZPA":
        rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, is_deleted=False)
            .order_by(ZPAResource.resource_type, ZPAResource.name)
            .all()
        )
        for row in rows:
            result.setdefault(row.resource_type, []).append(
                {"id": row.zpa_id, "name": row.name, "raw_config": row.raw_config or {}}
            )
    else:  # ZIA
        rows = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, is_deleted=False)
            .order_by(ZIAResource.resource_type, ZIAResource.name)
            .all()
        )
        for row in rows:
            result.setdefault(row.resource_type, []).append(
                {"id": row.zia_id, "name": row.name, "raw_config": row.raw_config or {}}
            )

    return result


def create_snapshot(
    tenant_id: int,
    product: str,
    name: str,
    comment: Optional[str],
    session: Session,
) -> RestorePoint:
    """Capture the current DB state as a new RestorePoint row."""
    current_data = get_snapshot_data_current(tenant_id, product, session)
    resource_count = sum(len(v) for v in current_data.values())
    snap = RestorePoint(
        tenant_id=tenant_id,
        product=product.upper(),
        name=name,
        comment=comment or None,
        created_at=datetime.utcnow(),
        resource_count=resource_count,
        snapshot={"resources": current_data},
    )
    session.add(snap)
    session.flush()  # populate snap.id before caller returns
    return snap


def list_snapshots(tenant_id: int, product: str, session: Session) -> List[RestorePoint]:
    """Return all snapshots for a tenant+product, newest first."""
    return (
        session.query(RestorePoint)
        .filter_by(tenant_id=tenant_id, product=product.upper())
        .order_by(RestorePoint.created_at.desc())
        .all()
    )


def delete_snapshot(snapshot_id: int, session: Session) -> None:
    """Delete a snapshot by primary key."""
    snap = session.query(RestorePoint).filter_by(id=snapshot_id).first()
    if snap:
        session.delete(snap)


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def _compute_field_changes(old_config: dict, new_config: dict) -> List[FieldChange]:
    """Return field-level changes between two raw_config dicts, skipping IGNORED_FIELDS."""
    changes = []
    all_keys = sorted(set(old_config.keys()) | set(new_config.keys()))
    for key in all_keys:
        if key in IGNORED_FIELDS:
            continue
        old_val = old_config.get(key)
        new_val = new_config.get(key)
        if old_val != new_val:
            changes.append(FieldChange(field=key, old=old_val, new=new_val))
    return changes


def compute_diff(snapshot_a: dict, snapshot_b: dict) -> DiffResult:
    """Compute the diff between two resource dicts.

    snapshot_a — base/older state  ({"resource_type": [{"id","name","raw_config"}, ...]})
    snapshot_b — current/newer state

    Returns a DiffResult containing only resource types with ≥1 change.
    """
    all_types = sorted(set(snapshot_a.keys()) | set(snapshot_b.keys()))
    diffs: List[ResourceDiff] = []

    for rtype in all_types:
        a_by_id = {item["id"]: item for item in snapshot_a.get(rtype, [])}
        b_by_id = {item["id"]: item for item in snapshot_b.get(rtype, [])}

        added   = [b_by_id[id_] for id_ in b_by_id if id_ not in a_by_id]
        removed = [a_by_id[id_] for id_ in a_by_id if id_ not in b_by_id]

        modified = []
        for id_ in a_by_id:
            if id_ in b_by_id:
                a_item = a_by_id[id_]
                b_item = b_by_id[id_]
                changes = _compute_field_changes(
                    a_item.get("raw_config") or {},
                    b_item.get("raw_config") or {},
                )
                if changes:
                    modified.append({
                        "id": id_,
                        "name": b_item.get("name") or a_item.get("name"),
                        "field_changes": changes,
                        "old_config": a_item.get("raw_config") or {},
                        "new_config": b_item.get("raw_config") or {},
                    })

        if added or removed or modified:
            diffs.append(ResourceDiff(
                resource_type=rtype,
                added=added,
                removed=removed,
                modified=modified,
            ))

    return DiffResult(resource_diffs=diffs)
