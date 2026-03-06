"""ZIA Firewall Rule sync service.

Business logic for exporting and syncing cloud firewall rules from/to CSV.
No CLI concerns — returns plain data structures.

CSV columns:
    id                  ZIA rule ID — blank for new rules, filled on export
    name                (required) Rule name
    order               Desired rule order (1-based); row sequence drives reorder
    action              (required) ALLOW, BLOCK_DROP, BLOCK_RESET, BLOCK_ICMP, EVAL_SEC_POLICY
    state               ENABLED or DISABLED (default ENABLED)
    description         Free text
    src_ips             Semicolon-separated source IP/CIDR literals
    src_ip_groups       Semicolon-separated IP source group names (resolved from DB)
    dest_addresses      Semicolon-separated destination IP/CIDR literals
    dest_ip_groups      Semicolon-separated IP destination group names (resolved from DB)
    nw_services         Semicolon-separated network service names (resolved from DB)
    nw_service_groups   Semicolon-separated network service group names (resolved from DB)
    locations           Semicolon-separated location names (resolved from DB)
    enable_full_logging true or false
"""

import csv
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from db.database import get_session
from db.models import ZIAResource
from services import audit_service


# ---------------------------------------------------------------------------
# CSV schema
# ---------------------------------------------------------------------------

CSV_FIELDNAMES = [
    "id", "name", "order", "action", "state", "description",
    "src_ips", "src_ip_groups", "dest_addresses", "dest_ip_groups",
    "nw_services", "nw_service_groups", "locations", "enable_full_logging",
]

TEMPLATE_ROWS = [
    {
        "id": "",
        "name": "Allow-Corp-DNS",
        "order": "1",
        "action": "ALLOW",
        "state": "ENABLED",
        "description": "Allow corporate DNS traffic",
        "src_ips": "",
        "src_ip_groups": "Corporate Subnets",
        "dest_addresses": "8.8.8.8;8.8.4.4",
        "dest_ip_groups": "",
        "nw_services": "DNS",
        "nw_service_groups": "",
        "locations": "HQ;Branch-London",
        "enable_full_logging": "false",
    },
    {
        "id": "",
        "name": "Block-Unknown",
        "order": "2",
        "action": "BLOCK_DROP",
        "state": "ENABLED",
        "description": "Block all unmatched traffic",
        "src_ips": "",
        "src_ip_groups": "",
        "dest_addresses": "",
        "dest_ip_groups": "",
        "nw_services": "",
        "nw_service_groups": "",
        "locations": "",
        "enable_full_logging": "true",
    },
]

_REQUIRED = {"name", "action"}
_VALID_ACTIONS = {
    "ALLOW", "BLOCK_DROP", "BLOCK_RESET", "BLOCK_ICMP", "EVAL_SEC_POLICY",
}
_VALID_STATES = {"ENABLED", "DISABLED"}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SyncClassification:
    """Output of classify_sync() — what would happen on apply."""
    csv_rows: List[Dict] = field(default_factory=list)  # action: UPDATE|CREATE|SKIP
    to_delete: List[Dict] = field(default_factory=list)
    reorder_needed: bool = False

    @property
    def to_update(self) -> List[Dict]:
        return [e for e in self.csv_rows if e["action"] == "UPDATE"]

    @property
    def to_create(self) -> List[Dict]:
        return [e for e in self.csv_rows if e["action"] == "CREATE"]

    @property
    def unchanged(self) -> List[Dict]:
        return [e for e in self.csv_rows if e["action"] == "SKIP"]

    @property
    def missing_dep(self) -> List[Dict]:
        return [e for e in self.csv_rows if e["action"] == "MISSING_DEP"]


