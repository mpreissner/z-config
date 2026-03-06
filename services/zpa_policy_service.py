"""ZPA Access Policy Rule service.

Business logic for syncing access policy rules from CSV.
No CLI concerns — returns plain data structures.

CSV columns:
    id              Rule ID — blank for new rules, filled on export
    name            (required) Rule name
    action          (required) ALLOW or DENY
    description     Free text description
    rule_order      Informational on import (row order determines sequence); filled on export
    app_groups      Semicolon-separated segment group names
    applications    Semicolon-separated application segment names
                    NOTE: at least one of app_groups or applications is required
    saml_attributes Semicolon-separated AttributeName=Value pairs
    scim_groups     Semicolon-separated IdpName:GroupName pairs
    client_types    Semicolon-separated client type identifiers
                    e.g. zpn_client_type_zapp;zpn_client_type_browser_isolation
    machine_groups  Semicolon-separated machine group names
    trusted_networks Semicolon-separated trusted network names
    platforms       Semicolon-separated platform identifiers
                    Valid: ios, android, mac_os, windows, linux, chrome_os
    country_codes   Semicolon-separated ISO 3166-1 alpha-2 country codes (e.g. US;GB;DE)
    idp_names       Semicolon-separated Identity Provider names
"""

import csv
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from db.database import get_session
from db.models import ZPAResource
from services import audit_service


# ---------------------------------------------------------------------------
# CSV schema
# ---------------------------------------------------------------------------

TEMPLATE_ROWS = [
    {
        "id": "",
        "name": "Allow-Engineering-Apps",
        "action": "ALLOW",
        "description": "Allow Engineering group access to internal apps",
        "rule_order": "",
        "app_groups": "Engineering Apps",
        "applications": "SSH Bastion;Jenkins",
        "saml_attributes": "Department=Engineering",
        "scim_groups": "Okta:Engineering",
        "client_types": "zpn_client_type_zapp",
        "machine_groups": "",
        "trusted_networks": "",
        "platforms": "",
        "country_codes": "",
        "idp_names": "",
    },
    {
        "id": "",
        "name": "Deny-Contractors",
        "action": "DENY",
        "description": "Deny contractor access by default",
        "rule_order": "",
        "app_groups": "",
        "applications": "Contractor Portal",
        "saml_attributes": "UserType=Contractor",
        "scim_groups": "",
        "client_types": "zpn_client_type_zapp;zpn_client_type_browser_isolation",
        "machine_groups": "",
        "trusted_networks": "",
        "platforms": "windows;mac_os",
        "country_codes": "",
        "idp_names": "",
    },
]

CSV_FIELDNAMES = list(TEMPLATE_ROWS[0].keys())

_REQUIRED = {"name", "action"}
_VALID_ACTIONS = {"ALLOW", "DENY"}

# Fields stripped before PUT (read-only in ZPA API)
ZPA_READONLY = frozenset({
    "id", "policy_set_id", "modified_time", "creation_time", "modified_by",
    "policy_type", "action_id", "default_rule", "read_only", "zscaler_managed",
})

# Valid platform identifiers (lowercase SDK values)
VALID_PLATFORMS = frozenset({"ios", "android", "mac_os", "windows", "linux", "chrome_os"})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BulkCreateResult:
    created: int = 0
    failed: int = 0
    skipped: int = 0
    rows_detail: List[Dict] = field(default_factory=list)


@dataclass
class SyncClassification:
    """Output of classify_sync() — what would happen on apply."""
    # CSV rows in CSV order. action: "UPDATE" | "CREATE" | "SKIP"
    csv_rows: List[Dict] = field(default_factory=list)
    # DB rules not present in CSV → will be deleted
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
    """Read and validate a CSV file of access policy rule rows.

    Returns a list of row dicts. Raises ValueError on validation failure.
    """
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
                row_errors.append(f"'action' must be ALLOW or DENY, got '{action}'")

            # Validate platform identifiers if provided
            for platform in _split(row.get("platforms", "")):
                if platform.lower() not in VALID_PLATFORMS:
                    row_errors.append(
                        f"invalid platform '{platform}' — valid: {', '.join(sorted(VALID_PLATFORMS))}"
                    )

            if row_errors:
                name = row.get("name", f"row {i}")
                errors.append(f"Row {i} ({name!r}): {'; '.join(row_errors)}")
            else:
                rows.append(dict(row))

    if errors:
        raise ValueError("CSV validation failed:\n" + "\n".join(errors))

    return rows


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------

