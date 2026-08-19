"""ZIA Template service.

A template is a sanitised ZIA snapshot with tenant-specific and reference-only
resource types stripped out.  Templates are global (not tied to any single tenant)
and can be applied to any target tenant via ZIAPushService.

A template is owned by whoever created it and holds either everything portable in
the source snapshot (scope='full') or only the entries its author picked, closed
over their references (scope='scoped').  Who may see it is decided in
template_share_service, not here — this module only takes the resulting set of
visible IDs.

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
from typing import Dict, Iterator, List, Optional, Set, Tuple

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
    # Identity — not portable across tenants
    "user",
    "group",
    "department",
    "admin_user",
    "admin_role",
    # network_service is kept — rules reference services by source-tenant ID and the
    # push service needs the source entries to remap those IDs to target-tenant IDs.
    # Tenant-specific admin hierarchy / entitlement-scoped
    "tenancy_restriction_profile",
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
    "user":                     "Identity data, not portable across tenants",
    "group":                    "Identity data, not portable across tenants",
    "department":               "Identity data, not portable across tenants",
    "admin_user":               "Admin accounts are tenant-specific",
    "admin_role":               "Admin roles are tenant-specific",
    "tenancy_restriction_profile": "Tenant-specific; references tenant-specific IDs",
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

    dlp_dictionary / dlp_engine / network_app / network_app_group /
    cloud_app_policy / cloud_app_ssl_policy / cloud_app_instance / url_category
                    — keep ALL; system/reference entries needed for source→target ID
                      remapping; push service skips creating read-only entries
    cloud_app_control_rule — strip if scoped to tenancy profiles (tenant-specific IDs)

    All rule types:
      - Strip system rules (order < 0)
      - Strip firewall_dns_rule entries named "ZPA Resolver …" (auto-managed by Zscaler)
      - Strip entries referencing non-portable locations (anything except LOC_DEFAULT / Cloud Browser)
      - Strip entries referencing ZPA App Segments or segment groups
    """
    rc = entry.get("raw_config", {})

    if rtype in (
        "dlp_dictionary", "dlp_engine",
        "network_app", "network_app_group",
        "cloud_app_policy", "cloud_app_ssl_policy", "cloud_app_instance",
        "url_category",
    ):
        # Keep ALL entries — built-ins are needed so classify_baseline can register
        # source→target ID remaps. The push service skips creating entries that already
        # exist in the target; custom entries are created there. Both must be present in
        # the template so the smart wipe preserves them instead of deleting them.
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


# ---------------------------------------------------------------------------
# Reference resolution (scoped templates)
# ---------------------------------------------------------------------------

# raw_config field name → the snapshot resource type it points at.
#
# This is deliberately a *separate* table from the _norm_* handlers in
# zia_push_service: those decide payload shape, this decides template contents.
# Merging them would let a payload fix silently change which resources a scoped
# template pulls in.  Both snake_case and camelCase spellings appear in
# raw_config depending on which SDK path produced the entry, so both are listed.
#
# Fields NOT listed here are references that need no closure: app_service_groups
# and nw_applications name predefined ZIA objects whose IDs are identical in
# every tenant, and the identity/location/ZPA fields belong to types a template
# never carries at all (an entry referencing one is stripped outright).
_REF_FIELDS: Dict[str, str] = {
    "labels":                 "rule_label",
    "nw_services":            "network_service",
    "nwServices":             "network_service",
    "nw_service_groups":      "network_svc_group",
    "nwServiceGroups":        "network_svc_group",
    "nw_application_groups":  "network_app_group",
    "nwApplicationGroups":    "network_app_group",
    "src_ip_groups":          "ip_source_group",
    "srcIpGroups":            "ip_source_group",
    "source_ip_groups":       "ip_source_group",
    "sourceIpGroups":         "ip_source_group",
    "dest_ip_groups":         "ip_destination_group",
    "destIpGroups":           "ip_destination_group",
    "dlp_engines":            "dlp_engine",
    "dlpEngines":             "dlp_engine",
    "dlp_dictionaries":       "dlp_dictionary",
    "sub_dictionaries":       "dlp_dictionary",
    "subDictionaries":        "dlp_dictionary",
    "time_windows":           "time_interval",
    "timeWindows":            "time_interval",
    "workload_groups":        "workload_group",
    "workloadGroups":         "workload_group",
    "bandwidth_classes":      "bandwidth_class",
    "bandwidthClasses":       "bandwidth_class",
    "proxy_gateways":         "proxy_gateway",
    "proxyGateways":          "proxy_gateway",
    "proxy_gateway":          "proxy_gateway",
    "proxyGateway":           "proxy_gateway",
    "primary_proxy":          "proxy",
    "primaryProxy":           "proxy",
    "secondary_proxy":        "proxy",
    "secondaryProxy":         "proxy",
    "cert":                   "root_certificate",
    "url_categories":         "url_category",
    "urlCategories":          "url_category",
    "tenancy_profile_ids":    "tenancy_restriction_profile",
}

