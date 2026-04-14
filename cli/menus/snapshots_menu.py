"""Config Snapshots menu.

Allows users to save, list, compare, export, and delete point-in-time
snapshots of a tenant's ZPA or ZIA configuration.
"""

import json
import os
import re
from datetime import datetime, timezone

from lib.defaults import DEFAULT_WORK_DIR

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

# Sentinel for an explicit "← Cancel" choice in snapshot pickers.
# Distinguishes intentional cancellation from Ctrl+C (questionary returns None).
_CANCEL = object()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def snapshots_menu(tenant, product: str, client=None) -> None:
    while True:
        render_banner()
        choices = [
            questionary.Choice("Save Snapshot", value="save"),
            questionary.Choice("List Snapshots", value="list"),
            questionary.Choice("Compare Snapshot to Current DB", value="compare_current"),
            questionary.Choice("Compare Two Snapshots", value="compare_two"),
            questionary.Choice("Export Snapshot to JSON", value="export"),
        ]
        if product == "ZIA" and client is not None:
            choices.append(questionary.Choice("Restore Snapshot", value="restore"))
        choices += [
            questionary.Choice("Delete Snapshot", value="delete"),
            questionary.Separator(),
            questionary.Choice("← Back", value="back"),
        ]

        choice = questionary.select(
            f"Config Snapshots — {product}",
            choices=choices,
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
        elif choice == "restore":
            _restore_snapshot(tenant, client)
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

    export_dir = questionary.path("Export directory:", default=str(DEFAULT_WORK_DIR)).ask()
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


def _restore_snapshot(tenant, client) -> None:
    snap = _pick_snapshot(tenant, "ZIA")
    if snap is None:
        return
    restore_snapshot_menu(tenant, client, snap)


def restore_snapshot_menu(tenant, client, snap) -> None:
    """Full restore flow for a ZIA snapshot."""
    # Deferred imports — zia_menu imports snapshots_menu at module level.
    from cli.menus.zia_menu import _zia_changed
    from services.zia_push_service import ZIAPushService

    render_banner()
    console.print(f"\n[bold]Restore Snapshot — {snap.name}[/bold]")
    ts = snap.created_at.replace(tzinfo=timezone.utc).astimezone()
    console.print(f"  [dim]Created:[/dim]   {ts.strftime('%Y-%m-%d %H:%M:%S')}")
    console.print(f"  [dim]Resources:[/dim] {snap.resource_count}")
    if snap.comment:
        console.print(f"  [dim]Comment:[/dim]   {snap.comment}")
    console.print()

    service = ZIAPushService(client, tenant_id=tenant.id)
    baseline = {"product": "ZIA", "resources": snap.snapshot["resources"]}

    # Step 5: classify
    with console.status("[cyan]Classifying snapshot vs live state...[/cyan]") as status:
        def _progress(rtype, done, total):
            status.update(f"[cyan]Importing: {rtype} ({done}/{total})[/cyan]")

        dry_run = service.classify_baseline(baseline, import_progress_callback=_progress)
        delete_candidates = service.classify_snapshot_deletes(snap.snapshot["resources"])

    # Step 6: dry-run display
    _render_restore_dry_run(dry_run, delete_candidates, snap.name)

    # Step 7: nothing to do
    if (dry_run.create_count == 0
            and dry_run.update_count == 0
            and len(delete_candidates) == 0):
        console.print("[green]Nothing to restore — tenant already matches this snapshot.[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Step 8: single confirmation
    confirmed = questionary.confirm(
        f"Apply restore of snapshot '{snap.name}' to {tenant.name}?",
        default=False,
    ).ask()
    if not confirmed:
        return

    push_records: list = []
    verify1_result = None

    # Step 9: push creates + updates
    if dry_run.create_count > 0 or dry_run.update_count > 0:
        current_pass = [0]
        console.print()
        with console.status("[cyan]Pushing creates and updates...[/cyan]") as status:
            def _push_progress(pass_num, rtype, rec):
                if pass_num != current_pass[0]:
                    current_pass[0] = pass_num
                status.update(f"[cyan][Pass {pass_num}] {rtype} — {rec.name}[/cyan]")

            push_records = service.push_classified(dry_run, progress_callback=_push_progress)

        created  = sum(1 for r in push_records if r.is_created)
        updated  = sum(1 for r in push_records if r.is_updated)
        failed   = sum(1 for r in push_records if r.is_failed)
        console.print(f"  [green]Created:[/green]  {created}")
        console.print(f"  [cyan]Updated:[/cyan]  {updated}")
        if failed:
            console.print(f"  [red]Failed:[/red]   {failed}")

    # Step 10: verify pass 1 (creates/updates)
    if push_records:
        console.print()
        with console.status("[cyan]Verifying creates and updates...[/cyan]") as status:
            def _verify1_progress(rtype, done, total):
                status.update(f"[cyan]Verifying: {rtype} ({done}/{total})[/cyan]")
            try:
                verify1_result = service.verify_push(
                    baseline,
                    import_progress_callback=_verify1_progress,
                )
            except Exception as exc:
                console.print(f"[yellow]⚠ Verify pass 1 failed: {exc}[/yellow]")
                verify1_result = None

        if verify1_result is not None:
            v_creates, v_updates, v_deletes = verify1_result.changes_by_action()
            # Exclude resources already queued for deletion — they're expected to
            # still be present at this point since deletes haven't run yet.
            pending_deletes = {(r.resource_type, r.name) for r in delete_candidates}
            v_deletes = [(rtype, name) for rtype, name in v_deletes
                         if (rtype, name) not in pending_deletes]
            discrepancies = len(v_creates) + len(v_updates) + len(v_deletes)
            if discrepancies == 0:
                console.print("[green]✓ Creates/updates confirmed.[/green]")
            else:
                console.print(
                    f"[bold yellow]⚠ {discrepancies} discrepancy(ies) after push:[/bold yellow]"
                )
                disc_table = Table(show_lines=False)
                disc_table.add_column("Issue", style="yellow")
                disc_table.add_column("Resource Type")
                disc_table.add_column("Name")
                for rtype, name in v_creates:
                    disc_table.add_row("Not created", rtype, name)
                for rtype, name in v_updates:
                    disc_table.add_row("Config mismatch", rtype, name)
                for rtype, name in v_deletes:
                    disc_table.add_row("Not deleted", rtype, name)
                console.print(disc_table)

                remediate = questionary.confirm(
                    f"Attempt to remediate {discrepancies} discrepancy(ies)?", default=True
                ).ask()
                if remediate:
                    rem_pass = [0]
                    with console.status("[cyan]Remediating...[/cyan]") as status:
                        def _rem_progress(pass_num, rtype, rec):
                            if pass_num != rem_pass[0]:
                                rem_pass[0] = pass_num
                            status.update(f"[cyan][Pass {pass_num}] {rtype} — {rec.name}[/cyan]")
                        rem_records = service.push_classified(
                            verify1_result, progress_callback=_rem_progress
                        )
                    rem_created = sum(1 for r in rem_records if r.is_created)
                    rem_updated = sum(1 for r in rem_records if r.is_updated)
                    rem_failed  = sum(1 for r in rem_records if r.is_failed)
                    console.print(
                        f"  [green]Created:[/green] {rem_created}  "
                        f"[cyan]Updated:[/cyan] {rem_updated}  "
                        f"[red]Failed:[/red] {rem_failed}"
                    )
                    push_records = push_records + rem_records

    delete_records: list = []

    # Step 11: execute deletes
    if delete_candidates:
        console.print()
        with console.status("[red]Deleting resources absent from snapshot...[/red]") as status:
            def _del_progress(_, rtype, rec):
                status.update(f"[red]Deleting {rtype} — {rec.name}[/red]")

            delete_records = service.execute_deletes(
                delete_candidates, progress_callback=_del_progress
            )

        deleted_count   = sum(1 for r in delete_records if r.is_deleted)
        del_failed_count = sum(1 for r in delete_records if r.is_failed)
        console.print(f"  [red]Deleted:[/red]  {deleted_count}")
        if del_failed_count:
            console.print(f"  [red]Failed:[/red]   {del_failed_count}")

        # Activate deletions (mirrors apply_baseline wipe-first pattern)
        if deleted_count > 0:
            console.print()
            console.print("[dim]Activating deletions...[/dim]")
            try:
                client.activate()
            except Exception as e:
                console.print(f"[yellow]⚠ Activation after deletes failed: {e} — proceeding anyway[/yellow]")

    # Step 12: verify pass 2 (deletions)
    verify2_result: list = []
    if delete_candidates:
        console.print()
        with console.status("[cyan]Verifying deletions...[/cyan]") as status:
            def _verify2_progress(rtype, done, total):
                status.update(f"[cyan]Verifying deletions: {rtype} ({done}/{total})[/cyan]")
            try:
                verify2_result = service.verify_deleted(
                    delete_candidates,
                    import_progress_callback=_verify2_progress,
                )
            except Exception as exc:
                console.print(f"[yellow]⚠ Verify pass 2 failed: {exc}[/yellow]")
                verify2_result = []

        if verify2_result:
            console.print(
                f"[bold yellow]⚠ {len(verify2_result)} resource(s) still present after delete:[/bold yellow]"
            )
            still_table = Table(show_lines=False)
            still_table.add_column("Resource Type", style="yellow")
            still_table.add_column("Name")
            for r in verify2_result:
                still_table.add_row(r.resource_type, r.name)
            console.print(still_table)
        else:
            console.print("[green]✓ Deletions confirmed.[/green]")

    # Step 13: mark pending
    console.print()
    _zia_changed()

    # Step 14: write restore log
    log_path = _write_restore_log(
        snap, tenant, dry_run, delete_candidates,
        push_records, delete_records, verify1_result, verify2_result,
    )
    if log_path:
        console.print(f"[dim]Restore log: {log_path}[/dim]")

    # Step 15: offer activation
    console.print()
    activate_now = questionary.confirm(
        "Activate changes in ZIA now?", default=True
    ).ask()
    if activate_now:
        try:
            result = client.activate()
            state = result.get("status", "UNKNOWN") if result else "UNKNOWN"
            console.print(f"[green]✓ Activated — status: {state}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Activation failed: {e}[/red]")

    # Step 16: done
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


_MAX_DETAIL = 30


def _render_restore_dry_run(dry_run, delete_candidates, snap_name: str) -> None:
    """Print a unified dry-run summary for the restore flow.

    The Delete column is populated from delete_candidates (resources absent from
    the snapshot), not from dry_run.to_delete (which reflects cross-tenant logic).
    """
    from services.zia_push_service import PUSH_ORDER

    # Build per-type counts
    summary: dict = {}
    for r in dry_run.skipped:
        row = summary.setdefault(r.resource_type, {"create": 0, "update": 0, "delete": 0, "skip": 0})
        row["skip"] += 1
    for rtype, entries in dry_run.pending.items():
        row = summary.setdefault(rtype, {"create": 0, "update": 0, "delete": 0, "skip": 0})
        for e in entries:
            if e.get("__action") == "create":
                row["create"] += 1
            else:
                row["update"] += 1
    for r in delete_candidates:
        row = summary.setdefault(r.resource_type, {"create": 0, "update": 0, "delete": 0, "skip": 0})
        row["delete"] += 1

    console.print(f"\n[bold]Restore Dry Run — snapshot: '{snap_name}'[/bold]\n")

    if summary:
        tbl = Table(show_lines=False)
        tbl.add_column("Resource Type")
        tbl.add_column("Create",  justify="right", style="green")
        tbl.add_column("Update",  justify="right", style="cyan")
        tbl.add_column("Delete",  justify="right", style="red")
        tbl.add_column("Skip",    justify="right", style="dim")

        # Show types in a stable order (PUSH_ORDER first, then alphabetical remainders)
        ordered_types = [t for t in PUSH_ORDER if t in summary]
        ordered_types += sorted(k for k in summary if k not in ordered_types)

        for rtype in ordered_types:
            counts = summary[rtype]
            tbl.add_row(
                rtype,
                str(counts["create"]) if counts["create"] else "—",
                str(counts["update"]) if counts["update"] else "—",
                str(counts["delete"]) if counts["delete"] else "—",
                str(counts["skip"])   if counts["skip"]   else "—",
            )
        console.print(tbl)

    # Per-action detail lists
    creates_list  = [(rtype, e.get("__display_name") or e.get("name") or "?")
                     for rtype, entries in dry_run.pending.items()
                     for e in entries if e.get("__action") == "create"]
    updates_list  = [(rtype, e.get("__display_name") or e.get("name") or "?")
                     for rtype, entries in dry_run.pending.items()
                     for e in entries if e.get("__action") != "create"]
    deletes_list  = [(r.resource_type, r.name) for r in delete_candidates]

    if creates_list:
        console.print(f"\n[green]To create ({len(creates_list)}):[/green]")
        for rtype, name in creates_list[:_MAX_DETAIL]:
            console.print(f"  [dim]{rtype}:[/dim] {name}")
        if len(creates_list) > _MAX_DETAIL:
            console.print(f"  [dim]... and {len(creates_list) - _MAX_DETAIL} more[/dim]")

    if updates_list:
        console.print(f"\n[cyan]To update ({len(updates_list)}):[/cyan]")
        for rtype, name in updates_list[:_MAX_DETAIL]:
            console.print(f"  [dim]{rtype}:[/dim] {name}")
        if len(updates_list) > _MAX_DETAIL:
            console.print(f"  [dim]... and {len(updates_list) - _MAX_DETAIL} more[/dim]")

    if deletes_list:
        console.print(f"\n[red]To delete ({len(deletes_list)}):[/red]")
        for rtype, name in deletes_list[:_MAX_DETAIL]:
            console.print(f"  [dim]{rtype}:[/dim] {name}")
        if len(deletes_list) > _MAX_DETAIL:
            console.print(f"  [dim]... and {len(deletes_list) - _MAX_DETAIL} more[/dim]")

    total_creates = len(creates_list)
    total_updates = len(updates_list)
    total_deletes = len(deletes_list)
    total_skips   = sum(1 for r in dry_run.skipped)
    console.print(
        f"\n[dim]Total: {total_creates} create(s), {total_updates} update(s), "
        f"{total_deletes} delete(s), {total_skips} skip(s)[/dim]"
    )


def _write_restore_log(
    snap,
    tenant,
    dry_run,
    delete_candidates,
    push_records,
    delete_records,
    verify1,
    verify2,
):
    """Write a full restore log to the zs-config data directory.

    Returns the path written, or None if writing failed.
    """
    import platform
    from pathlib import Path

    try:
        from datetime import datetime, timezone as tz
        ts = datetime.now(tz.utc).strftime("%Y%m%d-%H%M%S")
        if platform.system() == "Windows":
            import os as _os
            log_dir = Path(_os.environ.get("APPDATA", Path.home())) / "zs-config" / "logs"
        else:
            log_dir = Path.home() / ".local" / "share" / "zs-config" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"zia-restore-{ts}.log"

        lines = []
        lines.append(f"ZIA Snapshot Restore Log — {datetime.now(tz.utc).isoformat()}")
        lines.append(f"Tenant   : {tenant.name} (id={tenant.id})")
        lines.append(f"Snapshot : {snap.name} (id={snap.id})")
        if snap.comment:
            lines.append(f"Comment  : {snap.comment}")
        lines.append("")

        lines.append("=== Dry-Run Classification ===")
        lines.append(f"  To create       : {dry_run.create_count}")
        lines.append(f"  To update       : {dry_run.update_count}")
        lines.append(f"  To delete       : {len(delete_candidates)}")
        lines.append(f"  Skipped         : {dry_run.skip_count}")
        lines.append("")

        # Push results
        created = sum(1 for r in push_records if r.is_created)
        updated = sum(1 for r in push_records if r.is_updated)
        failed  = sum(1 for r in push_records if r.is_failed)
        lines.append("=== Push Results (creates/updates) ===")
        lines.append(f"  Created : {created}")
        lines.append(f"  Updated : {updated}")
        lines.append(f"  Failed  : {failed}")
        lines.append("")

        if push_records:
            lines.append("=== Push Records ===")
            for r in push_records:
                lines.append(f"  [{r.status}] {r.resource_type} :: {r.name}")
            lines.append("")

        push_failures = [r for r in push_records if r.is_failed]
        if push_failures:
            lines.append("=== Push Failures (full detail) ===")
            for r in push_failures:
                lines.append(f"  {r.resource_type} :: {r.name}")
                lines.append(f"    {r.failure_reason}")
            lines.append("")

        # Delete results
        if delete_records:
            del_deleted = sum(1 for r in delete_records if r.is_deleted)
            del_failed  = sum(1 for r in delete_records if r.is_failed)
            lines.append("=== Delete Results ===")
            lines.append(f"  Deleted : {del_deleted}")
            lines.append(f"  Failed  : {del_failed}")
            lines.append("")
            lines.append("=== Delete Records ===")
            for r in delete_records:
                lines.append(f"  [{r.status}] {r.resource_type} :: {r.name}")
            lines.append("")

        # Verify pass 1
        if verify1 is not None:
            v_creates, v_updates, v_deletes = verify1.changes_by_action()
            disc = len(v_creates) + len(v_updates) + len(v_deletes)
            lines.append("=== Verify Pass 1 (creates/updates) ===")
            lines.append(f"  Discrepancies : {disc}")
            for rtype, name in v_creates:
                lines.append(f"  [not_created] {rtype} :: {name}")
            for rtype, name in v_updates:
                lines.append(f"  [config_mismatch] {rtype} :: {name}")
            for rtype, name in v_deletes:
                lines.append(f"  [not_deleted] {rtype} :: {name}")
            lines.append("")

        # Verify pass 2
        lines.append("=== Verify Pass 2 (deletions) ===")
        if verify2:
            lines.append(f"  Still present : {len(verify2)}")
            for r in verify2:
                lines.append(f"  [still_present] {r.resource_type} :: {r.name}")
        else:
            lines.append("  All deletions confirmed.")
        lines.append("")

        # Manual-action warnings
        warned = [r for r in push_records if r.warnings]
        if warned:
            lines.append("=== Manual Action Required ===")
            for r in warned:
                for w in r.warnings:
                    lines.append(f"  {r.resource_type} :: {r.name}")
                    lines.append(f"    {w}")
            lines.append("")

        log_file.write_text("\n".join(lines), encoding="utf-8")
        return str(log_file)
    except Exception:
        return None


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
    choices.append(questionary.Choice("← Cancel", value=_CANCEL))
    result = questionary.select(prompt, choices=choices).ask()
    return None if (result is None or result is _CANCEL) else result


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