def resolve_dependencies(
    tenant_id: int,
    rows: List[Dict],
) -> Tuple[List[Dict], Dict[str, List[str]]]:
    """Look up IDs for named conditions from the local ZPA DB cache.

    Returns (enriched_rows, missing) where missing maps resource type to
    a list of unresolved names.
    """
    missing: Dict[str, List[str]] = {
        "app_group": [],
        "application": [],
        "saml_attribute": [],
        "scim_group": [],
        "machine_group": [],
        "trusted_network": [],
        "idp": [],
    }

    # Collect unique names to resolve
    app_group_names: set = set()
    app_names: set = set()
    saml_pairs: set = set()   # (attr_name, value)
    scim_pairs: set = set()   # (idp_name, group_name)
    machine_group_names: set = set()
    trusted_network_names: set = set()
    idp_names: set = set()

    for row in rows:
        for name in _split(row.get("app_groups", "")):
            app_group_names.add(name)
        for name in _split(row.get("applications", "")):
            app_names.add(name)
        for pair in _split(row.get("saml_attributes", "")):
            if "=" in pair:
                attr_name, _, val = pair.partition("=")
                saml_pairs.add((attr_name.strip(), val.strip()))
        for pair in _split(row.get("scim_groups", "")):
            if ":" in pair:
                idp_name, _, group_name = pair.partition(":")
                scim_pairs.add((idp_name.strip(), group_name.strip()))
        for name in _split(row.get("machine_groups", "")):
            machine_group_names.add(name)
        for name in _split(row.get("trusted_networks", "")):
            trusted_network_names.add(name)
        for name in _split(row.get("idp_names", "")):
            idp_names.add(name)

    app_group_map: Dict[str, str] = {}
    app_map: Dict[str, str] = {}
    saml_map: Dict[Tuple[str, str], str] = {}   # (attr_name, value) → attr_id
    scim_map: Dict[Tuple[str, str], str] = {}   # (idp_name, group_name) → group_id
    machine_group_map: Dict[str, str] = {}
    trusted_network_map: Dict[str, str] = {}
    idp_map: Dict[str, str] = {}

    def _lookup_by_type(session, resource_type: str, names: set, result_map: dict, missing_key: str):
        for name in names:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=tenant_id, resource_type=resource_type,
                            name=name, is_deleted=False)
                .first()
            )
            if rec:
                result_map[name] = rec.zpa_id
            elif name not in missing[missing_key]:
                missing[missing_key].append(name)

    with get_session() as session:
        _lookup_by_type(session, "segment_group",    app_group_names,        app_group_map,        "app_group")
        _lookup_by_type(session, "application",      app_names,              app_map,              "application")
        _lookup_by_type(session, "machine_group",    machine_group_names,    machine_group_map,    "machine_group")
        _lookup_by_type(session, "trusted_network",  trusted_network_names,  trusted_network_map,  "trusted_network")
        _lookup_by_type(session, "idp",              idp_names,              idp_map,              "idp")

        # SAML attributes — resolve by attribute name
        saml_attr_names = {pair[0] for pair in saml_pairs}
        saml_by_name: Dict[str, str] = {}
        for name in saml_attr_names:
            rec = (
                session.query(ZPAResource)
                .filter_by(tenant_id=tenant_id, resource_type="saml_attribute",
                            name=name, is_deleted=False)
                .first()
            )
            if rec:
                saml_by_name[name] = rec.zpa_id
            elif name not in missing["saml_attribute"]:
                missing["saml_attribute"].append(name)

        for attr_name, val in saml_pairs:
            if attr_name in saml_by_name:
                saml_map[(attr_name, val)] = saml_by_name[attr_name]

        # SCIM groups — match by group name + IdP name via raw_config
        all_scim = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="scim_group", is_deleted=False)
            .all()
        )
        scim_by_idp_and_name: Dict[Tuple[str, str], str] = {}
        for rec in all_scim:
            cfg = rec.raw_config or {}
            idp_n = (cfg.get("idpName") or "").strip()
            group_n = (rec.name or "").strip()
            if idp_n and group_n:
                scim_by_idp_and_name[(idp_n, group_n)] = rec.zpa_id

        for idp_name, group_name in scim_pairs:
            key = (idp_name, group_name)
            if key in scim_by_idp_and_name:
                scim_map[key] = scim_by_idp_and_name[key]
            else:
                label = f"{idp_name}:{group_name}"
                if label not in missing["scim_group"]:
                    missing["scim_group"].append(label)

    # Annotate rows
    enriched: List[Dict] = []
    for row in rows:
        r = dict(row)

        r["_app_group_ids"] = [
            app_group_map[n] for n in _split(row.get("app_groups", ""))
            if n in app_group_map
        ]
        r["_app_ids"] = [
            app_map[n] for n in _split(row.get("applications", ""))
            if n in app_map
        ]
        r["_saml_conditions"] = []
        for pair in _split(row.get("saml_attributes", "")):
            if "=" in pair:
                attr_name, _, val = pair.partition("=")
                attr_name, val = attr_name.strip(), val.strip()
                attr_id = saml_map.get((attr_name, val))
                if attr_id:
                    r["_saml_conditions"].append((attr_id, val))

        r["_scim_group_ids"] = []
        for pair in _split(row.get("scim_groups", "")):
            if ":" in pair:
                idp_name, _, group_name = pair.partition(":")
                gid = scim_map.get((idp_name.strip(), group_name.strip()))
                if gid:
                    r["_scim_group_ids"].append(gid)

        r["_client_types"] = [ct for ct in _split(row.get("client_types", "")) if ct]
        r["_machine_group_ids"] = [
            machine_group_map[n] for n in _split(row.get("machine_groups", ""))
            if n in machine_group_map
        ]
        r["_trusted_network_ids"] = [
            trusted_network_map[n] for n in _split(row.get("trusted_networks", ""))
            if n in trusted_network_map
        ]
        r["_platforms"] = [p.lower() for p in _split(row.get("platforms", "")) if p]
        r["_country_codes"] = [c.upper() for c in _split(row.get("country_codes", "")) if c]
        r["_idp_ids"] = [
            idp_map[n] for n in _split(row.get("idp_names", ""))
            if n in idp_map
        ]

        enriched.append(r)

    return enriched, missing


