# Spec: ZPA Migration Readiness Check

**Feature branch:** `feature/zpa-apply-baseline`
**Parent feature:** `docs/specs/zpa_apply_baseline.md`
**Scope:** Single inner-helper addition to `apply_baseline_menu()` in `cli/menus/zpa_menu.py`
**Status:** Ready for implementation

---

## 1. Overview

Before the baseline file contents table is displayed in `apply_baseline_menu()`, insert a migration readiness gate. The gate asks whether this is a cross-tenant migration. If yes, it compares the identity resources in the baseline file against the target tenant's current DB state and reports coverage. The user decides whether to proceed based on that report.

No new service file. No fresh API import. Pure menu-layer logic using existing DB query patterns.

---

## 2. Insertion Point

In `apply_baseline_menu()`, the current flow after validation is:

```
# line ~4284 — Step 1: show what's in the file
file_table = Table(title="Baseline File Contents", ...)
```

The migration readiness check inserts **between the two existing validation blocks and Step 1**. Specifically, after line 4282 (the `if not resources:` guard) and before line 4284 (the `file_table = Table(...)` line):

```python
    # resources key validated — migration readiness check goes here
    if not _run_migration_readiness(resources, tenant):
        return

    # ── Step 1: show what's in the file ──────────────────────────────
    file_table = Table(...)
```

The helper returns `True` to continue or `False` to abort (so a bare `if not` return covers both "user declined" and "user said no to migration").

---

## 3. Helper Signature

```python
def _run_migration_readiness(resources: dict, tenant) -> bool:
```

This is a **nested function** defined inside `apply_baseline_menu()`, not a module-level function. It closes over `console` (already in scope at module level) and imports `get_session` / `ZPAResource` locally.

Return value:
- `True` — caller should continue with the rest of the menu
- `False` — caller should `return` (abort)

---

## 4. Algorithm

### 4.1 Migration prompt

```python
console.print()
console.print(
    "[dim]If you are performing a cross-tenant migration, it is recommended that you "
    "pre-configure your IdPs and sync Users, Groups, and Attributes in the target "
    "tenant prior to executing this operation.[/dim]"
)
console.print()
is_migration = questionary.confirm("Is this a migration?", default=False).ask()
if is_migration is None:
    return False  # Ctrl-C / EOF — abort
if not is_migration:
    return True   # not a migration — proceed immediately
```

### 4.2 Identity types to check

```python
IDENTITY_TYPES = ("saml_attribute", "scim_group", "scim_attribute")
IDP_TYPE = "idp"
```

### 4.3 Source names (from baseline)

For each type in `IDENTITY_TYPES`:

```python
source_names[rtype] = {
    entry["name"]
    for entry in resources.get(rtype, [])
    if isinstance(entry, dict) and entry.get("name")
}
```

For `IDP_TYPE`:

```python
source_idp_count = len([
    e for e in resources.get(IDP_TYPE, [])
    if isinstance(e, dict)
])
```

### 4.4 Target names (from DB)

Open a single `get_session()` block and query `ZPAResource` rows for `tenant.id`, filtering `is_deleted=False`. Collect into a dict keyed by `resource_type`:

```python
from db.database import get_session
from db.models import ZPAResource

target_names: dict[str, set] = {t: set() for t in IDENTITY_TYPES}
target_idp_count = 0

with get_session() as session:
    rows = (
        session.query(ZPAResource)
        .filter(
            ZPAResource.tenant_id == tenant.id,
            ZPAResource.is_deleted == False,
            ZPAResource.resource_type.in_(list(IDENTITY_TYPES) + [IDP_TYPE]),
        )
        .all()
    )
    for row in rows:
        if row.resource_type in IDENTITY_TYPES:
            if row.name:
                target_names[row.resource_type].add(row.name)
        elif row.resource_type == IDP_TYPE:
            target_idp_count += 1
```

No import is run. If the tenant has never been imported, all target sets will be empty and coverage will be 0%.

### 4.5 Per-type overlap calculation

For each type in `IDENTITY_TYPES`:

```python
src = source_names[rtype]           # set of names from baseline
tgt = target_names[rtype]           # set of names from DB
matched = src & tgt
if len(src) == 0:
    pct = 100.0
else:
    pct = len(matched) / len(src) * 100
```

Store `(len(src), len(matched), pct)` per type for display.

### 4.6 Overall coverage (weighted)

```python
total_source = sum(len(source_names[t]) for t in IDENTITY_TYPES)
total_matched = sum(len(source_names[t] & target_names[t]) for t in IDENTITY_TYPES)
if total_source == 0:
    overall_pct = 100.0
else:
    overall_pct = total_matched / total_source * 100
```

IdP is excluded from the weighted calculation — it is reported separately as a presence check only.