#: Types whose entries are identified by a string rather than a numeric ID.
#: url_category is the only one: predefined categories key on their constant
#: ("ADULT_THEMES") and custom ones on "CUSTOM_nn", and the same field carries
#: bare strings on some rule types and {id, ...} objects on others.
_STR_ID_TYPES: frozenset = frozenset({"url_category"})


def _iter_refs(raw_config: dict) -> Iterator[Tuple[str, str]]:
    """Yield (resource_type, referenced_id) for every reference in one entry.

    Walks nested structures, because a few references live below the top level
    (an SSL rule's certificate hangs off `action`).  Only field names in
    _REF_FIELDS are followed, so an unknown embedded object is ignored rather
    than guessed at.
    """
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                rtype = _REF_FIELDS.get(key)
                if rtype is not None:
                    items = value if isinstance(value, list) else [value]
                    for item in items:
                        ref_id = None
                        if isinstance(item, dict):
                            if item.get("id") is not None:
                                ref_id = str(item["id"])
                        elif isinstance(item, (str, int)) and item != "":
                            ref_id = str(item)
                        if ref_id is None:
                            continue
                        # url_category entries key on their constant ("ADULT_THEMES",
                        # "CUSTOM_03"), but a DLP web rule reports the same field as
                        # [{"id": 130}] — an internal ordinal with no entry to match.
                        # Those are unresolvable by construction, so they are not
                        # references to chase and not warnings to raise.
                        if rtype in _STR_ID_TYPES and ref_id.isdigit():
                            continue
                        yield rtype, ref_id
                yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    yield from walk(raw_config)


def _index(resources: Dict[str, List[dict]]) -> Dict[str, Dict[str, dict]]:
    """resource_type → {entry id (as str) → entry}."""
    return {
        rtype: {str(e.get("id")): e for e in entries}
        for rtype, entries in resources.items()
    }


def resolve_dependencies(
    selection: Dict[str, List[str]],
    available: Dict[str, List[dict]],
) -> Tuple[Dict[str, List[str]], List[dict], List[str]]:
    """Close a user's selection over the references its entries make.

    A rule the user ticked is useless in the target tenant without the objects it
    names, so those objects are pulled in behind it — transitively, since a
    service group names services and a proxy names a certificate.

    Three outcomes per reference:
      * the target is in `available`      → add it, and follow its own references
      * the target's type isn't portable  → warn; the reference travels unresolved
      * the target is missing from the snapshot → warn; same

    In the last two cases nothing is dropped from the selected entry itself: the
    push service already tolerates an unmapped reference, and silently editing a
    user's rule would be worse than telling them about it.

    Returns (closed_selection, additions, warnings).  `additions` describes what
    the closure pulled in — each entry carries `predefined`, so the UI can show a
    referenced built-in without implying the push will create it.
    """
    index = _index(available)
    closed: Dict[str, Set[str]] = {
        rtype: {str(i) for i in ids} for rtype, ids in selection.items() if ids
    }
    chosen: Set[Tuple[str, str]] = {
        (rtype, eid) for rtype, ids in closed.items() for eid in ids
    }

    additions: List[dict] = []
    warnings: List[str] = []
    warned: Set[Tuple[str, str]] = set()

    # Worklist over (type, id) pairs; `seen` bounds it, so a reference cycle
    # (a rule label on a rule that labels it back) terminates instead of looping.
    worklist: List[Tuple[str, str]] = sorted(chosen)
    seen: Set[Tuple[str, str]] = set(worklist)

    while worklist:
        rtype, eid = worklist.pop()
        entry = index.get(rtype, {}).get(eid)
        if entry is None:
            continue
        for ref_type, ref_id in _iter_refs(entry.get("raw_config") or {}):
            key = (ref_type, ref_id)
            if key in seen:
                continue
            target = index.get(ref_type, {}).get(ref_id)
            if target is None:
                if key not in warned:
                    warned.add(key)
                    why = ("is not portable and was stripped from the template"
                           if ref_type in TEMPLATE_STRIP_TYPES
                           else "is not present in the snapshot")
                    warnings.append(
                        f'"{entry.get("name") or eid}" references {ref_type} '
                        f"{ref_id}, which {why}. The reference will not resolve "
                        f"in the target tenant."
                    )
                continue
            seen.add(key)
            worklist.append(key)
            closed.setdefault(ref_type, set()).add(ref_id)
            rc = target.get("raw_config") or {}
            additions.append({
                "resource_type": ref_type,
                "id": ref_id,
                "name": _entry_name(ref_type, target),
                "predefined": _is_predefined(ref_type, rc),
                "required_by": entry.get("name") or eid,
            })

    return {rtype: sorted(ids) for rtype, ids in closed.items()}, additions, warnings


