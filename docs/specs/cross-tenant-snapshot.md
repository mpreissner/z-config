# Spec: cross-tenant-snapshot

**Status:** Ready for implementation
**Target branches:**
- `zs-config`: `feature/cross-tenant-snapshot`
- `zs-plugins`: `feature/zia-snapshot-tools`

---

## 1. Goal and Motivation

Today, applying a ZIA baseline requires exporting a snapshot to a JSON file from one tenant and then importing that file via the "Apply Baseline from JSON" menu option in the target tenant — a round-trip through the filesystem that is cumbersome and error-prone. This work has two goals. First, move the file-based export and file-based import operations out of zs-config's core menus and into a dedicated `zia-snapshot-tools` plugin in the `zs-plugins` repo; this keeps the core application focused and lets the plugin be installed only when needed. Second, add a new native ZIA menu option — "Apply Snapshot from Another Tenant" — that eliminates the file round-trip entirely: the user picks a source tenant's snapshot directly from the local DB and feeds it straight into the existing `apply_baseline_menu` push flow, with no file on disk.

---

## 2. Scope Table

| Item | Disposition |
|---|---|
| `_export_snapshot()` in `snapshots_menu.py` | **Removed** from zs-config entirely |
| "Export Snapshot to JSON" menu choice in `snapshots_menu.py` | **Removed** |
| "Apply Baseline from JSON" menu item in ZIA menu | **Removed** from zs-config |
| File-loading branch (`if baseline is None: questionary.path(...)`) in `apply_baseline_menu()` | **Removed** from `apply_baseline_menu()` |
| New `_pick_cross_tenant_snapshot()` helper in `zia_menu.py` | **Added** to zs-config |
| New "Apply Snapshot from Another Tenant" ZIA menu entry | **Added** to zs-config |
| New `zia-snapshot-tools` plugin in `zs-plugins` | **New** — Export and Apply-from-file both live here |
| `manifest.json` in `zs-plugins` | **Updated** — new plugin entry added |
| `apply_baseline_menu()` push flow from product validation onward | **Unchanged** |
| `services/zia_push_service.py` | **Unchanged** |
| `services/snapshot_service.py` | **Unchanged** |
| `db/models.py` | **Unchanged** |
| palo-tools plugin | **Unchanged** |
| GitHub auth / plugin manager | **Unchanged** |
| palo-tools callback into `apply_baseline_menu(client, tenant, baseline=dict, baseline_path=path)` | **Unchanged** |

---

## 3. zs-config Changes

### 3a. `cli/menus/snapshots_menu.py`

**Remove `_export_snapshot()`** — delete the entire function (lines 218–246 in the current file). It is not kept as an internal helper; the plugin re-implements equivalent logic using the same service layer.

**Remove the "Export Snapshot to JSON" menu entry** — in `snapshots_menu()`, delete the `questionary.Choice("Export Snapshot to JSON", value="export")` entry from the `choices` list and the corresponding `elif choice == "export": _export_snapshot(tenant, product)` dispatch branch.

No other changes to this file.

---

### 3b. `cli/menus/zia_menu.py`

#### 3b-i. Remove "Apply Baseline from JSON" menu item

Locate the `questionary.Choice` for "Apply Baseline from JSON" in the ZIA menu choices list and delete it along with its dispatch branch (the `elif` that calls `apply_baseline_menu(client, tenant)`).

#### 3b-ii. Strip file-loading branch from `apply_baseline_menu()`

The current function signature is:

```python
def apply_baseline_menu(client, tenant, *, baseline=None, baseline_path=None)
```

This signature does not change.

Remove the entire `if baseline is None:` block that currently spans lines 4421–4432:

```python
if baseline is None:
    path = questionary.path("Path to baseline JSON file:", default=str(DEFAULT_WORK_DIR)).ask()
    if not path:
        return
    baseline_path = path.strip()
    try:
        with open(baseline_path) as fh:
            baseline = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
```

