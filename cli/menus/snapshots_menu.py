"""Config Snapshots menu.

Allows users to save, list, compare, export, and delete point-in-time
snapshots of a tenant's ZPA or ZIA configuration.
"""

import json
import os
import re
from datetime import datetime, timezone

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.banner import capture_banner, render_banner
from cli.scroll_view import render_rich_to_lines, scroll_view
from db.database import get_session
from services import audit_service
from services.snapshot_service import (
    IGNORED_FIELDS,
    DiffResult,
    compute_diff,
    create_snapshot,
    delete_snapshot,
    get_snapshot_data_current,
    list_snapshots,
)

console = Console()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def snapshots_menu(tenant, product: str) -> None:
    while True:
        render_banner()
        choice = questionary.select(
            f"Config Snapshots — {product}",
            choices=[
                questionary.Choice("Save Snapshot", value="save"),
                questionary.Choice("List Snapshots", value="list"),
                questionary.Choice("Compare Snapshot to Current DB", value="compare_current"),
                questionary.Choice("Compare Two Snapshots", value="compare_two"),
                questionary.Choice("Export Snapshot to JSON", value="export"),
                questionary.Choice("Delete Snapshot", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "save":
            _save_snapshot(tenant, product)
        elif choice == "list":
            _list_snapshots(tenant, product)
        elif choice == "compare_current":
            _compare_to_current(tenant, product)
        elif choice == "compare_two":
            _compare_two_snapshots(tenant, product)
        elif choice == "export":
            _export_snapshot(tenant, product)
        elif choice == "delete":
            _delete_snapshot(tenant, product)
        elif choice in ("back", None):
            break


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _save_snapshot(tenant, product: str) -> None:
    name = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    comment = questionary.text("Comment (optional — press Enter to skip):").ask()
    if comment is None:  # Ctrl+C
        return

    with console.status("Capturing snapshot..."):
        with get_session() as session:
            snap = create_snapshot(
                tenant_id=tenant.id,
                product=product,
                name=name,
                comment=comment.strip() or None,
                session=session,
            )
            resource_count = snap.resource_count

    audit_service.log(
        product=product,
        operation="save_snapshot",
        action="CREATE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_name=name,
        details={"comment": comment.strip() or None, "resource_count": resource_count},
    )
    console.print(f"[green]✓ Snapshot saved: {name}  ({resource_count} resources)[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _list_snapshots(tenant, product: str) -> None:
    with get_session() as session:
        snapshots = list_snapshots(tenant.id, product, session)

    if not snapshots:
        console.print("[yellow]No snapshots found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"{product} Snapshots — {len(snapshots)} total", show_lines=False)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Comment")
    table.add_column("Resources", justify="right")
    table.add_column("Created", style="dim")

    for i, snap in enumerate(snapshots, 1):
        ts = snap.created_at.replace(tzinfo=timezone.utc).astimezone()
        table.add_row(
            str(i),
            snap.name,
            snap.comment or "[dim]—[/dim]",
            str(snap.resource_count),
            ts.strftime("%Y-%m-%d %H:%M:%S"),
        )

    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _compare_to_current(tenant, product: str) -> None:
    snap = _pick_snapshot(tenant, product)
    if snap is None:
        return

    view_mode = questionary.select(
        "View diff as:",
        choices=[
            questionary.Choice("Field-level summary", value="field"),
            questionary.Choice("Full JSON diff", value="json"),
        ],
    ).ask()
    if view_mode is None:
        return

    with console.status("Building diff..."):
        with get_session() as session:
            current_dict = get_snapshot_data_current(tenant.id, product, session)
        diff = compute_diff(snap.snapshot["resources"], current_dict)

    if diff.is_empty:
        console.print("[green]No differences — current DB matches this snapshot.[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    lines = _render_diff(diff, view_mode, label_a=snap.name, label_b="Current DB")
    scroll_view(lines, header_ansi=capture_banner())


def _compare_two_snapshots(tenant, product: str) -> None:
    with get_session() as session:
        snaps = list_snapshots(tenant.id, product, session)

    if len(snaps) < 2:
        console.print("[yellow]Need at least 2 snapshots to compare.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    snap_a = _pick_snapshot_from_list(snaps, prompt="Base snapshot (A):")
    if snap_a is None:
        return

    snap_b = _pick_snapshot_from_list(snaps, prompt="Compare to (B):")
    if snap_b is None:
        return

    view_mode = questionary.select(
        "View diff as:",
        choices=[
            questionary.Choice("Field-level summary", value="field"),
            questionary.Choice("Full JSON diff", value="json"),
        ],
    ).ask()
    if view_mode is None:
        return

    with console.status("Building diff..."):
        diff = compute_diff(snap_a.snapshot["resources"], snap_b.snapshot["resources"])

    if diff.is_empty:
        console.print("[green]Snapshots are identical.[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    lines = _render_diff(diff, view_mode, label_a=snap_a.name, label_b=snap_b.name)
    scroll_view(lines, header_ansi=capture_banner())


def _export_snapshot(tenant, product: str) -> None:
    snap = _pick_snapshot(tenant, product)
    if snap is None:
        return

    export_dir = questionary.path("Export directory:", default=os.getcwd()).ask()
    if not export_dir:
        return

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

    console.print(f"[green]✓ Exported to {full_path}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_snapshot(tenant, product: str) -> None:
    snap = _pick_snapshot(tenant, product)
    if snap is None:
        return

    confirmed = questionary.confirm(
        f"Delete snapshot '{snap.name}'? This cannot be undone.", default=False
    ).ask()
    if not confirmed:
        return

    with get_session() as session:
        delete_snapshot(snap.id, session)

    console.print("[green]✓ Snapshot deleted.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pick_snapshot(tenant, product: str):
    """Fetch snapshots and show a picker. Returns selected RestorePoint or None."""
    with get_session() as session:
        snaps = list_snapshots(tenant.id, product, session)
    if not snaps:
        console.print("[yellow]No snapshots found.[/yellow]")
        return None
    return _pick_snapshot_from_list(snaps)


def _pick_snapshot_from_list(snaps, prompt: str = "Select snapshot:"):
    """Pick from a pre-fetched list of snapshots. Returns selected RestorePoint or None."""
    choices = []
    for snap in snaps:
        ts = snap.created_at.replace(tzinfo=timezone.utc).astimezone()
        comment_part = f"  {snap.comment}" if snap.comment else ""
        label = (
            f"{snap.name}{comment_part}"
            f"  ({snap.resource_count} resources)"
            f"  [{ts.strftime('%Y-%m-%d %H:%M:%S')}]"
        )
        choices.append(questionary.Choice(label, value=snap))
    choices.append(questionary.Choice("← Cancel", value=None))
    return questionary.select(prompt, choices=choices).ask()


# ---------------------------------------------------------------------------
# Diff rendering
# ---------------------------------------------------------------------------

def _fmt_value(v) -> str:
    """Format a config value for compact display."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        if len(v) > 2:
            return f"[{len(v)} items]"
        return str(v)
    s = str(v)
    return s[:37] + "..." if len(s) > 40 else s


def _safe_json(v) -> str:
    """JSON-encode a value, falling back to repr for non-serialisable types."""
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return repr(v)


def _render_diff(diff: DiffResult, view_mode: str, label_a: str, label_b: str):
    """Render diff result to a list of ANSI strings suitable for scroll_view."""
    lines = []

    # Header
    header = Panel(
        Text(f"DIFF: {label_a}  →  {label_b}", style="bold"),
        border_style="cyan",
    )
    lines.extend(render_rich_to_lines(header))

    # Summary table
    summary = Table(title="Summary", show_lines=False)
    summary.add_column("Resource Type", style="bold")
    summary.add_column("Added", style="green", justify="right")
    summary.add_column("Removed", style="red", justify="right")
    summary.add_column("Modified", style="yellow", justify="right")
    for rd in diff.resource_diffs:
        summary.add_row(
            rd.resource_type,
            str(len(rd.added)),
            str(len(rd.removed)),
            str(len(rd.modified)),
        )
    lines.extend(render_rich_to_lines(summary))

    # Added
    for rd in diff.resource_diffs:
        for item in rd.added:
            t = Text()
            t.append(f"+ [{rd.resource_type}]  {item.get('name') or item['id']}", style="green")
            lines.extend(render_rich_to_lines(t))

    # Removed
    for rd in diff.resource_diffs:
        for item in rd.removed:
            t = Text()
            t.append(f"- [{rd.resource_type}]  {item.get('name') or item['id']}", style="red")
            lines.extend(render_rich_to_lines(t))

    # Modified
    for rd in diff.resource_diffs:
        if not rd.modified:
            continue

        if view_mode == "field":
            mod_table = Table(title=f"Modified: {rd.resource_type}", show_lines=True)
            mod_table.add_column("Resource", style="bold")
            mod_table.add_column("Field")
            mod_table.add_column(f"{label_a[:20]}  →  {label_b[:20]}")
            for item in rd.modified:
                for fc in item["field_changes"]:
                    mod_table.add_row(
                        item.get("name") or item["id"],
                        fc.field,
                        f"{_fmt_value(fc.old)}  →  {_fmt_value(fc.new)}",
                    )
            lines.extend(render_rich_to_lines(mod_table))

        else:  # json mode
            for item in rd.modified:
                changed_keys = {fc.field for fc in item["field_changes"]}
                old_cfg = item["old_config"]
                new_cfg = item["new_config"]
                all_keys = sorted(set(old_cfg.keys()) | set(new_cfg.keys()))

                t = Text()
                t.append(
                    f"Modified [{rd.resource_type}]: {item.get('name') or item['id']}\n",
                    style="bold",
                )
                for key in all_keys:
                    if key in IGNORED_FIELDS:
                        continue
                    if key in changed_keys:
                        old_val = old_cfg.get(key)
                        new_val = new_cfg.get(key)
                        t.append(f'  - "{key}": {_safe_json(old_val)}\n', style="red")
                        t.append(f'  + "{key}": {_safe_json(new_val)}\n', style="green")
                    else:
                        val = old_cfg.get(key, new_cfg.get(key))
                        t.append(f'    "{key}": {_safe_json(val)}\n', style="dim")
                lines.extend(render_rich_to_lines(t))

    return lines
