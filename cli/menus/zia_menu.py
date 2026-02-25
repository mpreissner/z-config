import questionary
from rich.console import Console
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zia_client

console = Console()


def zia_menu():
    client, tenant = get_zia_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZIA",
            choices=[
                questionary.Choice("SSL Inspection", value="ssl"),
                questionary.Choice("Locations", value="locations"),
                questionary.Choice("Firewall Policy", value="firewall"),
                questionary.Choice("URL Lookup", value="url_lookup"),
                questionary.Separator(),
                questionary.Choice("Security Policy Settings  [coming soon]", value="noop"),
                questionary.Choice("URL Categories  [coming soon]", value="noop"),
                questionary.Choice("URL Filtering  [coming soon]", value="noop"),
                questionary.Choice("Traffic Forwarding  [coming soon]", value="noop"),
                questionary.Separator(),
                questionary.Choice("Activation", value="activation"),
                questionary.Choice("Import Config", value="import"),
                questionary.Choice("Reset N/A Resource Types", value="reset_na"),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "activation":
            activation_menu(client, tenant)
        elif choice == "url_lookup":
            _url_lookup(client, tenant)
        elif choice == "firewall":
            firewall_policy_menu(client, tenant)
        elif choice == "locations":
            locations_menu(client, tenant)
        elif choice == "ssl":
            ssl_inspection_menu(client, tenant)
        elif choice == "import":
            _import_zia_config(client, tenant)
        elif choice == "reset_na":
            _reset_zia_na_resources(client, tenant)
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Activation
# ------------------------------------------------------------------

def activation_menu(client, tenant):
    from services.zia_service import ZIAService
    service = ZIAService(client, tenant_id=tenant.id)
    while True:
        render_banner()
        with console.status("Checking activation status..."):
            try:
                status = service.get_activation_status()
            except Exception as e:
                console.print(f"[red]✗ Could not fetch status: {e}[/red]")
                return

        state = status.get("status", "UNKNOWN")
        state_colour = "green" if state == "ACTIVE" else "yellow"
        console.print(f"\nActivation status: [{state_colour}][bold]{state}[/bold][/{state_colour}]")

        choice = questionary.select(
            "Activation",
            choices=[
                questionary.Choice("Activate Pending Changes", value="activate"),
                questionary.Choice("Refresh Status", value="refresh"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "activate":
            _activate(client, tenant)
        elif choice == "refresh":
            continue
        elif choice in ("back", None):
            break


def _activate(client, tenant):
    confirmed = questionary.confirm(
        "Activate all pending ZIA configuration changes?", default=True
    ).ask()
    if not confirmed:
        return

    from services.zia_service import ZIAService

    service = ZIAService(client, tenant_id=tenant.id)
    with console.status("Activating..."):
        try:
            result = service.activate()
            state = result.get("status", "UNKNOWN") if result else "UNKNOWN"
            console.print(f"[green]✓ Activation complete — status: {state}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Activation failed: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# URL Lookup
# ------------------------------------------------------------------

def _url_lookup(client, tenant):
    from services.zia_service import ZIAService
    service = ZIAService(client, tenant_id=tenant.id)

    console.print("\n[bold]URL Category Lookup[/bold]")
    console.print("[dim]Enter URLs to look up (one per line, blank line to submit).[/dim]\n")

    urls = []
    while True:
        url = questionary.text("URL (blank to submit):").ask()
        if not url:
            break
        urls.append(url.strip())

    if not urls:
        return

    with console.status("Looking up URLs..."):
        try:
            results = service.url_lookup(urls)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return

    table = Table(title="URL Lookup Results", show_lines=False)
    table.add_column("URL")
    table.add_column("Category")

    for r in results:
        categories = ", ".join(r.get("urlClassifications", [])) or "[dim]Uncategorised[/dim]"
        table.add_row(r.get("url", ""), categories)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


# ------------------------------------------------------------------
# Import Config
# ------------------------------------------------------------------

def _import_zia_config(client, tenant):
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zia_import_service import ZIAImportService, RESOURCE_DEFINITIONS

    console.print("\n[bold]Import ZIA Config[/bold]")
    console.print(f"[dim]Fetching {len(RESOURCE_DEFINITIONS)} resource types from ZIA.[/dim]\n")

    confirmed = questionary.confirm("Start import?", default=True).ask()
    if not confirmed:
        return

    service = ZIAImportService(client, tenant_id=tenant.id)
    total = len(RESOURCE_DEFINITIONS)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Importing...", total=total)

        def on_progress(resource_type, done, _total):
            progress.update(task, completed=done, description=f"[cyan]{resource_type}[/cyan]")

        sync = service.run(progress_callback=on_progress)

    status_style = "green" if sync.status == "SUCCESS" else (
        "yellow" if sync.status == "PARTIAL" else "red"
    )
    console.print(f"\n[{status_style}]■ Sync {sync.status}[/{status_style}]")
    console.print(f"  Resources synced:  {sync.resources_synced}")
    console.print(f"  Records updated:   {sync.resources_updated}")
    console.print(f"  Marked deleted:    {sync.resources_deleted}")
    skipped = (sync.details or {}).get("skipped_na", [])
    if skipped:
        console.print(f"\n[dim]N/A (not entitled):[/dim] {', '.join(skipped)}")
    if sync.error_message:
        console.print(f"\n[yellow]Warnings:[/yellow]\n{sync.error_message}")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _reset_zia_na_resources(client, tenant):
    from services.zia_import_service import ZIAImportService
    service = ZIAImportService(client, tenant_id=tenant.id)
    disabled = service._get_disabled_resource_types()
    if not disabled:
        console.print("[dim]No N/A resource types recorded for this tenant.[/dim]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
    console.print(f"\n[yellow]N/A resource types:[/yellow] {', '.join(disabled)}")
    confirmed = questionary.confirm(
        "Clear the N/A list? They will be retried on the next import.", default=False
    ).ask()
    if confirmed:
        service.clear_disabled_resource_types()
        console.print("[green]✓ N/A list cleared.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Firewall Policy
# ------------------------------------------------------------------

def firewall_policy_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Firewall Policy",
            choices=[
                questionary.Choice("List Firewall Rules", value="list_fw"),
                questionary.Choice("Search Firewall Rules", value="search_fw"),
                questionary.Choice("Enable / Disable Firewall Rules", value="toggle_fw"),
                questionary.Separator(),
                questionary.Choice("List DNS Filter Rules", value="list_dns"),
                questionary.Choice("Search DNS Filter Rules", value="search_dns"),
                questionary.Choice("Enable / Disable DNS Rules", value="toggle_dns"),
                questionary.Separator(),
                questionary.Choice("List IPS Rules", value="list_ips"),
                questionary.Choice("Search IPS Rules", value="search_ips"),
                questionary.Choice("Enable / Disable IPS Rules", value="toggle_ips"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list_fw":
            _list_firewall_rules(tenant)
        elif choice == "search_fw":
            _search_firewall_rules(tenant)
        elif choice == "toggle_fw":
            _toggle_firewall_rules(client, tenant)
        elif choice == "list_dns":
            _list_dns_rules(tenant)
        elif choice == "search_dns":
            _search_dns_rules(tenant)
        elif choice == "toggle_dns":
            _toggle_dns_rules(client, tenant)
        elif choice == "list_ips":
            _list_ips_rules(tenant)
        elif choice == "search_ips":
            _search_ips_rules(tenant)
        elif choice == "toggle_ips":
            _toggle_ips_rules(client, tenant)
        elif choice in ("back", None):
            break


def _list_firewall_rules(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No firewall rules in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"Firewall Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        description = str(cfg.get("description") or "")[:60]
        table.add_row(order, r["name"] or "—", action, state_str, description)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_firewall_rules(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_rule", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No firewall rules matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"Matching Firewall Rules ({len(rows)})", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        table.add_row(order, r["name"] or "—", action, state_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _toggle_firewall_rules(client, tenant):
    from db.database import get_session
    from db.models import ZIAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zia_id": r.zia_id,
                "state": (r.raw_config or {}).get("state", "UNKNOWN"),
            }
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No firewall rules in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        "Select rules to toggle:",
        choices=[
            questionary.Choice(
                f"{'✓' if r['state'] == 'ENABLED' else '✗'}  {r['name']}",
                value=r,
            )
            for r in rows
        ],
    ).ask()
    if not selected:
        return

    action = questionary.select(
        "Action:",
        choices=[
            questionary.Choice("Enable", value="ENABLED"),
            questionary.Choice("Disable", value="DISABLED"),
        ],
    ).ask()
    if not action:
        return

    verb = "Enable" if action == "ENABLED" else "Disable"
    confirmed = questionary.confirm(f"{verb} {len(selected)} rule(s)?", default=True).ask()
    if not confirmed:
        return

    ok = 0
    for r in selected:
        try:
            config = client.get_firewall_rule(r["zia_id"])
            config["state"] = action
            client.update_firewall_rule(r["zia_id"], config)
            _update_zia_resource_field(tenant.id, "firewall_rule", r["zia_id"], "state", action)
            audit_service.log(
                product="ZIA", operation="toggle_firewall_rule", action="UPDATE",
                status="SUCCESS", tenant_id=tenant.id, resource_type="firewall_rule",
                resource_id=r["zia_id"], resource_name=r["name"],
                details={"state": action},
            )
            ok += 1
        except Exception as e:
            console.print(f"[red]✗ {r['name']}: {e}[/red]")
            audit_service.log(
                product="ZIA", operation="toggle_firewall_rule", action="UPDATE",
                status="FAILURE", tenant_id=tenant.id, resource_type="firewall_rule",
                resource_id=r["zia_id"], resource_name=r["name"], error_message=str(e),
            )

    if ok:
        console.print(f"[green]✓ {ok} rule(s) updated. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _list_dns_rules(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_dns_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No DNS filter rules in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"DNS Filter Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        description = str(cfg.get("description") or "")[:60]
        table.add_row(order, r["name"] or "—", action, state_str, description)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_dns_rules(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_dns_rule", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No DNS filter rules matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"Matching DNS Filter Rules ({len(rows)})", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        table.add_row(order, r["name"] or "—", action, state_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _toggle_dns_rules(client, tenant):
    from db.database import get_session
    from db.models import ZIAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_dns_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zia_id": r.zia_id,
                "state": (r.raw_config or {}).get("state", "UNKNOWN"),
            }
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No DNS filter rules in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        "Select rules to toggle:",
        choices=[
            questionary.Choice(
                f"{'✓' if r['state'] == 'ENABLED' else '✗'}  {r['name']}",
                value=r,
            )
            for r in rows
        ],
    ).ask()
    if not selected:
        return

    action = questionary.select(
        "Action:",
        choices=[
            questionary.Choice("Enable", value="ENABLED"),
            questionary.Choice("Disable", value="DISABLED"),
        ],
    ).ask()
    if not action:
        return

    verb = "Enable" if action == "ENABLED" else "Disable"
    confirmed = questionary.confirm(f"{verb} {len(selected)} rule(s)?", default=True).ask()
    if not confirmed:
        return

    ok = 0
    for r in selected:
        try:
            config = client.get_firewall_dns_rule(r["zia_id"])
            config["state"] = action
            client.update_firewall_dns_rule(r["zia_id"], config)
            _update_zia_resource_field(tenant.id, "firewall_dns_rule", r["zia_id"], "state", action)
            audit_service.log(
                product="ZIA", operation="toggle_dns_rule", action="UPDATE",
                status="SUCCESS", tenant_id=tenant.id, resource_type="firewall_dns_rule",
                resource_id=r["zia_id"], resource_name=r["name"],
                details={"state": action},
            )
            ok += 1
        except Exception as e:
            console.print(f"[red]✗ {r['name']}: {e}[/red]")
            audit_service.log(
                product="ZIA", operation="toggle_dns_rule", action="UPDATE",
                status="FAILURE", tenant_id=tenant.id, resource_type="firewall_dns_rule",
                resource_id=r["zia_id"], resource_name=r["name"], error_message=str(e),
            )

    if ok:
        console.print(f"[green]✓ {ok} rule(s) updated. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _list_ips_rules(tenant):
    if _is_zia_resource_na(tenant.id, "firewall_ips_rule"):
        console.print(
            "[yellow]Cloud Firewall IPS is not available for this tenant "
            "(subscription required).[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_ips_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No IPS rules in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"IPS Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        description = str(cfg.get("description") or "")[:60]
        table.add_row(order, r["name"] or "—", action, state_str, description)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_ips_rules(tenant):
    if _is_zia_resource_na(tenant.id, "firewall_ips_rule"):
        console.print(
            "[yellow]Cloud Firewall IPS is not available for this tenant "
            "(subscription required).[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    from db.database import get_session
    from db.models import ZIAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_ips_rule", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No IPS rules matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"Matching IPS Rules ({len(rows)})", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        table.add_row(order, r["name"] or "—", action, state_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _toggle_ips_rules(client, tenant):
    if _is_zia_resource_na(tenant.id, "firewall_ips_rule"):
        console.print(
            "[yellow]Cloud Firewall IPS is not available for this tenant "
            "(subscription required).[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print("[yellow]No IPS rules available to toggle.[/yellow]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Locations
# ------------------------------------------------------------------

def locations_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Locations",
            choices=[
                questionary.Choice("List Locations", value="list"),
                questionary.Choice("Search Locations", value="search"),
                questionary.Choice("List Location Groups", value="list_groups"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_locations(tenant)
        elif choice == "search":
            _search_locations(tenant)
        elif choice == "list_groups":
            _list_location_groups(tenant)
        elif choice in ("back", None):
            break


def _list_locations(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="location", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No locations in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Locations ({len(rows)} total)", show_lines=False)
    table.add_column("Name")
    table.add_column("Country")
    table.add_column("Timezone")
    table.add_column("Sub-location")
    table.add_column("VPN")

    for r in rows:
        cfg = r["raw_config"]
        country = cfg.get("country") or "—"
        tz = cfg.get("tz") or "—"
        is_sub = "[dim]Yes[/dim]" if cfg.get("parent_id") else "No"
        has_vpn = "[green]Yes[/green]" if cfg.get("vpn_credentials") else "No"
        table.add_row(r["name"] or "—", country, tz, is_sub, has_vpn)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_locations(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="location", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No locations matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Matching Locations ({len(rows)})", show_lines=False)
    table.add_column("Name")
    table.add_column("Country")
    table.add_column("Timezone")
    table.add_column("Sub-location")
    table.add_column("VPN")

    for r in rows:
        cfg = r["raw_config"]
        country = cfg.get("country") or "—"
        tz = cfg.get("tz") or "—"
        is_sub = "[dim]Yes[/dim]" if cfg.get("parent_id") else "No"
        has_vpn = "[green]Yes[/green]" if cfg.get("vpn_credentials") else "No"
        table.add_row(r["name"] or "—", country, tz, is_sub, has_vpn)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _list_location_groups(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="location_group", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No location groups in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Location Groups ({len(rows)} total)", show_lines=False)
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Locations", justify="right")

    for r in rows:
        cfg = r["raw_config"]
        group_type = cfg.get("group_type") or cfg.get("groupType") or "—"
        loc_count = str(len(cfg.get("locations", [])))
        table.add_row(r["name"] or "—", group_type, loc_count)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


# ------------------------------------------------------------------
# SSL Inspection
# ------------------------------------------------------------------

def ssl_inspection_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "SSL Inspection",
            choices=[
                questionary.Choice("List Rules", value="list"),
                questionary.Choice("Search Rules", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_ssl_rules(tenant)
        elif choice == "search":
            _search_ssl_rules(tenant)
        elif choice in ("back", None):
            break


def _list_ssl_rules(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ssl_inspection_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No SSL Inspection rules in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"SSL Inspection Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        description = str(cfg.get("description") or "")[:60]
        table.add_row(order, r["name"] or "—", action, state_str, description)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_ssl_rules(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ssl_inspection_rule", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No SSL rules matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"Matching SSL Rules ({len(rows)})", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action_val = cfg.get("action")
        action = (action_val.get("type") if isinstance(action_val, dict) else action_val) or "—"
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        table.add_row(order, r["name"] or "—", action, state_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


# ------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------

def _is_zia_resource_na(tenant_id: int, resource_type: str) -> bool:
    from db.database import get_session
    from db.models import TenantConfig
    with get_session() as session:
        cfg = session.get(TenantConfig, tenant_id)
        return resource_type in list(cfg.zia_disabled_resources or []) if cfg else False


def _update_zia_resource_field(tenant_id: int, resource_type: str, zia_id: str,
                                field: str, value) -> None:
    from db.database import get_session
    from db.models import ZIAResource
    from sqlalchemy.orm.attributes import flag_modified

    with get_session() as session:
        rec = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type=resource_type, zia_id=zia_id)
            .first()
        )
        if rec:
            cfg = dict(rec.raw_config or {})
            cfg[field] = value
            rec.raw_config = cfg
            flag_modified(rec, "raw_config")