Replace it with a guard that simply returns if `baseline` was not provided by the caller:

```python
if baseline is None:
    return
```

All callers (palo-tools, the new cross-tenant menu handler, and any future plugin) are required to supply `baseline=dict` and `baseline_path=str`. The guard exists only to prevent accidental bare calls from crashing.

The rest of `apply_baseline_menu()` from the product-validation check (`if baseline.get("product") != "ZIA":`) onward is completely unchanged.

#### 3b-iii. Add `_CANCEL` sentinel

Add at module level, near the top of `zia_menu.py` alongside other module-level constants:

```python
_CANCEL = object()
```

Verify whether `_CANCEL` already exists in the file before adding.

#### 3b-iv. New helper: `_pick_cross_tenant_snapshot(current_tenant)`

Add this function immediately before `apply_baseline_menu`. Full specification:

```python
def _pick_cross_tenant_snapshot(current_tenant):
    """
    Prompt user to select a source tenant (excluding current_tenant) then a ZIA
    snapshot from that tenant.

    Returns a tuple (source_tenant, snap: RestorePoint) or (None, None).
    """
```

Implementation steps, in order:

1. Call `list_tenants()` (already imported at module level in `zia_menu.py` from `services.config_service`; verify before adding). Filter the result to exclude the current target tenant by ID: `[t for t in list_tenants() if t.id != current_tenant.id]`.

2. If the filtered list is empty, print `"[yellow]No other tenants are configured.[/yellow]"` and return `(None, None)`.

3. Build a `questionary.select` tenant picker:
   - Prompt text: `"Select source tenant:"`
   - One `questionary.Choice` per tenant; label is `tenant.name` (plain text — no Rich markup).
   - Append `questionary.Choice("← Cancel", value=_CANCEL)` as the last entry.
   - `use_indicator=True`.
   - If `.ask()` returns `None` or `_CANCEL`, return `(None, None)`.

4. Open exactly one `with get_session() as session:` block. Inside it, call `list_snapshots(source_tenant.id, "ZIA", session)`. Assign the result to a local variable before the block exits. Do not call `audit_service.log()` or any other session-opening function inside this block.

5. If the resulting list is empty, print `f"[yellow]No ZIA snapshots found for {source_tenant.name}.[/yellow]"` and return `(None, None)`.

6. Build a `questionary.select` snapshot picker:
   - Prompt text: `f"Select snapshot from {source_tenant.name}:"`
   - One `questionary.Choice` per snapshot; `value=snap` (the RestorePoint object).
   - Label format (all plain text, no Rich markup):

     ```
     {snap.name}  [{local_ts}]  {snap.resource_count} resources{comment_suffix}
     ```

     Where:
     - `local_ts` = `snap.created_at.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")`
     - `comment_suffix` = `f"  {snap.comment}"` if `snap.comment` else `""`

     Example with comment:    `2025-11-04 14:30:00  [2025-11-04 14:30:00]  412 resources  pre-change backup`
     Example without comment: `2025-11-04 14:30:00  [2025-11-04 14:30:00]  412 resources`

   - Snapshots are already returned newest-first by `list_snapshots`; no additional sorting.
   - Append `questionary.Choice("← Cancel", value=_CANCEL)` as the last entry.
   - `use_indicator=True`.
   - If `.ask()` returns `None` or `_CANCEL`, return `(None, None)`.

7. Return `(source_tenant, selected_snap)`.

Required imports (add at module level if not already present):
- `from services.snapshot_service import list_snapshots`
- `from db.database import get_session`
- `from datetime import timezone`

#### 3b-v. Add new ZIA menu entry: "Apply Snapshot from Another Tenant"

Add a new `questionary.Choice("Apply Snapshot from Another Tenant", value="cross_tenant_snap")` to the ZIA menu choices list. Place it in the baseline/snapshot section of the menu, adjacent to where "Apply Baseline from JSON" used to appear.

Add the dispatch branch:

```python
elif choice == "cross_tenant_snap":
    source_tenant, snap = _pick_cross_tenant_snapshot(tenant)
    if source_tenant is None or snap is None:
        pass  # user cancelled; loop continues
    else:
        baseline_path = f"{source_tenant.name}/{snap.name}"
        baseline = {
            "product": "ZIA",
            "tenant_name": source_tenant.name,
            "snapshot_name": snap.name,
            "comment": snap.comment or "",
            "created_at": snap.created_at.isoformat() + "Z",
            "resource_count": snap.resource_count,
            "resources": snap.snapshot["resources"],
        }
        apply_baseline_menu(client, tenant, baseline=baseline, baseline_path=baseline_path)
```

The `baseline` dict construction is specified in full in Section 5.

---

## 4. New Plugin: `zia-snapshot-tools` in `zs-plugins`

### 4a. Directory Structure

Mirror the palo-tools layout exactly:

```
zs-plugins/
  zia-snapshot-tools/
    pyproject.toml
    zia_snapshot_tools/
      __init__.py
      plugin.py
      menu.py
```

No `data/` subdirectory is needed (no bundled data files).

### 4b. `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "zia-snapshot-tools"
version = "0.1.0"
description = "ZIA snapshot export and baseline apply plugin for zs-config"
requires-python = ">=3.10"
dependencies = [
    "zs-config",
    "questionary>=2.0.0",
    "rich>=13.7.0",
]

[project.entry-points."zs_config.plugins"]
zia_snapshot_tools = "zia_snapshot_tools.plugin:register"

[tool.setuptools.packages.find]
where = ["."]
include = ["zia_snapshot_tools*"]
```

`zs-config` is listed as a dependency because the plugin imports from `cli.menus.zia_menu`, `cli.menus`, `services.snapshot_service`, and `db.database`. These are not installed as a package API but are available at runtime when the plugin runs inside the zs-config process.

### 4c. `zia_snapshot_tools/__init__.py`

Empty file.

### 4d. `zia_snapshot_tools/plugin.py`

```python
"""zs-config plugin entry point for zia-snapshot-tools."""


def register() -> dict:
    """Called by zs-config's plugin manager at startup."""
    from zia_snapshot_tools.menu import zia_snapshot_menu

    return {
        "name": "ZIA Snapshot Tools",
        "menu": zia_snapshot_menu,
    }
```

### 4e. `zia_snapshot_tools/menu.py`

The plugin exposes a single top-level menu with two operations.

Module-level setup:

```python
"""ZIA Snapshot Tools TUI menu — zs-config plugin."""

import json
import os
import re
from datetime import timezone
from pathlib import Path

import questionary
from rich.console import Console

try:
    from lib.defaults import DEFAULT_WORK_DIR
except ImportError:
    DEFAULT_WORK_DIR = Path.home() / "Documents" / "zs-config"

console = Console()
_CANCEL = object()
```

Top-level menu function:

```python
def zia_snapshot_menu() -> None:
    """Entry point called by zs-config when the user selects ZIA Snapshot Tools."""
    from cli.banner import render_banner

    while True:
        render_banner()
        choice = questionary.select(
            "ZIA Snapshot Tools",
            choices=[
                questionary.Choice("  Export Snapshot to JSON",    value="export"),
                questionary.Choice("  Apply Baseline from JSON",   value="apply"),
                questionary.Separator(),
                questionary.Choice("  Back",                       value="back"),
            ],
        ).ask()

        if choice == "export":
            _export_snapshot()
        elif choice == "apply":
            _apply_baseline()
        elif choice in ("back", None):
            break
```

#### 4e-i. Export Snapshot to JSON flow

```python
def _export_snapshot() -> None:
    ...