# ---------------------------------------------------------------------------
# Dry run (legacy — for bulk_create flow)
# ---------------------------------------------------------------------------

def dry_run(tenant_id: int, rows: List[Dict]) -> List[Dict]:
    """Tag each row READY or MISSING_DEPENDENCY. No API calls."""
    enriched, missing = resolve_dependencies(tenant_id, rows)

    missing_app_groups = set(missing.get("app_group", []))
    missing_apps = set(missing.get("application", []))
    missing_saml = set(missing.get("saml_attribute", []))
    missing_scim = set(missing.get("scim_group", []))
    missing_machine = set(missing.get("machine_group", []))
    missing_tn = set(missing.get("trusted_network", []))
    missing_idp = set(missing.get("idp", []))

    result: List[Dict] = []
    for row in enriched:
        issues = []

        # Require at least one app or app_group
        has_app = bool(_split(row.get("app_groups", "")) or _split(row.get("applications", "")))
        if not has_app:
            issues.append("at least one 'app_groups' or 'applications' entry is required")

        for name in _split(row.get("app_groups", "")):
            if name in missing_app_groups:
                issues.append(f"app_group '{name}' not found in DB")
        for name in _split(row.get("applications", "")):
            if name in missing_apps:
                issues.append(f"application '{name}' not found in DB")
        for pair in _split(row.get("saml_attributes", "")):
            if "=" in pair:
                attr_name = pair.partition("=")[0].strip()
                if attr_name in missing_saml:
                    issues.append(f"saml_attribute '{attr_name}' not found in DB")
        for pair in _split(row.get("scim_groups", "")):
            if ":" in pair:
                label = ":".join(p.strip() for p in pair.split(":", 1))
                if label in missing_scim:
                    issues.append(f"scim_group '{label}' not found in DB")
        for name in _split(row.get("machine_groups", "")):
            if name in missing_machine:
                issues.append(f"machine_group '{name}' not found in DB")
        for name in _split(row.get("trusted_networks", "")):
            if name in missing_tn:
                issues.append(f"trusted_network '{name}' not found in DB")
        for name in _split(row.get("idp_names", "")):
            if name in missing_idp:
                issues.append(f"idp '{name}' not found in DB")

        r = dict(row)
        r["_status"] = "MISSING_DEPENDENCY" if issues else "READY"
        r["_issues"] = issues
        result.append(r)

    return result


