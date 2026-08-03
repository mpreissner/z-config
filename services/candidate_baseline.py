"""Adapter between staged candidates and the product push engines.

`candidate_service` owns the lifecycle; this module owns the handoff to a push.
It sits between them so `candidate_service` stays free of any dependency on the
push services, and so the two questions a push needs answered up front —
*which candidates can this engine actually write?* and *does any of them
reference a candidate that is not coming along?* — are answered before a single
API call is made.

Outbound, `build_baseline()` turns accepted candidates into the snapshot wire
shape that `ZPAPushService.classify_merge()` and
`ZIAPushService.classify_baseline()` consume.  Inbound, `promote_after_push()`
maps the records those engines return back onto candidate rows, so a resource
the tenant accepted stops being a candidate and becomes live config.

Candidates reference each other by synthetic id (`palo:SG-Finance`).  The push
engines resolve those as they go: creating a segment group registers its
tenant-assigned id, and a later application referencing the synthetic id gets it
rewritten.  That only works if the referenced candidate is in the same baseline,
which is why unresolved references are reported rather than discovered at push
time as an API rejection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from services import candidate_service as cs

# ---------------------------------------------------------------------------
# Exclusion reasons — wire strings, surfaced in the UI
# ---------------------------------------------------------------------------

REASON_UNKNOWN_TYPE = "resource type is not one the push engine handles"
REASON_NO_CREATE = "push engine cannot create this resource type"


def _engine_types(product: str) -> Tuple[List[str], Optional[Set[str]]]:
    """(dependency-ordered types, creatable types or None if unconstrained).

    ZPA publishes explicit capability sets; ZIA's push order is itself the list
    of what it can write, so there is nothing further to constrain.
    """
    product = (product or "").upper()
    if product == "ZPA":
        from services.zpa_push_service import CAN_CREATE, RTYPE_ORDER
        return list(RTYPE_ORDER), set(CAN_CREATE)
    if product == "ZIA":
        from services.zia_push_service import PUSH_ORDER
        return list(PUSH_ORDER), None
    raise ValueError(f"Unsupported product for candidate push: {product!r}")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BaselineResult:
    """A push-ready baseline plus everything the caller should show first."""

    product: str
    resources: Dict[str, List[dict]] = field(default_factory=dict)
    included: List[cs.Candidate] = field(default_factory=list)
    excluded: List[dict] = field(default_factory=list)     # {resource_type, name, reason}
    unresolved: List[dict] = field(default_factory=list)   # {resource_type, name, references}
    key_index: Dict[Tuple[str, str], str] = field(default_factory=dict)

    def as_baseline(self) -> Dict[str, Any]:
        """The dict the push classifiers take."""
        return {"resources": self.resources}

    @property
    def is_empty(self) -> bool:
        return not self.resources

    @property
    def include_count(self) -> int:
        return len(self.included)

    def type_summary(self) -> Dict[str, int]:
        return {rtype: len(items) for rtype, items in self.resources.items()}

    def summary(self) -> Dict[str, Any]:
        """Job-payload shape for the preview UI."""
        return {
            "product": self.product,
            "included": self.include_count,
            "excluded": len(self.excluded),
            "unresolved": len(self.unresolved),
            "by_type": self.type_summary(),
            "excluded_items": self.excluded,
            "unresolved_items": self.unresolved,
        }


# ---------------------------------------------------------------------------
# Outbound: candidates -> baseline
# ---------------------------------------------------------------------------

def build_baseline(
    tenant_id: int,
    product: str,
    resource_type: Optional[str] = None,
    source: Optional[str] = None,
    candidate_ids: Optional[Sequence[int]] = None,
) -> BaselineResult:
    """Assemble the accepted candidates into a baseline the push engine can take.

    Only accepted candidates are considered — pending and rejected ones are not
    a decision the user has made yet, or one they have made against.

    Candidates of a type the engine does not handle, or cannot create, are moved
    to `excluded` rather than dropped: a caller that silently pushes fewer
    resources than the user accepted is worse than one that says which and why.

    `candidate_ids` narrows to a specific selection, for pushing part of an
    accepted set.  Note that narrowing is exactly how a reference goes
    unresolved, so check `unresolved` before pushing a subset.
    """
    order, creatable = _engine_types(product)
    rank = {rtype: i for i, rtype in enumerate(order)}

    accepted = cs.list_candidates(
        tenant_id, product, status=cs.STATUS_ACCEPTED,
        resource_type=resource_type, source=source,
    )
    if candidate_ids is not None:
        wanted = {int(i) for i in candidate_ids}
        accepted = [c for c in accepted if c.id in wanted]

    result = BaselineResult(product=(product or "").upper())

    for cand in accepted:
        if cand.resource_type not in rank:
            result.excluded.append({
                "resource_type": cand.resource_type,
                "name": cand.name,
                "reason": REASON_UNKNOWN_TYPE,
            })
            continue
        if creatable is not None and cand.resource_type not in creatable:
            result.excluded.append({
                "resource_type": cand.resource_type,
                "name": cand.name,
                "reason": REASON_NO_CREATE,
            })
            continue
        result.included.append(cand)
        result.key_index[(cand.resource_type, cand.name)] = cand.key

    # Emit in dependency order.  Both classifiers order types themselves, but a
    # baseline that already reads in push order is what a human reviewing the
    # preview expects to see.
    for cand in sorted(result.included, key=lambda c: (rank[c.resource_type], c.name)):
        result.resources.setdefault(cand.resource_type, []).append(cand.to_item())

    result.unresolved = _unresolved_references(tenant_id, product, result)
    return result


def _unresolved_references(
    tenant_id: int,
    product: str,
    result: BaselineResult,
) -> List[dict]:
    """Find included candidates pointing at candidates that are not coming along.

    References are matched against the tenant's full set of candidate keys
    rather than guessed from the `<source>:<name>` shape, so a live resource
    whose id happens to contain a colon is never mistaken for one.
    """
    all_keys = {
        c.key
        for c in cs.list_candidates(tenant_id, product)
    }
    if not all_keys:
        return []

    present = set(result.key_index.values())
    dangling = all_keys - present
    if not dangling:
        return []

    out: List[dict] = []
    for cand in result.included:
        hits = sorted(_referenced_keys(cand.raw_config, dangling))
        if hits:
            out.append({
                "resource_type": cand.resource_type,
                "name": cand.name,
                "references": hits,
            })
    return out


def _referenced_keys(obj: Any, keys: Set[str]) -> Set[str]:
    """Every member of `keys` appearing as a string anywhere in `obj`."""
    found: Set[str] = set()
    if isinstance(obj, str):
        if obj in keys:
            found.add(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            found |= _referenced_keys(value, keys)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            found |= _referenced_keys(value, keys)
    return found


# ---------------------------------------------------------------------------
# Inbound: push records -> promotions
# ---------------------------------------------------------------------------

def _record_outcome(record: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(resource_type, name, tenant_id) for a written record, else (…, None).

    The two push services predate any shared record type: ZPA's carries
    `action`/`status`/`resource_id`, ZIA's a single `status` string and
    `zia_id`.  Reading both here keeps that difference out of the callers.
    """
    rtype = getattr(record, "resource_type", None)
    name = getattr(record, "name", None)

    if hasattr(record, "zia_id"):                       # ZIA
        status = getattr(record, "status", "")
        written = status in ("created", "updated")
        return rtype, name, (str(record.zia_id) if written and record.zia_id else None)

    if getattr(record, "is_applied", False) and getattr(record, "action", "") in ("create", "update"):
        rid = getattr(record, "resource_id", None)      # ZPA
        return rtype, name, (str(rid) if rid else None)

    return rtype, name, None


def promotions_from(result: BaselineResult, records: Iterable[Any]) -> List[Tuple[str, str]]:
    """(candidate key, tenant-assigned id) pairs for every record that landed.

    Records are matched back to candidates by (resource_type, name), which is
    what the push engines carry through — the plan entry's name comes straight
    from the baseline item.  Records for anything not in this baseline, and
    records that failed or were skipped, produce no promotion.
    """
    out: List[Tuple[str, str]] = []
    for record in records or []:
        rtype, name, real_id = _record_outcome(record)
        if not real_id:
            continue
        key = result.key_index.get((rtype, name))
        if key and key != real_id:
            out.append((key, real_id))
    return out


def promote_after_push(
    tenant_id: int,
    product: str,
    result: BaselineResult,
    records: Iterable[Any],
) -> cs.PromoteResult:
    """Turn the candidates this push wrote into live rows.

    Candidates whose write failed stay accepted, so a retry pushes exactly the
    ones still outstanding.
    """
    return cs.promote(tenant_id, product, promotions_from(result, records))