```

Step-by-step implementation:

1. Call `select_tenant()` from `cli.menus` to let the user choose a tenant. If it returns `None`, return immediately.

   ```python
   from cli.menus import select_tenant
   tenant = select_tenant()
   if tenant is None:
       return
   ```

2. Prompt for product:

   ```python
   product = questionary.select(
       "Product:",
       choices=[
           questionary.Choice("ZIA", value="ZIA"),
           questionary.Choice("ZPA", value="ZPA"),
           questionary.Choice("← Cancel", value=_CANCEL),
       ],
       use_indicator=True,
   ).ask()
   if product is None or product is _CANCEL:
       return
   ```

3. Open `with get_session() as session:` and call `list_snapshots(tenant.id, product, session)`. Store the result before the block closes. If the list is empty, print `f"[yellow]No {product} snapshots found for {tenant.name}.[/yellow]"` and return.

   ```python
   from db.database import get_session
   from services.snapshot_service import list_snapshots

   with get_session() as session:
       snaps = list_snapshots(tenant.id, product, session)

   if not snaps:
       console.print(f"[yellow]No {product} snapshots found for {tenant.name}.[/yellow]")
       questionary.press_any_key_to_continue("Press any key to continue...").ask()
       return
   ```

4. Build a `questionary.select` snapshot picker using the same label format as `_pick_cross_tenant_snapshot` in zs-config (plain text, no Rich markup):

   ```
   {snap.name}  [{local_ts}]  {snap.resource_count} resources{comment_suffix}
   ```

   Add `questionary.Choice("← Cancel", value=_CANCEL)` at the end. If `.ask()` returns `None` or `_CANCEL`, return.

5. Prompt for the output directory:

   ```python
   export_dir = questionary.path(
       "Export directory:", default=str(DEFAULT_WORK_DIR)
   ).ask()
   if not export_dir:
       return
   ```

6. Construct the filename and write the JSON envelope:

   ```python
   sanitized = re.sub(r"[^\w\-]", "-", snap.name)
   filename = f"{tenant.name}-{product}-{sanitized}.json"
   full_path = os.path.join(export_dir, filename)

   envelope = {
       "product": product,
       "tenant_name": tenant.name,
       "snapshot_name": snap.name,
       "comment": snap.comment or "",
       "created_at": snap.created_at.isoformat() + "Z",
       "resource_count": snap.resource_count,
       "resources": snap.snapshot["resources"],
   }

   os.makedirs(export_dir, exist_ok=True)
   with open(full_path, "w", encoding="utf-8") as f:
       json.dump(envelope, f, indent=2)

   console.print(f"[green]Exported to {full_path}[/green]")
   questionary.press_any_key_to_continue("Press any key to continue...").ask()
   ```

The envelope structure is identical to what `_export_snapshot()` produced in zs-config, ensuring files written by the plugin are consumable by the plugin's apply flow.

#### 4e-ii. Apply Baseline from JSON flow

```python
def _apply_baseline() -> None:
    ...