# ---------------------------------------------------------------------------
# Sync classification (dry run for sync)
# ---------------------------------------------------------------------------

def classify_sync(tenant_id: int, rows: List[Dict]) -> SyncClassification:
    """Classify CSV rows vs existing DB rules. No API calls.

    Returns a SyncClassification describing what would be updated, created,
    deleted, and whether a reorder is needed.
    """
    classification = SyncClassification()

    # Load existing rules from DB
    with get_session() as session:
        existing_records = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="policy_access", is_deleted=False)
            .all()
        )
        existing_by_id = {
            r.zpa_id: {"zpa_id": r.zpa_id, "name": r.name, "raw_config": r.raw_config or {}}
            for r in existing_records
        }
        existing_ordered = sorted(
            existing_by_id.values(),
            key=lambda r: int(r["raw_config"].get("rule_order") or 0),
        )

    # Resolve dependencies for all rows
    enriched, missing = resolve_dependencies(tenant_id, rows)

    # Build flat missing set for quick lookup
    all_missing: Dict[str, set] = {k: set(v) for k, v in missing.items()}

    seen_ids: set = set()
    csv_existing_ids: List[str] = []

    for row in enriched:
        rule_id = (row.get("id") or "").strip()
        issues = _check_dependency_issues(row, all_missing)
        # Require at least one app or app_group
        has_app = bool(_split(row.get("app_groups", "")) or _split(row.get("applications", "")))
        if not has_app:
            issues.append("at least one 'app_groups' or 'applications' entry is required")

        if rule_id and rule_id in existing_by_id:
            seen_ids.add(rule_id)
            csv_existing_ids.append(rule_id)
            existing_cfg = existing_by_id[rule_id]["raw_config"]
            if issues:
                classification.csv_rows.append({
                    "action": "MISSING_DEP",
                    "row": row,
                    "zpa_id": rule_id,
                    "changes": [],
                    "issues": issues,
                })
            else:
                unchanged, changes = _is_row_unchanged(row, existing_cfg)
                if unchanged:
                    classification.csv_rows.append({
                        "action": "SKIP",
                        "row": row,
                        "zpa_id": rule_id,
                        "changes": [],
                    })
                else:
                    classification.csv_rows.append({
                        "action": "UPDATE",
                        "row": row,
                        "zpa_id": rule_id,
                        "existing_cfg": existing_cfg,
                        "changes": changes,
                    })
        elif rule_id and rule_id not in existing_by_id:
            classification.csv_rows.append({
                "action": "MISSING_DEP" if issues else "CREATE",
                "row": row,
                "zpa_id": None,
                "warn": f"ID {rule_id!r} not found in DB — creating as new rule",
                "issues": issues,
            })
        else:
            classification.csv_rows.append({
                "action": "MISSING_DEP" if issues else "CREATE",
                "row": row,
                "zpa_id": None,
                "issues": issues,
            })

    # Rules in DB but not in CSV → delete
    for zpa_id, rec in existing_by_id.items():
        if zpa_id not in seen_ids:
            classification.to_delete.append({"zpa_id": zpa_id, "name": rec["name"]})

    # Reorder check
    existing_id_order = [r["zpa_id"] for r in existing_ordered]
    applicable = [e for e in classification.csv_rows if e["action"] in ("UPDATE", "SKIP", "CREATE")]
    csv_existing_ids_applicable = [e["zpa_id"] for e in applicable if e.get("zpa_id")]
    if (classification.to_create or classification.to_delete
            or csv_existing_ids_applicable != existing_id_order):
        classification.reorder_needed = True

    return classification


