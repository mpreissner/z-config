import questionary
from rich.console import Console
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zia_client
from cli.menus.snapshots_menu import snapshots_menu
from lib.defaults import DEFAULT_WORK_DIR

console = Console()

_CANCEL = object()


def _rule_order_key(n):
    """Sort key: positive integers ascending first, then negative integers descending.

    Positive/zero positions (user rules) come first in ascending order.
    Negative positions (system/default rules) come last in descending order.
    e.g. 1, 2, 3, ..., -1, -2, -3, ...
    """
    return (0, n) if n >= 0 else (1, -n)


def _zia_changed():
    """Mark the active tenant's ZIA config as having unactivated changes."""
    from cli.session import get_active_tenant, mark_zia_pending
    t = get_active_tenant()
    if t:
        mark_zia_pending(t.id)
    console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")


def zia_menu():
    client, tenant = get_zia_client()
    if client is None:
        return

    while True:
        render_banner()
        from cli.session import has_zia_pending
        if has_zia_pending(tenant.id):
            console.print("[yellow]⚠  Changes pending activation[/yellow]\n")
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
                questionary.Choice("DLP Web Rules", value="dlp_web_rules"),
                questionary.Separator("── Cloud Apps ──"),
                questionary.Choice("Cloud Applications", value="cloud_applications"),
                questionary.Choice("Cloud App Control", value="cloud_app_control"),
                questionary.Separator("── Baseline ──"),
                questionary.Choice("Apply Snapshot from Another Tenant", value="cross_tenant_snap"),
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
        elif choice == "dlp_web_rules":
            dlp_web_rules_menu(client, tenant)
        elif choice == "cloud_applications":
            cloud_applications_menu(client, tenant)
        elif choice == "cloud_app_control":
            cloud_app_control_menu(client, tenant)
        elif choice == "activation":
            activation_menu(client, tenant)
        elif choice == "import":
            _import_zia_config(client, tenant)
        elif choice == "snapshots":
            snapshots_menu(tenant, "ZIA", client=client)
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
    last_result = None  # ("ok", state) or ("err", msg)

    while True:
        render_banner()
        from cli.session import has_zia_pending
        if has_zia_pending(tenant.id):
            console.print("[yellow]⚠  Changes pending activation[/yellow]\n")

        try:
            status = service.get_activation_status()
        except Exception as e:
            console.print(f"[red]✗ Could not fetch status: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

        state = status.get("status", "UNKNOWN")
        state_colour = "green" if state == "ACTIVE" else "yellow"
        console.print(f"Activation status: [{state_colour}][bold]{state}[/bold][/{state_colour}]")

        if last_result is not None:
            kind, msg = last_result
            if kind == "ok":
                console.print(f"[green]✓ Activation complete — {msg}[/green]")
            else:
                console.print(f"[red]✗ Activation failed: {msg}[/red]")
            last_result = None

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
            try:
                result = service.activate()
                activated_state = result.get("status", "UNKNOWN") if result else "UNKNOWN"
                last_result = ("ok", f"status: {activated_state}")
                from cli.session import clear_zia_pending
                clear_zia_pending(tenant.id)
            except Exception as e:
                last_result = ("err", str(e))
        elif choice in ("back", None):
            break


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
                questionary.Choice("Export Firewall Rules to CSV", value="export_fw"),
                questionary.Choice("Import / Sync Firewall Rules", value="sync_fw"),
                questionary.Choice("Source IPv4 Group Management", value="create_src_groups"),
                questionary.Choice("Dest IPv4 Group Management", value="create_dst_groups"),
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
        elif choice == "export_fw":
            _export_firewall_rules_to_csv(tenant)
        elif choice == "sync_fw":
            _sync_firewall_rules(client, tenant)
        elif choice == "create_src_groups":
            ip_source_group_menu(client, tenant)
        elif choice == "create_dst_groups":
            ip_dest_group_menu(client, tenant)
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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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
        console.print(f"[green]✓ {ok} rule(s) updated.[/green]")
        _zia_changed()
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _export_firewall_rules_to_csv(tenant):
    import csv as _csv
    import os
    from services.zia_firewall_service import export_rules_to_csv, CSV_FIELDNAMES

    csv_rows = export_rules_to_csv(tenant.id)

    if not csv_rows:
        console.print("[yellow]No firewall rules in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    default_path = str(DEFAULT_WORK_DIR / f"firewall_rules_{tenant.name}.csv")
    out_path = questionary.path("Output path:", default=default_path).ask()
    if not out_path:
        return
    out_path = os.path.expanduser(out_path)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = _csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(csv_rows)

    console.print(f"[green]✓ {len(csv_rows)} rule(s) exported to {out_path}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _sync_firewall_rules(client, tenant):
    """Import / Sync cloud firewall rules from CSV."""
    import os
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zia_firewall_service import parse_csv, classify_sync, sync_rules

    console.print("\n[bold]Import / Sync Cloud Firewall Rules from CSV[/bold]\n")

    csv_path = questionary.path("Path to CSV file:", default=str(DEFAULT_WORK_DIR)).ask()
    if not csv_path:
        return
    csv_path = os.path.expanduser(csv_path)

    try:
        rows = parse_csv(csv_path)
    except ValueError as exc:
        console.print(f"\n[red]CSV validation errors:[/red]\n{exc}")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print(f"\n[dim]Classifying {len(rows)} row(s) against tenant...[/dim]")
    classification = classify_sync(tenant.id, rows)

    # Dry-run table
    dry_table = Table(title="Sync Preview (Dry Run)", show_lines=False)
    dry_table.add_column("Action", width=8)
    dry_table.add_column("Name")
    dry_table.add_column("Detail")

    ACTION_STYLE = {
        "UPDATE":      "[yellow]UPDATE[/yellow]",
        "CREATE":      "[green]CREATE[/green]",
        "SKIP":        "[dim]SKIP[/dim]",
        "MISSING_DEP": "[red]MISSING[/red]",
    }

    for item in classification.csv_rows:
        action_label = ACTION_STYLE.get(item["action"], item["action"])
        name = item["row"].get("name", "")
        if item["action"] == "UPDATE":
            detail = "; ".join(item.get("changes", [])) or "—"
        elif item["action"] == "CREATE":
            detail = item.get("warn", "(new)")
        elif item["action"] == "MISSING_DEP":
            detail = "; ".join(item.get("issues", []))
        else:
            detail = "unchanged"
        dry_table.add_row(action_label, name, detail)

    for item in classification.to_delete:
        dry_table.add_row("[red]DELETE[/red]", item["name"], f"id {item['zia_id']} not in CSV")

    if classification.reorder_needed:
        total_rules = len([e for e in classification.csv_rows if e.get("zia_id") or e["action"] == "CREATE"])
        dry_table.add_row("[blue]REORDER[/blue]", f"({total_rules} rules)", "sequence will change")

    console.print(dry_table)

    n_missing = len(classification.missing_dep)
    if n_missing:
        console.print(f"\n[red]⚠ {n_missing} row(s) have unresolved dependencies and will be skipped.[/red]")
        console.print("[dim]Create the referenced IP groups, services, or locations first, "
                      "then re-run Import Config before retrying.[/dim]")

    for item in classification.csv_rows:
        if item.get("warn"):
            console.print(f"  [yellow]⚠ {item['row'].get('name', '')}:[/yellow] {item['warn']}")

    n_update = len(classification.to_update)
    n_create = len(classification.to_create)
    n_delete = len(classification.to_delete)
    n_skip = len(classification.unchanged)

    if n_update + n_create + n_delete == 0 and not classification.reorder_needed:
        console.print("\n[green]Everything is up to date — no changes needed.[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    parts = []
    if n_update:
        parts.append(f"{n_update} update(s)")
    if n_create:
        parts.append(f"{n_create} create(s)")
    if n_delete:
        parts.append(f"{n_delete} delete(s)")
    if classification.reorder_needed:
        parts.append("reorder")
    if n_skip:
        parts.append(f"{n_skip} skip(s)")

    confirmed = questionary.confirm(
        f"\nApply: {', '.join(parts)}? (Changes will require ZIA activation)",
        default=False,
    ).ask()
    if not confirmed:
        return

    total_ops = n_update + n_delete + n_create + (1 if classification.reorder_needed else 0)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Syncing...", total=total_ops)

        def on_progress(label, done, total):
            progress.update(task, completed=done, description=label)

        result = sync_rules(client, tenant.id, classification, progress_callback=on_progress)

    console.print(
        f"\n[green]✓ Updated {result.updated}[/green]  "
        f"[green]✓ Created {result.created}[/green]  "
        f"[red]✗ Deleted {result.deleted}[/red]  "
        f"[dim]— Skipped {result.skipped}[/dim]"
        + (f"  [blue]↕ Reordered[/blue]" if result.reordered else "")
    )

    for err in result.errors:
        console.print(f"  [red]Error:[/red] {err}")

    if result.updated or result.created or result.deleted or result.reordered:
        from services.zia_import_service import ZIAImportService
        with console.status("Syncing changes to local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["firewall_rule"])
        console.print("[green]✓ Local DB updated.[/green]")
        _zia_changed()

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Source IPv4 Groups — full CRUD submenu
# ------------------------------------------------------------------

def ip_source_group_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Source IPv4 Group Management",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("Create", value="create"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("Bulk Create from CSV", value="bulk_csv"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_ip_source_groups(tenant)
        elif choice == "search":
            _search_ip_source_groups(tenant)
        elif choice == "create":
            _create_ip_source_group_single(client, tenant)
        elif choice == "edit":
            _edit_ip_source_group(client, tenant)
        elif choice == "delete":
            _delete_ip_source_group(client, tenant)
        elif choice == "bulk_csv":
            _create_ip_source_groups(client, tenant)
        elif choice in ("back", None):
            break


def _list_ip_source_groups(tenant, search=None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_source_group", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]
    rows.sort(key=lambda r: (r["name"] or "").lower())

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No source groups matching '{search}'.[/yellow]" if search
            else "[yellow]No source IP groups in local DB. Run Import Config first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Source IPv4 Groups ({len(rows)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("IPs", justify="right", style="dim")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        ips = cfg.get("ip_addresses") or []
        table.add_row(
            r["zia_id"],
            r["name"] or "—",
            str(len(ips)),
            (cfg.get("description") or "")[:60] or "[dim]—[/dim]",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_ip_source_groups(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_ip_source_groups(tenant, search=search.strip())


def _pick_ip_source_group(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_source_group", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No source IP groups in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    chosen = questionary.select(
        "Select group:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ] + [questionary.Choice("← Cancel", value="cancel")],
    ).ask()
    if chosen in (None, "cancel"):
        return None
    return chosen


def _create_ip_source_group_single(client, tenant):
    console.print("\n[bold]Create Source IPv4 Group[/bold]")
    name = questionary.text("Name:").ask()
    if not name or not name.strip():
        return
    description = questionary.text("Description (optional):").ask() or ""
    ips_raw = questionary.text("IP addresses / CIDRs (semicolon-separated):").ask()
    if not ips_raw or not ips_raw.strip():
        console.print("[red]At least one IP address is required.[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
    ip_list = [ip.strip() for ip in ips_raw.split(";") if ip.strip()]
    try:
        result = client.create_ip_source_group({
            "name": name.strip(),
            "description": description.strip(),
            "ip_addresses": ip_list,
        })
        console.print(f"[green]✓ Created source group '{result.get('name', name)}' (ID: {result.get('id', '?')}).[/green]")
        _zia_changed()
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_ip_source_group(client, tenant):
    chosen = _pick_ip_source_group(tenant)
    if not chosen:
        return
    cfg = chosen["raw_config"]
    current_name = cfg.get("name") or chosen["name"] or ""
    current_desc = cfg.get("description") or ""
    current_ips = cfg.get("ip_addresses") or []
    current_ips_str = ";".join(current_ips)

    console.print(f"\n[bold]Edit Source IPv4 Group — {chosen['name']}[/bold]")
    console.print("[dim]Leave blank to keep current value.[/dim]\n")

    name = questionary.text(f"Name [{current_name}]:").ask()
    if name is None:
        return
    description = questionary.text(f"Description [{current_desc or '(none)'}]:").ask()
    if description is None:
        return
    ips_raw = questionary.text(f"IP addresses [{current_ips_str}]:").ask()
    if ips_raw is None:
        return

    new_name = name.strip() or current_name
    new_desc = description.strip() if description.strip() else current_desc
    new_ips = [ip.strip() for ip in ips_raw.split(";") if ip.strip()] if ips_raw.strip() else current_ips

    confirmed = questionary.confirm(
        f"Update group '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return
    try:
        client.update_ip_source_group(chosen["zia_id"], {
            "name": new_name, "description": new_desc, "ip_addresses": new_ips
        })
        console.print("[green]✓ Source group updated.[/green]")
        _zia_changed()
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_ip_source_group(client, tenant):
    chosen = _pick_ip_source_group(tenant)
    if not chosen:
        return
    confirmed = questionary.confirm(
        f"Delete source group '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return
    try:
        client.delete_ip_source_group(chosen["zia_id"])
        console.print("[green]✓ Source group deleted.[/green]")
        _zia_changed()
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Destination IPv4 Groups — full CRUD submenu
# ------------------------------------------------------------------

def ip_dest_group_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Dest IPv4 Group Management",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("Create", value="create"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("Bulk Create from CSV", value="bulk_csv"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_ip_dest_groups(tenant)
        elif choice == "search":
            _search_ip_dest_groups(tenant)
        elif choice == "create":
            _create_ip_dest_group_single(client, tenant)
        elif choice == "edit":
            _edit_ip_dest_group(client, tenant)
        elif choice == "delete":
            _delete_ip_dest_group(client, tenant)
        elif choice == "bulk_csv":
            _create_ip_dest_groups(client, tenant)
        elif choice in ("back", None):
            break


def _list_ip_dest_groups(tenant, search=None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_destination_group", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]
    rows.sort(key=lambda r: (r["name"] or "").lower())

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No destination groups matching '{search}'.[/yellow]" if search
            else "[yellow]No destination IP groups in local DB. Run Import Config first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Destination IPv4 Groups ({len(rows)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Type", style="dim")
    table.add_column("Addresses", justify="right", style="dim")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        addrs = cfg.get("addresses") or []
        table.add_row(
            r["zia_id"],
            r["name"] or "—",
            cfg.get("type") or "—",
            str(len(addrs)),
            (cfg.get("description") or "")[:60] or "[dim]—[/dim]",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_ip_dest_groups(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_ip_dest_groups(tenant, search=search.strip())


def _pick_ip_dest_group(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_destination_group", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No destination IP groups in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    chosen = questionary.select(
        "Select group:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ] + [questionary.Choice("← Cancel", value="cancel")],
    ).ask()
    if chosen in (None, "cancel"):
        return None
    return chosen


_DSTN_TYPES = ["DSTN_IP", "DSTN_FQDN", "DSTN_DOMAIN", "DSTN_OTHER"]


def _create_ip_dest_group_single(client, tenant):
    console.print("\n[bold]Create Destination IPv4 Group[/bold]")
    name = questionary.text("Name:").ask()
    if not name or not name.strip():
        return
    grp_type = questionary.select("Type:", choices=_DSTN_TYPES).ask()
    if not grp_type:
        return
    description = questionary.text("Description (optional):").ask() or ""
    addrs_raw = questionary.text("Addresses (semicolon-separated IPs/FQDNs/CIDRs):").ask()
    if not addrs_raw or not addrs_raw.strip():
        console.print("[red]At least one address is required.[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
    addr_list = [a.strip() for a in addrs_raw.split(";") if a.strip()]
    try:
        result = client.create_ip_destination_group({
            "name": name.strip(),
            "type": grp_type,
            "description": description.strip(),
            "addresses": addr_list,
        })
        console.print(f"[green]✓ Created destination group '{result.get('name', name)}' (ID: {result.get('id', '?')}).[/green]")
        _zia_changed()
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_ip_dest_group(client, tenant):
    chosen = _pick_ip_dest_group(tenant)
    if not chosen:
        return
    cfg = chosen["raw_config"]
    current_name = cfg.get("name") or chosen["name"] or ""
    current_type = cfg.get("type") or "DSTN_IP"
    current_desc = cfg.get("description") or ""
    current_addrs = cfg.get("addresses") or []
    current_addrs_str = ";".join(current_addrs)

    console.print(f"\n[bold]Edit Destination IPv4 Group — {chosen['name']}[/bold]")
    console.print("[dim]Leave blank to keep current value.[/dim]\n")

    name = questionary.text(f"Name [{current_name}]:").ask()
    if name is None:
        return
    grp_type = questionary.select(
        f"Type [{current_type}]:",
        choices=_DSTN_TYPES,
        default=current_type if current_type in _DSTN_TYPES else _DSTN_TYPES[0],
    ).ask()
    if grp_type is None:
        return
    description = questionary.text(f"Description [{current_desc or '(none)'}]:").ask()
    if description is None:
        return
    addrs_raw = questionary.text(f"Addresses [{current_addrs_str}]:").ask()
    if addrs_raw is None:
        return

    new_name = name.strip() or current_name
    new_desc = description.strip() if description.strip() else current_desc
    new_addrs = [a.strip() for a in addrs_raw.split(";") if a.strip()] if addrs_raw.strip() else current_addrs

    confirmed = questionary.confirm(
        f"Update group '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return
    try:
        client.update_ip_destination_group(chosen["zia_id"], {
            "name": new_name, "type": grp_type, "description": new_desc, "addresses": new_addrs
        })
        console.print("[green]✓ Destination group updated.[/green]")
        _zia_changed()
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_ip_dest_group(client, tenant):
    chosen = _pick_ip_dest_group(tenant)
    if not chosen:
        return
    confirmed = questionary.confirm(
        f"Delete destination group '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return
    try:
        client.delete_ip_destination_group(chosen["zia_id"])
        console.print("[green]✓ Destination group deleted.[/green]")
        _zia_changed()
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Source IPv4 Groups — full CRUD submenu
# ------------------------------------------------------------------

def ip_source_group_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Source IPv4 Group Management",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("Create", value="create"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("Bulk Create from CSV", value="bulk_csv"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_ip_source_groups(tenant)
        elif choice == "search":
            _search_ip_source_groups(tenant)
        elif choice == "create":
            _create_ip_source_group_single(client, tenant)
        elif choice == "edit":
            _edit_ip_source_group(client, tenant)
        elif choice == "delete":
            _delete_ip_source_group(client, tenant)
        elif choice == "bulk_csv":
            _create_ip_source_groups(client, tenant)
        elif choice in ("back", None):
            break


def _list_ip_source_groups(tenant, search=None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_source_group", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]
    rows.sort(key=lambda r: (r["name"] or "").lower())

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No source groups matching '{search}'.[/yellow]" if search
            else "[yellow]No source IP groups in local DB. Run Import Config first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Source IPv4 Groups ({len(rows)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("IPs", justify="right", style="dim")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        ips = cfg.get("ip_addresses") or []
        table.add_row(
            r["zia_id"],
            r["name"] or "—",
            str(len(ips)),
            (cfg.get("description") or "")[:60] or "[dim]—[/dim]",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_ip_source_groups(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_ip_source_groups(tenant, search=search.strip())


def _pick_ip_source_group(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_source_group", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No source IP groups in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    chosen = questionary.select(
        "Select group:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ] + [questionary.Choice("← Cancel", value="cancel")],
    ).ask()
    if chosen in (None, "cancel"):
        return None
    return chosen


def _create_ip_source_group_single(client, tenant):
    console.print("\n[bold]Create Source IPv4 Group[/bold]")
    name = questionary.text("Name:").ask()
    if not name or not name.strip():
        return
    description = questionary.text("Description (optional):").ask() or ""
    ips_raw = questionary.text("IP addresses / CIDRs (semicolon-separated):").ask()
    if not ips_raw or not ips_raw.strip():
        console.print("[red]At least one IP address is required.[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
    ip_list = [ip.strip() for ip in ips_raw.split(";") if ip.strip()]
    try:
        result = client.create_ip_source_group({
            "name": name.strip(),
            "description": description.strip(),
            "ip_addresses": ip_list,
        })
        console.print(f"[green]✓ Created source group '{result.get('name', name)}' (ID: {result.get('id', '?')}).[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_ip_source_group(client, tenant):
    chosen = _pick_ip_source_group(tenant)
    if not chosen:
        return
    cfg = chosen["raw_config"]
    current_name = cfg.get("name") or chosen["name"] or ""
    current_desc = cfg.get("description") or ""
    current_ips = cfg.get("ip_addresses") or []
    current_ips_str = ";".join(current_ips)

    console.print(f"\n[bold]Edit Source IPv4 Group — {chosen['name']}[/bold]")
    console.print("[dim]Leave blank to keep current value.[/dim]\n")

    name = questionary.text(f"Name [{current_name}]:").ask()
    if name is None:
        return
    description = questionary.text(f"Description [{current_desc or '(none)'}]:").ask()
    if description is None:
        return
    ips_raw = questionary.text(f"IP addresses [{current_ips_str}]:").ask()
    if ips_raw is None:
        return

    new_name = name.strip() or current_name
    new_desc = description.strip() if description.strip() else current_desc
    new_ips = [ip.strip() for ip in ips_raw.split(";") if ip.strip()] if ips_raw.strip() else current_ips

    confirmed = questionary.confirm(
        f"Update group '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return
    try:
        client.update_ip_source_group(chosen["zia_id"], {
            "name": new_name, "description": new_desc, "ip_addresses": new_ips
        })
        console.print("[green]✓ Source group updated.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_ip_source_group(client, tenant):
    chosen = _pick_ip_source_group(tenant)
    if not chosen:
        return
    confirmed = questionary.confirm(
        f"Delete source group '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return
    try:
        client.delete_ip_source_group(chosen["zia_id"])
        console.print("[green]✓ Source group deleted.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Destination IPv4 Groups — full CRUD submenu
# ------------------------------------------------------------------

def ip_dest_group_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Dest IPv4 Group Management",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("Create", value="create"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("Bulk Create from CSV", value="bulk_csv"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_ip_dest_groups(tenant)
        elif choice == "search":
            _search_ip_dest_groups(tenant)
        elif choice == "create":
            _create_ip_dest_group_single(client, tenant)
        elif choice == "edit":
            _edit_ip_dest_group(client, tenant)
        elif choice == "delete":
            _delete_ip_dest_group(client, tenant)
        elif choice == "bulk_csv":
            _create_ip_dest_groups(client, tenant)
        elif choice in ("back", None):
            break


def _list_ip_dest_groups(tenant, search=None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_destination_group", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]
    rows.sort(key=lambda r: (r["name"] or "").lower())

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No destination groups matching '{search}'.[/yellow]" if search
            else "[yellow]No destination IP groups in local DB. Run Import Config first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Destination IPv4 Groups ({len(rows)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Type", style="dim")
    table.add_column("Addresses", justify="right", style="dim")
    table.add_column("Description")

    for r in rows:
        cfg = r["raw_config"]
        addrs = cfg.get("addresses") or []
        table.add_row(
            r["zia_id"],
            r["name"] or "—",
            cfg.get("type") or "—",
            str(len(addrs)),
            (cfg.get("description") or "")[:60] or "[dim]—[/dim]",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_ip_dest_groups(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_ip_dest_groups(tenant, search=search.strip())


def _pick_ip_dest_group(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="ip_destination_group", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No destination IP groups in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    chosen = questionary.select(
        "Select group:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ] + [questionary.Choice("← Cancel", value="cancel")],
    ).ask()
    if chosen in (None, "cancel"):
        return None
    return chosen


_DSTN_TYPES = ["DSTN_IP", "DSTN_FQDN", "DSTN_DOMAIN", "DSTN_OTHER"]


def _create_ip_dest_group_single(client, tenant):
    console.print("\n[bold]Create Destination IPv4 Group[/bold]")
    name = questionary.text("Name:").ask()
    if not name or not name.strip():
        return
    grp_type = questionary.select("Type:", choices=_DSTN_TYPES).ask()
    if not grp_type:
        return
    description = questionary.text("Description (optional):").ask() or ""
    addrs_raw = questionary.text("Addresses (semicolon-separated IPs/FQDNs/CIDRs):").ask()
    if not addrs_raw or not addrs_raw.strip():
        console.print("[red]At least one address is required.[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
    addr_list = [a.strip() for a in addrs_raw.split(";") if a.strip()]
    try:
        result = client.create_ip_destination_group({
            "name": name.strip(),
            "type": grp_type,
            "description": description.strip(),
            "addresses": addr_list,
        })
        console.print(f"[green]✓ Created destination group '{result.get('name', name)}' (ID: {result.get('id', '?')}).[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _edit_ip_dest_group(client, tenant):
    chosen = _pick_ip_dest_group(tenant)
    if not chosen:
        return
    cfg = chosen["raw_config"]
    current_name = cfg.get("name") or chosen["name"] or ""
    current_type = cfg.get("type") or "DSTN_IP"
    current_desc = cfg.get("description") or ""
    current_addrs = cfg.get("addresses") or []
    current_addrs_str = ";".join(current_addrs)

    console.print(f"\n[bold]Edit Destination IPv4 Group — {chosen['name']}[/bold]")
    console.print("[dim]Leave blank to keep current value.[/dim]\n")

    name = questionary.text(f"Name [{current_name}]:").ask()
    if name is None:
        return
    grp_type = questionary.select(
        f"Type [{current_type}]:",
        choices=_DSTN_TYPES,
        default=current_type if current_type in _DSTN_TYPES else _DSTN_TYPES[0],
    ).ask()
    if grp_type is None:
        return
    description = questionary.text(f"Description [{current_desc or '(none)'}]:").ask()
    if description is None:
        return
    addrs_raw = questionary.text(f"Addresses [{current_addrs_str}]:").ask()
    if addrs_raw is None:
        return

    new_name = name.strip() or current_name
    new_desc = description.strip() if description.strip() else current_desc
    new_addrs = [a.strip() for a in addrs_raw.split(";") if a.strip()] if addrs_raw.strip() else current_addrs

    confirmed = questionary.confirm(
        f"Update group '{chosen['name']}' (ID: {chosen['zia_id']})?", default=True
    ).ask()
    if not confirmed:
        return
    try:
        client.update_ip_destination_group(chosen["zia_id"], {
            "name": new_name, "type": grp_type, "description": new_desc, "addresses": new_addrs
        })
        console.print("[green]✓ Destination group updated.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_ip_dest_group(client, tenant):
    chosen = _pick_ip_dest_group(tenant)
    if not chosen:
        return
    confirmed = questionary.confirm(
        f"Delete destination group '{chosen['name']}' (ID: {chosen['zia_id']})? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return
    try:
        client.delete_ip_destination_group(chosen["zia_id"])
        console.print("[green]✓ Destination group deleted.[/green]")
        console.print("[yellow]Remember to activate changes in ZIA.[/yellow]")
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _create_ip_source_groups(client, tenant):
    """Bulk-create IP source groups from a CSV file."""
    import csv as _csv
    import os
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zia_firewall_service import (
        parse_ip_source_group_csv, bulk_create_ip_source_groups,
        IP_SOURCE_GROUP_FIELDNAMES, IP_SOURCE_GROUP_TEMPLATE,
    )

    console.print("\n[bold]Create Source IP Groups from CSV[/bold]\n")
    console.print("[dim]CSV columns: name, description, ip_addresses (semicolon-separated IPs/CIDRs)[/dim]\n")

    choice = questionary.select(
        "Action:",
        choices=[
            questionary.Choice("Import from CSV", value="import"),
            questionary.Choice("Export blank template", value="template"),
            questionary.Choice("← Cancel", value="cancel"),
        ],
    ).ask()

    if choice == "template":
        default_path = str(DEFAULT_WORK_DIR / "ip_source_groups_template.csv")
        out_path = questionary.path("Output path:", default=default_path).ask()
        if out_path:
            out_path = os.path.expanduser(out_path)
            with open(out_path, "w", newline="", encoding="utf-8") as fh:
                writer = _csv.DictWriter(fh, fieldnames=IP_SOURCE_GROUP_FIELDNAMES)
                writer.writeheader()
                writer.writerows(IP_SOURCE_GROUP_TEMPLATE)
            console.print(f"[green]✓ Template written to {out_path}[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    if choice in (None, "cancel"):
        return

    csv_path = questionary.path("Path to CSV file:", default=str(DEFAULT_WORK_DIR)).ask()
    if not csv_path:
        return
    csv_path = os.path.expanduser(csv_path)

    try:
        rows = parse_ip_source_group_csv(csv_path)
    except ValueError as exc:
        console.print(f"\n[red]CSV validation errors:[/red]\n{exc}")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    confirmed = questionary.confirm(
        f"Create {len(rows)} IP source group(s)?", default=True
    ).ask()
    if not confirmed:
        return

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Creating groups...", total=len(rows))
        result = bulk_create_ip_source_groups(
            client, tenant.id, rows,
            progress_callback=lambda done, total: progress.update(task, completed=done),
        )

    console.print(f"\n[green]✓ Created {result.created}[/green]  [red]✗ Failed {result.failed}[/red]")
    for d in result.rows_detail:
        if d["status"] == "FAILED":
            console.print(f"  [red]{d['name']}:[/red] {d['error']}")

    if result.created:
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_source_group"])
        console.print("[green]✓ Local DB updated.[/green]")
        _zia_changed()

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _create_ip_dest_groups(client, tenant):
    """Bulk-create IP destination groups from a CSV file."""
    import csv as _csv
    import os
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zia_firewall_service import (
        parse_ip_dest_group_csv, bulk_create_ip_dest_groups,
        IP_DEST_GROUP_FIELDNAMES, IP_DEST_GROUP_TEMPLATE,
    )

    console.print("\n[bold]Create Destination IP Groups from CSV[/bold]\n")
    console.print("[dim]CSV columns: name, type (DSTN_IP/DSTN_FQDN/DSTN_DOMAIN/DSTN_OTHER), description, ip_addresses[/dim]\n")

    choice = questionary.select(
        "Action:",
        choices=[
            questionary.Choice("Import from CSV", value="import"),
            questionary.Choice("Export blank template", value="template"),
            questionary.Choice("← Cancel", value="cancel"),
        ],
    ).ask()

    if choice == "template":
        default_path = str(DEFAULT_WORK_DIR / "ip_dest_groups_template.csv")
        out_path = questionary.path("Output path:", default=default_path).ask()
        if out_path:
            out_path = os.path.expanduser(out_path)
            with open(out_path, "w", newline="", encoding="utf-8") as fh:
                writer = _csv.DictWriter(fh, fieldnames=IP_DEST_GROUP_FIELDNAMES)
                writer.writeheader()
                writer.writerows(IP_DEST_GROUP_TEMPLATE)
            console.print(f"[green]✓ Template written to {out_path}[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    if choice in (None, "cancel"):
        return

    csv_path = questionary.path("Path to CSV file:", default=str(DEFAULT_WORK_DIR)).ask()
    if not csv_path:
        return
    csv_path = os.path.expanduser(csv_path)

    try:
        rows = parse_ip_dest_group_csv(csv_path)
    except ValueError as exc:
        console.print(f"\n[red]CSV validation errors:[/red]\n{exc}")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    confirmed = questionary.confirm(
        f"Create {len(rows)} IP destination group(s)?", default=True
    ).ask()
    if not confirmed:
        return

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Creating groups...", total=len(rows))
        result = bulk_create_ip_dest_groups(
            client, tenant.id, rows,
            progress_callback=lambda done, total: progress.update(task, completed=done),
        )

    console.print(f"\n[green]✓ Created {result.created}[/green]  [red]✗ Failed {result.failed}[/red]")
    for d in result.rows_detail:
        if d["status"] == "FAILED":
            console.print(f"  [red]{d['name']}:[/red] {d['error']}")

    if result.created:
        from services.zia_import_service import ZIAImportService
        with console.status("Updating local DB..."):
            ZIAImportService(client, tenant.id).run(resource_types=["ip_destination_group"])
        console.print("[green]✓ Local DB updated.[/green]")
        _zia_changed()

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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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
        console.print(f"[green]✓ {ok} rule(s) updated.[/green]")
        _zia_changed()
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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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

    from db.database import get_session
    from db.models import ZIAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="firewall_ips_rule", is_deleted=False)
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
        console.print("[yellow]No IPS rules in local DB. Run Import Config first.[/yellow]")
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
            config = client.get_firewall_ips_rule(r["zia_id"])
            config["state"] = action
            client.update_firewall_ips_rule(r["zia_id"], config)
            _update_zia_resource_field(tenant.id, "firewall_ips_rule", r["zia_id"], "state", action)
            audit_service.log(
                product="ZIA", operation="toggle_ips_rule", action="UPDATE",
                status="SUCCESS", tenant_id=tenant.id, resource_type="firewall_ips_rule",
                resource_id=r["zia_id"], resource_name=r["name"],
                details={"state": action},
            )
            ok += 1
        except Exception as e:
            console.print(f"[red]✗ {r['name']}: {e}[/red]")
            audit_service.log(
                product="ZIA", operation="toggle_ips_rule", action="UPDATE",
                status="FAILURE", tenant_id=tenant.id, resource_type="firewall_ips_rule",
                resource_id=r["zia_id"], resource_name=r["name"], error_message=str(e),
            )

    if ok:
        console.print(f"[green]✓ {ok} rule(s) updated.[/green]")
        _zia_changed()
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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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
        console.print(f"[green]✓ {ok} rule(s) updated.[/green]")
        _zia_changed()
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
    console.print(f"[green]✓ {len(urls)} URL(s) added.[/green]")
    _zia_changed()
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
    console.print(f"[green]✓ {len(selected)} URL(s) removed.[/green]")
    _zia_changed()
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
    console.print(f"[green]✓ {len(urls)} URL(s) {'added to' if add else 'removed from'} '{cat['name']}'.[/green]")
    _zia_changed()
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

    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

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
        console.print(f"[green]✓ {ok} rule(s) updated.[/green]")
        _zia_changed()
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
    path = questionary.path("Path to JSON file:").ask()
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
        _zia_changed()
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
    path = questionary.path("Path to JSON file with updated config:").ask()
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
        _zia_changed()
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
        _zia_changed()
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
    path = questionary.path("Path to JSON file:").ask()
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
        _zia_changed()
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

    path = questionary.path("Path to CSV file:").ask()
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
        _zia_changed()
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
    path = questionary.path("Path to JSON file with updated config:").ask()
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
        _zia_changed()
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

    path = questionary.path("Path to CSV file:").ask()
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
        _zia_changed()
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
        _zia_changed()
        _sync_dlp_resource(client, tenant, "dlp_dictionary")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# DLP Web Rules (read-only view)
# ------------------------------------------------------------------

def dlp_web_rules_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "DLP Web Rules",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Choice("View Details", value="view"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_dlp_web_rules(tenant)
        elif choice == "search":
            _search_dlp_web_rules(tenant)
        elif choice == "view":
            _view_dlp_web_rule(tenant)
        elif choice in ("back", None):
            break


def _list_dlp_web_rules(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="dlp_web_rule", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}, "synced_at": r.synced_at}
            for r in resources
        ]
    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No DLP web rules matching '{search}'.[/yellow]" if search
            else "[yellow]No DLP web rules in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"DLP Web Rules ({len(rows)} total)", show_lines=False)
    table.add_column("Order", justify="right")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("State")
    table.add_column("Last Synced", style="dim")

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
        synced = r["synced_at"].strftime("%Y-%m-%d %H:%M") if r["synced_at"] else "—"
        table.add_row(order, r["name"] or "—", action, state_str, synced)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_dlp_web_rules(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_dlp_web_rules(tenant, search=search.strip())


def _pick_dlp_web_rule(tenant):
    from db.database import get_session
    from db.models import ZIAResource

    with get_session() as session:
        resources = (
            session.query(ZIAResource)
            .filter_by(tenant_id=tenant.id, resource_type="dlp_web_rule", is_deleted=False)
            .order_by(ZIAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zia_id": r.zia_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No DLP web rules in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    return questionary.select(
        "Select DLP web rule:",
        choices=[
            questionary.Choice(f"{r['name']} (ID: {r['zia_id']})", value=r)
            for r in rows
        ],
    ).ask()


def _view_dlp_web_rule(tenant):
    chosen = _pick_dlp_web_rule(tenant)
    if not chosen:
        return
    _view_raw_json(f"DLP Web Rule — {chosen['name']}", chosen["raw_config"])


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
    rows.sort(key=lambda r: _rule_order_key(r["raw_config"].get("order") or r["raw_config"].get("rank") or 0))
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
    path = questionary.path("Path to JSON file:").ask()
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
        _zia_changed()
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

    path = questionary.path("Path to JSON file with updated config:").ask()
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
        _zia_changed()
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
        _zia_changed()
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
        _zia_changed()
        audit_service.log(
            product="ZIA", operation="delete_cloud_app_rule", action="DELETE",
            status="SUCCESS", tenant_id=tenant.id,
            resource_type=rule_type, details={"id": chosen["zia_id"], "name": chosen["name"]},
        )
        _sync_cloud_app_resource(client, tenant)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Cross-Tenant Snapshot Picker
# ------------------------------------------------------------------

def _pick_cross_tenant_snapshot(current_tenant):
    """Prompt user to select a source tenant (excluding current_tenant) then a ZIA
    snapshot from that tenant.

    Returns a tuple (source_tenant, snap: RestorePoint) or (None, None).
    """
    from datetime import timezone
    from db.database import get_session
    from services.config_service import list_tenants
    from services.snapshot_service import list_snapshots

    other_tenants = [t for t in list_tenants() if t.id != current_tenant.id]
    if not other_tenants:
        console.print("[yellow]No other tenants are configured.[/yellow]")
        return None, None

    tenant_choices = [questionary.Choice(t.name, value=t) for t in other_tenants]
    tenant_choices.append(questionary.Choice("<- Cancel", value=_CANCEL))
    source_tenant = questionary.select(
        "Select source tenant:",
        choices=tenant_choices,
        use_indicator=True,
    ).ask()
    if source_tenant is None or source_tenant is _CANCEL:
        return None, None

    with get_session() as session:
        snaps = list_snapshots(source_tenant.id, "ZIA", session)

    if not snaps:
        console.print(f"[yellow]No ZIA snapshots found for {source_tenant.name}.[/yellow]")
        return None, None

    snap_choices = []
    for snap in snaps:
        local_ts = snap.created_at.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        comment_suffix = f"  {snap.comment}" if snap.comment else ""
        label = f"{snap.name}  [{local_ts}]  {snap.resource_count} resources{comment_suffix}"
        snap_choices.append(questionary.Choice(label, value=snap))
    snap_choices.append(questionary.Choice("<- Cancel", value=_CANCEL))

    selected_snap = questionary.select(
        f"Select snapshot from {source_tenant.name}:",
        choices=snap_choices,
        use_indicator=True,
    ).ask()
    if selected_snap is None or selected_snap is _CANCEL:
        return None, None

    return source_tenant, selected_snap


# ------------------------------------------------------------------
# Apply Baseline from JSON
# ------------------------------------------------------------------

def _write_push_log(baseline_path, tenant, dry_run, push_records):
    """Write a full push log to the zs-config data directory.

    Returns the path written, or None if writing failed.
    """
    import platform
    from datetime import datetime, timezone
    from pathlib import Path

    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if platform.system() == "Windows":
            import os
            log_dir = Path(os.environ.get("APPDATA", Path.home())) / "zs-config" / "logs"
        else:
            log_dir = Path.home() / ".local" / "share" / "zs-config" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"zia-push-{ts}.log"

        lines = []
        lines.append(f"ZIA Baseline Push Log — {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"Tenant  : {tenant.name} (id={tenant.id})")
        lines.append(f"Baseline: {baseline_path}")
        lines.append("")

        # Dry-run summary
        lines.append("=== Dry-Run Classification ===")
        lines.append(f"  To create : {dry_run.create_count}")
        lines.append(f"  To update : {dry_run.update_count}")
        lines.append(f"  To delete : {dry_run.delete_count}")
        lines.append(f"  Skipped   : {dry_run.skip_count}")
        lines.append("")

        # Push results
        created  = sum(1 for r in push_records if r.is_created)
        updated  = sum(1 for r in push_records if r.is_updated)
        deleted  = sum(1 for r in push_records if r.is_deleted)
        failed   = sum(1 for r in push_records if r.is_failed)
        lines.append("=== Push Results ===")
        lines.append(f"  Created : {created}")
        lines.append(f"  Updated : {updated}")
        lines.append(f"  Deleted : {deleted}")
        lines.append(f"  Failed  : {failed}")
        lines.append("")

        # All records detail
        lines.append("=== All Records ===")
        for r in push_records:
            lines.append(f"  [{r.status}] {r.resource_type} :: {r.name}")
        lines.append("")

        # Full failure detail (untruncated)
        failures = [r for r in push_records if r.is_failed]
        if failures:
            lines.append("=== Failures (full detail) ===")
            for r in failures:
                lines.append(f"  {r.resource_type} :: {r.name}")
                lines.append(f"    {r.failure_reason}")
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

        # Proposed deletes not yet executed (if any remain in to_delete)
        pending_deletes = [
            r for r in dry_run.to_delete
            if not any(pr.name == r.name and pr.resource_type == r.resource_type
                       and pr.is_deleted for pr in push_records)
        ]
        if pending_deletes:
            lines.append("=== Proposed Deletes (not executed — user declined or skipped) ===")
            for r in pending_deletes:
                zia_id = r.status.partition(":")[2]
                lines.append(f"  {r.resource_type} :: {r.name}  (id={zia_id})")
            lines.append("")

        log_file.write_text("\n".join(lines), encoding="utf-8")
        return str(log_file)
    except Exception:
        return None


def apply_baseline_menu(client, tenant, *, baseline=None, baseline_path=None):
    import json
    from collections import defaultdict
    from services.zia_push_service import SKIP_TYPES, ZIAPushService

    render_banner()

    # Determine source context for display strings.
    # A cross-tenant baseline_path looks like "TenantA/snap-name" (no leading slash).
    # A file-based baseline_path is an absolute filesystem path.
    import os as _os
    _is_file_source = baseline_path is None or _os.path.isabs(str(baseline_path))
    if _is_file_source:
        _page_title    = "Apply Baseline from JSON"
        _page_subtitle = "Reads a ZIA snapshot export file and pushes it to the live tenant."
        _table_title   = "Baseline File Contents"
        _count_col     = "In File"
        _err_prefix    = "baseline file"
    else:
        _src_tenant  = baseline.get("tenant_name", baseline_path.split("/")[0]) if baseline else baseline_path.split("/")[0]
        _snap_name   = baseline.get("snapshot_name", "") if baseline else ""
        _page_title    = "Apply Snapshot from Another Tenant"
        _page_subtitle = f"Applying snapshot '{_snap_name}' from {_src_tenant} to {tenant.name}."
        _table_title   = "Snapshot Contents"
        _count_col     = "Count"
        _err_prefix    = "snapshot"

    console.print(f"\n[bold]{_page_title}[/bold]")
    console.print(f"[dim]{_page_subtitle}[/dim]\n")

    if baseline is None:
        return

    if baseline.get("product") != "ZIA":
        console.print(f"[red]✗ Invalid {_err_prefix} — 'product' must be 'ZIA'.[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    resources = baseline.get("resources")
    if not resources:
        console.print(f"[red]✗ {_err_prefix.capitalize()} has no 'resources' key.[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # ── Step 1: show what's in the baseline ───────────────────────────────
    file_table = Table(title=_table_title, show_lines=False)
    file_table.add_column("Resource Type")
    file_table.add_column(_count_col, justify="right")
    pushable_types = 0
    for rtype, entries in sorted(resources.items()):
        count = len(entries) if isinstance(entries, list) else 1
        skipped_note = "  [dim](env-specific, skipped)[/dim]" if rtype in SKIP_TYPES else ""
        file_table.add_row(rtype + skipped_note, str(count))
        if rtype not in SKIP_TYPES:
            pushable_types += 1
    console.print(file_table)

    # ── Step 1b: mode selection ────────────────────────────────────────────
    console.print()
    mode = questionary.select(
        "Push mode:",
        choices=[
            questionary.Choice(
                "Wipe-first  — delete resources absent from baseline first, then push",
                value="wipe",
            ),
            questionary.Choice(
                "Delta-only  — non-destructive merge: creates and updates only, no deletes",
                value="delta",
            ),
        ],
    ).ask()
    if mode is None:
        return

    confirmed = questionary.confirm(
        f"Compare {pushable_types} resource types against current state of {tenant.name}?",
        default=True,
    ).ask()
    if not confirmed:
        return

    # ── Step 2: import + classify (dry run) ───────────────────────────────
    service = ZIAPushService(client, tenant_id=tenant.id)
    console.print()

    with console.status(f"[cyan]Syncing current state from {tenant.name}...[/cyan]") as status:
        def _import_progress(rtype, done, total):
            status.update(f"[cyan]Comparing: {rtype} ({done}/{total})[/cyan]")

        dry_run = service.classify_baseline(baseline, import_progress_callback=_import_progress)

    creates, updates, deletes = dry_run.changes_by_action()
    create_update_count = len(creates) + len(updates)

    # ── Step 3: show dry-run summary ──────────────────────────────────────
    console.print()
    summary = dry_run.type_summary()
    delta_table = Table(title="Comparison Result (dry run)", show_lines=False)
    delta_table.add_column("Resource Type")
    delta_table.add_column("Create", justify="right", style="green")
    delta_table.add_column("Update", justify="right", style="cyan")
    delta_table.add_column("Delete", justify="right", style="red")
    delta_table.add_column("Skip", justify="right", style="dim")
    for rtype in sorted(summary):
        counts = summary[rtype]
        delta_table.add_row(
            rtype,
            str(counts["create"]) if counts["create"] else "—",
            str(counts["update"]) if counts["update"] else "—",
            str(counts["delete"]) if counts["delete"] else "—",
            str(counts["skip"])   if counts["skip"]   else "—",
        )
    console.print(delta_table)

    if create_update_count == 0 and not deletes:
        console.print("\n[green]✓ Nothing to push — target is already in sync with the baseline.[/green]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Show per-resource detail for creates and updates (cap at 30 each)
    _MAX_DETAIL = 30
    if creates:
        console.print(f"\n[green]To create ({len(creates)}):[/green]")
        for rtype, name in creates[:_MAX_DETAIL]:
            console.print(f"  [dim]{rtype}:[/dim] {name}")
        if len(creates) > _MAX_DETAIL:
            console.print(f"  [dim]... and {len(creates) - _MAX_DETAIL} more[/dim]")

    if updates:
        console.print(f"\n[cyan]To update ({len(updates)}):[/cyan]")
        for rtype, name in updates[:_MAX_DETAIL]:
            console.print(f"  [dim]{rtype}:[/dim] {name}")
        if len(updates) > _MAX_DETAIL:
            console.print(f"  [dim]... and {len(updates) - _MAX_DETAIL} more[/dim]")

    if deletes:
        if mode == "wipe":
            console.print(f"\n[red]To delete ({len(deletes)}) — present in tenant but not in baseline:[/red]")
        else:
            console.print(f"\n[dim]Not in baseline ({len(deletes)}) — skipped in delta mode (use wipe-first to remove):[/dim]")
        for rtype, name in deletes[:_MAX_DETAIL]:
            console.print(f"  [dim]{rtype}:[/dim] {name}")
        if len(deletes) > _MAX_DETAIL:
            console.print(f"  [dim]... and {len(deletes) - _MAX_DETAIL} more[/dim]")
        if mode == "wipe":
            console.print("[dim]  Wipe-first: deletes will execute before creates/updates.[/dim]")

    # ── Step 4a (wipe-first): delete extraneous resources before pushing ──
    delete_records: list = []
    deleted = 0

    if mode == "wipe" and dry_run.to_delete:
        console.print()
        confirm_wipe_deletes = questionary.confirm(
            f"Delete {len(dry_run.to_delete)} resource(s) absent from baseline before pushing?",
            default=False,
        ).ask()
        if not confirm_wipe_deletes:
            return

        console.print()
        with console.status("[red]Deleting extraneous resources...[/red]") as status:
            def _wipe_del_progress(_, rtype, rec):
                status.update(f"[red]Deleting {rtype} — {rec.name}[/red]")
            delete_records = service.execute_deletes(
                dry_run.to_delete, progress_callback=_wipe_del_progress
            )
        deleted = sum(1 for r in delete_records if r.is_deleted)
        del_failed = sum(1 for r in delete_records if r.is_failed)
        console.print(f"  [red]Deleted:[/red]  {deleted}")
        if del_failed:
            console.print(f"  [red]Failed:[/red]   {del_failed}")

        # Activate deletions before pushing to avoid stale-state ordering errors
        if deleted > 0:
            console.print()
            console.print("[dim]Activating deletions before push...[/dim]")
            try:
                client.activate()
            except Exception as e:
                console.print(f"[yellow]⚠ Activation after wipe failed: {e} — proceeding anyway[/yellow]")

    # ── Step 4b: push creates + updates ───────────────────────────────────
    push_records = []
    current_pass = [0]

    if create_update_count > 0:
        console.print()
        action_summary = []
        if creates:
            action_summary.append(f"[green]{len(creates)} create(s)[/green]")
        if updates:
            action_summary.append(f"[cyan]{len(updates)} update(s)[/cyan]")
        confirmed = questionary.confirm(
            f"Apply {', '.join(action_summary)} to {tenant.name}?",
            default=False,
        ).ask()
        if not confirmed:
            return

        console.print()
        with console.status("[cyan]Pushing...[/cyan]") as status:
            def _push_progress(pass_num, rtype, rec):
                if pass_num != current_pass[0]:
                    current_pass[0] = pass_num
                status.update(f"[cyan][Pass {pass_num}] {rtype} — {rec.name}[/cyan]")

            push_records = service.push_classified(dry_run, progress_callback=_push_progress)

    all_records = dry_run.skipped + push_records
    created  = sum(1 for r in push_records if r.is_created)
    updated  = sum(1 for r in push_records if r.is_updated)
    skipped  = sum(1 for r in all_records  if r.is_skipped)
    failed   = sum(1 for r in push_records if r.is_failed)
    passes   = current_pass[0] or 1

    if push_records:
        console.print(f"\n[bold]Push complete[/bold] — {passes} pass(es)")
        console.print(f"  [green]Created:[/green]  {created}")
        console.print(f"  [cyan]Updated:[/cyan]  {updated}")
        console.print(f"  [dim]Skipped:[/dim]  {skipped}")
        console.print(f"  [red]Failed:[/red]   {failed}")

    push_records = push_records + delete_records

    # Results table by type (push records only — skips are uninteresting here)
    if push_records:
        by_type = defaultdict(lambda: {"created": 0, "updated": 0, "deleted": 0, "failed": 0})
        for r in push_records:
            if r.is_created:
                by_type[r.resource_type]["created"] += 1
            elif r.is_updated:
                by_type[r.resource_type]["updated"] += 1
            elif r.is_deleted:
                by_type[r.resource_type]["deleted"] += 1
            elif r.is_failed:
                by_type[r.resource_type]["failed"] += 1

        results_table = Table(title="Push Results by Type", show_lines=False)
        results_table.add_column("Resource Type")
        results_table.add_column("Created", justify="right", style="green")
        results_table.add_column("Updated", justify="right", style="cyan")
        results_table.add_column("Deleted", justify="right", style="red")
        results_table.add_column("Failed",  justify="right", style="red")
        for rtype, counts in sorted(by_type.items()):
            results_table.add_row(
                rtype,
                str(counts["created"]) if counts["created"] else "—",
                str(counts["updated"]) if counts["updated"] else "—",
                str(counts["deleted"]) if counts["deleted"] else "—",
                str(counts["failed"])  if counts["failed"]  else "—",
            )
        console.print(results_table)

    # Failure detail
    failures = [r for r in push_records if r.is_failed]
    if failures:
        console.print("\n[bold red]Failures:[/bold red]")
        fail_table = Table(show_lines=False)
        fail_table.add_column("Type")
        fail_table.add_column("Name")
        fail_table.add_column("Reason")
        for r in failures:
            fail_table.add_row(r.resource_type, r.name, r.failure_reason[:80])
        console.print(fail_table)

    # Manual-action warnings (location scope stripped, custom cloud apps missing, etc.)
    warned = [r for r in push_records if r.warnings]
    if warned:
        console.print()
        console.print("[bold yellow]Manual action required:[/bold yellow]")
        console.print("[yellow]The following resources require manual steps in the target tenant.[/yellow]")
        for r in warned:
            for w in r.warnings:
                console.print(f"  [dim]{r.resource_type}:[/dim] {r.name} — {w}")

    # Write push log
    log_path = _write_push_log(baseline_path, tenant, dry_run, push_records)
    if log_path:
        console.print(f"\n[dim]Push log: {log_path}[/dim]")

    # Post-push consistency check
    verify_clean = True
    if created > 0 or updated > 0 or delete_records:
        console.print()
        verify_result = None
        with console.status("[cyan]Verifying push consistency...[/cyan]") as status:
            def _verify_progress(rtype, done, total):
                status.update(f"[cyan]Verifying: {rtype} ({done}/{total})[/cyan]")
            try:
                verify_result = service.verify_push(baseline, import_progress_callback=_verify_progress)
            except Exception as exc:
                console.print(f"[yellow]⚠ Consistency check failed: {exc}[/yellow]")

        if verify_result is not None:
            v_creates, v_updates, v_deletes = verify_result.changes_by_action()
            discrepancies = len(v_creates) + len(v_updates) + len(v_deletes)
            if discrepancies == 0:
                console.print("[green]✓ Consistency check passed — tenant state matches baseline[/green]")
            else:
                verify_clean = False
                console.print(f"[bold yellow]⚠ Consistency check found {discrepancies} discrepancy(ies):[/bold yellow]")
                disc_table = Table(show_lines=False)
                disc_table.add_column("Issue", style="yellow")
                disc_table.add_column("Resource Type")
                disc_table.add_column("Name")
                for rtype, name in v_creates:
                    disc_table.add_row("Not created", rtype, name)
                for rtype, name in v_updates:
                    disc_table.add_row("Config / order mismatch", rtype, name)
                for rtype, name in v_deletes:
                    disc_table.add_row("Not deleted", rtype, name)
                console.print(disc_table)

                remediate = questionary.confirm(
                    f"Attempt to remediate {discrepancies} discrepancy(ies) now?", default=True
                ).ask()
                if remediate:
                    remediate_pass = [0]
                    with console.status("[cyan]Remediating...[/cyan]") as status:
                        def _rem_progress(pass_num, rtype, rec):
                            if pass_num != remediate_pass[0]:
                                remediate_pass[0] = pass_num
                            status.update(f"[cyan][Pass {pass_num}] {rtype} — {rec.name}[/cyan]")
                        rem_records = service.push_classified(verify_result, progress_callback=_rem_progress)
                    rem_created = sum(1 for r in rem_records if r.is_created)
                    rem_updated = sum(1 for r in rem_records if r.is_updated)
                    rem_failed  = sum(1 for r in rem_records if r.is_failed)
                    console.print(f"  [green]Created:[/green] {rem_created}  "
                                  f"[cyan]Updated:[/cyan] {rem_updated}  "
                                  f"[red]Failed:[/red] {rem_failed}")
                    if rem_failed == 0:
                        verify_clean = True
                        push_records = push_records + rem_records
                        created += rem_created
                        updated += rem_updated
                    else:
                        console.print("[yellow]Some remediations failed — review before activating.[/yellow]")

    # Offer activation
    if created > 0 or updated > 0:
        activate_now = questionary.confirm(
            "Activate changes in ZIA now?", default=verify_clean
        ).ask()
        if activate_now:
            try:
                result = client.activate()
                state = result.get("status", "UNKNOWN") if result else "UNKNOWN"
                console.print(f"[green]✓ Activated — status: {state}[/green]")
            except Exception as e:
                console.print(f"[red]✗ Activation failed: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()
