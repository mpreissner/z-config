"""Lifecycle for migration candidates staged in the resource tables.

A *candidate* is a resource a generator (today, the palo-tools plugin) proposes
for a tenant but that does not exist there yet.  Candidates live in the same
`zpa_resources` / `zia_resources` tables as imported tenant config, marked by
`source != 'tenant'` and carrying a synthetic id `<source>:<name>` in place of
the tenant-assigned one.

    ingest -> pending -> accepted -> (push) -> promote -> live row
                  |
                  +-> rejected -> discard

`promote` is what ends a row's life as a candidate: it writes the id the tenant
assigned during the push, reverts `source` to 'tenant' and clears
`candidate_status`, leaving a row indistinguishable from natively imported
config.  `purge_plugin_data` (lib/plugin_manager.py) already relies on that
contract to avoid deleting objects a plugin successfully pushed.

Two invariants keep candidates from leaking into live state:

* `synced_at` is never set on a candidate row.  Both import services mark rows
  stale with `synced_at < run_start`, and a candidate is never returned by the
  tenant API, so a non-NULL value would get it flagged deleted on the next
  import.
* readers of live state filter on `source == 'tenant'` — see
  `get_snapshot_data_current`, which feeds snapshots, the push baseline and the
  diff endpoint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from db.database import get_session
from db.models import ZIAResource, ZPAResource

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_TENANT = "tenant"          # a live row imported from the tenant

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
VALID_STATUSES = (STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED)

# (model, id column name) per product
_PRODUCTS = {
    "ZPA": (ZPAResource, "zpa_id"),
    "ZIA": (ZIAResource, "zia_id"),
}


def _model_for(product: str):
    try:
        return _PRODUCTS[(product or "").upper()]
    except KeyError:
        raise ValueError(f"Unsupported product for candidates: {product!r}")


def candidate_key(source: str, name: str) -> str:
    """Synthetic id for a candidate: stable per (source, name) within a type.

    Stability is what makes re-ingesting the same generated object an update
    rather than a duplicate — the table's unique constraint on
    (tenant_id, resource_type, <product>_id) does the deduplication.
    """
    return f"{source}:{name}"


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """A staged resource, detached from the session that read it."""
    id: int
    tenant_id: int
    product: str
    resource_type: str
    key: str                       # synthetic id, '<source>:<name>'
    name: str
    raw_config: dict
    source: str
    status: Optional[str]
    first_seen_at: Optional[datetime]
    live_match_id: Optional[str] = None      # live row of the same type+name, if any

    def to_item(self) -> dict:
        """Snapshot wire shape, as consumed by the push services."""
        return {"id": self.key, "name": self.name, "raw_config": self.raw_config}


@dataclass
class IngestResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    discarded: int = 0             # non-zero only when replace=True
    skipped: List[str] = field(default_factory=list)   # reasons, e.g. unnamed records

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


@dataclass
class PromoteResult:
    promoted: int = 0
    superseded: int = 0            # a live row already held the tenant id
    missing: List[str] = field(default_factory=list)   # keys with no candidate row


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest(
    tenant_id: int,
    product: str,
    resources: Dict[str, List[dict]],
    source: str = "palo",
    replace: bool = False,
) -> IngestResult:
    """Stage generated resources as pending candidates.

    `resources` uses the same shape as a snapshot — {"<rtype>": [{"name":...,
    "raw_config": {...}}, ...]} — so a generator can hand over what it produced
    without a bespoke format.

    An existing candidate with the same key is updated in place and keeps its
    status, except that a `rejected` row returns to `pending`: re-offering an
    object the user turned down is a deliberate act by the generator and should
    surface for review again.

    `replace=True` first discards this source's existing candidates for the
    tenant+product, for generators that regenerate their whole output.  Rows
    already promoted are unaffected — they are no longer candidates.
    """
    if source == SOURCE_TENANT:
        raise ValueError("'tenant' is reserved for live rows, not candidates")

    model, id_col = _model_for(product)
    result = IngestResult()
    pending_audit: List[dict] = []
    now = datetime.utcnow()

    with get_session() as session:
        if replace:
            doomed = (
                session.query(model)
                .filter(model.tenant_id == tenant_id, model.source == source)
                .all()
            )
            for row in doomed:
                session.delete(row)
            result.discarded = len(doomed)

        for resource_type, records in (resources or {}).items():
            for record in records or []:
                if not isinstance(record, dict):
                    result.skipped.append(f"{resource_type}: not a mapping")
                    continue
                name = record.get("name") or ""
                if not name:
                    result.skipped.append(f"{resource_type}: record has no name")
                    continue
                raw_config = record.get("raw_config")
                if raw_config is None:
                    raw_config = {k: v for k, v in record.items() if k not in ("raw_config",)}

                key = candidate_key(source, name)
                new_hash = _hash(raw_config)

                existing = (
                    session.query(model)
                    .filter(
                        model.tenant_id == tenant_id,
                        model.resource_type == resource_type,
                        getattr(model, id_col) == key,
                    )
                    .first()
                )

                if existing is None:
                    row = model(
                        tenant_id=tenant_id,
                        resource_type=resource_type,
                        name=name,
                        raw_config=raw_config,
                        config_hash=new_hash,
                        # synced_at deliberately left NULL — see module docstring
                        is_deleted=False,
                        first_seen_at=now,
                        source=source,
                        candidate_status=STATUS_PENDING,
                    )
                    setattr(row, id_col, key)
                    session.add(row)
                    result.created += 1
                    pending_audit.append(dict(
                        action="CREATE", resource_type=resource_type,
                        resource_id=key, resource_name=name,
                    ))
                elif existing.source == SOURCE_TENANT:
                    # Should not happen: a live id never looks like '<source>:<name>'.
                    result.skipped.append(f"{resource_type}/{name}: id collides with a live row")
                else:
                    changed = existing.config_hash != new_hash
                    existing.name = name
                    existing.raw_config = raw_config
                    existing.config_hash = new_hash
                    existing.is_deleted = False
                    if existing.candidate_status == STATUS_REJECTED:
                        existing.candidate_status = STATUS_PENDING
                        changed = True
                    if changed:
                        result.updated += 1
                        pending_audit.append(dict(
                            action="UPDATE", resource_type=resource_type,
                            resource_id=key, resource_name=name,
                        ))
                    else:
                        result.unchanged += 1

    # Session is closed — safe to write audit entries now.
    _audit_many(product, "candidate_ingest", tenant_id, pending_audit, source=source)
    return result


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def list_candidates(
    tenant_id: int,
    product: str,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    source: Optional[str] = None,
    with_live_match: bool = False,
) -> List[Candidate]:
    """Return staged candidates, newest generator output last.

    `with_live_match` annotates each row with the id of the live resource of the
    same type and name, if one exists, so a review UI can warn that accepting
    this candidate would modify an object the tenant already has.
    """
    model, id_col = _model_for(product)
    product = product.upper()

    with get_session() as session:
        q = session.query(model).filter(
            model.tenant_id == tenant_id,
            model.source != SOURCE_TENANT,
            model.is_deleted == False,  # noqa: E712 — SQLAlchemy column comparison
        )
        if status:
            q = q.filter(model.candidate_status == status)
        if resource_type:
            q = q.filter(model.resource_type == resource_type)
        if source:
            q = q.filter(model.source == source)
        rows = q.order_by(model.resource_type, model.name).all()

        out = [
            Candidate(
                id=row.id,
                tenant_id=row.tenant_id,
                product=product,
                resource_type=row.resource_type,
                key=getattr(row, id_col),
                name=row.name or "",
                raw_config=row.raw_config or {},
                source=row.source,
                status=row.candidate_status,
                first_seen_at=row.first_seen_at,
            )
            for row in rows
        ]

        if with_live_match and out:
            live = (
                session.query(model)
                .filter(
                    model.tenant_id == tenant_id,
                    model.source == SOURCE_TENANT,
                    model.is_deleted == False,  # noqa: E712
                    model.resource_type.in_({c.resource_type for c in out}),
                )
                .all()
            )
            by_name = {
                (r.resource_type, (r.name or "").casefold()): getattr(r, id_col)
                for r in live
                if r.name
            }
            for cand in out:
                cand.live_match_id = by_name.get((cand.resource_type, cand.name.casefold()))

    return out


def counts(tenant_id: int, product: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """Candidate counts per product, keyed by status — for review badges.

    Shape: {"ZPA": {"pending": 3, "accepted": 0, "rejected": 1, "total": 4}, ...}
    """
    products = [product.upper()] if product else list(_PRODUCTS)
    out: Dict[str, Dict[str, int]] = {}

    with get_session() as session:
        for prod in products:
            model, _ = _model_for(prod)
            rows = (
                session.query(model.candidate_status)
                .filter(
                    model.tenant_id == tenant_id,
                    model.source != SOURCE_TENANT,
                    model.is_deleted == False,  # noqa: E712
                )
                .all()
            )
            tally = {s: 0 for s in VALID_STATUSES}
            for (st,) in rows:
                if st in tally:
                    tally[st] += 1
            tally["total"] = sum(tally[s] for s in VALID_STATUSES)
            out[prod] = tally

    return out


def accepted_resources(
    tenant_id: int,
    product: str,
    resource_type: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, List[dict]]:
    """Accepted candidates in the snapshot wire shape, ready to push.

    Returns {"<rtype>": [{"id", "name", "raw_config"}, ...]}.  The ids are
    synthetic; the push services match candidates by name and remap those ids to
    the tenant-assigned ones as each resource is created.
    """
    out: Dict[str, List[dict]] = {}
    for cand in list_candidates(
        tenant_id, product, status=STATUS_ACCEPTED,
        resource_type=resource_type, source=source,
    ):
        out.setdefault(cand.resource_type, []).append(cand.to_item())
    return out


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def set_status(
    tenant_id: int,
    product: str,
    candidate_ids: Sequence[int],
    status: str,
) -> int:
    """Move candidates to `status`.  Returns the number of rows changed.

    Only rows that are candidates are eligible — a live row can never be moved
    into the candidate state machine by this call.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid candidate status: {status!r}")
    ids = [int(i) for i in candidate_ids or []]
    if not ids:
        return 0

    model, id_col = _model_for(product)
    pending_audit: List[dict] = []

    with get_session() as session:
        rows = (
            session.query(model)
            .filter(
                model.tenant_id == tenant_id,
                model.id.in_(ids),
                model.source != SOURCE_TENANT,
            )
            .all()
        )
        for row in rows:
            if row.candidate_status == status:
                continue
            row.candidate_status = status
            pending_audit.append(dict(
                action="UPDATE", resource_type=row.resource_type,
                resource_id=getattr(row, id_col), resource_name=row.name,
            ))

    _audit_many(product, f"candidate_{status}", tenant_id, pending_audit)
    return len(pending_audit)