# ---------------------------------------------------------------------------
# Per-entry preview
# ---------------------------------------------------------------------------

def _is_predefined(rtype: str, rc: dict) -> bool:
    """Whether an entry already exists in every tenant and is matched, not created."""
    if rc.get("predefined") is True:
        return True
    if rtype == "url_category":
        return rc.get("custom_category") is not True
    if rtype == "network_service":
        return rc.get("type") in ("PREDEFINED", "STANDARD")
    if rtype == "dlp_engine":
        return rc.get("custom_dlp_engine") is False
    for flag in ("is_name_l10n_tag", "isNameL10nTag", "name_l10n_tag",
                 "default_rule", "defaultRule"):
        if rc.get(flag) is True:
            return True
    return False


def _entry_name(rtype: str, entry: dict) -> str:
    """A display name for one entry.

    Predefined URL categories carry an empty `name` and put the useful string in
    the ID ("ADULT_THEMES"); custom ones put it in `configured_name` and get an
    opaque "CUSTOM_03" ID; DLP engines use `predefined_engine_name`.  Everything
    else has a real name.
    """
    name = (entry.get("name") or "").strip()
    if name:
        return name
    rc = entry.get("raw_config") or {}
    for field in ("configured_name", "configuredName", "predefined_engine_name",
                  "predefinedEngineName", "display_name", "displayName"):
        candidate = (rc.get(field) or "").strip()
        if candidate:
            return candidate
    return str(entry.get("id"))


def _summarize(rtype: str, rc: dict) -> str:
    """One line of context for a picker row — enough to tell two rules apart.

    Never includes raw_config itself: the picker is shown to anyone who can
    create a template, and a rule's full config can name internal hosts.
    """
    bits: List[str] = []
    action = rc.get("action")
    if isinstance(action, dict):
        action = action.get("type")
    if isinstance(action, str) and action:
        bits.append(action.replace("_", " ").title())
    forward = rc.get("forward_method") or rc.get("forwardMethod")
    if forward:
        bits.append(str(forward))
    state = rc.get("state")
    if state:
        bits.append("Enabled" if state == "ENABLED" else "Disabled")

    if rtype in ("ip_destination_group", "ip_source_group"):
        n = len(rc.get("addresses") or rc.get("ip_addresses") or [])
        if n:
            bits.append(f"{n} address{'es' if n != 1 else ''}")
        if rc.get("type"):
            bits.append(str(rc["type"]))
    elif rtype == "url_category":
        n = len(rc.get("urls") or [])
        if n:
            bits.append(f"{n} URL{'s' if n != 1 else ''}")
    elif rtype == "network_svc_group":
        n = len(rc.get("services") or [])
        if n:
            bits.append(f"{n} service{'s' if n != 1 else ''}")
    elif rtype == "root_certificate":
        bits.extend(str(t) for t in (rc.get("cert_types") or rc.get("certTypes") or []))

    if not bits:
        desc = (rc.get("description") or "").strip()
        if desc:
            return desc[:120]
    return " · ".join(bits)


def preview_template_detail(
    snapshot_id: int,
    source_tenant_id: int,
    session: Session,
) -> Dict:
    """Every selectable entry in a snapshot, grouped by type, for the picker.

    Returns the same included/stripped breakdown as preview_template_from_snapshot
    plus an `entries` map:

        {"firewall_rule": [{"id", "name", "predefined", "summary", "order"}, …]}

    raw_config is deliberately absent — see _summarize.
    """
    base = preview_template_from_snapshot(snapshot_id, source_tenant_id, session)
    snap = _load_snapshot(snapshot_id, source_tenant_id, session)
    kept, _, included_types, _ = _strip_snapshot(snap.snapshot.get("resources", {}))

    entries: Dict[str, List[dict]] = {}
    for rtype in included_types:
        rows = []
        for e in kept[rtype]:
            rc = e.get("raw_config") or {}
            rows.append({
                "id": str(e.get("id")),
                "name": _entry_name(rtype, e),
                "predefined": _is_predefined(rtype, rc),
                "summary": _summarize(rtype, rc),
                "order": rc.get("order"),
            })
        rows.sort(key=lambda r: (r["order"] is None, r["order"] or 0, r["name"].lower()))
        entries[rtype] = rows

    base["entries"] = entries
    return base