### 4.7 No-import warning

If `total_source > 0` and `sum(len(v) for v in target_names.values()) == 0` and `target_idp_count == 0`, prepend a note before the table:

```
[yellow]Warning: No identity resources found in DB for {tenant.name}. Run "Import Config" first for a more accurate assessment.[/yellow]
```

---

## 5. Display Format

Print a Rich `Table` titled `"Migration Readiness Assessment"` with `show_lines=False`:

| Column | Justify | Notes |
|---|---|---|
| `Identity Type` | left | display name (see below) |
| `In Baseline` | right | count from source |
| `In Target` | right | count matched in DB |
| `Coverage` | right | `N%` with color styling |

Display names for row labels (plain strings — no Rich markup in the cell value itself; use `style` parameter on `add_row`):

| `resource_type` | Display label |
|---|---|
| `saml_attribute` | `SAML Attributes` |
| `scim_group` | `SCIM Groups` |
| `scim_attribute` | `SCIM Attributes` |

Coverage cell coloring (applied via `style` on `add_row`, not inline markup):
- `pct >= 80` → `"green"`
- `40 <= pct < 80` → `"yellow"`
- `pct < 40` → `"red"`

After the three identity-type rows, add a separator row and then an IdP row:

| `IdP` | `source_idp_count` | `target_idp_count` | presence label |

IdP presence label (plain string):
- `target_idp_count >= 1` → `"Present"`  (style `"green"`)
- `target_idp_count == 0` and `source_idp_count > 0` → `"None configured"`  (style `"red"`)
- `source_idp_count == 0` → `"N/A"`  (style `"dim"`)

Example rendered output (Rich table, not literal text):

```
Migration Readiness Assessment
 Identity Type    | In Baseline | In Target | Coverage
------------------+-------------+-----------+---------
 SAML Attributes  |          12 |        10 |      83%
 SCIM Groups      |          45 |        45 |     100%
 SCIM Attributes  |           8 |         3 |      38%
------------------+-------------+-----------+---------
 IdP              |           2 |         1 |  Present
```

Print the table, then a blank line, then the overall verdict line:

```python
if overall_pct >= 80:
    console.print(
        f"[green]Migration readiness: GOOD[/green] — {overall_pct:.0f}% of identity "
        "scoping criteria found in target. Policies will be applied with minimal stripping."
    )
else:
    console.print(
        f"[yellow]Migration readiness: LOW[/yellow] — only {overall_pct:.0f}% of identity "
        "scoping criteria found in target. Many policy conditions will have operand "
        "values stripped, leaving rules with reduced or no scoping."
    )
console.print()
```

---

## 6. Decision Prompt

```python
if overall_pct >= 80:
    proceed = questionary.confirm("Proceed with migration?", default=True).ask()
else:
    proceed = questionary.confirm(
        f"Coverage is below 80%. Proceed anyway?", default=False
    ).ask()

if proceed is None or not proceed:
    return False
return True
```

If `questionary.confirm` returns `None` (user pressed Ctrl-C or EOF), treat as abort. `not None` evaluates to `True`, so a bare `if not proceed` check would incorrectly continue — the explicit `proceed is None` guard is required.

---

## 7. Full Inner-Helper Skeleton

