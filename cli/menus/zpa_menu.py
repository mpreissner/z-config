import os

import questionary
from rich.console import Console
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zpa_client

console = Console()


def zpa_menu():
    client, tenant = get_zpa_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZPA",
            choices=[
                questionary.Choice("Application Segments", value="apps"),
                questionary.Choice("Certificate Management", value="certs"),
                questionary.Choice("Connectors", value="connectors"),
                questionary.Choice("Privileged Remote Access", value="pra"),
                questionary.Separator(),
                questionary.Choice("Access Policy  [coming soon]", value="noop"),
                questionary.Separator(),
                questionary.Choice("Import Config", value="import"),
                questionary.Choice("Reset N/A Resource Types", value="reset_na"),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "certs":
            cert_menu(client, tenant)
        elif choice == "import":
            _import_config(client, tenant)
        elif choice == "reset_na":
            _reset_na_resources(client, tenant)
        elif choice == "apps":
            app_segments_menu(client, tenant)
        elif choice == "pra":
            privileged_access_menu(client, tenant)
        elif choice == "connectors":
            connectors_menu(client, tenant)
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Certificate Management
# ------------------------------------------------------------------

def cert_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Certificate Management",
            choices=[
                questionary.Choice("List Certificates", value="list"),
                questionary.Choice("Rotate Certificate for Domain", value="rotate"),
                questionary.Choice("Delete Certificate", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_certificates(client, tenant)
        elif choice == "rotate":
            _rotate_certificate(client, tenant)
        elif choice == "delete":
            _delete_certificate(client, tenant)
        elif choice in ("back", None):
            break


def _list_certificates(client, tenant):
    from services.zpa_service import ZPAService
    service = ZPAService(client, tenant_id=tenant.id)
    with console.status("Fetching certificates..."):
        try:
            certs = service.list_certificates()
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return

    if not certs:
        console.print("[yellow]No certificates found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZPA Certificates ({len(certs)} total)", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Expiry")

    for c in certs:
        table.add_row(
            str(c.get("id", "")),
            c.get("name", ""),
            c.get("status", ""),
            c.get("issuedTo", "") or "[dim]—[/dim]",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _rotate_certificate(client, tenant):
    console.print("\n[bold]Rotate Certificate for Domain[/bold]")
    console.print("[dim]This will upload a new cert and update all matching apps and PRA portals.[/dim]\n")

    domain = questionary.text("Domain (e.g. *.example.com):").ask()
    if not domain:
        return

    cert_path = questionary.path("Path to certificate PEM file:").ask()
    key_path = questionary.path("Path to private key PEM file:").ask()

    if not all([cert_path, key_path]):
        return

    confirmed = questionary.confirm(
        f"Rotate certificate for '{domain}'?", default=True
    ).ask()
    if not confirmed:
        return

    from services.zpa_service import ZPAService

    service = ZPAService(client, tenant_id=tenant.id)

    with console.status(f"Rotating certificate for {domain}..."):
        try:
            result = service.rotate_certificate(cert_path, key_path, domain)
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            return

    console.print(f"\n[green]✓ Certificate rotation complete[/green]")
    console.print(f"  New cert:    [bold]{result['cert_name']}[/bold] (ID: {result['new_cert_id']})")
    console.print(f"  Apps updated:    {result['apps_updated']}")
    console.print(f"  Portals updated: {result['portals_updated']}")
    console.print(f"  Old certs deleted: {result['certs_deleted']}")

    if result["apps_updated"] + result["portals_updated"] == 0:
        console.print(
            f"\n[yellow]⚠ No resources matched domain '{domain}'. "
            "Certificate was uploaded but not assigned.[/yellow]"
        )

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Config Import
# ------------------------------------------------------------------

def _reset_na_resources(client, tenant):
    from services.zpa_import_service import ZPAImportService
    service = ZPAImportService(client, tenant_id=tenant.id)
    disabled = service._get_disabled_resource_types()
    if not disabled:
        console.print("[dim]No N/A resource types recorded for this tenant.[/dim]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return
    console.print(f"\n[yellow]N/A resource types:[/yellow] {', '.join(disabled)}")
    confirmed = questionary.confirm("Clear the N/A list? They will be retried on the next import.", default=False).ask()
    if confirmed:
        service.clear_disabled_resource_types()
        console.print("[green]✓ N/A list cleared.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _import_config(client, tenant):
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zpa_import_service import ZPAImportService, RESOURCE_DEFINITIONS

    console.print("\n[bold]Import ZPA Config[/bold]")
    console.print(f"[dim]Fetching {len(RESOURCE_DEFINITIONS)} resource types from ZPA.[/dim]\n")

    confirmed = questionary.confirm("Start import?", default=True).ask()
    if not confirmed:
        return

    service = ZPAImportService(client, tenant_id=tenant.id)
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

    # Summary
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


# ------------------------------------------------------------------
# Application Segments
# ------------------------------------------------------------------

def app_segments_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Application Segments",
            choices=[
                questionary.Choice("List Segments", value="list"),
                questionary.Choice("Search by Domain", value="search"),
                questionary.Choice("Enable / Disable", value="toggle"),
                questionary.Choice("App Segment Groups  [coming soon]", value="noop"),
                questionary.Separator(),
                questionary.Choice("Bulk Create from CSV", value="bulk"),
                questionary.Choice("Export CSV Template", value="template"),
                questionary.Choice("CSV Field Reference", value="csvhelp"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_segments(tenant)
        elif choice == "search":
            _search_by_domain(tenant)
        elif choice == "toggle":
            _toggle_enable(client, tenant)
        elif choice == "bulk":
            _bulk_create(client, tenant)
        elif choice == "template":
            _export_template()
        elif choice == "csvhelp":
            _csv_field_reference()
        elif choice in ("back", None):
            break


def _list_segments(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="application", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        # Detach data before session closes
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "raw_config": r.raw_config or {},
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No application segments in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    filter_choice = questionary.select(
        "Show:",
        choices=[
            questionary.Choice("All", value="all"),
            questionary.Choice("Enabled only", value="enabled"),
            questionary.Choice("Disabled only", value="disabled"),
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if filter_choice is None:
        return

    if filter_choice == "enabled":
        rows = [r for r in rows if r["raw_config"].get("enabled") is not False]
    elif filter_choice == "disabled":
        rows = [r for r in rows if r["raw_config"].get("enabled") is False]

    if not rows:
        console.print("[yellow]No segments match that filter.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(
        title=f"Application Segments ({len(rows)} shown)",
        show_lines=False,
    )
    table.add_column("Name")
    table.add_column("Domains")
    table.add_column("Segment Group")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        domains = cfg.get("domain_names") or []
        domain_str = "; ".join(domains[:2])
        if len(domains) > 2:
            domain_str += f" [dim]+{len(domains) - 2} more[/dim]"

        seg_group = cfg.get("segment_group_name", "")

        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"

        table.add_row(r["name"], domain_str, seg_group, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_by_domain(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    search = questionary.text("Search string (domain or partial):").ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="application", is_deleted=False)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "raw_config": r.raw_config or {},
            }
            for r in resources
            if search in " ".join(
                (r.raw_config or {}).get("domain_names") or []
            ).lower()
        ]

    if not rows:
        console.print(f"[yellow]No segments matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Matching Segments ({len(rows)})", show_lines=False)
    table.add_column("Name")
    table.add_column("Domains")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        domains = cfg.get("domain_names") or []
        domain_str = "; ".join(domains[:3])
        if len(domains) > 3:
            domain_str += f" [dim]+{len(domains) - 3} more[/dim]"
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"
        table.add_row(r["name"], domain_str, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _toggle_enable(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="application", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "enabled": (r.raw_config or {}).get("enabled", True),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No application segments in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        "Select segments:",
        choices=[
            questionary.Choice(
                f"{'✓' if r['enabled'] else '✗'}  {r['name']}",
                value=r,
            )
            for r in rows
        ],
        instruction="(Space to select, Enter to confirm, Ctrl+C to cancel)",
    ).ask()

    if not selected:
        return

    action = questionary.select(
        f"Action for {len(selected)} segment(s):",
        choices=[
            questionary.Choice("Enable", value="enable"),
            questionary.Choice("Disable", value="disable"),
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if action is None:
        return

    confirmed = questionary.confirm(
        f"{action.title()} {len(selected)} segment(s)?", default=True
    ).ask()
    if not confirmed:
        return

    success_count = 0
    fail_count = 0
    new_state = action == "enable"

    for seg in selected:
        try:
            if new_state:
                client.enable_application(seg["zpa_id"])
            else:
                client.disable_application(seg["zpa_id"])

            _update_segment_enabled_in_db(tenant.id, seg["zpa_id"], new_state)

            console.print(f"  [green]✓ {seg['name']}[/green]")
            audit_service.log(
                product="ZPA",
                operation="toggle_application",
                action="UPDATE",
                status="SUCCESS",
                tenant_id=tenant.id,
                resource_type="application",
                resource_id=seg["zpa_id"],
                resource_name=seg["name"],
                details={"enabled": new_state},
            )
            success_count += 1
        except Exception as exc:
            console.print(f"  [red]✗ {seg['name']}: {exc}[/red]")
            audit_service.log(
                product="ZPA",
                operation="toggle_application",
                action="UPDATE",
                status="FAILURE",
                tenant_id=tenant.id,
                resource_type="application",
                resource_id=seg["zpa_id"],
                resource_name=seg["name"],
                error_message=str(exc),
            )
            fail_count += 1

    console.print(
        f"\n[green]✓ {success_count} succeeded[/green]"
        + (f"  [red]✗ {fail_count} failed[/red]" if fail_count else "")
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _update_segment_enabled_in_db(tenant_id: int, zpa_id: str, enabled: bool) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="application", zpa_id=zpa_id)
            .first()
        )
        if rec:
            cfg = dict(rec.raw_config or {})
            cfg["enabled"] = enabled
            rec.raw_config = cfg
            flag_modified(rec, "raw_config")


def _bulk_create(client, tenant):
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zpa_segment_service import (
        parse_csv, dry_run, bulk_create, create_missing_groups,
    )

    console.print("\n[bold]Bulk Create Application Segments from CSV[/bold]\n")

    # 1. Prompt for CSV path
    csv_path = questionary.path("Path to CSV file:").ask()
    if not csv_path:
        return
    csv_path = os.path.expanduser(csv_path)

    # 2. Parse and validate CSV
    try:
        rows = parse_csv(csv_path)
    except ValueError as exc:
        console.print(f"\n[red]CSV validation errors:[/red]\n{exc}")
        proceed = questionary.confirm(
            "Skip invalid rows and continue with valid rows?", default=False
        ).ask()
        if not proceed:
            return
        # Re-parse skipping invalid: re-read without raising
        import csv as _csv
        rows = []
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for row in _csv.DictReader(fh):
                if (
                    row.get("name", "").strip()
                    and row.get("domain_names", "").strip()
                    and row.get("segment_group", "").strip()
                    and row.get("server_groups", "").strip()
                    and (row.get("tcp_ports", "").strip() or row.get("udp_ports", "").strip())
                ):
                    rows.append(dict(row))
        if not rows:
            console.print("[red]No valid rows to process.[/red]")
            return

    # 3. Dry run — show status table
    console.print(f"\n[dim]Validating {len(rows)} rows...[/dim]")
    annotated = dry_run(tenant.id, rows)

    dry_table = Table(title="Dry Run", show_lines=False)
    dry_table.add_column("#", style="dim", width=4)
    dry_table.add_column("Name")
    dry_table.add_column("Domains")
    dry_table.add_column("Seg Group")
    dry_table.add_column("Server Groups")
    dry_table.add_column("Ports")
    dry_table.add_column("Status")

    for idx, row in enumerate(annotated, start=1):
        status = row.get("_status", "")
        if status == "READY":
            status_cell = "[green]READY[/green]"
        elif status == "MISSING_DEPENDENCY":
            status_cell = "[yellow]MISSING_DEP[/yellow]"
        else:
            status_cell = "[red]INVALID[/red]"

        domains = [d.strip() for d in row.get("domain_names", "").split(";") if d.strip()]
        domain_str = "; ".join(domains[:2])
        if len(domains) > 2:
            domain_str += f" +{len(domains) - 2}"

        ports = []
        if row.get("tcp_ports", "").strip():
            ports.append(f"TCP:{row['tcp_ports']}")
        if row.get("udp_ports", "").strip():
            ports.append(f"UDP:{row['udp_ports']}")

        dry_table.add_row(
            str(idx),
            row.get("name", ""),
            domain_str,
            row.get("segment_group", ""),
            row.get("server_groups", ""),
            " ".join(ports),
            status_cell,
        )

    console.print(dry_table)

    # Show per-row issues
    for row in annotated:
        for issue in row.get("_issues", []):
            console.print(f"  [yellow]⚠ {row['name']}:[/yellow] {issue}")

    # 4. Offer to fix missing dependencies
    missing_dep_rows = [r for r in annotated if r.get("_status") == "MISSING_DEPENDENCY"]
    if missing_dep_rows:
        missing: dict = {"segment_group": [], "server_group": []}
        for row in missing_dep_rows:
            for issue in row.get("_issues", []):
                if "segment_group" in issue:
                    name = row["segment_group"].strip()
                    if name not in missing["segment_group"]:
                        missing["segment_group"].append(name)
                if "server_group" in issue:
                    for sg in row["server_groups"].split(";"):
                        sg = sg.strip()
                        if sg and sg not in missing["server_group"]:
                            missing["server_group"].append(sg)

        fix = questionary.confirm(
            f"Fix {len(missing_dep_rows)} rows with missing dependencies "
            f"(create missing groups)?",
            default=True,
        ).ask()
        if fix:
            with console.status("Creating missing groups..."):
                fix_result = create_missing_groups(client, tenant.id, missing)

            for name in fix_result["created"]:
                console.print(f"  [green]✓ Created {name}[/green]")
            for name in fix_result["failed"]:
                console.print(f"  [red]✗ Failed: {name}[/red]")
            for warn in fix_result["warnings"]:
                console.print(f"  [yellow]⚠ {warn}[/yellow]")

            # Re-run dry run after creating groups
            console.print("\n[dim]Re-validating...[/dim]")
            annotated = dry_run(tenant.id, rows)
            for row in annotated:
                tag = "[green]READY[/green]" if row["_status"] == "READY" else f"[yellow]{row['_status']}[/yellow]"
                console.print(f"  {tag}  {row['name']}")

    # 5. Count ready rows and confirm
    ready = [r for r in annotated if r.get("_status") == "READY"]
    not_ready = [r for r in annotated if r.get("_status") != "READY"]

    if not ready:
        console.print("\n[yellow]No READY rows — nothing to create.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    confirmed = questionary.confirm(
        f"\nCreate {len(ready)} segment(s)? "
        f"({len(not_ready)} will be skipped)",
        default=True,
    ).ask()
    if not confirmed:
        return

    # 6. Bulk create with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Creating segments...", total=len(ready))

        def on_progress(done, total):
            progress.update(task, completed=done)

        result = bulk_create(client, tenant.id, annotated, progress_callback=on_progress)

    # 7. Summary
    console.print(
        f"\n[green]✓ Created {result.created}[/green]  "
        f"[red]✗ Failed {result.failed}[/red]  "
        f"[dim]— Skipped {result.skipped}[/dim]"
    )

    # 8. Per-row errors with hints
    for detail in result.rows_detail:
        if detail["status"] == "FAILED":
            err = detail["error"] or ""
            hint = ""
            if "already exists" in err.lower():
                hint = " → segment with this name already exists in ZPA"
            elif "segment_group" in err.lower():
                hint = " → check segment group ID"
            elif "server_group" in err.lower():
                hint = " → check server group ID"
            console.print(f"  [red]{detail['name']}:[/red] {err}{hint}")

    # 9. Re-import application segments into local DB
    if result.created:
        from services.zpa_import_service import ZPAImportService
        with console.status(f"Syncing {result.created} new segment(s) to local DB..."):
            ZPAImportService(client, tenant.id).run(resource_types=["application"])
        console.print("[green]✓ Local DB updated.[/green]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _csv_field_reference():
    from rich.table import Table as RichTable

    console.print("\n[bold]CSV Field Reference — Application Segments[/bold]\n")

    t = RichTable(show_lines=True, box=None, padding=(0, 1))
    t.add_column("Field", style="bold cyan", no_wrap=True)
    t.add_column("Required", justify="center")
    t.add_column("Default", style="dim")
    t.add_column("Accepted values / format")

    rows = [
        ("name",                          "✓", "",              "Any string — must be unique within the tenant"),
        ("domain_names",                  "✓", "",              "Semicolon-separated FQDNs or wildcards\n  e.g. app.example.com;*.internal.example.com"),
        ("segment_group",                 "✓", "",              "Exact name of an existing Segment Group\n  (must be in local DB — run Import Config first)"),
        ("server_groups",                 "✓", "",              "Semicolon-separated Segment Group names\n  e.g. SG-East;SG-West"),
        ("tcp_ports",                     "if no udp", "",      "Semicolon-separated ports or ranges\n  e.g. 443  or  80;443;8080-8090"),
        ("udp_ports",                     "if no tcp", "",      "Same format as tcp_ports\n  e.g. 53;123"),
        ("description",                   "",  "(blank)",       "Free text"),
        ("enabled",                       "",  "true",          "true / false"),
        ("app_type",                      "",  "(blank)",       "Leave blank for standard segments (ZPA Client Connector access)\n  BROWSER_ACCESS  |  SIPA  |  INSPECT  |  SECURE_REMOTE_ACCESS\n  Only applies to clientless/browser-based segment types"),
        ("bypass_type",                   "",  "NEVER",         "NEVER  |  ALWAYS  |  ON_NET"),
        ("double_encrypt",                "",  "false",         "true / false"),
        ("health_check_type",             "",  "DEFAULT",       "DEFAULT  |  NONE"),
        ("health_reporting",              "",  "ON_ACCESS",     "NONE  |  ON_ACCESS  |  CONTINUOUS"),
        ("icmp_access_type",              "",  "NONE",          "NONE  |  PING  |  PING_TRACEROUTING"),
        ("passive_health_enabled",        "",  "true",          "true / false"),
        ("is_cname_enabled",              "",  "true",          "true / false"),
        ("select_connector_close_to_app", "",  "false",         "true / false"),
    ]

    for row in rows:
        req_style = "green" if row[1] == "✓" else ("yellow" if row[1].startswith("if") else "dim")
        t.add_row(row[0], f"[{req_style}]{row[1]}[/{req_style}]", row[2], row[3])

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view

    lines = render_rich_to_lines(t)
    lines += render_rich_to_lines(
        "\n[dim]Port format examples:[/dim]\n"
        "  [cyan]443[/cyan]              single port\n"
        "  [cyan]8080-8090[/cyan]        range (inclusive)\n"
        "  [cyan]80;443;8080-8090[/cyan] multiple entries separated by semicolons\n"
    )
    scroll_view(lines, header_ansi=capture_banner())


def _export_template():
    from services.zpa_segment_service import CSV_FIELDNAMES, TEMPLATE_ROWS

    default_path = os.path.expanduser("~/app_segment_template.csv")
    out_path = questionary.path(
        "Output path:", default=default_path
    ).ask()
    if not out_path:
        return
    out_path = os.path.expanduser(out_path)

    import csv as _csv
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = _csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(TEMPLATE_ROWS)

    console.print(f"[green]✓ Template written to {out_path}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Privileged Remote Access
# ------------------------------------------------------------------

def privileged_access_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Privileged Remote Access",
            choices=[
                questionary.Choice("PRA Portals", value="portals"),
                questionary.Choice("PRA Consoles  [coming soon]", value="noop"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "portals":
            pra_portals_menu(client, tenant)
        elif choice in ("back", None):
            break


# PRA Portals
# ------------------------------------------------------------------

def pra_portals_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "PRA Portals",
            choices=[
                questionary.Choice("List PRA Portals", value="list"),
                questionary.Choice("Search by Domain", value="search"),
                questionary.Choice("Create Portal", value="create"),
                questionary.Choice("Enable / Disable", value="toggle"),
                questionary.Choice("Delete Portal", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_pra_portals(tenant)
        elif choice == "search":
            _search_pra_by_domain(tenant)
        elif choice == "create":
            _create_pra_portal(client, tenant)
        elif choice == "toggle":
            _toggle_pra_portal(client, tenant)
        elif choice == "delete":
            _delete_pra_portal(client, tenant)
        elif choice in ("back", None):
            break


def _list_pra_portals(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="pra_portal", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

        cert_rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="certificate", is_deleted=False)
            .all()
        )
        cert_map = {str(c.zpa_id): c.name for c in cert_rows}

    if not rows:
        console.print(
            "[yellow]No PRA Portals in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"PRA Portals ({len(rows)} total)", show_lines=False)
    table.add_column("Name")
    table.add_column("Domain")
    table.add_column("Enabled")
    table.add_column("Certificate")

    for r in rows:
        cfg = r["raw_config"]
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"

        cert_id = cfg.get("certificateId") or cfg.get("certificate_id")
        if not cert_id or str(cert_id) in ("0", ""):
            cert_str = "[dim]Zscaler-managed[/dim]"
        else:
            cert_str = cert_map.get(str(cert_id), str(cert_id))

        table.add_row(
            r["name"],
            cfg.get("domain", ""),
            enabled_str,
            cert_str,
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_pra_by_domain(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    search = questionary.text(
        "Search string (domain or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="pra_portal", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.raw_config or {}).get("domain", "").lower()
        ]

        cert_rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="certificate", is_deleted=False)
            .all()
        )
        cert_map = {str(c.zpa_id): c.name for c in cert_rows}

    if not rows:
        console.print(f"[yellow]No PRA Portals matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Matching PRA Portals ({len(rows)})", show_lines=False)
    table.add_column("Name")
    table.add_column("Domain")
    table.add_column("Enabled")
    table.add_column("Certificate")

    for r in rows:
        cfg = r["raw_config"]
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"

        cert_id = cfg.get("certificateId") or cfg.get("certificate_id")
        if not cert_id or str(cert_id) in ("0", ""):
            cert_str = "[dim]Zscaler-managed[/dim]"
        else:
            cert_str = cert_map.get(str(cert_id), str(cert_id))

        table.add_row(r["name"], cfg.get("domain", ""), enabled_str, cert_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _create_pra_portal(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service
    from services.zpa_import_service import ZPAImportService

    # 1. Gather basic fields
    name = questionary.text("Portal name:").ask()
    if not name:
        return

    domain = questionary.text("Domain (e.g. pra.example.com):").ask()
    if not domain:
        return

    description = questionary.text(
        "Description (optional — blank to skip):"
    ).ask() or ""

    # 2. Certificate selection
    with get_session() as session:
        cert_rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="certificate", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        certs = [
            {"id": c.zpa_id, "name": c.name or c.zpa_id}
            for c in cert_rows
        ]

    if not certs:
        console.print(
            "[yellow]No certificates in DB — run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    cert_choice = questionary.select(
        "Certificate:",
        choices=[
            questionary.Choice(f"{c['name']}  (ID: {c['id']})", value=c)
            for c in certs
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if cert_choice is None:
        return

    # 3. Enabled / user notification
    enabled = questionary.confirm("Enable portal?", default=True).ask()
    if enabled is None:
        return

    notif_enabled = questionary.confirm(
        "Enable user notification?", default=False
    ).ask()
    if notif_enabled is None:
        return

    user_notification = ""
    if notif_enabled:
        user_notification = questionary.text("Notification text/HTML:").ask() or ""

    # 4. Confirm
    confirmed = questionary.confirm(
        f"Create portal '{name}'?", default=True
    ).ask()
    if not confirmed:
        return

    # 5. API call
    kwargs = {
        "name": name,
        "domain": domain,
        "certificate_id": cert_choice["id"],
        "enabled": enabled,
        "user_notification_enabled": notif_enabled,
    }
    if description:
        kwargs["description"] = description
    if user_notification:
        kwargs["user_notification"] = user_notification

    try:
        result = client.create_pra_portal(**kwargs)
    except Exception as exc:
        console.print(f"[red]✗ Error creating portal: {exc}[/red]")
        audit_service.log(
            product="ZPA",
            operation="create_pra_portal",
            action="CREATE",
            status="FAILURE",
            tenant_id=tenant.id,
            resource_type="pra_portal",
            resource_name=name,
            error_message=str(exc),
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # 6. Audit log
    audit_service.log(
        product="ZPA",
        operation="create_pra_portal",
        action="CREATE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="pra_portal",
        resource_id=str(result.get("id", "")),
        resource_name=name,
        details={"domain": domain, "certificate_id": cert_choice["id"]},
    )

    # 7. Re-import pra_portal into local DB
    with console.status("Syncing to local DB..."):
        ZPAImportService(client, tenant.id).run(resource_types=["pra_portal"])

    console.print(f"[green]✓ Portal '{name}' created.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _toggle_pra_portal(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="pra_portal", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "domain": (r.raw_config or {}).get("domain", ""),
                "enabled": (r.raw_config or {}).get("enabled", True),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No PRA Portals in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        "Select portals:",
        choices=[
            questionary.Choice(
                f"{'✓' if r['enabled'] else '✗'}  {r['name']}  ({r['domain']})",
                value=r,
            )
            for r in rows
        ],
        instruction="(Space to select, Enter to confirm, Ctrl+C to cancel)",
    ).ask()

    if not selected:
        return

    action = questionary.select(
        f"Action for {len(selected)} portal(s):",
        choices=[
            questionary.Choice("Enable", value="enable"),
            questionary.Choice("Disable", value="disable"),
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if action is None:
        return

    confirmed = questionary.confirm(
        f"{action.title()} {len(selected)} portal(s)?", default=True
    ).ask()
    if not confirmed:
        return

    new_state = action == "enable"
    success_count = 0
    fail_count = 0

    for portal in selected:
        try:
            config = client.get_pra_portal(portal["zpa_id"])
            config["enabled"] = new_state
            client.update_pra_portal(portal["zpa_id"], config)

            _update_pra_portal_enabled_in_db(tenant.id, portal["zpa_id"], new_state)

            icon = "✓" if new_state else "✗"
            color = "green" if new_state else "red"
            console.print(f"  [{color}]{icon} {portal['name']}[/{color}]")

            audit_service.log(
                product="ZPA",
                operation="toggle_pra_portal",
                action="UPDATE",
                status="SUCCESS",
                tenant_id=tenant.id,
                resource_type="pra_portal",
                resource_id=portal["zpa_id"],
                resource_name=portal["name"],
                details={"enabled": new_state},
            )
            success_count += 1
        except Exception as exc:
            console.print(f"  [red]✗ {portal['name']}: {exc}[/red]")
            audit_service.log(
                product="ZPA",
                operation="toggle_pra_portal",
                action="UPDATE",
                status="FAILURE",
                tenant_id=tenant.id,
                resource_type="pra_portal",
                resource_id=portal["zpa_id"],
                resource_name=portal["name"],
                error_message=str(exc),
            )
            fail_count += 1

    console.print(
        f"\n[green]✓ {success_count} succeeded[/green]"
        + (f"  [red]✗ {fail_count} failed[/red]" if fail_count else "")
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _update_pra_portal_enabled_in_db(tenant_id: int, zpa_id: str, enabled: bool) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="pra_portal", zpa_id=zpa_id)
            .first()
        )
        if rec:
            cfg = dict(rec.raw_config or {})
            cfg["enabled"] = enabled
            rec.raw_config = cfg
            flag_modified(rec, "raw_config")


def _delete_pra_portal(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="pra_portal", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "domain": (r.raw_config or {}).get("domain", ""),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No PRA Portals in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    portal = questionary.select(
        "Select portal to delete:",
        choices=[
            questionary.Choice(
                f"{r['name']}  ({r['domain']})",
                value=r,
            )
            for r in rows
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()

    if not portal:
        return

    confirmed = questionary.confirm(
        f"Delete '{portal['name']}'? This cannot be undone.", default=False
    ).ask()
    if not confirmed:
        return

    try:
        client.delete_pra_portal(portal["zpa_id"])
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/red]")
        audit_service.log(
            product="ZPA",
            operation="delete_pra_portal",
            action="DELETE",
            status="FAILURE",
            tenant_id=tenant.id,
            resource_type="pra_portal",
            resource_id=portal["zpa_id"],
            resource_name=portal["name"],
            error_message=str(exc),
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Mark deleted in local DB immediately
    from sqlalchemy.orm.attributes import flag_modified
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(
                tenant_id=tenant.id,
                resource_type="pra_portal",
                zpa_id=portal["zpa_id"],
            )
            .first()
        )
        if rec:
            rec.is_deleted = True

    audit_service.log(
        product="ZPA",
        operation="delete_pra_portal",
        action="DELETE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="pra_portal",
        resource_id=portal["zpa_id"],
        resource_name=portal["name"],
    )

    console.print("[green]✓ Portal deleted.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_certificate(client, tenant):
    with console.status("Fetching certificates..."):
        try:
            certs = client.list_certificates()
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            return

    if not certs:
        console.print("[yellow]No certificates found.[/yellow]")
        return

    cert = questionary.select(
        "Select certificate to delete:",
        choices=[
            questionary.Choice(
                f"{c.get('name', 'unnamed')}  (ID: {c.get('id')})",
                value=c,
            )
            for c in certs
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()

    if not cert:
        return

    confirmed = questionary.confirm(
        f"Delete '{cert.get('name')}'? This cannot be undone.", default=False
    ).ask()
    if not confirmed:
        return

    from services.zpa_service import ZPAService

    service = ZPAService(client, tenant_id=tenant.id)
    try:
        service.delete_certificate(str(cert["id"]))
        console.print(f"[green]✓ Certificate deleted.[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Connectors
# ------------------------------------------------------------------

def connectors_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Connectors",
            choices=[
                questionary.Choice("List Connectors", value="list"),
                questionary.Choice("Search Connectors", value="search"),
                questionary.Choice("Enable / Disable", value="toggle"),
                questionary.Choice("Rename Connector", value="rename"),
                questionary.Choice("Delete Connector", value="delete"),
                questionary.Separator(),
                questionary.Choice("List Connector Groups", value="list_groups"),
                questionary.Choice("Search Connector Groups", value="search_groups"),
                questionary.Choice("Create Connector Group", value="create_group"),
                questionary.Choice("Enable / Disable Group", value="toggle_group"),
                questionary.Choice("Delete Connector Group", value="delete_group"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_connectors(tenant)
        elif choice == "search":
            _search_connectors(tenant)
        elif choice == "toggle":
            _toggle_connector(client, tenant)
        elif choice == "rename":
            _rename_connector(client, tenant)
        elif choice == "delete":
            _delete_connector(client, tenant)
        elif choice == "list_groups":
            _list_connector_groups(tenant)
        elif choice == "search_groups":
            _search_connector_groups(tenant)
        elif choice == "create_group":
            _create_connector_group(client, tenant)
        elif choice == "toggle_group":
            _toggle_connector_group(client, tenant)
        elif choice == "delete_group":
            _delete_connector_group(client, tenant)
        elif choice in ("back", None):
            break


def _list_connectors(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No App Connectors in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"App Connectors ({len(rows)} total)", show_lines=False)
    table.add_column("Name")
    table.add_column("Group")
    table.add_column("Status")
    table.add_column("Private IP")
    table.add_column("Version")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        group = cfg.get("app_connector_group_name", "—") or "—"
        status_val = cfg.get("control_channel_status", "—") or "—"
        status_str = (
            f"[green]{status_val}[/green]"
            if status_val == "ZPN_STATUS_AUTHENTICATED"
            else f"[red]{status_val}[/red]"
        )
        private_ip = cfg.get("private_ip", "—") or "—"
        version = cfg.get("current_version", "—") or "—"
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"
        table.add_row(r["name"], group, status_str, private_ip, version, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_connectors(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No connectors matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Matching Connectors ({len(rows)})", show_lines=False)
    table.add_column("Name")
    table.add_column("Group")
    table.add_column("Status")
    table.add_column("Private IP")
    table.add_column("Version")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        group = cfg.get("app_connector_group_name", "—") or "—"
        status_val = cfg.get("control_channel_status", "—") or "—"
        status_str = (
            f"[green]{status_val}[/green]"
            if status_val == "ZPN_STATUS_AUTHENTICATED"
            else f"[red]{status_val}[/red]"
        )
        private_ip = cfg.get("private_ip", "—") or "—"
        version = cfg.get("current_version", "—") or "—"
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"
        table.add_row(r["name"], group, status_str, private_ip, version, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _toggle_connector(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "group": (r.raw_config or {}).get("app_connector_group_name", ""),
                "enabled": (r.raw_config or {}).get("enabled", True),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No App Connectors in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        "Select connectors:",
        choices=[
            questionary.Choice(
                f"{'✓' if r['enabled'] else '✗'}  {r['name']}  ({r['group']})",
                value=r,
            )
            for r in rows
        ],
        instruction="(Space to select, Enter to confirm, Ctrl+C to cancel)",
    ).ask()

    if not selected:
        return

    action = questionary.select(
        f"Action for {len(selected)} connector(s):",
        choices=[
            questionary.Choice("Enable", value="enable"),
            questionary.Choice("Disable", value="disable"),
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if action is None:
        return

    confirmed = questionary.confirm(
        f"{action.title()} {len(selected)} connector(s)?", default=True
    ).ask()
    if not confirmed:
        return

    new_state = action == "enable"
    success_count = 0
    fail_count = 0

    for connector in selected:
        try:
            config = client.get_connector(connector["zpa_id"])
            config["enabled"] = new_state
            client.update_connector(connector["zpa_id"], config)

            _update_connector_enabled_in_db(tenant.id, connector["zpa_id"], new_state)

            icon = "✓" if new_state else "✗"
            color = "green" if new_state else "red"
            console.print(f"  [{color}]{icon} {connector['name']}[/{color}]")

            audit_service.log(
                product="ZPA",
                operation="toggle_connector",
                action="UPDATE",
                status="SUCCESS",
                tenant_id=tenant.id,
                resource_type="app_connector",
                resource_id=connector["zpa_id"],
                resource_name=connector["name"],
                details={"enabled": new_state},
            )
            success_count += 1
        except Exception as exc:
            console.print(f"  [red]✗ {connector['name']}: {exc}[/red]")
            audit_service.log(
                product="ZPA",
                operation="toggle_connector",
                action="UPDATE",
                status="FAILURE",
                tenant_id=tenant.id,
                resource_type="app_connector",
                resource_id=connector["zpa_id"],
                resource_name=connector["name"],
                error_message=str(exc),
            )
            fail_count += 1

    console.print(
        f"\n[green]✓ {success_count} succeeded[/green]"
        + (f"  [red]✗ {fail_count} failed[/red]" if fail_count else "")
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _rename_connector(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service
    from sqlalchemy.orm.attributes import flag_modified

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "group": (r.raw_config or {}).get("app_connector_group_name", ""),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No App Connectors in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    connector = questionary.select(
        "Select connector to rename:",
        choices=[
            questionary.Choice(
                f"{r['name']}  ({r['group']})",
                value=r,
            )
            for r in rows
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if connector is None:
        return

    old_name = connector["name"]
    new_name = questionary.text("New name:", default=old_name).ask()
    if not new_name or new_name == old_name:
        return

    confirmed = questionary.confirm(
        f"Rename '{old_name}' → '{new_name}'?", default=True
    ).ask()
    if not confirmed:
        return

    try:
        config = client.get_connector(connector["zpa_id"])
        config["name"] = new_name
        client.update_connector(connector["zpa_id"], config)
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/red]")
        audit_service.log(
            product="ZPA",
            operation="rename_connector",
            action="UPDATE",
            status="FAILURE",
            tenant_id=tenant.id,
            resource_type="app_connector",
            resource_id=connector["zpa_id"],
            resource_name=old_name,
            error_message=str(exc),
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(
                tenant_id=tenant.id,
                resource_type="app_connector",
                zpa_id=connector["zpa_id"],
            )
            .first()
        )
        if rec:
            cfg = dict(rec.raw_config or {})
            cfg["name"] = new_name
            rec.raw_config = cfg
            flag_modified(rec, "raw_config")
            rec.name = new_name

    audit_service.log(
        product="ZPA",
        operation="rename_connector",
        action="UPDATE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="app_connector",
        resource_id=connector["zpa_id"],
        resource_name=new_name,
        details={"old_name": old_name, "new_name": new_name},
    )

    console.print("[green]✓ Renamed.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_connector(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "group": (r.raw_config or {}).get("app_connector_group_name", ""),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No App Connectors in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    connector = questionary.select(
        "Select connector to delete:",
        choices=[
            questionary.Choice(
                f"{r['name']}  ({r['group']})",
                value=r,
            )
            for r in rows
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if connector is None:
        return

    confirmed = questionary.confirm(
        f"Delete '{connector['name']}'? This cannot be undone.", default=False
    ).ask()
    if not confirmed:
        return

    try:
        client.delete_connector(connector["zpa_id"])
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/red]")
        audit_service.log(
            product="ZPA",
            operation="delete_connector",
            action="DELETE",
            status="FAILURE",
            tenant_id=tenant.id,
            resource_type="app_connector",
            resource_id=connector["zpa_id"],
            resource_name=connector["name"],
            error_message=str(exc),
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(
                tenant_id=tenant.id,
                resource_type="app_connector",
                zpa_id=connector["zpa_id"],
            )
            .first()
        )
        if rec:
            rec.is_deleted = True

    audit_service.log(
        product="ZPA",
        operation="delete_connector",
        action="DELETE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="app_connector",
        resource_id=connector["zpa_id"],
        resource_name=connector["name"],
    )

    console.print("[green]✓ Connector deleted.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _update_connector_enabled_in_db(tenant_id: int, zpa_id: str, enabled: bool) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="app_connector", zpa_id=zpa_id)
            .first()
        )
        if rec:
            cfg = dict(rec.raw_config or {})
            cfg["enabled"] = enabled
            rec.raw_config = cfg
            flag_modified(rec, "raw_config")


# ------------------------------------------------------------------
# Connector Groups
# ------------------------------------------------------------------

def _list_connector_groups(tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from collections import defaultdict

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector_group", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

        connector_rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .all()
        )
        count_map: dict = defaultdict(int)
        for c in connector_rows:
            gid = str((c.raw_config or {}).get("app_connector_group_id", ""))
            if gid:
                count_map[gid] += 1

    if not rows:
        console.print(
            "[yellow]No Connector Groups in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Connector Groups ({len(rows)} total)", show_lines=False)
    table.add_column("Name")
    table.add_column("Location")
    table.add_column("Connectors", justify="right")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        location = cfg.get("location") or cfg.get("city_country") or "—"
        connector_count = str(count_map.get(str(r["zpa_id"]), 0))
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"
        table.add_row(r["name"], location, connector_count, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_connector_groups(tenant):
    from db.database import get_session
    from db.models import ZPAResource

    search = questionary.text(
        "Search (name or partial):",
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if not search:
        return
    search = search.lower()

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector_group", is_deleted=False)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
            if search in (r.name or "").lower()
        ]

    if not rows:
        console.print(f"[yellow]No connector groups matching '{search}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Matching Connector Groups ({len(rows)})", show_lines=False)
    table.add_column("Name")
    table.add_column("Location")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        location = cfg.get("location") or cfg.get("city_country") or "—"
        enabled = cfg.get("enabled", True)
        enabled_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"
        table.add_row(r["name"], location, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _create_connector_group(client, tenant):
    from services import audit_service
    from services.zpa_import_service import ZPAImportService

    name = questionary.text("Group name:").ask()
    if not name:
        return

    description = questionary.text(
        "Description (optional — blank to skip):"
    ).ask() or ""

    confirmed = questionary.confirm(
        f"Create connector group '{name}'?", default=True
    ).ask()
    if not confirmed:
        return

    kwargs = {"name": name, "enabled": True}
    if description:
        kwargs["description"] = description

    try:
        result = client.create_connector_group(**kwargs)
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/red]")
        audit_service.log(
            product="ZPA",
            operation="create_connector_group",
            action="CREATE",
            status="FAILURE",
            tenant_id=tenant.id,
            resource_type="app_connector_group",
            resource_name=name,
            error_message=str(exc),
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    audit_service.log(
        product="ZPA",
        operation="create_connector_group",
        action="CREATE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="app_connector_group",
        resource_id=str(result.get("id", "")),
        resource_name=name,
    )

    with console.status("Syncing to local DB..."):
        ZPAImportService(client, tenant.id).run(resource_types=["app_connector_group"])

    console.print(f"[green]✓ Connector group '{name}' created.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _toggle_connector_group(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector_group", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zpa_id": r.zpa_id,
                "location": (r.raw_config or {}).get("location")
                    or (r.raw_config or {}).get("city_country", ""),
                "enabled": (r.raw_config or {}).get("enabled", True),
            }
            for r in resources
        ]

    if not rows:
        console.print(
            "[yellow]No Connector Groups in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    selected = questionary.checkbox(
        "Select connector groups:",
        choices=[
            questionary.Choice(
                f"{'✓' if r['enabled'] else '✗'}  {r['name']}  ({r['location']})",
                value=r,
            )
            for r in rows
        ],
        instruction="(Space to select, Enter to confirm, Ctrl+C to cancel)",
    ).ask()

    if not selected:
        return

    action = questionary.select(
        f"Action for {len(selected)} group(s):",
        choices=[
            questionary.Choice("Enable", value="enable"),
            questionary.Choice("Disable", value="disable"),
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if action is None:
        return

    confirmed = questionary.confirm(
        f"{action.title()} {len(selected)} group(s)?", default=True
    ).ask()
    if not confirmed:
        return

    new_state = action == "enable"
    success_count = 0
    fail_count = 0

    for group in selected:
        try:
            config = client.get_connector_group(group["zpa_id"])
            config["enabled"] = new_state
            client.update_connector_group(group["zpa_id"], config)

            _update_connector_group_enabled_in_db(tenant.id, group["zpa_id"], new_state)

            icon = "✓" if new_state else "✗"
            color = "green" if new_state else "red"
            console.print(f"  [{color}]{icon} {group['name']}[/{color}]")

            audit_service.log(
                product="ZPA",
                operation="toggle_connector_group",
                action="UPDATE",
                status="SUCCESS",
                tenant_id=tenant.id,
                resource_type="app_connector_group",
                resource_id=group["zpa_id"],
                resource_name=group["name"],
                details={"enabled": new_state},
            )
            success_count += 1
        except Exception as exc:
            console.print(f"  [red]✗ {group['name']}: {exc}[/red]")
            audit_service.log(
                product="ZPA",
                operation="toggle_connector_group",
                action="UPDATE",
                status="FAILURE",
                tenant_id=tenant.id,
                resource_type="app_connector_group",
                resource_id=group["zpa_id"],
                resource_name=group["name"],
                error_message=str(exc),
            )
            fail_count += 1

    console.print(
        f"\n[green]✓ {success_count} succeeded[/green]"
        + (f"  [red]✗ {fail_count} failed[/red]" if fail_count else "")
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_connector_group(client, tenant):
    from db.database import get_session
    from db.models import ZPAResource
    from services import audit_service
    from collections import defaultdict

    with get_session() as session:
        resources = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector_group", is_deleted=False)
            .order_by(ZPAResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zpa_id": r.zpa_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

        connector_rows = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant.id, resource_type="app_connector", is_deleted=False)
            .all()
        )
        count_map: dict = defaultdict(int)
        for c in connector_rows:
            gid = str((c.raw_config or {}).get("app_connector_group_id", ""))
            if gid:
                count_map[gid] += 1

    if not rows:
        console.print(
            "[yellow]No Connector Groups in local DB. "
            "Run [bold]Import Config[/bold] first.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    group = questionary.select(
        "Select connector group to delete:",
        choices=[
            questionary.Choice(
                f"{r['name']}  ({count_map.get(str(r['zpa_id']), 0)} connectors)",
                value=r,
            )
            for r in rows
        ],
        instruction="(Ctrl+C to cancel)",
    ).ask()
    if group is None:
        return

    confirmed = questionary.confirm(
        f"Delete group '{group['name']}'? This cannot be undone.", default=False
    ).ask()
    if not confirmed:
        return

    try:
        client.delete_connector_group(group["zpa_id"])
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/red]")
        audit_service.log(
            product="ZPA",
            operation="delete_connector_group",
            action="DELETE",
            status="FAILURE",
            tenant_id=tenant.id,
            resource_type="app_connector_group",
            resource_id=group["zpa_id"],
            resource_name=group["name"],
            error_message=str(exc),
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(
                tenant_id=tenant.id,
                resource_type="app_connector_group",
                zpa_id=group["zpa_id"],
            )
            .first()
        )
        if rec:
            rec.is_deleted = True

    audit_service.log(
        product="ZPA",
        operation="delete_connector_group",
        action="DELETE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="app_connector_group",
        resource_id=group["zpa_id"],
        resource_name=group["name"],
    )

    console.print("[green]✓ Connector group deleted.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _update_connector_group_enabled_in_db(tenant_id: int, zpa_id: str, enabled: bool) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from db.database import get_session
    from db.models import ZPAResource

    with get_session() as session:
        rec = (
            session.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="app_connector_group", zpa_id=zpa_id)
            .first()
        )
        if rec:
            cfg = dict(rec.raw_config or {})
            cfg["enabled"] = enabled
            rec.raw_config = cfg
            flag_modified(rec, "raw_config")