```

Step-by-step implementation:

1. Call `select_tenant()` from `cli.menus` to choose the **target** tenant. If it returns `None`, return.

   ```python
   from cli.menus import select_tenant
   tenant = select_tenant()
   if tenant is None:
       return
   ```

2. Prompt for the JSON file path:

   ```python
   path = questionary.path(
       "Path to baseline JSON file:", default=str(DEFAULT_WORK_DIR)
   ).ask()
   if not path:
       return
   baseline_path = path.strip()
   ```

3. Load the file. On any error, print the error and return:

   ```python
   try:
       with open(baseline_path) as fh:
           baseline = json.load(fh)
   except Exception as e:
       console.print(f"[red]Could not read file: {e}[/red]")
       questionary.press_any_key_to_continue("Press any key to continue...").ask()
       return
   ```

4. Obtain a ZIA client for the selected tenant using the existing helper in zs-config:

   ```python
   from cli.menus import get_zia_client
   client, zia_tenant = get_zia_client()
   ```

   Note: `get_zia_client()` acquires the currently active tenant's client. If the `tenant` selected in step 1 differs from the currently active session tenant, the Coder must determine whether `get_zia_client()` accepts a tenant argument or whether `select_tenant()` should be skipped and the active-session tenant used instead. Consult `cli/menus/__init__.py` to resolve this. The invariant is: the client and the target tenant must be for the same tenant; they must not be mismatched.

5. Call `apply_baseline_menu` with the populated `baseline` and `baseline_path`:

   ```python
   from cli.menus.zia_menu import apply_baseline_menu
   apply_baseline_menu(client, zia_tenant, baseline=baseline, baseline_path=baseline_path)
   ```

   This bypasses the (now-removed) file-loading branch entirely and enters the push flow directly, exactly as palo-tools does.

### 4f. `manifest.json` Addition

Add a second entry to the `"plugins"` array in `/Users/mike/Documents/CodeProjects/zs-plugins/manifest.json`:

```json
{
  "name": "zia-snapshot-tools",
  "display_name": "ZIA Snapshot Tools",
  "description": "Export ZIA snapshots to JSON and apply baseline files to live tenants",
  "package": "zia-snapshot-tools",
  "version": "0.1.0",
  "install_url": "git+ssh://git@github.com/mpreissner/zs-plugins.git#subdirectory=zia-snapshot-tools",
  "install_url_dev": "git+ssh://git@github.com/mpreissner/zs-plugins.git@dev#subdirectory=zia-snapshot-tools"
}
```

---

## 5. Cross-Tenant Snapshot Flow in zs-config (Baseline Dict Construction)

The baseline dict is constructed in the ZIA menu dispatch branch immediately after `_pick_cross_tenant_snapshot` returns a non-None pair:

| Key | Value | Notes |
|---|---|---|
| `product` | `"ZIA"` | Hardcoded — only ZIA snapshots are offered by this picker |
| `tenant_name` | `source_tenant.name` | Source tenant's display name |
| `snapshot_name` | `snap.name` | Timestamp string used as the snapshot name |
| `comment` | `snap.comment or ""` | Empty string if no comment |
| `created_at` | `snap.created_at.isoformat() + "Z"` | UTC ISO-8601 with Z suffix |
| `resource_count` | `snap.resource_count` | Integer |
| `resources` | `snap.snapshot["resources"]` | Direct reference to the parsed JSON dict — no copy needed |

`baseline_path` is set to `f"{source_tenant.name}/{snap.name}"`. This string is passed as the `Baseline:` label in `_write_push_log` output. It is safe to log (contains no secrets).

---

## 6. Picker UX

### Tenant picker (cross-tenant flow in zs-config)

- Prompt text: `"Select source tenant:"`
- Choices: one entry per active tenant excluding `current_tenant` (filtered by `.id`), plus `"← Cancel"` appended last
- Choice label: `tenant.name` — plain text, no Rich markup
- `use_indicator=True`

### Snapshot picker (cross-tenant flow in zs-config and plugin export flow)

- Prompt text: `f"Select snapshot from {source_tenant.name}:"` (cross-tenant) or `"Select snapshot:"` (plugin export)
- Choices sorted newest-first (already returned that way by `list_snapshots`)
- Choice label format (all plain text):

  ```
  {snap.name}  [{local_ts}]  {snap.resource_count} resources{comment_suffix}
  ```

  - `local_ts` = `snap.created_at.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")`
  - `comment_suffix` = `f"  {snap.comment}"` if `snap.comment` else `""`

- `use_indicator=True`
- Cancel choice appended last

---

## 7. Edge Cases