```python
def _run_migration_readiness(resources: dict, tenant) -> bool:
    from db.database import get_session
    from db.models import ZPAResource

    IDENTITY_TYPES = ("saml_attribute", "scim_group", "scim_attribute")
    IDP_TYPE = "idp"

    console.print()
    console.print(
        "[dim]If you are performing a cross-tenant migration, it is recommended that you "
        "pre-configure your IdPs and sync Users, Groups, and Attributes in the target "
        "tenant prior to executing this operation.[/dim]"
    )
    console.print()
    is_migration = questionary.confirm("Is this a migration?", default=False).ask()
    if is_migration is None:
        return False
    if not is_migration:
        return True

    # -- source names from baseline --
    source_names = {
        rtype: {
            e["name"]
            for e in resources.get(rtype, [])
            if isinstance(e, dict) and e.get("name")
        }
        for rtype in IDENTITY_TYPES
    }
    source_idp_count = len([
        e for e in resources.get(IDP_TYPE, []) if isinstance(e, dict)
    ])

    # -- target names from DB (no import) --
    target_names = {t: set() for t in IDENTITY_TYPES}
    target_idp_count = 0
    with get_session() as session:
        rows = (
            session.query(ZPAResource)
            .filter(
                ZPAResource.tenant_id == tenant.id,
                ZPAResource.is_deleted == False,
                ZPAResource.resource_type.in_(list(IDENTITY_TYPES) + [IDP_TYPE]),
            )
            .all()
        )
        for row in rows:
            if row.resource_type in IDENTITY_TYPES and row.name:
                target_names[row.resource_type].add(row.name)
            elif row.resource_type == IDP_TYPE:
                target_idp_count += 1

    # -- no-import warning --
    total_source = sum(len(source_names[t]) for t in IDENTITY_TYPES)
    if (
        total_source > 0
        and sum(len(v) for v in target_names.values()) == 0
        and target_idp_count == 0
    ):
        console.print(
            f"[yellow]Warning: No identity resources found in DB for "
            f"{tenant.name}. Run 'Import Config' first for a more accurate "
            "assessment.[/yellow]"
        )
        console.print()

    # -- per-type stats --
    type_labels = {
        "saml_attribute": "SAML Attributes",
        "scim_group":     "SCIM Groups",
        "scim_attribute": "SCIM Attributes",
    }
    per_type = {}
    for rtype in IDENTITY_TYPES:
        src = source_names[rtype]
        matched = src & target_names[rtype]
        pct = (len(matched) / len(src) * 100) if src else 100.0
        per_type[rtype] = (len(src), len(matched), pct)

    total_matched = sum(len(source_names[t] & target_names[t]) for t in IDENTITY_TYPES)
    overall_pct = (total_matched / total_source * 100) if total_source > 0 else 100.0

    # -- build table --
    tbl = Table(title="Migration Readiness Assessment", show_lines=False)
    tbl.add_column("Identity Type")
    tbl.add_column("In Baseline", justify="right")
    tbl.add_column("In Target",   justify="right")
    tbl.add_column("Coverage",    justify="right")

    for rtype in IDENTITY_TYPES:
        src_count, matched_count, pct = per_type[rtype]
        if pct >= 80:
            row_style = "green"
        elif pct >= 40:
            row_style = "yellow"
        else:
            row_style = "red"
        tbl.add_row(
            type_labels[rtype],
            str(src_count),
            str(matched_count),
            f"{pct:.0f}%",
            style=row_style,
        )

    tbl.add_section()

    if source_idp_count == 0:
        idp_label, idp_style = "N/A", "dim"
    elif target_idp_count >= 1:
        idp_label, idp_style = "Present", "green"
    else:
        idp_label, idp_style = "None configured", "red"
    tbl.add_row("IdP", str(source_idp_count), str(target_idp_count), idp_label, style=idp_style)

    console.print(tbl)
    console.print()

    # -- verdict --
    if overall_pct >= 80:
        console.print(
            f"[green]Migration readiness: GOOD[/green] — {overall_pct:.0f}% of identity "
            "scoping criteria found in target. Policies will be applied with minimal stripping."
        )
    else:
        console.print(
            f"[yellow]Migration readiness: LOW[/yellow] — only {overall_pct:.0f}% of identity "
            "scoping criteria found in target. Many policy conditions will have operand "
            "values stripped, leaving rules with reduced or no scoping."
        )
    console.print()

    # -- decision prompt --
    if overall_pct >= 80:
        proceed = questionary.confirm("Proceed with migration?", default=True).ask()
    else:
        proceed = questionary.confirm("Coverage is below 80%. Proceed anyway?", default=False).ask()

    if proceed is None or not proceed:
        return False
    return True
```

---

## 8. Architecture Notes

- **No session inside a session.** The `get_session()` call in `_run_migration_readiness` is opened and closed before `apply_baseline_menu` reaches its own DB work (the push service opens its own sessions later). No nesting occurs.
- **No fresh import.** The check queries only `ZPAResource` rows already in the DB. Stale DB state is an acceptable trade-off; the no-import warning covers this case.
- **questionary constraint.** The `questionary.confirm` prompt text must be plain strings. No Rich markup appears in the prompt argument.
- **Rich markup only in `console.print`.** Table cell values are plain strings; color is applied via the `style` parameter on `add_row`, not inline `[green]...[/green]` markup inside cell text.
- **Abort path.** If the user presses Ctrl-C on the migration prompt (`is_migration is None`) or answers `False`/Ctrl-C on the decision prompt (`proceed is None or not proceed`), `_run_migration_readiness` returns `False`. The caller executes `if not _run_migration_readiness(...): return`, which exits the menu cleanly without error output.
- **No audit event.** The readiness check is a read-only, pre-flight query. No audit log entry is written for it.

---

## 9. Backlog Impact

- Self-contained within `apply_baseline_menu()`. No other menus, services, or clients are touched.
- Does not affect the push service (`services/zpa_push_service.py`) or any shared service layer.
- No new dependencies. `get_session` and `ZPAResource` are already imported elsewhere in `zpa_menu.py` (verify the exact import pattern at the top of the file before coding; import locally inside the helper if not already present at module level to avoid circular imports).