@dataclass
class SyncResult:
    updated: int = 0
    created: int = 0
    deleted: int = 0
    skipped: int = 0
    reordered: bool = False
    rows_detail: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_csv(path: str) -> List[Dict]:
    """Read and validate a firewall rule CSV. Raises ValueError on failure."""
    errors: List[str] = []
    rows: List[Dict] = []

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):
            row_errors = []

            for col in _REQUIRED:
                if not row.get(col, "").strip():
                    row_errors.append(f"'{col}' is required")

            action = row.get("action", "").strip().upper()
            if action and action not in _VALID_ACTIONS:
                row_errors.append(
                    f"'action' must be one of {sorted(_VALID_ACTIONS)}, got '{action}'"
                )

            state = row.get("state", "").strip().upper()
            if state and state not in _VALID_STATES:
                row_errors.append(f"'state' must be ENABLED or DISABLED, got '{state}'")

            if row_errors:
                name = row.get("name", f"row {i}")
                errors.append(f"Row {i} ({name!r}): {'; '.join(row_errors)}")
            else:
                rows.append(dict(row))

    if errors:
        raise ValueError("CSV validation failed:\n" + "\n".join(errors))

    return rows


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def export_rules_to_csv(tenant_id: int) -> List[Dict]:
    """Read firewall rules from DB and return list of CSV-ready dicts."""
    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type="firewall_rule", is_deleted=False)
            .all()
        )
        records = [
            {"zia_id": r.zia_id, "name": r.name, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not records:
        return []

    records.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    # Build name lookup for ZIA group resources
    with get_session() as session:
        group_records = (
            session.query(ZIAResource)
            .filter(
                ZIAResource.tenant_id == tenant_id,
                ZIAResource.resource_type.in_([
                    "ip_source_group", "ip_destination_group",
                    "network_service", "network_svc_group", "location",
                ]),
                ZIAResource.is_deleted.is_(False),
            )
            .all()
        )
        # Map: (resource_type, zia_id) → name
        id_to_name: Dict[Tuple[str, str], str] = {}
        for rec in group_records:
            if rec.zia_id and rec.name:
                id_to_name[(rec.resource_type, str(rec.zia_id))] = rec.name

    def _resolve_names(obj_list: list, rtype: str) -> str:
        names = []
        for obj in obj_list or []:
            obj_id = str(obj.get("id", "")) if isinstance(obj, dict) else str(obj)
            name = id_to_name.get((rtype, obj_id)) or obj_id
            if name:
                names.append(name)
        return ";".join(names)

    csv_rows = []
    for r in records:
        cfg = r["raw_config"]
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or ""

        order = cfg.get("order") or cfg.get("rank") or ""
        logging_val = cfg.get("enable_full_logging")
        if logging_val is None:
            logging_str = ""
        else:
            logging_str = "true" if logging_val else "false"

        src_ips_raw = cfg.get("src_ips") or []
        dest_addrs_raw = cfg.get("dest_addresses") or []

        csv_rows.append({
            "id":                 r["zia_id"] or cfg.get("id") or "",
            "name":               r["name"] or "",
            "order":              str(order),
            "action":             action,
            "state":              cfg.get("state") or "ENABLED",
            "description":        cfg.get("description") or "",
            "src_ips":            ";".join(str(ip) for ip in src_ips_raw),
            "src_ip_groups":      _resolve_names(cfg.get("src_ip_groups"), "ip_source_group"),
            "dest_addresses":     ";".join(str(ip) for ip in dest_addrs_raw),
            "dest_ip_groups":     _resolve_names(cfg.get("dest_ip_groups"), "ip_destination_group"),
            "nw_services":        _resolve_names(cfg.get("nw_services"), "network_service"),
            "nw_service_groups":  _resolve_names(cfg.get("nw_service_groups"), "network_svc_group"),
            "locations":          _resolve_names(cfg.get("locations"), "location"),
            "enable_full_logging": logging_str,
        })

    return csv_rows


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------

def resolve_dependencies(
    tenant_id: int,
    rows: List[Dict],
) -> Tuple[List[Dict], Dict[str, List[str]]]:
    """Look up group IDs for named conditions from ZIA DB cache.

    Returns (enriched_rows, missing).
    """
    missing: Dict[str, List[str]] = {
        "src_ip_group": [],
        "dest_ip_group": [],
        "nw_service": [],
        "nw_service_group": [],
        "location": [],
    }

    # Collect unique names
    src_group_names: set = set()
    dest_group_names: set = set()
    nw_service_names: set = set()
    nw_svc_group_names: set = set()
    location_names: set = set()

    for row in rows:
        for n in _split(row.get("src_ip_groups", "")):
            src_group_names.add(n)
        for n in _split(row.get("dest_ip_groups", "")):
            dest_group_names.add(n)
        for n in _split(row.get("nw_services", "")):
            nw_service_names.add(n)
        for n in _split(row.get("nw_service_groups", "")):
            nw_svc_group_names.add(n)
        for n in _split(row.get("locations", "")):
            location_names.add(n)

    src_group_map: Dict[str, str] = {}
    dest_group_map: Dict[str, str] = {}
    nw_service_map: Dict[str, str] = {}
    nw_svc_group_map: Dict[str, str] = {}
    location_map: Dict[str, str] = {}

    def _lookup(session, resource_type: str, names: set, result_map: dict, missing_key: str):
        for name in names:
            rec = (
                session.query(ZIAResource)
                .filter_by(tenant_id=tenant_id, resource_type=resource_type,
                            name=name, is_deleted=False)
                .first()
            )
            if rec:
                result_map[name] = str(rec.zia_id)
            elif name not in missing[missing_key]:
                missing[missing_key].append(name)

    with get_session() as session:
        _lookup(session, "ip_source_group",      src_group_names,    src_group_map,    "src_ip_group")
        _lookup(session, "ip_destination_group", dest_group_names,   dest_group_map,   "dest_ip_group")
        _lookup(session, "network_service",      nw_service_names,   nw_service_map,   "nw_service")
        _lookup(session, "network_svc_group",    nw_svc_group_names, nw_svc_group_map, "nw_service_group")
        _lookup(session, "location",             location_names,     location_map,     "location")

    enriched: List[Dict] = []
    for row in rows:
        r = dict(row)
        r["_src_ip_group_ids"]  = [src_group_map[n]    for n in _split(row.get("src_ip_groups", ""))   if n in src_group_map]
        r["_dest_ip_group_ids"] = [dest_group_map[n]   for n in _split(row.get("dest_ip_groups", ""))  if n in dest_group_map]
        r["_nw_service_ids"]    = [nw_service_map[n]   for n in _split(row.get("nw_services", ""))     if n in nw_service_map]
        r["_nw_svc_group_ids"]  = [nw_svc_group_map[n] for n in _split(row.get("nw_service_groups", "")) if n in nw_svc_group_map]
        r["_location_ids"]      = [location_map[n]     for n in _split(row.get("locations", ""))       if n in location_map]
        r["_src_ips"]           = [ip for ip in _split(row.get("src_ips", "")) if ip]
        r["_dest_addresses"]    = [ip for ip in _split(row.get("dest_addresses", "")) if ip]
        enriched.append(r)

    return enriched, missing


# ---------------------------------------------------------------------------
# Sync classification (dry run)
# ---------------------------------------------------------------------------

def classify_sync(tenant_id: int, rows: List[Dict]) -> SyncClassification:
    """Classify CSV rows vs existing DB rules. No API calls."""
    classification = SyncClassification()

    with get_session() as session:
        existing_records = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type="firewall_rule", is_deleted=False)
            .all()
        )
        existing_by_id = {
            str(r.zia_id): {"zia_id": str(r.zia_id), "name": r.name, "raw_config": r.raw_config or {}}
            for r in existing_records
        }
        existing_ordered = sorted(
            existing_by_id.values(),
            key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0,
        )

    enriched, missing = resolve_dependencies(tenant_id, rows)
    all_missing: Dict[str, set] = {k: set(v) for k, v in missing.items()}

    seen_ids: set = set()
    csv_existing_ids: List[str] = []

    for idx, row in enumerate(enriched):
        rule_id = (row.get("id") or "").strip()
        desired_order = idx + 1  # 1-based CSV position
        issues = _check_dependency_issues(row, all_missing)

        if rule_id and rule_id in existing_by_id:
            seen_ids.add(rule_id)
            csv_existing_ids.append(rule_id)
            existing_cfg = existing_by_id[rule_id]["raw_config"]
            if issues:
                classification.csv_rows.append({
                    "action": "MISSING_DEP",
                    "row": row,
                    "zia_id": rule_id,
                    "desired_order": desired_order,
                    "existing_cfg": existing_cfg,
                    "changes": [],
                    "issues": issues,
                })
            else:
                unchanged, changes = _is_row_unchanged(row, existing_cfg)
                if unchanged:
                    classification.csv_rows.append({
                        "action": "SKIP",
                        "row": row,
                        "zia_id": rule_id,
                        "desired_order": desired_order,
                        "existing_cfg": existing_cfg,
                        "changes": [],
                    })
                else:
                    classification.csv_rows.append({
                        "action": "UPDATE",
                        "row": row,
                        "zia_id": rule_id,
                        "desired_order": desired_order,
                        "existing_cfg": existing_cfg,
                        "changes": changes,
                    })
        elif rule_id and rule_id not in existing_by_id:
            classification.csv_rows.append({
                "action": "MISSING_DEP" if issues else "CREATE",
                "row": row,
                "zia_id": None,
                "desired_order": desired_order,
                "warn": f"ID {rule_id!r} not found in DB — creating as new rule",
                "issues": issues,
            })
        else:
            classification.csv_rows.append({
                "action": "MISSING_DEP" if issues else "CREATE",
                "row": row,
                "zia_id": None,
                "desired_order": desired_order,
                "issues": issues,
            })

    for zia_id, rec in existing_by_id.items():
        if zia_id not in seen_ids:
            classification.to_delete.append({"zia_id": zia_id, "name": rec["name"]})

    existing_id_order = [r["zia_id"] for r in existing_ordered]
    if (classification.to_create or classification.to_delete
            or csv_existing_ids != existing_id_order):
        classification.reorder_needed = True

    return classification