# ---------------------------------------------------------------------------
# Sync execution
# ---------------------------------------------------------------------------

def sync_policy(
    client,
    tenant_id: int,
    classification: SyncClassification,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> SyncResult:
    """Execute the sync: updates → deletes → creates → bulk_reorder.

    progress_callback(label, done, total) called after each operation.
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
        zpa_id = item["zpa_id"]
        name = row.get("name", "")
        action = row.get("action", "ALLOW").strip().upper()
        try:
            conditions = _build_conditions(row)
            kwargs = {"description": row.get("description", "")}
            if conditions:
                kwargs["conditions"] = conditions
            client.update_access_rule(zpa_id, name=name, action=action, **kwargs)
            audit_service.log(
                product="ZPA", operation="sync_access_rules", action="UPDATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="policy_access",
                resource_id=zpa_id, resource_name=name,
                details={"changes": item.get("changes", [])},
            )
            result.rows_detail.append({"name": name, "status": "UPDATED", "id": zpa_id, "error": None})
            result.updated += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZPA", operation="sync_access_rules", action="UPDATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="policy_access",
                resource_id=zpa_id, resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "id": zpa_id, "error": error_msg})
            result.errors.append(f"UPDATE {name!r}: {error_msg}")
        _tick(f"Updating {name}")

    # 2. Deletes
    for item in classification.to_delete:
        zpa_id = item["zpa_id"]
        name = item["name"]
        try:
            client.delete_access_rule(zpa_id)
            audit_service.log(
                product="ZPA", operation="sync_access_rules", action="DELETE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="policy_access",
                resource_id=zpa_id, resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "DELETED", "id": zpa_id, "error": None})
            result.deleted += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZPA", operation="sync_access_rules", action="DELETE",
                status="FAILURE", tenant_id=tenant_id, resource_type="policy_access",
                resource_id=zpa_id, resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "id": zpa_id, "error": error_msg})
            result.errors.append(f"DELETE {name!r}: {error_msg}")
        _tick(f"Deleting {name}")

    # 3. Creates — capture new IDs, store back in csv_rows entry
    for item in classification.to_create:
        row = item["row"]
        name = row.get("name", "")
        action = row.get("action", "ALLOW").strip().upper()
        try:
            conditions = _build_conditions(row)
            kwargs = {}
            if row.get("description"):
                kwargs["description"] = row["description"]
            if conditions:
                kwargs["conditions"] = conditions
            created = client.create_access_rule(name=name, action=action, **kwargs)
            rule_id = str(created.get("id", ""))
            item["zpa_id"] = rule_id
            audit_service.log(
                product="ZPA", operation="sync_access_rules", action="CREATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="policy_access",
                resource_id=rule_id, resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "CREATED", "id": rule_id, "error": None})
            result.created += 1
        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZPA", operation="sync_access_rules", action="CREATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="policy_access",
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
            "id": item.get("zpa_id"),
            "error": None,
        })

    # Add MISSING_DEP entries
    for item in classification.csv_rows:
        if item["action"] == "MISSING_DEP":
            name = item["row"].get("name", "")
            result.rows_detail.append({
                "name": name,
                "status": "SKIPPED (missing deps)",
                "id": item.get("zpa_id"),
                "error": "; ".join(item.get("issues", [])),
            })

    # 4. Bulk reorder
    if classification.reorder_needed:
        ordered_ids = [
            item["zpa_id"]
            for item in classification.csv_rows
            if item.get("zpa_id") and item["action"] in ("UPDATE", "SKIP", "CREATE")
        ]
        if ordered_ids:
            try:
                client.bulk_reorder_access_rules(ordered_ids)
                result.reordered = True
                audit_service.log(
                    product="ZPA", operation="sync_access_rules", action="REORDER",
                    status="SUCCESS", tenant_id=tenant_id, resource_type="policy_access",
                    details={"rule_count": len(ordered_ids)},
                )
            except Exception as exc:
                error_msg = str(exc)
                result.errors.append(f"REORDER: {error_msg}")
                audit_service.log(
                    product="ZPA", operation="sync_access_rules", action="REORDER",
                    status="FAILURE", tenant_id=tenant_id, resource_type="policy_access",
                    error_message=error_msg,
                )
        _tick("Reordering rules")

    return result


# ---------------------------------------------------------------------------
# Bulk create (legacy)
# ---------------------------------------------------------------------------

def bulk_create(
    client,
    tenant_id: int,
    rows: List[Dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> BulkCreateResult:
    """Create access policy rules for READY rows."""
    result = BulkCreateResult()
    ready_rows = [r for r in rows if r.get("_status") == "READY"]
    skipped_rows = [r for r in rows if r.get("_status") != "READY"]
    result.skipped = len(skipped_rows)
    total = len(ready_rows)

    for i, row in enumerate(ready_rows, start=1):
        name = row.get("name", "")
        action = row.get("action", "ALLOW").strip().upper()
        try:
            conditions = _build_conditions(row)
            kwargs = {}
            if row.get("description"):
                kwargs["description"] = row["description"]
            if row.get("rule_order", "").strip():
                kwargs["rule_order"] = row["rule_order"].strip()
            if conditions:
                kwargs["conditions"] = conditions

            created = client.create_access_rule(name=name, action=action, **kwargs)
            rule_id = str(created.get("id", ""))

            audit_service.log(
                product="ZPA", operation="bulk_create_access_rules", action="CREATE",
                status="SUCCESS", tenant_id=tenant_id, resource_type="policy_access",
                resource_id=rule_id, resource_name=name,
            )
            result.rows_detail.append({"name": name, "status": "CREATED", "id": rule_id, "error": None})
            result.created += 1

        except Exception as exc:
            error_msg = str(exc)
            audit_service.log(
                product="ZPA", operation="bulk_create_access_rules", action="CREATE",
                status="FAILURE", tenant_id=tenant_id, resource_type="policy_access",
                resource_name=name, error_message=error_msg,
            )
            result.rows_detail.append({"name": name, "status": "FAILED", "id": None, "error": error_msg})
            result.failed += 1

        if progress_callback:
            progress_callback(i, total)

    for row in skipped_rows:
        result.rows_detail.append({
            "name": row.get("name", ""),
            "status": f"SKIPPED ({row.get('_status', 'UNKNOWN')})",
            "id": None,
            "error": "; ".join(row.get("_issues", [])),
        })

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split(value: str) -> List[str]:
    """Split a semicolon-separated string, stripping whitespace and empty parts."""
    return [v.strip() for v in value.split(";") if v.strip()]


def _check_dependency_issues(row: Dict, all_missing: Dict[str, set]) -> List[str]:
    """Return list of dependency issue strings for a single row."""
    issues = []
    for name in _split(row.get("app_groups", "")):
        if name in all_missing.get("app_group", set()):
            issues.append(f"app_group '{name}' not found in DB")
    for name in _split(row.get("applications", "")):
        if name in all_missing.get("application", set()):
            issues.append(f"application '{name}' not found in DB")
    for pair in _split(row.get("saml_attributes", "")):
        if "=" in pair:
            attr_name = pair.partition("=")[0].strip()
            if attr_name in all_missing.get("saml_attribute", set()):
                issues.append(f"saml_attribute '{attr_name}' not found in DB")
    for pair in _split(row.get("scim_groups", "")):
        if ":" in pair:
            label = ":".join(p.strip() for p in pair.split(":", 1))
            if label in all_missing.get("scim_group", set()):
                issues.append(f"scim_group '{label}' not found in DB")
    for name in _split(row.get("machine_groups", "")):
        if name in all_missing.get("machine_group", set()):
            issues.append(f"machine_group '{name}' not found in DB")
    for name in _split(row.get("trusted_networks", "")):
        if name in all_missing.get("trusted_network", set()):
            issues.append(f"trusted_network '{name}' not found in DB")
    for name in _split(row.get("idp_names", "")):
        if name in all_missing.get("idp", set()):
            issues.append(f"idp '{name}' not found in DB")
    return issues


def _build_conditions(row: Dict) -> List[Tuple]:
    """Build SDK condition tuples from an enriched row."""
    conditions = []
    for gid in row.get("_app_group_ids", []):
        conditions.append(("app_group", "id", gid))
    for aid in row.get("_app_ids", []):
        conditions.append(("app", "id", aid))
    for attr_id, val in row.get("_saml_conditions", []):
        conditions.append(("saml", attr_id, val))
    for gid in row.get("_scim_group_ids", []):
        conditions.append(("scim_group", gid, gid))
    for ct in row.get("_client_types", []):
        conditions.append(("client_type", ct, ct))
    for gid in row.get("_machine_group_ids", []):
        conditions.append(("machine_grp", "id", gid))
    for nid in row.get("_trusted_network_ids", []):
        conditions.append(("trusted_network", nid, True))
    for platform in row.get("_platforms", []):
        conditions.append(("platform", "id", platform))
    for code in row.get("_country_codes", []):
        conditions.append(("country_code", "id", code))
    for idp_id in row.get("_idp_ids", []):
        conditions.append(("idp", "id", idp_id))
    return conditions


def _decode_conditions(cfg: Dict) -> Dict[str, str]:
    """Decode conditions from raw_config into CSV-format semicolon strings."""
    conditions = cfg.get("conditions") or []
    app_groups, applications, saml_attrs, scim_groups, client_types = [], [], [], [], []
    machine_groups, trusted_networks, platforms, country_codes, idp_names = [], [], [], [], []

    for group in conditions:
        for op in group.get("operands") or []:
            otype = (op.get("object_type") or "").upper()
            name = op.get("name") or ""
            rhs = op.get("rhs") or ""
            lhs = op.get("lhs") or ""
            idp_name = op.get("idp_name") or ""

            if otype == "APP_GROUP" and name:
                app_groups.append(name)
            elif otype == "APP" and name:
                applications.append(name)
            elif otype == "CLIENT_TYPE" and rhs:
                client_types.append(rhs)
            elif otype == "SAML" and name and rhs:
                saml_attrs.append(f"{name}={rhs}")
            elif otype == "SCIM_GROUP" and name:
                prefix = f"{idp_name}:" if idp_name else ""
                scim_groups.append(f"{prefix}{name}")
            elif otype == "MACHINE_GRP":
                if name:
                    machine_groups.append(name)
            elif otype == "TRUSTED_NETWORK":
                # name is the human-readable network name
                if name:
                    trusted_networks.append(name)
            elif otype == "PLATFORM" and rhs:
                platforms.append(rhs)
            elif otype == "COUNTRY_CODE" and rhs:
                country_codes.append(rhs)
            elif otype == "IDP":
                if name:
                    idp_names.append(name)

    return {
        "app_groups":       ";".join(app_groups),
        "applications":     ";".join(applications),
        "saml_attributes":  ";".join(saml_attrs),
        "scim_groups":      ";".join(scim_groups),
        "client_types":     ";".join(client_types),
        "machine_groups":   ";".join(machine_groups),
        "trusted_networks": ";".join(trusted_networks),
        "platforms":        ";".join(platforms),
        "country_codes":    ";".join(country_codes),
        "idp_names":        ";".join(idp_names),
    }


def _is_row_unchanged(row: Dict, existing_cfg: Dict) -> Tuple[bool, List[str]]:
    """Compare CSV row against existing raw_config.

    Returns (unchanged, list_of_change_descriptions).
    """
    changes = []

    for csv_key, cfg_key in [("name", "name"), ("action", "action"), ("description", "description")]:
        csv_val = (row.get(csv_key) or "").strip()
        db_val = (existing_cfg.get(cfg_key) or "").strip()
        if csv_key == "action":
            csv_val = csv_val.upper()
            db_val = db_val.upper()
        if csv_val != db_val:
            changes.append(f"{csv_key}: {db_val!r} → {csv_val!r}")

    db_cond = _decode_conditions(existing_cfg)
    condition_fields = [
        "app_groups", "applications", "saml_attributes", "scim_groups", "client_types",
        "machine_groups", "trusted_networks", "platforms", "country_codes", "idp_names",
    ]
    for field_name in condition_fields:
        csv_val = ";".join(_split(row.get(field_name, "")))
        db_val = ";".join(_split(db_cond.get(field_name, "")))
        if csv_val != db_val:
            changes.append(f"{field_name} changed")

    return len(changes) == 0, changes
