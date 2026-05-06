"""ZIA Template service.

A template is a sanitised ZIA snapshot with tenant-specific and reference-only
resource types stripped out.  Templates are global (not tied to any single tenant)
and can be applied to any target tenant via ZIAPushService.

Usage:
    from db.database import get_session
    from services.template_service import (
        create_template_from_snapshot,
        preview_template_from_snapshot,
        list_templates,
        get_template,
        delete_template,
    )

    with get_session() as session:
        tmpl = create_template_from_snapshot(
            snapshot_id=42,
            source_tenant_id=1,
            name="Corp Baseline Q2",
            description="Quarterly policy baseline",
            session=session,
        )
    # audit events must be written after the session closes (SQLite write-lock rule)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from db.models import RestorePoint, ZIATemplate


# Resource types stripped entirely when creating a template.
TEMPLATE_STRIP_TYPES: set = {
    # Tenant-specific — encode public IPs, PSKs, or physical topology
    "location",
    "sublocation",
    "vpn_credential",
    "static_ip",
    "gre_tunnel",
    "pac_file",
    # Reference-only — imported for ID remapping; not pushable
    "location_lite",
    "location_group",
    "device_group",
    "network_app",
    "cloud_app_policy",
    "cloud_app_ssl_policy",
    # Identity — not portable across tenants
    "user",
    "group",
    "department",
    "admin_user",
    "admin_role",
    # Reference-only
    "cloud_app_instance",
    # System-defined, not pushable via API
    "network_app_group",
    # network_service is kept — rules reference services by source-tenant ID and the
    # push service needs the source entries to remap those IDs to target-tenant IDs.
    # Tenant-specific admin hierarchy / entitlement-scoped
    "tenancy_restriction_profile",
    # DLP engines: Zscaler-supplied defaults are indistinguishable from custom;
    # target tenant already has all built-in engines.
    "dlp_engine",
}

# Zscaler-managed locations that exist in every tenant and are safe to reference
# in a portable template.  Any other location name is a physical/tenant-specific
# location and causes that rule entry to be stripped.
#   LOC_DEFAULT   — Road Warrior / Client Connector users
#   Cloud Browser — CBI isolation (entitlement-gated, but the location always exists)
PORTABLE_LOCATIONS: frozenset = frozenset({"LOC_DEFAULT", "Cloud Browser"})

# Human-readable reasons for type-level strips (shown in the preview UI).
_STRIP_REASONS: Dict[str, str] = {
    "location":                 "Encodes public IP addresses and VPN credential references",
    "sublocation":              "Child of a location; IP-topology-specific",
    "vpn_credential":           "Contains FQDN + pre-shared key unique to source network",
    "static_ip":                "Public IP registered with ZIA; unique to source network",
    "gre_tunnel":               "References source public IPs; entirely topology-specific",
    "pac_file":                 "May reference internal hostnames or proxy IPs",
    "location_lite":            "Reference-only — imported for ID remapping, not pushable",
    "location_group":           "Reference-only — read-only in SDK",
    "device_group":             "Reference-only — predefined OS/platform groups",
    "network_app":              "Reference-only — system-defined, read-only",
    "cloud_app_policy":         "Reference data, not policy",
    "cloud_app_ssl_policy":     "Reference data, not policy",
    "user":                     "Identity data, not portable across tenants",
    "group":                    "Identity data, not portable across tenants",
    "department":               "Identity data, not portable across tenants",
    "admin_user":               "Admin accounts are tenant-specific",
    "admin_role":               "Admin roles are tenant-specific",
    "cloud_app_instance":       "Reference-only — tenant-specific cloud app instance IDs",
    "network_app_group":        "System-defined — not pushable via API",
    "tenancy_restriction_profile": "Tenant-specific; references tenant-specific IDs",
    "dlp_engine":               "Zscaler-supplied defaults indistinguishable from custom; target tenant already has built-in engines",
}

_ENTRY_STRIP_REASON = "Some entries stripped (tenant-specific scope, system rules, or non-portable references)"


def _has_tenant_location(rc: dict) -> bool:
    """Return True if raw_config references any non-portable (physical) location."""
    return any(
        loc.get("name") not in PORTABLE_LOCATIONS
        for loc in rc.get("locations", [])
    )


def _has_zpa_ref(rc: dict) -> bool:
    """Return True if raw_config references ZPA App Segments or segment groups."""
    return bool(
        rc.get("zpa_app_segments")
        or rc.get("zpa_application_segments")
        or rc.get("zpa_application_segment_groups")
    )


def _should_strip_entry(rtype: str, entry: dict) -> bool:
    """Return True if an individual resource entry should be excluded from the template.

    Decisions per type:

    dlp_dictionary  — keep only custom=True; BUILTIN dictionaries exist in every tenant
    url_category    — keep ALL; built-in categories needed for source→target ID remapping
    cloud_app_control_rule — strip if scoped to tenancy profiles (tenant-specific IDs)

    All rule types:
      - Strip system rules (order < 0)
      - Strip firewall_dns_rule entries named "ZPA Resolver …" (auto-managed by Zscaler)
      - Strip entries referencing non-portable locations (anything except LOC_DEFAULT / Cloud Browser)
      - Strip entries referencing ZPA App Segments or segment groups
    """
    rc = entry.get("raw_config", {})

    if rtype == "dlp_dictionary":
        return not rc.get("custom", False)

    if rtype == "url_category":
        # Keep ALL categories — built-in categories are needed in the template so
        # classify_baseline can register source→target ID remaps for rule payloads.
        # Custom categories are created in the target; built-ins are matched by name
        # and skipped (already exist), but both must be present for ID remapping.
        return False

    if rtype == "cloud_app_control_rule":
        return bool(rc.get("tenancy_profile_ids"))

    # Rule-level checks apply to all remaining types
    order = rc.get("order")
    if order is not None and order < 0:
        return True

    if rtype == "firewall_dns_rule" and "ZPA Resolver" in entry.get("name", ""):
        return True

    if _has_tenant_location(rc):
        return True

    if _has_zpa_ref(rc):
        return True

    return False


def _renumber_single_list(entries: List[dict]) -> List[dict]:
    """Sort by original order and assign sequential orders 1, 2, 3, …"""
    sorted_entries = sorted(
        entries,
        key=lambda e: (
            e.get("raw_config", {}).get("order") is None,
            e.get("raw_config", {}).get("order", 0),
        ),
    )
    result = []
    new_order = 1
    for entry in sorted_entries:
        rc = entry.get("raw_config", {})
        if "order" in rc:
            entry = {**entry, "raw_config": {**rc, "order": new_order}}
            new_order += 1
        result.append(entry)
    return result


def _renumber_orders(entries: List[dict], group_field: Optional[str] = None) -> List[dict]:
    """Renumber order fields sequentially after stripping entries to close gaps.

    For most rule types, entries share a single global ordered list.
    cloud_app_control_rule is an exception: each value of its `type` field
    (WEBMAIL, STREAMING_MEDIA, etc.) has its own independent 1-based ordered list,
    so group_field="type" must be passed for that type.

    Entries without an order field in raw_config are left unchanged.
    """
    if not entries:
        return entries
    if not any("order" in e.get("raw_config", {}) for e in entries):
        return entries

    if group_field:
        from collections import defaultdict
        groups: Dict[str, List[dict]] = defaultdict(list)
        for e in entries:
            key = e.get("raw_config", {}).get(group_field, "")
            groups[key].append(e)
        result = []
        for group_entries in groups.values():
            result.extend(_renumber_single_list(group_entries))
        return result

    return _renumber_single_list(entries)


def _strip_snapshot(
    resources: Dict[str, List[dict]],
) -> Tuple[Dict[str, List[dict]], List[str], List[str], Dict[str, int]]:
    """Separate portable from tenant-specific resources.

    Every type in TEMPLATE_STRIP_TYPES is dropped entirely.  For all other types,
    _should_strip_entry is applied to each entry individually; if all entries are
    stripped the type is treated as fully stripped.

    Returns:
        (kept_resources, stripped_type_names, included_type_names,
         stripped_entry_counts)

    stripped_entry_counts maps resource_type → number of entries stripped (only
    for types where at least one entry was kept).
    """
    kept: Dict[str, List[dict]] = {}
    stripped_types: List[str] = []
    included_types: List[str] = []
    stripped_entry_counts: Dict[str, int] = {}

    for rtype, entries in resources.items():
        if rtype in TEMPLATE_STRIP_TYPES:
            stripped_types.append(rtype)
            continue

        portable = []
        n_stripped_total = 0
        n_stripped_noisy = 0  # strips worth surfacing in the preview UI
        for e in entries:
            if not _should_strip_entry(rtype, e):
                portable.append(e)
            else:
                n_stripped_total += 1
                # order < 0 entries are Zscaler default/catch-all system rules that
                # exist in every tenant — strip silently without surfacing a warning.
                rc = e.get("raw_config", {})
                order = rc.get("order")
                if order is None or order >= 0:
                    n_stripped_noisy += 1

        if portable:
            if n_stripped_total:
                group_field = "type" if rtype == "cloud_app_control_rule" else None
                kept[rtype] = _renumber_orders(portable, group_field=group_field)
            else:
                kept[rtype] = portable
            included_types.append(rtype)
            if n_stripped_noisy:
                stripped_entry_counts[rtype] = n_stripped_noisy
        elif entries:
            # Only surface as a stripped type when at least one entry was a noisy
            # strip (user-created rule dropped for portability). Types where every
            # entry was a silent strip (order < 0 system defaults) are simply absent
            # from the template — no user-visible warning needed.
            if n_stripped_noisy:
                stripped_types.append(rtype)

    return kept, sorted(stripped_types), sorted(included_types), stripped_entry_counts


def _load_snapshot(
    snapshot_id: int,
    source_tenant_id: int,
    session: Session,
) -> RestorePoint:
    """Load and validate a ZIA RestorePoint."""
    snap = session.query(RestorePoint).filter_by(
        id=snapshot_id, tenant_id=source_tenant_id, product="ZIA"
    ).first()
    if snap is None:
        raise LookupError(f"ZIA snapshot {snapshot_id} not found for tenant {source_tenant_id}")
    return snap


def preview_template_from_snapshot(
    snapshot_id: int,
    source_tenant_id: int,
    session: Session,
) -> Dict:
    """Compute the included/stripped resource breakdown without writing to DB.

    Returns a dict suitable for the API preview response:
        {
            "included": [{"resource_type": str, "count": int}],
            "stripped": [{"resource_type": str, "count": int, "reason": str}],
            "stripped_rule_entries": [{"resource_type": str, "count": int, "reason": str}],
        }
    """
    snap = _load_snapshot(snapshot_id, source_tenant_id, session)
    resources = snap.snapshot.get("resources", {})
    kept, stripped_types, included_types, stripped_entry_counts = _strip_snapshot(resources)

    included = [
        {"resource_type": rt, "count": len(kept[rt])}
        for rt in included_types
    ]
    stripped = [
        {
            "resource_type": rt,
            "count": len(resources.get(rt, [])),
            "reason": _STRIP_REASONS.get(rt, "Tenant-specific or reference-only"),
        }
        for rt in stripped_types
    ]
    stripped_rule_entries = [
        {"resource_type": rt, "count": n, "reason": _ENTRY_STRIP_REASON}
        for rt, n in sorted(stripped_entry_counts.items())
    ]

    return {"included": included, "stripped": stripped, "stripped_rule_entries": stripped_rule_entries}


def create_template_from_snapshot(
    snapshot_id: int,
    source_tenant_id: int,
    name: str,
    description: Optional[str],
    session: Session,
) -> ZIATemplate:
    """Create a ZIATemplate from an existing ZIA RestorePoint.

    Strips tenant-specific and reference-only resource types before saving.

    Raises:
        LookupError: Snapshot not found or not a ZIA snapshot for that tenant.
        ValueError: Template name already taken (409 equivalent).
        ValueError: No portable resources remain after stripping (422 equivalent).

    The caller is responsible for writing audit events AFTER the session closes
    (SQLite write-lock rule — do not call audit_service.log() inside this block).
    """
    existing = session.query(ZIATemplate).filter_by(name=name).first()
    if existing is not None:
        raise ValueError(f"duplicate_name:A template with this name already exists")

    snap = _load_snapshot(snapshot_id, source_tenant_id, session)
    resources = snap.snapshot.get("resources", {})
    kept, stripped_types, _, _ = _strip_snapshot(resources)

    resource_count = sum(len(v) for v in kept.values())
    if resource_count == 0:
        stripped_summary = ", ".join(stripped_types) if stripped_types else "all types"
        raise ValueError(
            f"no_portable_resources:Snapshot has no portable resources after stripping "
            f"tenant-specific types ({stripped_summary})"
        )

    now = datetime.utcnow()
    tmpl = ZIATemplate(
        name=name,
        description=description,
        source_tenant_id=source_tenant_id,
        source_snapshot_id=snapshot_id,
        created_at=now,
        updated_at=now,
        resource_count=resource_count,
        stripped_types=stripped_types,
        snapshot=kept,
    )
    session.add(tmpl)
    session.flush()
    return tmpl


def list_templates(session: Session) -> List[ZIATemplate]:
    """Return all ZIATemplate rows, newest first."""
    return (
        session.query(ZIATemplate)
        .order_by(ZIATemplate.created_at.desc())
        .all()
    )


def get_template(template_id: int, session: Session) -> ZIATemplate:
    """Return a single ZIATemplate by ID.

    Raises:
        LookupError: Template not found.
    """
    tmpl = session.get(ZIATemplate, template_id)
    if tmpl is None:
        raise LookupError(f"Template {template_id} not found")
    return tmpl


def delete_template(template_id: int, session: Session) -> None:
    """Delete a ZIATemplate by ID.

    Raises:
        LookupError: Template not found.
    """
    tmpl = session.get(ZIATemplate, template_id)
    if tmpl is None:
        raise LookupError(f"Template {template_id} not found")
    session.delete(tmpl)