def _apply_selection(
    kept: Dict[str, List[dict]],
    selection: Dict[str, List[str]],
) -> Dict[str, List[dict]]:
    """Reduce the stripped snapshot to the closed selection, renumbering rules.

    Rule order is per-tenant and 1-based with no gaps, so dropping rule 2 of 5
    means the survivors have to be renumbered — the same renumbering a type-level
    strip already does.

    Raises ValueError if the selection names something that isn't there: a
    stale picker is better rejected than quietly honored in part.
    """
    result: Dict[str, List[dict]] = {}
    for rtype, ids in selection.items():
        if not ids:
            continue
        available = kept.get(rtype)
        if available is None:
            raise ValueError(
                f"invalid_selection:Resource type '{rtype}' is not portable and "
                f"cannot be included in a template"
            )
        wanted = {str(i) for i in ids}
        picked = [e for e in available if str(e.get("id")) in wanted]
        missing = wanted - {str(e.get("id")) for e in picked}
        if missing:
            raise ValueError(
                f"invalid_selection:{rtype} entr{'y' if len(missing) == 1 else 'ies'} "
                f"{', '.join(sorted(missing))} cannot be included — stripped as "
                f"tenant-specific, or no longer in the snapshot"
            )
        group_field = "type" if rtype == "cloud_app_control_rule" else None
        result[rtype] = _renumber_orders(picked, group_field=group_field)
    return result


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
    selection: Optional[Dict[str, List[str]]] = None,
    owner_user_id: Optional[int] = None,
    owner_username: Optional[str] = None,
    visibility: str = "private",
) -> ZIATemplate:
    """Create a ZIATemplate from an existing ZIA RestorePoint.

    Strips tenant-specific and reference-only resource types before saving.  With
    `selection` given, the result is narrowed further to the entries the author
    picked plus everything those entries reference (see resolve_dependencies);
    the template is marked scope='scoped' and records what was picked, what the
    closure added, and which references could not be resolved.

    selection=None keeps the historical behavior byte for byte: a full template
    over everything portable in the snapshot.

    Raises:
        LookupError: Snapshot not found or not a ZIA snapshot for that tenant.
        ValueError: Template name already taken (409 equivalent).
        ValueError: Selection names an entry that isn't portable (422 equivalent).
        ValueError: No portable resources remain after stripping (422 equivalent).

    The caller is responsible for writing audit events AFTER the session closes
    (SQLite write-lock rule — do not call audit_service.log() inside this block).
    """
    existing = session.query(ZIATemplate).filter_by(name=name).first()
    if existing is not None:
        owner = existing.owner_username
        suffix = f" (owned by {owner})" if owner else ""
        raise ValueError(
            f'duplicate_name:A template named "{name}" already exists{suffix}'
        )

    snap = _load_snapshot(snapshot_id, source_tenant_id, session)
    resources = snap.snapshot.get("resources", {})
    kept, stripped_types, _, _ = _strip_snapshot(resources)

    scope = "full"
    selection_meta: Optional[Dict] = None
    if selection:
        closed, additions, warnings = resolve_dependencies(selection, kept)
        kept = _apply_selection(kept, closed)
        scope = "scoped"
        selection_meta = {
            "selected": {k: sorted(str(i) for i in v) for k, v in selection.items() if v},
            "auto_included": additions,
            "warnings": warnings,
        }

    resource_count = sum(len(v) for v in kept.values())
    if resource_count == 0:
        if selection:
            raise ValueError(
                "invalid_selection:No resources were selected"
            )
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
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        visibility=visibility,
        scope=scope,
        selection_meta=selection_meta,
    )
    session.add(tmpl)
    session.flush()
    return tmpl


def list_templates(
    session: Session,
    visible_ids: Optional[Set[int]] = None,
) -> List[ZIATemplate]:
    """Return ZIATemplate rows, newest first.

    `visible_ids` is the set from template_share_service.visible_template_ids;
    None means no restriction (an admin), which is why it is not defaulted to an
    empty set — those two cases are opposites.
    """
    query = session.query(ZIATemplate)
    if visible_ids is not None:
        if not visible_ids:
            return []
        query = query.filter(ZIATemplate.id.in_(visible_ids))
    return query.order_by(ZIATemplate.created_at.desc()).all()


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