# ---------------------------------------------------------------------------
# Sync execution
# ---------------------------------------------------------------------------

def sync_rules(
    client,
    tenant_id: int,
    classification: SyncClassification,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> SyncResult:
    """Execute firewall rule sync: updates → deletes → creates → reorder.

    ZIA has no bulk reorder endpoint. Reorder is done via individual PUTs
    issued in descending order of desired position to avoid conflicts.
    """
    result = SyncResult()
    result.skipped = len(classification.unchanged)

    total_ops = (
        len(classification.to_update)
        + len(classification.to_delete)
        + len(classification.to_create)
        + (1 if classification.reorder_needed else 0)
    )
    op_num = [0]

    def _tick(label: str) -> None:
        op_num[0] += 1
        if progress_callback:
            progress_callback(label, op_num[0], total_ops)

    # 1. Updates
    for item in classification.to_update:
        row = item["row"]
        zia_id = item["zia_id"]
        name = row.get("name", "")
        try:
            config = _build_payload(row, item["desired_order"])
            client.update_firewall_rule(zia_id, config)
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="UPDATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="firewall_rule",
                resource_id=zia_id, resource_name=name,
                details={"changes": item.get("changes", [])},
            )
            result.rows_detail.append({"name": name, "status": "UPDATED", "id": zia_id, "error": None})
            result.updated += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="UPDATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="firewall_rule",
                resource_id=zia_id, resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "id": zia_id, "error": error_msg})
            result.errors.append(f"UPDATE {name!r}: {error_msg}")
        _tick(f"Updating {name}")

    # 2. Deletes
    for item in classification.to_delete:
        zia_id = item["zia_id"]
        name = item["name"]
        try:
            client.delete_firewall_rule(zia_id)
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="DELETE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="firewall_rule",
                resource_id=zia_id, resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "DELETED", "id": zia_id, "error": None})
            result.deleted += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="DELETE",
                status="FAILURE", tenant_id=tenant_id, resource_type="firewall_rule",
                resource_id=zia_id, resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "id": zia_id, "error": error_msg})
            result.errors.append(f"DELETE {name!r}: {error_msg}")
        _tick(f"Deleting {name}")

    # 3. Creates — capture new IDs
    for item in classification.to_create:
        row = item["row"]
        name = row.get("name", "")
        try:
            config = _build_payload(row, item["desired_order"])
            created = client.create_firewall_rule(config)
            rule_id = str(created.get("id", ""))
            item["zia_id"] = rule_id
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="CREATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="firewall_rule",
                resource_id=rule_id, resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "CREATED", "id": rule_id, "error": None})
            result.created += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="CREATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="firewall_rule",
                resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "id": None, "error": error_msg})
            result.errors.append(f"CREATE {name!r}: {error_msg}")
        _tick(f"Creating {name}")

    # Add SKIPPED entries
    for item in classification.unchanged:
        row = item["row"]
        result.rows_detail.append({
            "name": row.get("name", ""),
            "status": "SKIPPED",
            "id": item.get("zia_id"),
            "error": None,
        })

    # Add MISSING_DEP entries
    for item in classification.missing_dep:
        row = item["row"]
        result.rows_detail.append({
            "name": row.get("name", ""),
            "status": "SKIPPED (missing deps)",
            "id": item.get("zia_id"),
            "error": "; ".join(item.get("issues", [])),
        })

    # 4. Reorder SKIP rules (content unchanged but position may differ)
    # Issue PUTs in descending order to avoid upward conflicts.
    if classification.reorder_needed:
        skip_items_needing_reorder = []
        for item in classification.unchanged:
            existing_order = (
                item.get("existing_cfg", {}).get("order")
                or item.get("existing_cfg", {}).get("rank")
                or 0
            )
            if item["desired_order"] != existing_order:
                skip_items_needing_reorder.append(item)

        # Sort descending by desired order
        skip_items_needing_reorder.sort(key=lambda x: x["desired_order"], reverse=True)

        reorder_errors = []
        for item in skip_items_needing_reorder:
            zia_id = item["zia_id"]
            name = item["row"].get("name", "")
            try:
                # Minimal PUT — just set the new order
                config = _build_payload(item["row"], item["desired_order"])
                client.update_firewall_rule(zia_id, config)
            except Exception as exc:
                reorder_errors.append(f"{name}: {exc}")

        if reorder_errors:
            result.errors.extend([f"REORDER {e}" for e in reorder_errors])
        else:
            result.reordered = True
            audit_service.log(
                product="ZIA", operation="sync_firewall_rules", action="REORDER",
                status="SUCCESS", tenant_id=tenant_id, resource_type="firewall_rule",
                details={"reordered_count": len(skip_items_needing_reorder)},
            )
        _tick("Reordering rules")

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split(value: str) -> List[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def _build_payload(row: Dict, order: int) -> Dict:
    """Build the API payload dict for create or update."""
    payload: Dict = {
        "name":   row.get("name", ""),
        "order":  order,
        "action": (row.get("action") or "").strip().upper() or "ALLOW",
        "state":  (row.get("state") or "ENABLED").strip().upper(),
    }

    if row.get("description"):
        payload["description"] = row["description"]

    logging_str = (row.get("enable_full_logging") or "").strip().lower()
    if logging_str in ("true", "false"):
        payload["enable_full_logging"] = logging_str == "true"

    if row.get("_src_ips"):
        payload["src_ips"] = row["_src_ips"]
    if row.get("_dest_addresses"):
        payload["dest_addresses"] = row["_dest_addresses"]
    if row.get("_src_ip_group_ids"):
        payload["src_ip_groups"] = [{"id": int(gid)} for gid in row["_src_ip_group_ids"]]
    if row.get("_dest_ip_group_ids"):
        payload["dest_ip_groups"] = [{"id": int(gid)} for gid in row["_dest_ip_group_ids"]]
    if row.get("_nw_service_ids"):
        payload["nw_services"] = [{"id": int(sid)} for sid in row["_nw_service_ids"]]
    if row.get("_nw_svc_group_ids"):
        payload["nw_service_groups"] = [{"id": int(gid)} for gid in row["_nw_svc_group_ids"]]
    if row.get("_location_ids"):
        payload["locations"] = [{"id": int(lid)} for lid in row["_location_ids"]]

    return payload


def _decode_rule(cfg: Dict) -> Dict[str, str]:
    """Decode a firewall rule raw_config into comparable CSV-format strings.

    Only scalar and name-decoded fields needed for change detection.
    """
    action_val = cfg.get("action")
    action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or ""

    def _names(obj_list) -> str:
        if not obj_list:
            return ""
        return ";".join(
            obj.get("name", str(obj.get("id", "")))
            if isinstance(obj, dict) else str(obj)
            for obj in obj_list
        )

    return {
        "name":        (cfg.get("name") or "").strip(),
        "action":      action.strip().upper(),
        "state":       (cfg.get("state") or "ENABLED").strip().upper(),
        "description": (cfg.get("description") or "").strip(),
        "src_ips":     ";".join(str(ip) for ip in (cfg.get("src_ips") or [])),
        "src_ip_groups":     _names(cfg.get("src_ip_groups")),
        "dest_addresses":    ";".join(str(ip) for ip in (cfg.get("dest_addresses") or [])),
        "dest_ip_groups":    _names(cfg.get("dest_ip_groups")),
        "nw_services":       _names(cfg.get("nw_services")),
        "nw_service_groups": _names(cfg.get("nw_service_groups")),
        "locations":         _names(cfg.get("locations")),
        "enable_full_logging": str(cfg.get("enable_full_logging") or "").lower(),
    }


def _is_row_unchanged(row: Dict, existing_cfg: Dict) -> Tuple[bool, List[str]]:
    """Compare CSV row against existing raw_config.

    Returns (unchanged, list_of_change_descriptions).
    """
    changes = []
    db = _decode_rule(existing_cfg)

    scalar_map = [
        ("name", "name"),
        ("action", "action"),
        ("state", "state"),
        ("description", "description"),
    ]
    for csv_key, db_key in scalar_map:
        csv_val = (row.get(csv_key) or "").strip()
        db_val = db.get(db_key, "")
        if csv_key in ("action", "state"):
            csv_val = csv_val.upper()
        if csv_val != db_val:
            changes.append(f"{csv_key}: {db_val!r} → {csv_val!r}")

    # Compare group/address fields by name string (best effort)
    for csv_key, db_key in [
        ("src_ips",           "src_ips"),
        ("src_ip_groups",     "src_ip_groups"),
        ("dest_addresses",    "dest_addresses"),
        ("dest_ip_groups",    "dest_ip_groups"),
        ("nw_services",       "nw_services"),
        ("nw_service_groups", "nw_service_groups"),
        ("locations",         "locations"),
        ("enable_full_logging", "enable_full_logging"),
    ]:
        csv_val = ";".join(_split(row.get(csv_key, "")))
        db_val = ";".join(_split(db.get(db_key, "")))
        if csv_val != db_val:
            changes.append(f"{csv_key} changed")

    return len(changes) == 0, changes


def _check_dependency_issues(row: Dict, all_missing: Dict[str, set]) -> List[str]:
    """Return list of dependency issue strings for a single row."""
    issues = []
    for name in _split(row.get("src_ip_groups", "")):
        if name in all_missing.get("src_ip_group", set()):
            issues.append(f"src_ip_group '{name}' not found in DB")
    for name in _split(row.get("dest_ip_groups", "")):
        if name in all_missing.get("dest_ip_group", set()):
            issues.append(f"dest_ip_group '{name}' not found in DB")
    for name in _split(row.get("nw_services", "")):
        if name in all_missing.get("nw_service", set()):
            issues.append(f"nw_service '{name}' not found in DB")
    for name in _split(row.get("nw_service_groups", "")):
        if name in all_missing.get("nw_service_group", set()):
            issues.append(f"nw_service_group '{name}' not found in DB")
    for name in _split(row.get("locations", "")):
        if name in all_missing.get("location", set()):
            issues.append(f"location '{name}' not found in DB")
    return issues


# ---------------------------------------------------------------------------
# IP Group creation (bulk, from CSV)
# ---------------------------------------------------------------------------

IP_SOURCE_GROUP_FIELDNAMES = ["name", "description", "ip_addresses"]
IP_DEST_GROUP_FIELDNAMES   = ["name", "type", "description", "ip_addresses"]

IP_SOURCE_GROUP_TEMPLATE = [
    {"name": "Corp-HQ-Subnet", "description": "Headquarters IP range", "ip_addresses": "10.1.0.0/16;10.2.0.0/16"},
    {"name": "Branch-London",  "description": "London office",          "ip_addresses": "192.168.10.0/24"},
]
IP_DEST_GROUP_TEMPLATE = [
    {"name": "Cloud-DNS-Servers", "type": "DSTN_IP", "description": "Public DNS",        "ip_addresses": "8.8.8.8;8.8.4.4;1.1.1.1"},
    {"name": "Internal-Web-Farm", "type": "DSTN_IP", "description": "Internal web tier", "ip_addresses": "10.50.0.0/24"},
]

_VALID_DEST_TYPES = {"DSTN_IP", "DSTN_FQDN", "DSTN_DOMAIN", "DSTN_OTHER"}


@dataclass
class BulkGroupResult:
    created: int = 0
    failed: int = 0
    rows_detail: List[Dict] = field(default_factory=list)


def parse_ip_source_group_csv(path: str) -> List[Dict]:
    """Parse IP source group CSV. Raises ValueError on failure."""
    errors: List[str] = []
    rows: List[Dict] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):
            if not row.get("name", "").strip():
                errors.append(f"Row {i}: 'name' is required")
            elif not row.get("ip_addresses", "").strip():
                errors.append(f"Row {i} ({row['name']!r}): 'ip_addresses' is required")
            else:
                rows.append(dict(row))
    if errors:
        raise ValueError("CSV validation failed:\n" + "\n".join(errors))
    return rows