def discard(
    tenant_id: int,
    product: str,
    candidate_ids: Optional[Sequence[int]] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    """Delete candidate rows outright.  Returns the number removed.

    At least one of `candidate_ids`, `status` or `source` must be given — a
    bare call would otherwise wipe every candidate the tenant has, which is
    never what a caller means to ask for by omission.  Live rows are never
    touched, so this cannot remove config the tenant actually has.
    """
    if not candidate_ids and not status and not source:
        raise ValueError("discard() needs candidate_ids, status or source")

    model, id_col = _model_for(product)
    pending_audit: List[dict] = []

    with get_session() as session:
        q = session.query(model).filter(
            model.tenant_id == tenant_id,
            model.source != SOURCE_TENANT,
        )
        if candidate_ids:
            q = q.filter(model.id.in_([int(i) for i in candidate_ids]))
        if status:
            q = q.filter(model.candidate_status == status)
        if source:
            q = q.filter(model.source == source)

        for row in q.all():
            pending_audit.append(dict(
                action="DELETE", resource_type=row.resource_type,
                resource_id=getattr(row, id_col), resource_name=row.name,
            ))
            session.delete(row)

    _audit_many(product, "candidate_discard", tenant_id, pending_audit)
    return len(pending_audit)


def promote(
    tenant_id: int,
    product: str,
    promotions: Iterable[Tuple[str, str]],
) -> PromoteResult:
    """Turn pushed candidates into live rows.

    `promotions` is (synthetic_key, tenant_assigned_id) pairs, as known after a
    successful push.  Each row takes the tenant's id, reverts to
    `source='tenant'` and clears `candidate_status`.

    If a live row already holds that id — an import landed between the push and
    this call — the candidate row is deleted instead and the imported row
    stands: it came from the tenant, so it is authoritative, and keeping both
    would violate the table's unique constraint.

    `synced_at` is left NULL on a promoted row.  The push wrote the resource but
    did not read it back, so the row has never been reconciled against the
    tenant; the next import sets `synced_at` and, from then on, treats it like
    any other live row.
    """
    model, id_col = _model_for(product)
    result = PromoteResult()
    pending_audit: List[dict] = []

    with get_session() as session:
        for key, real_id in promotions or []:
            key, real_id = str(key), str(real_id)
            row = (
                session.query(model)
                .filter(
                    model.tenant_id == tenant_id,
                    getattr(model, id_col) == key,
                    model.source != SOURCE_TENANT,
                )
                .first()
            )
            if row is None:
                result.missing.append(key)
                continue

            clash = (
                session.query(model)
                .filter(
                    model.tenant_id == tenant_id,
                    model.resource_type == row.resource_type,
                    getattr(model, id_col) == real_id,
                    model.id != row.id,
                )
                .first()
            )

            audit = dict(
                resource_type=row.resource_type,
                resource_id=real_id,
                resource_name=row.name,
            )
            if clash is not None:
                session.delete(row)
                result.superseded += 1
                pending_audit.append(dict(action="DELETE", **audit))
            else:
                setattr(row, id_col, real_id)
                row.source = SOURCE_TENANT
                row.candidate_status = None
                row.is_deleted = False
                result.promoted += 1
                pending_audit.append(dict(action="UPDATE", **audit))

    _audit_many(product, "candidate_promote", tenant_id, pending_audit)
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _audit_many(
    product: str,
    operation: str,
    tenant_id: int,
    entries: List[dict],
    source: Optional[str] = None,
) -> None:
    """Write audit entries after the caller's session has closed.

    Opening a session inside an open one blocks on the SQLite write lock, so
    every mutator here collects entries and calls this at the end.
    """
    if not entries:
        return
    from services import audit_service
    audit_service.log_many([
        dict(
            product=product.upper(),
            operation=operation,
            status="SUCCESS",
            tenant_id=tenant_id,
            details={"source": source} if source else None,
            **entry,
        )
        for entry in entries
    ])
