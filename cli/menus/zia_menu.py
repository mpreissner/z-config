import questionary
from rich.console import Console
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zia_client
from cli.menus.snapshots_menu import snapshots_menu

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
                questionary.Separator("── Web & URL Policy ──"),
                questionary.Choice("URL Filtering", value="url_filtering"),
                questionary.Choice("URL Categories", value="url_categories"),
                questionary.Choice("Security Policy Settings", value="security_policy"),
                questionary.Choice("URL Lookup", value="url_lookup"),
                questionary.Separator("── Network Security ──"),
                questionary.Choice("Firewall Policy", value="firewall"),
                questionary.Choice("SSL Inspection", value="ssl"),
                questionary.Choice("Traffic Forwarding", value="traffic_forwarding"),
                questionary.Separator("── Identity & Access ──"),
                questionary.Choice("Users", value="users"),
                questionary.Choice("Locations", value="locations"),
                questionary.Separator("── DLP ──"),
                questionary.Choice("DLP Engines", value="dlp_engines"),
                questionary.Choice("DLP Dictionaries", value="dlp_dictionaries"),
                questionary.Separator("── Cloud Apps ──"),
                questionary.Choice("Cloud Applications", value="cloud_applications"),
                questionary.Choice("Cloud App Control", value="cloud_app_control"),
                questionary.Separator(),
                questionary.Choice("Activation", value="activation"),
                questionary.Choice("Import Config", value="import"),
                questionary.Choice("Config Snapshots", value="snapshots"),
                questionary.Choice("Reset N/A Resource Types", value="reset_na"),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "url_filtering":
            url_filtering_menu(client, tenant)
        elif choice == "url_categories":
            url_categories_menu(client, tenant)
        elif choice == "security_policy":
            security_policy_menu(client, tenant)
        elif choice == "url_lookup":
            _url_lookup(client, tenant)
        elif choice == "firewall":
            firewall_policy_menu(client, tenant)
        elif choice == "ssl":
            ssl_inspection_menu(client, tenant)
        elif choice == "traffic_forwarding":
            traffic_forwarding_menu(tenant)
        elif choice == "users":
            zia_users_menu(tenant)
        elif choice == "locations":
            locations_menu(client, tenant)
        elif choice == "dlp_engines":
            dlp_engines_menu(client, tenant)
        elif choice == "dlp_dictionaries":
            dlp_dictionaries_menu(client, tenant)
        elif choice == "cloud_applications":
            cloud_applications_menu(client, tenant)
        elif choice == "cloud_app_control":
            cloud_app_control_menu(client, tenant)
        elif choice == "activation":
            activation_menu(client, tenant)
        elif choice == "import":
            _import_zia_config(client, tenant)
        elif choice == "snapshots":
            snapshots_menu(tenant, "ZIA")
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
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not results:
        console.print("[yellow]No categorisation results returned.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
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
                questionary.Choice("Enable / Disable", value="toggle"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_ssl_rules(tenant)
        elif choice == "search":
            _search_ssl_rules(tenant)
        elif choice == "toggle":
            _toggle_ssl_rules(client, tenant)
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
def _toggle_ssl_rules(client, tenant):
    from db.database import get_session
    from db.models import ZIAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ssl_inspection_rule", is_deleted=False)
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
        console.print("[yellow]No SSL inspection rules in local DB. Run Import Config first.[/yellow]")
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
            config = client.get_ssl_inspection_rule(r["zia_id"])
            config["state"] = action
            client.update_ssl_inspection_rule(r["zia_id"], config)
            _update_zia_resource_field(tenant.id, "ssl_inspection_rule", r["zia_id"], "state", action)
            audit_service.log(
                product="ZIA", operation="toggle_ssl_rule", action="UPDATE",
                status="SUCCESS", tenant_id=tenant.id, resource_type="ssl_inspection_rule",
                resource_id=r["zia_id"], resource_name=r["name"],
                details={"state": action},
            )
            ok += 1
        except Exception as e:
            console.print(f"[red]✗ {r['name']}: {e}[/red]")
            audit_service.log(
                product="ZIA", operation="toggle_ssl_rule", action="UPDATE",
                status="FAILURE", tenant_id=tenant.id, resource_type="ssl_inspection_rule",
                resource_id=r["zia_id"], resource_name=r["name"], error_message=str(e),
            )

    if ok:
        console.print(f"[green]✓ {ok} rule(s) updated. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


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


# ------------------------------------------------------------------
# Security Policy Settings (Allowlist / Denylist)
# ------------------------------------------------------------------

def security_policy_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Security Policy Settings",
            choices=[
                questionary.Choice("View Allowlist (Permitted URLs)", value="view_allow"),
                questionary.Choice("Add URLs to Allowlist", value="add_allow"),
                questionary.Choice("Remove URLs from Allowlist", value="rm_allow"),
                questionary.Separator(),
                questionary.Choice("View Denylist (Blocked URLs)", value="view_deny"),
                questionary.Choice("Add URLs to Denylist", value="add_deny"),
                questionary.Choice("Remove URLs from Denylist", value="rm_deny"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "view_allow":
            _view_url_list(client, "allowlist")
        elif choice == "add_allow":
            _add_urls_to_list(client, tenant, "allowlist")
        elif choice == "rm_allow":
            _remove_urls_from_list(client, tenant, "allowlist")
        elif choice == "view_deny":
            _view_url_list(client, "denylist")
        elif choice == "add_deny":
            _add_urls_to_list(client, tenant, "denylist")
        elif choice == "rm_deny":
            _remove_urls_from_list(client, tenant, "denylist")
        elif choice in ("back", None):
            break


def _view_url_list(client, list_type: str):
    label = "Allowlist" if list_type == "allowlist" else "Denylist"
    with console.status(f"Fetching {label}..."):
        try:
            data = client.get_allowlist() if list_type == "allowlist" else client.get_denylist()
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    url_key = "whitelistUrls" if list_type == "allowlist" else "blacklistUrls"
    urls = data.get(url_key) or data.get("urls") or []

    if not urls:
        console.print(f"[yellow]{label} is empty.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"{label} ({len(urls)} URLs)", show_lines=False)
    table.add_column("URL")
    for url in sorted(urls):
        table.add_row(url)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _add_urls_to_list(client, tenant, list_type: str):
    from services import audit_service
    label = "allowlist" if list_type == "allowlist" else "denylist"
    console.print(f"\n[bold]Add URLs to {label.title()}[/bold]")
    console.print("[dim]Enter one URL per line, blank line to submit.[/dim]\n")

    urls = []
    while True:
        url = questionary.text("URL (blank to finish):").ask()
        if not url:
            break
        urls.append(url.strip())

    if not urls:
        return

    confirmed = questionary.confirm(f"Add {len(urls)} URL(s) to {label}?", default=True).ask()
    if not confirmed:
        return

    with console.status(f"Adding to {label}..."):
        try:
            if list_type == "allowlist":
                client.add_to_allowlist(urls)
            else:
                client.add_to_denylist(urls)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    audit_service.log(
        product="ZIA", operation=f"add_to_{label}", action="UPDATE",
        status="SUCCESS", tenant_id=tenant.id,
        resource_type=label, details={"urls_added": urls},
    )
    console.print(f"[green]✓ {len(urls)} URL(s) added. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _remove_urls_from_list(client, tenant, list_type: str):
    from services import audit_service
    label = "allowlist" if list_type == "allowlist" else "denylist"

    with console.status(f"Fetching {label}..."):
        try:
            data = client.get_allowlist() if list_type == "allowlist" else client.get_denylist()
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    url_key = "whitelistUrls" if list_type == "allowlist" else "blacklistUrls"
    urls = sorted(data.get(url_key) or data.get("urls") or [])

    if not urls:
        console.print(f"[yellow]{label.title()} is empty.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        f"Select URLs to remove from {label}:",
        choices=[questionary.Choice(u, value=u) for u in urls],
    ).ask()

    if not selected:
        return

    confirmed = questionary.confirm(
        f"Remove {len(selected)} URL(s) from {label}?", default=False
    ).ask()
    if not confirmed:
        return

    with console.status(f"Removing from {label}..."):
        try:
            if list_type == "allowlist":
                client.remove_from_allowlist(selected)
            else:
                client.remove_from_denylist(selected)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    audit_service.log(
        product="ZIA", operation=f"remove_from_{label}", action="UPDATE",
        status="SUCCESS", tenant_id=tenant.id,
        resource_type=label, details={"urls_removed": selected},
    )
    console.print(f"[green]✓ {len(selected)} URL(s) removed. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# URL Categories
# ------------------------------------------------------------------

def url_categories_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "URL Categories",
            choices=[
                questionary.Choice("List Custom Categories", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("Add URLs to Category", value="add_urls"),
                questionary.Choice("Remove URLs from Category", value="rm_urls"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_url_categories(tenant)
        elif choice == "search":
            _search_url_categories(tenant)
        elif choice == "add_urls":
            _modify_category_urls(client, tenant, add=True)
        elif choice == "rm_urls":
            _modify_category_urls(client, tenant, add=False)
        elif choice in ("back", None):
            break


def _list_url_categories(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="url_category", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    # Only show custom categories (not Zscaler built-ins)
    rows = [r for r in rows if r["raw_config"].get("customCategory") or r["raw_config"].get("type") == "URL_CATEGORY"]

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No URL categories matching '{search}'.[/yellow]" if search
            else "[yellow]No custom URL categories in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Custom URL Categories ({len(rows)} found)", show_lines=False)
    table.add_column("Name")
    table.add_column("URLs", justify="right")
    table.add_column("ID", style="dim")

    for r in rows:
        cfg = r["raw_config"]
        url_count = len(cfg.get("urls") or [])
        table.add_row(r["name"] or "—", str(url_count), r["zia_id"])

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_url_categories(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_url_categories(tenant, search=search.strip())


def _modify_category_urls(client, tenant, add: bool):
    from db.database import get_session
    from db.models import ZIAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="url_category", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        cats = [
            {"name": r.name, "zia_id": r.zia_id}
            for r in resources
            if r.raw_config and (r.raw_config.get("customCategory") or r.raw_config.get("type") == "URL_CATEGORY")
        ]

    if not cats:
        console.print("[yellow]No custom URL categories in DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    cat = questionary.select(
        "Select category:",
        choices=[questionary.Choice(c["name"], value=c) for c in cats],
    ).ask()
    if not cat:
        return

    verb = "Add" if add else "Remove"
    console.print(f"\n[dim]Enter URLs to {verb.lower()} (one per line, blank to finish).[/dim]\n")

    urls = []
    while True:
        url = questionary.text("URL (blank to finish):").ask()
        if not url:
            break
        urls.append(url.strip())

    if not urls:
        return

    confirmed = questionary.confirm(
        f"{verb} {len(urls)} URL(s) {'to' if add else 'from'} '{cat['name']}'?", default=True
    ).ask()
    if not confirmed:
        return

    with console.status(f"Updating category..."):
        try:
            if add:
                client.add_urls_to_category(cat["zia_id"], urls)
            else:
                client.remove_urls_from_category(cat["zia_id"], urls)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    audit_service.log(
        product="ZIA", operation=f"{'add' if add else 'remove'}_category_urls", action="UPDATE",
        status="SUCCESS", tenant_id=tenant.id, resource_type="url_category",
        resource_id=cat["zia_id"], resource_name=cat["name"],
        details={"urls": urls},
    )
    console.print(f"[green]✓ {len(urls)} URL(s) {'added to' if add else 'removed from'} '{cat['name']}'. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# URL Filtering
# ------------------------------------------------------------------

def url_filtering_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "URL Filtering",
            choices=[
                questionary.Choice("List Rules", value="list"),
                questionary.Choice("Search Rules", value="search"),
                questionary.Choice("Enable / Disable Rules", value="toggle"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_url_filtering_rules(tenant)
        elif choice == "search":
            _search_url_filtering_rules(tenant)
        elif choice == "toggle":
            _toggle_url_filtering_rules(client, tenant)
        elif choice in ("back", None):
            break


def _list_url_filtering_rules(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="url_filtering_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No URL filtering rules matching '{search}'.[/yellow]" if search
            else "[yellow]No URL filtering rules in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)

    table = Table(title=f"URL Filtering Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        action = str(cfg.get("action") or "—")
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


def _search_url_filtering_rules(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_url_filtering_rules(tenant, search=search.strip())


def _toggle_url_filtering_rules(client, tenant):
    from db.database import get_session
    from db.models import ZIAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="url_filtering_rule", is_deleted=False)
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
        console.print("[yellow]No URL filtering rules in local DB. Run Import Config first.[/yellow]")
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
            config = client.get_url_filtering_rule(r["zia_id"])
            config["state"] = action
            client.update_url_filtering_rule(r["zia_id"], config)
            _update_zia_resource_field(tenant.id, "url_filtering_rule", r["zia_id"], "state", action)
            audit_service.log(
                product="ZIA", operation="toggle_url_filtering_rule", action="UPDATE",
                status="SUCCESS", tenant_id=tenant.id, resource_type="url_filtering_rule",
                resource_id=r["zia_id"], resource_name=r["name"],
                details={"state": action},
            )
            ok += 1
        except Exception as e:
            console.print(f"[red]✗ {r['name']}: {e}[/red]")
            audit_service.log(
                product="ZIA", operation="toggle_url_filtering_rule", action="UPDATE",
                status="FAILURE", tenant_id=tenant.id, resource_type="url_filtering_rule",
                resource_id=r["zia_id"], resource_name=r["name"], error_message=str(e),
            )

    if ok:
        console.print(f"[green]✓ {ok} rule(s) updated. Remember to activate changes.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Traffic Forwarding (read-only)
# ------------------------------------------------------------------

def traffic_forwarding_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Traffic Forwarding",
            choices=[
                questionary.Choice("List Forwarding Rules", value="list"),
                questionary.Choice("Search Rules", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_forwarding_rules(tenant)
        elif choice == "search":
            _search_forwarding_rules(tenant)
        elif choice in ("back", None):
            break


def _list_forwarding_rules(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="forwarding_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No forwarding rules matching '{search}'.[/yellow]" if search
            else "[yellow]No forwarding rules in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Forwarding Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        fwd_type = str(cfg.get("type") or cfg.get("forwardingMethod") or "—")
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        description = str(cfg.get("description") or "")[:60]
        table.add_row(r["name"] or "—", fwd_type, state_str, description)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_forwarding_rules(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_forwarding_rules(tenant, search=search.strip())


# ------------------------------------------------------------------
# ZIA Users
# ------------------------------------------------------------------

def zia_users_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Users",
            choices=[
                questionary.Choice("List Users", value="list"),
                questionary.Choice("Search by Name / Email", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_zia_users(tenant)
        elif choice == "search":
            _search_zia_users(tenant)
        elif choice in ("back", None):
            break


def _list_zia_users(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="user", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        search_lower = search.lower()
        rows = [
            r for r in rows
            if search_lower in (r["name"] or "").lower()
            or search_lower in (r["raw_config"].get("email") or "").lower()
        ]

    if not rows:
        msg = (
            f"[yellow]No users matching '{search}'.[/yellow]" if search
            else "[yellow]No users in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZIA Users ({len(rows)} found)", show_lines=False)
    table.add_column("Name")
    table.add_column("Email")
    table.add_column("Department")
    table.add_column("Groups")

    for r in rows:
        cfg = r["raw_config"]
        email = cfg.get("email") or "—"
        dept = (cfg.get("department") or {}).get("name") or "—"
        groups = ", ".join(
            g.get("name", "") for g in (cfg.get("groups") or [])
        )[:50] or "—"
        table.add_row(r["name"] or "—", email, dept, groups)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_zia_users(tenant):
    search = questionary.text("Search (name or email, partial):").ask()
    if not search:
        return
    _list_zia_users(tenant, search=search.strip())


# ------------------------------------------------------------------
# DLP — shared helpers
# ------------------------------------------------------------------

def _sync_dlp_resource(client, tenant, resource_type: str):
    """Re-sync a single DLP resource type from the API into the DB."""
    from services.zia_import_service import ZIAImportService
    service = ZIAImportService(client, tenant_id=tenant.id)
    service.run(resource_types=[resource_type])


def _view_raw_json(title: str, data: dict):
    """Display a dict as pretty-printed JSON in the scroll viewer."""
    import json
    from rich.syntax import Syntax
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    syntax = Syntax(json.dumps(data, indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


# ------------------------------------------------------------------
# DLP Engines
# ------------------------------------------------------------------

def dlp_engines_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "DLP Engines",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Choice("View Details", value="view"),
                questionary.Separator(),
                questionary.Choice("Create from JSON File", value="create"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_dlp_engines(tenant)
        elif choice == "search":
            _search_dlp_engines(tenant)
        elif choice == "view":
            _view_dlp_engine(tenant)
        elif choice == "create":
            _create_dlp_engine(client, tenant)
        elif choice == "edit":
            _edit_dlp_engine(client, tenant)
        elif choice == "delete":
            _delete_dlp_engine(client, tenant)
        elif choice in ("back", None):
            break


def _list_dlp_engines(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="dlp_engine", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}, "synced_at": r.synced_at}
            for r in resources
        ]
    rows.sort(key=lambda r: int(r["zia_id"]) if r["zia_id"].isdigit() else float("inf"))

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No DLP engines matching '{search}'.[/yellow]" if search
            else "[yellow]No DLP engines in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"DLP Engines ({len(rows)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Engine Expression (preview)")
    table.add_column("Last Synced", style="dim")

    for r in rows:
        cfg = r["raw_config"]
        expr = str(cfg.get("engineExpression") or cfg.get("description") or "")[:60]
        synced = r["synced_at"].strftime("%Y-%m-%d %H:%M") if r["synced_at"] else "—"
        table.add_row(r["zia_id"], r["name"] or "—", expr or "[dim]—[/dim]", synced)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_dlp_engines(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_dlp_engines(tenant, search=search.strip())


def _pick_dlp_engine(tenant):
    """Let the user pick a DLP engine from the DB. Returns raw_config dict or None."""
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="dlp_engine", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No DLP engines in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    chosen = questionary.select(
        "Select DLP engine:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ],
    ).ask()
    return chosen


def _view_dlp_engine(tenant):
    chosen = _pick_dlp_engine(tenant)
    if not chosen:
        return
    _view_raw_json(f"DLP Engine — {chosen['name']}", chosen["raw_config"])


def _create_dlp_engine(client, tenant):
    import json
    console.print("\n[bold]Create DLP Engine from JSON File[/bold]")
    path = questionary.text("Path to JSON file:").ask()
    if not path:
        return
    try:
        with open(path.strip()) as fh:
            config = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print(f"[dim]Creating engine: {config.get('name', '(unnamed)')}[/dim]")
    try:
        result = client.create_dlp_engine(config)
        console.print(f"[green]✓ Created DLP engine ID {result.get('id', '?')}.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_engine")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_dlp_engine(client, tenant):
    import json
    chosen = _pick_dlp_engine(tenant)
    if not chosen:
        return

    console.print("\n[bold]Current configuration:[/bold]")
    _view_raw_json(chosen["name"], chosen["raw_config"])

    console.print("\n[bold]Edit DLP Engine[/bold]")
    path = questionary.text("Path to JSON file with updated config:").ask()
    if not path:
        return
    try:
        with open(path.strip()) as fh:
            config = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    confirmed = questionary.confirm(
        f"Update engine '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return

    try:
        client.update_dlp_engine(chosen["zia_id"], config)
        console.print("[green]✓ DLP engine updated.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_engine")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_dlp_engine(client, tenant):
    chosen = _pick_dlp_engine(tenant)
    if not chosen:
        return

    confirmed = questionary.confirm(
        f"Delete engine '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return

    try:
        client.delete_dlp_engine(chosen["zia_id"])
        console.print("[green]✓ DLP engine deleted.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_engine")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# DLP Dictionaries
# ------------------------------------------------------------------

def dlp_dictionaries_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "DLP Dictionaries",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Choice("View Details", value="view"),
                questionary.Separator(),
                questionary.Choice("Create from JSON File", value="create_json"),
                questionary.Choice("Create from CSV File", value="create_csv"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Edit from CSV", value="edit_csv"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_dlp_dictionaries(tenant)
        elif choice == "search":
            _search_dlp_dictionaries(tenant)
        elif choice == "view":
            _view_dlp_dictionary(tenant)
        elif choice == "create_json":
            _create_dlp_dictionary_json(client, tenant)
        elif choice == "create_csv":
            _create_dlp_dictionary_csv(client, tenant)
        elif choice == "edit":
            _edit_dlp_dictionary(client, tenant)
        elif choice == "edit_csv":
            _edit_dlp_dictionary_csv(client, tenant)
        elif choice == "delete":
            _delete_dlp_dictionary(client, tenant)
        elif choice in ("back", None):
            break


def _list_dlp_dictionaries(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="dlp_dictionary", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}, "synced_at": r.synced_at}
            for r in resources
        ]
    rows.sort(key=lambda r: int(r["zia_id"]) if r["zia_id"].isdigit() else float("inf"))

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No DLP dictionaries matching '{search}'.[/yellow]" if search
            else "[yellow]No DLP dictionaries in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"DLP Dictionaries ({len(rows)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Entries")
    table.add_column("Last Synced", style="dim")

    for r in rows:
        cfg = r["raw_config"]
        dict_type = str(cfg.get("dictionaryType") or cfg.get("type") or "—")
        phrases = len(cfg.get("phrases") or [])
        patterns = len(cfg.get("patterns") or [])
        entries = f"phrases:{phrases} patterns:{patterns}" if (phrases or patterns) else "—"
        synced = r["synced_at"].strftime("%Y-%m-%d %H:%M") if r["synced_at"] else "—"
        table.add_row(r["zia_id"], r["name"] or "—", dict_type, entries, synced)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_dlp_dictionaries(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_dlp_dictionaries(tenant, search=search.strip())


def _pick_dlp_dictionary(tenant):
    """Let the user pick a DLP dictionary from the DB. Returns row dict or None."""
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="dlp_dictionary", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No DLP dictionaries in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    chosen = questionary.select(
        "Select DLP dictionary:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ],
    ).ask()
    return chosen


def _view_dlp_dictionary(tenant):
    chosen = _pick_dlp_dictionary(tenant)
    if not chosen:
        return
    _view_raw_json(f"DLP Dictionary — {chosen['name']}", chosen["raw_config"])


def _read_csv_entries(path: str) -> list:
    """Read a CSV file and return a list of value strings (one per row, skips header)."""
    import csv
    entries = []
    with open(path.strip()) as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return []
    # Skip header if first row contains a non-data header word
    first = rows[0][0].strip().lower() if rows[0] else ""
    start = 1 if first in ("value", "phrase", "pattern", "entry") else 0
    for row in rows[start:]:
        if row and row[0].strip():
            entries.append(row[0].strip())
    return entries


def _create_dlp_dictionary_json(client, tenant):
    import json
    console.print("\n[bold]Create DLP Dictionary from JSON File[/bold]")
    path = questionary.text("Path to JSON file:").ask()
    if not path:
        return
    try:
        with open(path.strip()) as fh:
            config = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print(f"[dim]Creating dictionary: {config.get('name', '(unnamed)')}[/dim]")
    try:
        result = client.create_dlp_dictionary(config)
        console.print(f"[green]✓ Created DLP dictionary ID {result.get('id', '?')}.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_dictionary")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _create_dlp_dictionary_csv(client, tenant):
    """Create a DLP dictionary from a CSV file of phrases/patterns."""
    console.print("\n[bold]Create DLP Dictionary from CSV File[/bold]")
    console.print("[dim]CSV format: one value per row (phrase or regex pattern). Optional header: value/phrase/pattern.[/dim]")

    name = questionary.text("Dictionary name:").ask()
    if not name:
        return

    dict_type = questionary.select(
        "Dictionary type:",
        choices=[
            questionary.Choice("Phrases", value="PATTERNS_AND_PHRASES"),
            questionary.Choice("Patterns (regex)", value="PATTERNS_AND_PHRASES"),
        ],
    ).ask()

    entry_type = questionary.select(
        "Entry type:",
        choices=[
            questionary.Choice("Phrases", value="phrases"),
            questionary.Choice("Patterns (regex)", value="patterns"),
        ],
    ).ask()

    path = questionary.text("Path to CSV file:").ask()
    if not path:
        return
    try:
        entries = _read_csv_entries(path)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    if not entries:
        console.print("[yellow]No entries found in CSV.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print(f"[dim]Found {len(entries)} entries.[/dim]")

    if entry_type == "phrases":
        payload = {
            "name": name,
            "dictionaryType": dict_type,
            "phrases": [{"action": "PHRASE_COUNT_TYPE_UNIQUE", "phrase": e} for e in entries],
        }
    else:
        payload = {
            "name": name,
            "dictionaryType": dict_type,
            "patterns": [{"action": "PATTERN_COUNT_TYPE_UNIQUE", "pattern": e} for e in entries],
        }

    try:
        result = client.create_dlp_dictionary(payload)
        console.print(f"[green]✓ Created DLP dictionary ID {result.get('id', '?')} with {len(entries)} entries.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_dictionary")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_dlp_dictionary(client, tenant):
    import json
    chosen = _pick_dlp_dictionary(tenant)
    if not chosen:
        return

    console.print("\n[bold]Current configuration:[/bold]")
    _view_raw_json(chosen["name"], chosen["raw_config"])

    console.print("\n[bold]Edit DLP Dictionary[/bold]")
    path = questionary.text("Path to JSON file with updated config:").ask()
    if not path:
        return
    try:
        with open(path.strip()) as fh:
            config = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    confirmed = questionary.confirm(
        f"Update dictionary '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return

    try:
        client.update_dlp_dictionary(chosen["zia_id"], config)
        console.print("[green]✓ DLP dictionary updated.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_dictionary")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_dlp_dictionary_csv(client, tenant):
    """Replace the phrase/pattern list in an existing DLP dictionary from a CSV."""
    chosen = _pick_dlp_dictionary(tenant)
    if not chosen:
        return

    cfg = chosen["raw_config"]
    console.print(f"\n[dim]Current: {len(cfg.get('phrases') or [])} phrases, {len(cfg.get('patterns') or [])} patterns[/dim]")

    entry_type = questionary.select(
        "Replace which entry type:",
        choices=[
            questionary.Choice("Phrases", value="phrases"),
            questionary.Choice("Patterns (regex)", value="patterns"),
        ],
    ).ask()

    path = questionary.text("Path to CSV file:").ask()
    if not path:
        return
    try:
        entries = _read_csv_entries(path)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    if not entries:
        console.print("[yellow]No entries found in CSV.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print(f"[dim]Found {len(entries)} entries. Will replace existing {entry_type}.[/dim]")
    confirmed = questionary.confirm(
        f"Update dictionary '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return

    updated_cfg = dict(cfg)
    if entry_type == "phrases":
        updated_cfg["phrases"] = [{"action": "PHRASE_COUNT_TYPE_UNIQUE", "phrase": e} for e in entries]
    else:
        updated_cfg["patterns"] = [{"action": "PATTERN_COUNT_TYPE_UNIQUE", "pattern": e} for e in entries]

    try:
        client.update_dlp_dictionary(chosen["zia_id"], updated_cfg)
        console.print(f"[green]✓ DLP dictionary updated with {len(entries)} {entry_type}.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_dictionary")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_dlp_dictionary(client, tenant):
    chosen = _pick_dlp_dictionary(tenant)
    if not chosen:
        return

    confirmed = questionary.confirm(
        f"Delete dictionary '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return

    try:
        client.delete_dlp_dictionary(chosen["zia_id"])
        console.print("[green]✓ DLP dictionary deleted.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        _sync_dlp_resource(client, tenant, "dlp_dictionary")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Cloud Applications
# ------------------------------------------------------------------

def cloud_applications_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Cloud Applications",
            choices=[
                questionary.Choice("List Policy Apps (DLP / CAC)", value="list_policy"),
                questionary.Choice("List SSL Policy Apps", value="list_ssl"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list_policy":
            _list_cloud_apps_db(tenant, resource_type="cloud_app_policy")
        elif choice == "list_ssl":
            _list_cloud_apps_db(tenant, resource_type="cloud_app_ssl_policy")
        elif choice == "search":
            _search_cloud_apps_db(tenant)
        elif choice in ("back", None):
            break


def _list_cloud_apps_db(tenant, resource_type: str, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    label = "SSL Policy Apps" if resource_type == "cloud_app_ssl_policy" else "Policy Apps"

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type=resource_type, is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        rows = [r for r in rows if search.lower() in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No {label} matching '{search}'.[/yellow]" if search
            else f"[yellow]No {label} in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"{label} ({len(rows)} total)", show_lines=False)
    table.add_column("App Name")
    table.add_column("Parent Category")
    table.add_column("ID", style="dim")

    for r in rows:
        cfg = r["raw_config"]
        app_name = r["name"] or cfg.get("app_name") or cfg.get("appName") or "—"
        parent = cfg.get("parent_name") or cfg.get("parentName") or "—"
        app_id = r["zia_id"] or "—"
        table.add_row(app_name, parent, app_id)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_cloud_apps_db(tenant):
    search = questionary.text("Search (app name or partial):").ask()
    if not search:
        return
    policy_type = questionary.select(
        "Search in:",
        choices=[
            questionary.Choice("Policy Apps (DLP / CAC)", value="cloud_app_policy"),
            questionary.Choice("SSL Policy Apps", value="cloud_app_ssl_policy"),
        ],
    ).ask()
    if not policy_type:
        return
    _list_cloud_apps_db(tenant, resource_type=policy_type, search=search.strip())


# ------------------------------------------------------------------
# Cloud App Control
# ------------------------------------------------------------------

def _sync_cloud_app_resource(client, tenant):
    """Re-sync cloud_app_control_rule from the API into the DB."""
    from services.zia_import_service import ZIAImportService
    service = ZIAImportService(client, tenant_id=tenant.id)
    service.run(resource_types=["cloud_app_control_rule"])


def cloud_app_control_menu(client, tenant):
    while True:
        render_banner()

        # Build type list from DB (distinct 'type' values in raw_config)
        from db.database import get_session
        from db.models import ZIAResource

        with get_session() as session:
            resources = (
                session.query(ZIAResource)
                .filter_by(tenant_id=tenant.id, resource_type="cloud_app_control_rule", is_deleted=False)
                .all()
            )
            rule_types = sorted({
                (r.raw_config or {}).get("type")
                for r in resources
                if (r.raw_config or {}).get("type")
            })

        if not rule_types:
            console.print(
                "[yellow]No Cloud App Control rules in local DB. "
                "Run [bold]Import Config[/bold] first.[/yellow]"
            )
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

        type_choices = [
            questionary.Choice(rt.replace("_", " ").title(), value=rt)
            for rt in rule_types
        ] + [questionary.Separator(), questionary.Choice("← Back", value="back")]

        rule_type = questionary.select(
            "Cloud App Control — Select Rule Type",
            choices=type_choices,
            use_indicator=True,
        ).ask()

        if rule_type in ("back", None):
            break

        _cloud_app_rules_menu(client, tenant, rule_type)


def _cloud_app_rules_menu(client, tenant, rule_type: str):
    label = rule_type.replace("_", " ").title()
    while True:
        render_banner()
        choice = questionary.select(
            f"Cloud App Control — {label}",
            choices=[
                questionary.Choice("List Rules", value="list"),
                questionary.Choice("View Details", value="view"),
                questionary.Separator(),
                questionary.Choice("Create from JSON File", value="create"),
                questionary.Choice("Edit from JSON File", value="edit"),
                questionary.Choice("Duplicate Rule", value="duplicate"),
                questionary.Choice("Delete Rule", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_cloud_app_rules_db(tenant, rule_type)
        elif choice == "view":
            _view_cloud_app_rule_db(tenant, rule_type)
        elif choice == "create":
            _create_cloud_app_rule(client, tenant, rule_type)
        elif choice == "edit":
            _edit_cloud_app_rule(client, tenant, rule_type)
        elif choice == "duplicate":
            _duplicate_cloud_app_rule(client, tenant, rule_type)
        elif choice == "delete":
            _delete_cloud_app_rule(client, tenant, rule_type)
        elif choice in ("back", None):
            break


def _get_cloud_app_rules_from_db(tenant, rule_type: str):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="cloud_app_control_rule", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
            if (r.raw_config or {}).get("type") == rule_type
        ]
    rows.sort(key=lambda r: r["raw_config"].get("order") or r["raw_config"].get("rank") or 0)
    return rows


def _list_cloud_app_rules_db(tenant, rule_type: str):
    rows = _get_cloud_app_rules_from_db(tenant, rule_type)
    label = rule_type.replace("_", " ").title()

    if not rows:
        console.print(f"[yellow]No rules for {label} in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"{label} Rules ({len(rows)})", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("State")
    table.add_column("Actions")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        order = str(cfg.get("order") or cfg.get("rank") or "—")
        state_val = cfg.get("state") or "—"
        state_str = (
            f"[green]{state_val}[/green]" if state_val == "ENABLED"
            else f"[red]{state_val}[/red]" if state_val == "DISABLED"
            else state_val
        )
        actions = ", ".join(cfg.get("actions") or []) or "—"
        if len(actions) > 50:
            actions = actions[:47] + "..."
        desc = str(cfg.get("description") or "")[:50]
        table.add_row(order, r["name"] or "—", state_str, actions, desc)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _pick_cloud_app_rule_db(tenant, rule_type: str):
    """Pick a cloud app control rule from the DB. Returns row dict or None."""
    rows = _get_cloud_app_rules_from_db(tenant, rule_type)
    if not rows:
        console.print("[yellow]No rules in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None
    return questionary.select(
        "Select rule:",
        choices=[
            questionary.Choice(
                f"{r['name']}  (ID: {r['zia_id']}  order: {r['raw_config'].get('order', '—')})",
                value=r,
            )
            for r in rows
        ],
    ).ask()


def _view_cloud_app_rule_db(tenant, rule_type: str):
    chosen = _pick_cloud_app_rule_db(tenant, rule_type)
    if not chosen:
        return
    _view_raw_json(f"{rule_type} — {chosen['name']}", chosen["raw_config"])


def _create_cloud_app_rule(client, tenant, rule_type: str):
    import json
    from services import audit_service
    console.print(f"\n[bold]Create Cloud App Control Rule — {rule_type.replace('_', ' ').title()}[/bold]")
    path = questionary.text("Path to JSON file:").ask()
    if not path:
        return
    try:
        with open(path.strip()) as fh:
            config = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    try:
        result = client.create_cloud_app_rule(rule_type, config)
        console.print(f"[green]✓ Created rule ID {result.get('id', '?')}.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        audit_service.log(
            product="ZIA", operation="create_cloud_app_rule", action="CREATE",
            status="SUCCESS", tenant_id=tenant.id,
            resource_type=rule_type, details={"name": config.get("name")},
        )
        _sync_cloud_app_resource(client, tenant)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_cloud_app_rule(client, tenant, rule_type: str):
    import json
    from services import audit_service
    chosen = _pick_cloud_app_rule_db(tenant, rule_type)
    if not chosen:
        return

    _view_raw_json(f"Current — {chosen['name']}", chosen["raw_config"])

    path = questionary.text("Path to JSON file with updated config:").ask()
    if not path:
        return
    try:
        with open(path.strip()) as fh:
            config = json.load(fh)
    except Exception as e:
        console.print(f"[red]✗ Could not read file: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    try:
        client.update_cloud_app_rule(rule_type, chosen["zia_id"], config)
        console.print("[green]✓ Rule updated.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        audit_service.log(
            product="ZIA", operation="update_cloud_app_rule", action="UPDATE",
            status="SUCCESS", tenant_id=tenant.id,
            resource_type=rule_type, details={"id": chosen["zia_id"], "name": chosen["name"]},
        )
        _sync_cloud_app_resource(client, tenant)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _duplicate_cloud_app_rule(client, tenant, rule_type: str):
    from services import audit_service
    chosen = _pick_cloud_app_rule_db(tenant, rule_type)
    if not chosen:
        return

    new_name = questionary.text(
        "Name for duplicate rule:",
        default=f"Copy of {chosen['name']}",
    ).ask()
    if not new_name:
        return

    try:
        result = client.duplicate_cloud_app_rule(rule_type, chosen["zia_id"], new_name)
        console.print(f"[green]✓ Duplicated as '{new_name}' (ID {result.get('id', '?')}).[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        audit_service.log(
            product="ZIA", operation="duplicate_cloud_app_rule", action="CREATE",
            status="SUCCESS", tenant_id=tenant.id,
            resource_type=rule_type, details={"source_id": chosen["zia_id"], "new_name": new_name},
        )
        _sync_cloud_app_resource(client, tenant)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_cloud_app_rule(client, tenant, rule_type: str):
    from services import audit_service
    chosen = _pick_cloud_app_rule_db(tenant, rule_type)
    if not chosen:
        return

    confirmed = questionary.confirm(
        f"Delete rule '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return

    try:
        client.delete_cloud_app_rule(rule_type, chosen["zia_id"])
        console.print("[green]✓ Rule deleted.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        audit_service.log(
            product="ZIA", operation="delete_cloud_app_rule", action="DELETE",
            status="SUCCESS", tenant_id=tenant.id,
            resource_type=rule_type, details={"id": chosen["zia_id"], "name": chosen["name"]},
        )
        _sync_cloud_app_resource(client, tenant)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()