def parse_ip_dest_group_csv(path: str) -> List[Dict]:
    """Parse IP destination group CSV. Raises ValueError on failure."""
    errors: List[str] = []
    rows: List[Dict] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):
            row_errors = []
            if not row.get("name", "").strip():
                row_errors.append("'name' is required")
            if not row.get("ip_addresses", "").strip():
                row_errors.append("'ip_addresses' is required")
            grp_type = row.get("type", "DSTN_IP").strip().upper()
            if grp_type and grp_type not in _VALID_DEST_TYPES:
                row_errors.append(f"'type' must be one of {sorted(_VALID_DEST_TYPES)}")
            if row_errors:
                errors.append(f"Row {i} ({row.get('name', f'row {i}')!r}): {'; '.join(row_errors)}")
            else:
                rows.append(dict(row))
    if errors:
        raise ValueError("CSV validation failed:\n" + "\n".join(errors))
    return rows


def bulk_create_ip_source_groups(
    client,
    tenant_id: int,
    rows: List[Dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> BulkGroupResult:
    """Create IP source groups from parsed CSV rows."""
    result = BulkGroupResult()
    for i, row in enumerate(rows, start=1):
        name = row.get("name", "")
        ip_list = [ip.strip() for ip in row.get("ip_addresses", "").split(";") if ip.strip()]
        try:
            config: Dict = {"name": name, "ip_addresses": ip_list}
            if row.get("description"):
                config["description"] = row["description"]
            client.create_ip_source_group(config)
            audit_service.log(
                product="ZIA", operation="bulk_create_ip_source_groups", action="CREATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="ip_source_group",
                resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "CREATED", "error": None})
            result.created += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZIA", operation="bulk_create_ip_source_groups", action="CREATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="ip_source_group",
                resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "error": error_msg})
            result.failed += 1
        if progress_callback:
            progress_callback(i, len(rows))
    return result


def bulk_create_ip_dest_groups(
    client,
    tenant_id: int,
    rows: List[Dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> BulkGroupResult:
    """Create IP destination groups from parsed CSV rows."""
    result = BulkGroupResult()
    for i, row in enumerate(rows, start=1):
        name = row.get("name", "")
        ip_list = [ip.strip() for ip in row.get("ip_addresses", "").split(";") if ip.strip()]
        grp_type = row.get("type", "DSTN_IP").strip().upper() or "DSTN_IP"
        try:
            config: Dict = {"name": name, "type": grp_type, "addresses": ip_list}
            if row.get("description"):
                config["description"] = row["description"]
            client.create_ip_destination_group(config)
            audit_service.log(
                product="ZIA", operation="bulk_create_ip_dest_groups", action="CREATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="ip_destination_group",
                resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "CREATED", "error": None})
            result.created += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZIA", operation="bulk_create_ip_dest_groups", action="CREATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="ip_destination_group",
                resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "error": error_msg})
            result.failed += 1
        if progress_callback:
            progress_callback(i, len(rows))
    return result