| Condition | Path | Handling |
|---|---|---|
| No other tenants configured | zs-config cross-tenant picker | After filtering by ID, list is empty: print yellow message, return `(None, None)`, menu handler does nothing |
| Source tenant has no ZIA snapshots | zs-config cross-tenant picker | `list_snapshots` returns `[]`: print yellow message, return `(None, None)` |
| Source tenant has only ZPA snapshots | zs-config cross-tenant picker | `list_snapshots(id, "ZIA", session)` already filters by product; same empty-list path |
| User cancels tenant picker (Ctrl+C or "← Cancel") | zs-config cross-tenant picker | `questionary` returns `None` or `_CANCEL` sentinel; return `(None, None)` |
| User cancels snapshot picker (Ctrl+C or "← Cancel") | Both | Same sentinel/None handling; return `(None, None)` or `None` |
| `snap.snapshot["resources"]` is missing or malformed | zs-config cross-tenant, plugin apply | Existing `if not resources:` guard in `apply_baseline_menu` catches this; no new handling needed |
| `baseline_path` in push log (cross-tenant) | zs-config | Log shows e.g. `Baseline: TenantA/2025-11-04 14:30:00` — readable; contains no secrets |
| `baseline_path` in push log (plugin apply-from-file) | Plugin | Log shows the filesystem path the user provided — no secrets |
| `apply_baseline_menu` called with `baseline=None` (accidental bare call) | zs-config | Immediately returns; no crash, no prompt |
| Plugin export: no snapshots for chosen tenant/product | Plugin | Yellow message, press-any-key pause, return |
| Plugin apply: file not found or invalid JSON | Plugin | Red error message, press-any-key pause, return |
| Plugin apply: target tenant mismatched with active session | Plugin | Coder resolves via `cli/menus/__init__.py` inspection; client and tenant must be for the same tenant |
| `_export_snapshot` called from outside the menu (internal use) | N/A | Function is removed entirely; any future internal need must import from the plugin or re-implement |

---

## 8. Files Changed

### zs-config (`feature/cross-tenant-snapshot`)

| File | Change |
|---|---|
| `cli/menus/snapshots_menu.py` | Remove `_export_snapshot()` function and "Export Snapshot to JSON" menu entry |
| `cli/menus/zia_menu.py` | Remove "Apply Baseline from JSON" menu item; replace file-loading branch with early return guard; add `_CANCEL` sentinel; add `_pick_cross_tenant_snapshot()` helper; add "Apply Snapshot from Another Tenant" menu entry and dispatch |

### zs-plugins (`feature/zia-snapshot-tools`)

| File | Change |
|---|---|
| `manifest.json` | Add `zia-snapshot-tools` plugin entry |
| `zia-snapshot-tools/pyproject.toml` | New file |
| `zia-snapshot-tools/zia_snapshot_tools/__init__.py` | New empty file |
| `zia-snapshot-tools/zia_snapshot_tools/plugin.py` | New file |
| `zia-snapshot-tools/zia_snapshot_tools/menu.py` | New file |

---

## 9. Non-Negotiable Constraints

### Secrets

`client_secret` must never appear in logs, audit entries, or any rendered output. Neither the cross-tenant path nor the plugin touches credentials. The cross-tenant flow reads only `RestorePoint` rows (which contain no secrets) and the tenant's display name. The plugin reads a JSON file containing snapshot data only. `tenant_name` and `baseline_path` are safe to log. Constraint is satisfied by design in both repos.

### SQLite write-lock

`_pick_cross_tenant_snapshot` in zs-config opens exactly one `with get_session() as session:` block to call `list_snapshots`. It does not call `audit_service.log()` or any other session-opening function inside that block. The plugin's `_export_snapshot` similarly opens exactly one session block for `list_snapshots` and closes it before any further operations. No nested sessions are introduced anywhere in this feature.

### questionary plain text

All `questionary.Choice` labels in every picker — tenant picker, snapshot picker, product picker, menu entries — must be plain strings. No Rich markup (`[bold]`, `[green]`, `[dim]`, etc.) anywhere in a `Choice` title or `questionary.select`/`questionary.path` prompt string. This applies to both the zs-config changes and the plugin.

### ZIA activation

The cross-tenant path feeds into the existing `apply_baseline_menu` push flow unchanged. `_zia_changed()` is called by the existing flow at the appropriate points. No additional activation calls are needed. The plugin's `_apply_baseline()` also routes through `apply_baseline_menu`, so activation is handled identically.
