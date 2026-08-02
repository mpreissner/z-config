"""Shared result types for product push services.

`ZIAPushService` predates this module and defines its own `PushRecord` keyed on
`zia_id`; `rollback_pushed()` depends on that field name, so it is deliberately
left alone.  New push services use the product-neutral records defined here.
Converging the two is a follow-up, not a rider on this change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Execution status values.  These are the strings that reach the job payload and
# the UI, so they are wire format — do not rename without updating consumers.
APPLIED = "applied"
FAILED = "failed"
MANUAL = "manual"

CREATE = "create"
UPDATE = "update"
DELETE = "delete"


@dataclass
class PushRecord:
    """Outcome of one attempted write."""

    resource_type: str
    name: str
    action: str                                  # create | update | delete
    status: str                                  # applied | failed | manual
    reason: str = ""
    resource_id: Optional[str] = None            # set on applied create/update
    warnings: List[str] = field(default_factory=list)

    @property
    def is_applied(self) -> bool:
        return self.status == APPLIED

    @property
    def is_failed(self) -> bool:
        return self.status == FAILED

    @property
    def is_manual(self) -> bool:
        return self.status == MANUAL

    @property
    def is_created(self) -> bool:
        return self.action == CREATE and self.is_applied

    @property
    def is_updated(self) -> bool:
        return self.action == UPDATE and self.is_applied

    @property
    def is_deleted(self) -> bool:
        return self.action == DELETE and self.is_applied

    def to_item(self) -> Dict[str, str]:
        """Job-payload shape consumed by the web UI."""
        return {
            "action": self.action,
            "resource_type": self.resource_type,
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class PushPlanEntry:
    """One classified write, positioned in its execution phase.

    Unsupported entries stay in the plan rather than being filtered out: the
    executor emits a `manual` record in their place, which keeps the emitted
    record order identical to a straight walk of the diff.
    """

    resource_type: str
    name: str
    action: str
    supported: bool
    target_id: Optional[str] = None      # existing resource id (update/delete)
    source_id: Optional[str] = None      # id in the input set (create; may be synthetic)
    desired_config: Dict[str, Any] = field(default_factory=dict)
    pre_config: Dict[str, Any] = field(default_factory=dict)   # pre-write state, for rollback
    skip_reason: str = ""


@dataclass
class PushPlan:
    """Classification output.  No API writes have been made."""

    mode: str                                    # restore | merge
    deletes: List[PushPlanEntry] = field(default_factory=list)
    creates: List[PushPlanEntry] = field(default_factory=list)
    updates: List[PushPlanEntry] = field(default_factory=list)
    id_remap: Dict[str, str] = field(default_factory=dict)

    @property
    def entries(self) -> List[PushPlanEntry]:
        """All entries in execution order: deletes, then creates, then updates."""
        return [*self.deletes, *self.creates, *self.updates]

    @property
    def total(self) -> int:
        return len(self.deletes) + len(self.creates) + len(self.updates)

    @property
    def delete_count(self) -> int:
        return sum(1 for e in self.deletes if e.supported)

    @property
    def create_count(self) -> int:
        return sum(1 for e in self.creates if e.supported)

    @property
    def update_count(self) -> int:
        return sum(1 for e in self.updates if e.supported)

    @property
    def skip_count(self) -> int:
        return sum(1 for e in self.entries if not e.supported)

    @property
    def skipped(self) -> List[PushPlanEntry]:
        return [e for e in self.entries if not e.supported]

    @property
    def affected_types(self) -> List[str]:
        seen = {e.resource_type for e in self.entries}
        return sorted(seen)

    def type_summary(self) -> Dict[str, Dict[str, int]]:
        """{resource_type: {create|update|delete|skip: N}}"""
        out: Dict[str, Dict[str, int]] = {}
        for action, entries in ((DELETE, self.deletes), (CREATE, self.creates), (UPDATE, self.updates)):
            for e in entries:
                bucket = out.setdefault(e.resource_type, {"create": 0, "update": 0, "delete": 0, "skip": 0})
                bucket[action if e.supported else "skip"] += 1
        return out

    def changes_by_action(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str]]]:
        """(creates, updates, deletes) as (resource_type, name) pairs."""
        def pairs(entries: List[PushPlanEntry]) -> List[Tuple[str, str]]:
            return [(e.resource_type, e.name) for e in entries if e.supported]
        return pairs(self.creates), pairs(self.updates), pairs(self.deletes)
