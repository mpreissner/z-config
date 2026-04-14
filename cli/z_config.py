#!/usr/bin/env python3
"""zs-config — interactive TUI for Zscaler OneAPI.

Installed usage:  zs-config
Development:      pip install -e .  then  zs-config
"""


def _run_data_migrations(console) -> None:
    """Run any pending startup data migrations with progress + summary.

    Each migration is a tuple of:
      (description, get_pending_fn, process_one_fn)
    where get_pending_fn() returns a list of items and process_one_fn(item)
    returns (success: bool, error: str | None).
    """
    import questionary
    from rich.panel import Panel
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from services.config_service import backfill_org_info_for_tenant, get_tenants_needing_org_backfill

    migrations = [
        (
            "Populating tenant org info & subscriptions",
            get_tenants_needing_org_backfill,
            lambda t: backfill_org_info_for_tenant(t),
            lambda t: t.name,  # label extractor
        ),
        # Future data migrations go here, same pattern:
        # ("Description", get_pending_fn, process_one_fn, label_fn),
    ]

    any_ran = False
    for description, get_pending, process_one, get_label in migrations:
        pending = get_pending()
        if not pending:
            continue

        any_ran = True
        console.print(f"\n[bold cyan]DB Migration:[/bold cyan] {description}...")

        results: list = []  # (label, success, error)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(description, total=len(pending))
            for item in pending:
                label = get_label(item)
                progress.update(task, description=f"[dim]{label}[/dim]")
                ok, err = process_one(item)
                results.append((label, ok, err))
                progress.advance(task)

        # Summary table
        succeeded = [(l, e) for l, ok, e in results if ok]
        failed = [(l, e) for l, ok, e in results if not ok]

        table = Table(show_header=True, show_lines=False, box=None, padding=(0, 2))
        table.add_column("Tenant")
        table.add_column("Result")
        table.add_column("Detail", style="dim")
        for label, _ in succeeded:
            table.add_row(label, "[green]✓ OK[/green]", "")
        for label, err in failed:
            table.add_row(label, "[red]✗ Failed[/red]", err or "")

        border = "green" if not failed else "yellow"
        title = "[bold green]Migration Complete[/bold green]" if not failed else "[bold yellow]Migration Complete (with errors)[/bold yellow]"
        console.print(Panel(table, title=title, border_style=border))

        if failed:
            console.print(
                "[yellow]Some tenants could not be updated — credentials may be invalid or expired.\n"
                "Use [bold]Settings → Edit Tenant[/bold] to correct credentials and retry.[/yellow]"
            )

        questionary.press_any_key_to_continue("Press any key to continue...").ask()


def main():
    import os
    from pathlib import Path

    # ── SSL: use the OS trust store so corporate inspection certs are trusted ──
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass  # not installed; requests falls back to certifi

    # ── SSL: honour a user-supplied CA bundle (drop a PEM at this path) ───────
    _ca_bundle = Path.home() / ".config" / "zs-config" / "ca-bundle.pem"
    if _ca_bundle.exists() and "REQUESTS_CA_BUNDLE" not in os.environ:
        os.environ["REQUESTS_CA_BUNDLE"] = str(_ca_bundle)

    # ── Ensure default working directory exists ────────────────────────────
    from lib.defaults import DEFAULT_WORK_DIR
    DEFAULT_WORK_DIR.mkdir(parents=True, exist_ok=True)

    from db.database import init_db
    from cli.banner import render_banner
    from cli.menus import select_tenant
    from cli.menus.main_menu import main_menu
    from cli.update_checker import check_for_updates, check_plugin_updates
    from rich.console import Console

    console = Console()

    init_db()
    render_banner()
    zs_update_found = check_for_updates()
    if not zs_update_found:
        check_plugin_updates()

    from services.config_service import list_tenants
    if list_tenants():
        _run_data_migrations(console)
        tenant = select_tenant()
        if tenant:
            import questionary
            from cli.menus.main_menu import verify_and_activate_tenant
            verify_and_activate_tenant(tenant)
            questionary.press_any_key_to_continue("Press any key to continue...").ask()

    main_menu()


if __name__ == "__main__":
    main()
