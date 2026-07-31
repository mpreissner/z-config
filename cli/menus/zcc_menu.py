import os
from datetime import datetime

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zcc_client
from lib.zcc_client import OS_TYPE_LABELS, REGISTRATION_STATE_LABELS

console = Console()

_OS_CHOICES = [questionary.Choice(label, value=val) for val, label in OS_TYPE_LABELS.items()]
# value=0 is the "All OS types" sentinel; questionary returns the title string for value=None
_OS_CHOICES_ALL = [questionary.Choice("All OS types", value=0)] + _OS_CHOICES

_REG_STATE_CHOICES_FILTER = [
    questionary.Choice("All (except Removed)", value=None),
    questionary.Choice("Registered", value=1),
    questionary.Choice("Removal Pending", value=3),
    questionary.Choice("Unregistered", value=4),
    questionary.Choice("Removed", value=5),
    questionary.Choice("Quarantined", value=6),
]


def zcc_menu():
    client, tenant = get_zcc_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZCC  Zscaler Client Connector",
            choices=[
                questionary.Separator("── Devices ──"),
                questionary.Choice("Devices", value="devices"),
                questionary.Separator("── Device Credentials ──"),
                questionary.Choice("OTP Lookup", value="otp"),
                questionary.Choice("App Profile Passwords", value="passwords"),
                questionary.Separator("── Configuration ──"),
                questionary.Choice("Trusted Networks", value="trusted_networks"),
                questionary.Choice("Forwarding Profiles", value="forwarding_profiles"),
                questionary.Choice("Admin Users", value="admin_users"),
                questionary.Choice("Admin Roles", value="admin_roles"),
                questionary.Choice("Fail Open Policy", value="fail_open_policy"),
                questionary.Choice("Web Privacy", value="web_privacy"),
                questionary.Choice("Entitlements", value="entitlements"),
                questionary.Choice("App Profiles", value="app_profiles"),
                questionary.Choice("Bypass App Definitions", value="custom_bypasses"),
                questionary.Separator(),
                questionary.Choice("Export Devices CSV", value="export_devices"),
                questionary.Choice("Export Service Status CSV", value="export_status"),
                questionary.Choice("Export Disable Reasons CSV", value="export_disable_reasons"),
                questionary.Separator(),
                questionary.Choice("Import Config", value="import"),
                questionary.Choice("Reset N/A Resource Types", value="reset_na"),
                questionary.Separator(),
                questionary.Choice("Snapshots", value="snapshots"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "devices":
            devices_menu(client, tenant)
        elif choice == "otp":
            _otp_lookup(client, tenant)
        elif choice == "passwords":
            _password_lookup(client, tenant)
        elif choice == "trusted_networks":
            trusted_networks_menu(tenant)
        elif choice == "forwarding_profiles":
            forwarding_profiles_menu(tenant)
        elif choice == "admin_users":
            admin_users_menu(tenant)
        elif choice == "admin_roles":
            _admin_roles_menu(tenant)
        elif choice == "fail_open_policy":
            _fail_open_policy_menu(tenant)
        elif choice == "web_privacy":
            _web_privacy_menu(tenant)
        elif choice == "entitlements":
            entitlements_menu(client, tenant)
        elif choice == "app_profiles":
            _app_profiles_menu(client, tenant)
        elif choice == "custom_bypasses":
            _custom_app_bypasses_menu(tenant)
        elif choice == "export_devices":
            _export_devices(client, tenant)
        elif choice == "export_status":
            _export_service_status(client, tenant)
        elif choice == "export_disable_reasons":
            _export_disable_reasons(client, tenant)
        elif choice == "import":
            _import_zcc_config(client, tenant)
        elif choice == "reset_na":
            _reset_na_resources(client, tenant)
        elif choice == "snapshots":
            _zcc_snapshots_menu(client, tenant)
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Devices submenu
# ------------------------------------------------------------------

def devices_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Devices",
            choices=[
                questionary.Choice("List Devices", value="list"),
                questionary.Choice("Search by Username", value="search"),
                questionary.Separator(),
                questionary.Choice("Soft Remove Device", value="remove"),
                questionary.Choice("Force Remove Device", value="force_remove"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_devices(client, tenant)
        elif choice == "search":
            _search_devices(client, tenant)
        elif choice == "remove":
            _remove_device(client, tenant, force=False)
        elif choice == "force_remove":
            _remove_device(client, tenant, force=True)
        elif choice in ("back", None):
            break


def _list_devices(client, tenant, username=None, os_type=None):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    if os_type is None and username is None:
        os_type = questionary.select(
            "Filter by OS type:", choices=_OS_CHOICES_ALL
        ).ask()
        if os_type == 0:
            os_type = None  # sentinel → no filter

    with console.status("Fetching devices..."):
        try:
            devices = service.list_devices(username=username, os_type=os_type)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not devices:
        console.print("[yellow]No devices found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(
        title=f"ZCC Devices ({len(devices)} found)",
        show_lines=False,
    )
    table.add_column("Username", style="cyan")
    table.add_column("Device Name")
    table.add_column("OS", no_wrap=True)
    table.add_column("ZCC Version")
    table.add_column("Status")
    table.add_column("UDID", style="dim")

    for d in devices:
        os_int = d.get("type")
        reg_int = d.get("registration_state")
        os_str = OS_TYPE_LABELS.get(os_int, str(os_int) if os_int is not None else "—")
        reg_str = REGISTRATION_STATE_LABELS.get(reg_int, str(reg_int) if reg_int is not None else "—")
        reg_style = "green" if reg_int == 1 else ("yellow" if reg_int == 3 else "dim")
        table.add_row(
            d.get("user") or "—",
            d.get("machine_hostname") or "—",
            os_str,
            d.get("agent_version") or "—",
            f"[{reg_style}]{reg_str}[/{reg_style}]",
            d.get("udid") or "—",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_devices(client, tenant):
    username = questionary.text("Username to search:").ask()
    if not username:
        return
    _list_devices(client, tenant, username=username.strip())


def _device_details(client, tenant):
    console.print("\n[bold]Device Details[/bold]")
    lookup = questionary.select(
        "Look up by:",
        choices=[
            questionary.Choice("Username", value="username"),
            questionary.Choice("UDID", value="udid"),
        ],
    ).ask()
    if not lookup:
        return

    prompt = "Enter username (full email, e.g. user@company.com):" if lookup == "username" else "Enter UDID:"
    value = questionary.text(prompt).ask()
    if not value:
        return

    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    with console.status("Fetching device details..."):
        try:
            kwargs = {"username": value.strip()} if lookup == "username" else {"udid": value.strip()}
            details = service.get_device_details(**kwargs)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not details:
        console.print("[yellow]No device found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Render as a key-value panel
    lines = []
    field_map = [
        ("user_name", "Username"),
        ("machine_hostname", "Device Name"),
        ("type", "OS"),
        ("agent_version", "ZCC Version"),
        ("registration_state", "Status"),
        ("udid", "UDID"),
        ("owner", "Owner"),
        ("last_seen_time", "Last Seen"),
        ("tunnel_version", "Tunnel Version"),
        ("os_version", "OS Version"),
    ]
    for key, label in field_map:
        raw = details.get(key)
        if raw is None:
            continue
        if key == "type":
            raw = OS_TYPE_LABELS.get(raw, str(raw))
        elif key == "registration_state":
            raw = REGISTRATION_STATE_LABELS.get(raw, str(raw))
        lines.append(f"[bold]{label:<22}[/bold]{raw}")

    console.print(Panel("\n".join(lines), title="Device Details", border_style="cyan"))
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _remove_device(client, tenant, force: bool = False):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    op_label = "Force Remove" if force else "Soft Remove"
    console.print(f"\n[bold]{op_label} Device[/bold]")

    if force:
        console.print(
            "[yellow]Force remove permanently removes the device from the portal.\n"
            "Only Registered or Removal Pending devices can be force-removed.[/yellow]\n"
        )
    else:
        console.print(
            "[dim]Soft remove marks the device as Removal Pending. "
            "The ZCC client will be unenrolled on next connection.[/dim]\n"
        )

    by = questionary.select(
        "Target by:",
        choices=[
            questionary.Choice("Username (removes all devices for user)", value="username"),
            questionary.Choice("UDID (removes specific device)", value="udid"),
        ],
    ).ask()
    if not by:
        return

    value = questionary.text(f"Enter {by}:").ask()
    if not value:
        return
    value = value.strip()

    warning = (
        f"[red]Force remove[/red] {by} [bold]{value}[/bold]?"
        if force else
        f"Soft remove {by} [bold]{value}[/bold]?"
    )
    confirmed = questionary.confirm(warning, default=False).ask()
    if not confirmed:
        return

    kwargs = {"username": value} if by == "username" else {"udids": [value]}

    with console.status(f"{op_label} in progress..."):
        try:
            if force:
                result = service.force_remove_device(**kwargs)
            else:
                result = service.remove_device(**kwargs)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ {op_label} submitted.[/green]")
    if result:
        console.print(f"[dim]{result}[/dim]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# OTP Lookup
# ------------------------------------------------------------------

def _otp_lookup(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]OTP Lookup[/bold]")
    console.print(
        "[dim]One-time passwords are unique, single-use, and tied to a specific device UDID.[/dim]\n"
    )

    udid = questionary.text("Device UDID:").ask()
    if not udid:
        return

    with console.status("Fetching OTP..."):
        try:
            result = service.get_otp(udid=udid.strip())
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    otp = result.get("otp") or result.get("OTP") or str(result)
    console.print(
        Panel(
            f"[bold yellow]{otp}[/bold yellow]",
            title="One-Time Password",
            subtitle="[red]Single-use — do not share via insecure channels[/red]",
            border_style="yellow",
        )
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# App Profile Password Lookup
# ------------------------------------------------------------------

def _password_lookup(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]App Profile Passwords[/bold]")
    console.print("[dim]Returns the profile passwords assigned to a user on a given OS.[/dim]\n")

    username = questionary.text("Username:").ask()
    if not username:
        return

    os_type = questionary.select("OS type:", choices=_OS_CHOICES).ask()
    if os_type is None:
        return

    with console.status("Fetching passwords..."):
        try:
            result = service.get_passwords(username=username.strip(), os_type=os_type)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not result:
        console.print("[yellow]No password profile found for that user/OS combination.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    password_fields = [
        ("exitPass",        "Exit Password"),
        ("logoutPass",      "Logout Password"),
        ("uninstallPass",   "Uninstall Password"),
        ("zadDisablePass",  "ZAD Disable"),
        ("zdpDisablePass",  "ZDP Disable"),
        ("zdxDisablePass",  "ZDX Disable"),
        ("ziaDisablePass",  "ZIA Disable"),
        ("zpaDisablePass",  "ZPA Disable"),
    ]

    lines = []
    for key, label in password_fields:
        val = result.get(key)
        if val:
            lines.append(f"[bold]{label:<20}[/bold][yellow]{val}[/yellow]")

    if not lines:
        console.print("[yellow]No passwords set in this profile.[/yellow]")
    else:
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Passwords — {username} / {OS_TYPE_LABELS[os_type]}",
                border_style="yellow",
            )
        )

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# CSV Exports
# ------------------------------------------------------------------

def _export_devices(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]Export Devices CSV[/bold]\n")

    os_types = questionary.checkbox(
        "Filter by OS type (space to select, none = all):",
        choices=_OS_CHOICES,
    ).ask()

    reg_types = questionary.checkbox(
        "Filter by registration state (space to select, none = all):",
        choices=[
            questionary.Choice("Registered", value=1),
            questionary.Choice("Removal Pending", value=3),
            questionary.Choice("Unregistered", value=4),
            questionary.Choice("Removed", value=5),
            questionary.Choice("Quarantined", value=6),
        ],
    ).ask()

    default_path = os.path.expanduser(
        f"~/zcc-devices-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    filename = questionary.path("Save to:", default=default_path).ask()
    if not filename:
        return

    with console.status("Downloading..."):
        try:
            service.download_devices_csv(
                filename=filename,
                os_types=os_types or None,
                registration_types=reg_types or None,
            )
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ Saved to {filename}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _export_service_status(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]Export Service Status CSV[/bold]\n")

    os_types = questionary.checkbox(
        "Filter by OS type (space to select, none = all):",
        choices=_OS_CHOICES,
    ).ask()

    reg_types = questionary.checkbox(
        "Filter by registration state (space to select, none = all):",
        choices=[
            questionary.Choice("Registered", value=1),
            questionary.Choice("Removal Pending", value=3),
            questionary.Choice("Unregistered", value=4),
            questionary.Choice("Removed", value=5),
            questionary.Choice("Quarantined", value=6),
        ],
    ).ask()

    default_path = os.path.expanduser(
        f"~/zcc-service-status-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    filename = questionary.path("Save to:", default=default_path).ask()
    if not filename:
        return

    with console.status("Downloading..."):
        try:
            service.download_service_status_csv(
                filename=filename,
                os_types=os_types or None,
                registration_types=reg_types or None,
            )
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ Saved to {filename}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _export_disable_reasons(client, tenant):
    from services.zcc_service import ZCCService
    service = ZCCService(client, tenant_id=tenant.id)

    console.print("\n[bold]Export Disable Reasons CSV[/bold]\n")
    console.print("[dim]Columns: User, UDID, Platform, Service, Disable Time, Disable Reason[/dim]\n")

    start_date = questionary.text("Start date (YYYY-MM-DD):").ask()
    if not start_date:
        return

    end_date = questionary.text("End date (YYYY-MM-DD):").ask()
    if not end_date:
        return

    os_type_choice = questionary.select(
        "Filter by OS type:",
        choices=[questionary.Choice("All OS types", value=None)] + _OS_CHOICES,
    ).ask()

    tz_input = questionary.text(
        "Time zone for Disable Time column (IANA, e.g. America/New_York):",
        default="UTC",
    ).ask()
    if tz_input is None:
        return

    default_path = os.path.expanduser(
        f"~/zcc-disable-reasons-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    filename = questionary.path("Save to:", default=default_path).ask()
    if not filename:
        return

    with console.status("Downloading..."):
        try:
            service.download_disable_reasons_csv(
                filename=filename,
                start_date=start_date,
                end_date=end_date,
                os_type=os_type_choice,
                time_zone=tz_input or None,
            )
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ Saved to {filename}[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Import Config
# ------------------------------------------------------------------

def _import_zcc_config(client, tenant):
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from services.zcc_import_service import ZCCImportService, RESOURCE_DEFINITIONS

    console.print("\n[bold]Import ZCC Config[/bold]")
    console.print(f"[dim]Fetching {len(RESOURCE_DEFINITIONS)} resource types from ZCC.[/dim]\n")

    confirmed = questionary.confirm("Start import?", default=True).ask()
    if not confirmed:
        return

    service = ZCCImportService(client, tenant_id=tenant.id)
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


def _reset_na_resources(client, tenant):
    from services.zcc_import_service import ZCCImportService
    service = ZCCImportService(client, tenant_id=tenant.id)
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
# Trusted Networks (read-only, from ZCCResource DB cache)
# ------------------------------------------------------------------

def trusted_networks_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Trusted Networks",
            choices=[
                questionary.Choice("List Trusted Networks", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_trusted_networks(tenant)
        elif choice == "search":
            _search_trusted_networks(tenant)
        elif choice in ("back", None):
            break


def _list_trusted_networks(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="trusted_network", is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zcc_id": r.zcc_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        search_lower = search.lower()
        rows = [
            r for r in rows
            if search_lower in (r["raw_config"].get("network_name") or r["name"] or "").lower()
        ]

    if not rows:
        msg = (
            f"[yellow]No trusted networks matching '{search}'.[/yellow]" if search
            else "[yellow]No trusted networks in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZCC Trusted Networks ({len(rows)} found)", show_lines=False)
    table.add_column("Name")
    table.add_column("DNS Servers")
    table.add_column("DNS Search Domains")

    for r in rows:
        cfg = r["raw_config"]
        name = cfg.get("network_name") or r["name"] or "—"
        dns_servers = cfg.get("dns_servers") or "—"
        dns_domains = cfg.get("dns_search_domains") or "—"
        table.add_row(name, str(dns_servers), str(dns_domains))

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_trusted_networks(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_trusted_networks(tenant, search=search.strip())


# ------------------------------------------------------------------
# Forwarding Profiles (read-only, from ZCCResource DB cache)
# ------------------------------------------------------------------

def forwarding_profiles_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Forwarding Profiles",
            choices=[
                questionary.Choice("List Forwarding Profiles", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_forwarding_profiles(tenant)
        elif choice == "search":
            _search_forwarding_profiles(tenant)
        elif choice in ("back", None):
            break


def _list_forwarding_profiles(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="forwarding_profile", is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zcc_id": r.zcc_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No forwarding profiles matching '{search}'.[/yellow]" if search
            else "[yellow]No forwarding profiles in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZCC Forwarding Profiles ({len(rows)} found)", show_lines=False)
    table.add_column("Name")
    table.add_column("Active")
    table.add_column("Evaluate Trusted Network")
    table.add_column("Trusted Networks")

    for r in rows:
        cfg = r["raw_config"]
        active = str(cfg.get("active", "")) == "1"
        active_str = "[green]Yes[/green]" if active else "[red]No[/red]"
        eval_tn = cfg.get("evaluate_trusted_network", 0)
        eval_str = "Yes" if eval_tn else "No"
        trusted = cfg.get("trusted_networks") or []
        tn_str = ", ".join(trusted) if trusted else "[dim]None[/dim]"
        table.add_row(r["name"] or "—", active_str, eval_str, tn_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_forwarding_profiles(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_forwarding_profiles(tenant, search=search.strip())


# ------------------------------------------------------------------
# Admin Users (read-only, from ZCCResource DB cache)
# ------------------------------------------------------------------

def admin_users_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Admin Users",
            choices=[
                questionary.Choice("List Admin Users", value="list"),
                questionary.Choice("Search by Username", value="search"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_admin_users(tenant)
        elif choice == "search":
            _search_admin_users(tenant)
        elif choice in ("back", None):
            break


def _list_admin_users(tenant, search: str = None):
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="admin_user", is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zcc_id": r.zcc_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        search_lower = search.lower()
        rows = [r for r in rows if search_lower in (r["name"] or "").lower()]

    if not rows:
        msg = (
            f"[yellow]No admin users matching '{search}'.[/yellow]" if search
            else "[yellow]No ZCC admin users found. This tenant may manage admins through ZIdentity instead.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZCC Admin Users ({len(rows)} found)", show_lines=False)
    table.add_column("Username")
    table.add_column("Role")
    table.add_column("Email")

    for r in rows:
        cfg = r["raw_config"]
        username = r["name"] or cfg.get("login_name") or cfg.get("loginName") or "—"
        role = cfg.get("role") or cfg.get("adminRole") or "—"
        email = cfg.get("email") or "—"
        table.add_row(username, str(role), str(email))

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_admin_users(tenant):
    search = questionary.text("Search (username or partial):").ask()
    if not search:
        return
    _list_admin_users(tenant, search=search.strip())


# ------------------------------------------------------------------
# Entitlements (ZPA and ZDX group access)
# ------------------------------------------------------------------

def entitlements_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Entitlements",
            choices=[
                questionary.Separator("── ZPA Access ──"),
                questionary.Choice("View ZPA Entitlements", value="view_zpa"),
                questionary.Choice("Manage ZPA Group Access", value="manage_zpa"),
                questionary.Separator("── ZDX Access ──"),
                questionary.Choice("View ZDX Entitlements", value="view_zdx"),
                questionary.Choice("Manage ZDX Group Access", value="manage_zdx"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "view_zpa":
            _view_entitlements(client, tenant, "zpa")
        elif choice == "manage_zpa":
            _manage_entitlements(client, tenant, "zpa")
        elif choice == "view_zdx":
            _view_entitlements(client, tenant, "zdx")
        elif choice == "manage_zdx":
            _manage_entitlements(client, tenant, "zdx")
        elif choice in ("back", None):
            break


def _fetch_entitlements(client, product: str) -> dict:
    """Fetch raw entitlement data. Returns dict with 'groups' list and 'raw' for full response."""
    if product == "zpa":
        raw = client.get_zpa_entitlements()
    else:
        raw = client.get_zdx_entitlements()
    # Normalise: look for a list of group objects under common keys
    groups = (
        raw.get("upmGroupList")
        or raw.get("groupList")
        or raw.get("groups")
        or []
    )
    return {"raw": raw, "groups": groups}


def _view_entitlements(client, tenant, product: str):
    label = product.upper()
    with console.status(f"Fetching {label} entitlements..."):
        try:
            data = _fetch_entitlements(client, product)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch {label} entitlements: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    groups = data["groups"]
    raw = data["raw"]

    from services import audit_service
    audit_service.log(
        product="ZCC",
        operation=f"view_{product}_entitlements",
        action="READ",
        status="SUCCESS",
        tenant_id=tenant.id,
    )

    if not groups:
        # Show raw JSON if no normalised group list found
        import json
        from rich.syntax import Syntax
        from cli.banner import capture_banner
        from cli.scroll_view import render_rich_to_lines, scroll_view
        syntax = Syntax(json.dumps(raw, indent=2, default=str), "json", theme="monokai")
        scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())
        return

    table = Table(title=f"{label} Entitlements — Group Access ({len(groups)} groups)", show_lines=False)
    table.add_column("Group Name")
    table.add_column("Group ID", style="dim")
    table.add_column("Enabled")

    for g in groups:
        name = g.get("name") or g.get("groupName") or "—"
        gid = str(g.get("id") or g.get("groupId") or "—")
        enabled = g.get("enabled") if "enabled" in g else g.get("zdxEnabled") if "zdxEnabled" in g else None
        if enabled is True:
            enabled_str = "[green]Yes[/green]"
        elif enabled is False:
            enabled_str = "[red]No[/red]"
        else:
            enabled_str = "[dim]—[/dim]"
        table.add_row(name, gid, enabled_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _manage_entitlements(client, tenant, product: str):
    label = product.upper()
    with console.status(f"Fetching {label} entitlements..."):
        try:
            data = _fetch_entitlements(client, product)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch {label} entitlements: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    groups = data["groups"]
    raw = data["raw"]

    if not groups:
        console.print(
            f"[yellow]No group list found in {label} entitlements response.\n"
            "The API response structure may differ from expected. Use View to inspect the raw data.[/yellow]"
        )
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Build checkbox choices — pre-check currently enabled groups
    enabled_key = "enabled" if "enabled" in groups[0] else "zdxEnabled"
    choices = [
        questionary.Choice(
            title=g.get("name") or g.get("groupName") or str(g.get("id") or "?"),
            value=g,
            checked=bool(g.get(enabled_key)),
        )
        for g in groups
    ]

    selected = questionary.checkbox(
        f"Select groups to enable for {label} access:",
        choices=choices,
    ).ask()

    if selected is None:
        return

    selected_ids = {
        str(g.get("id") or g.get("groupId")) for g in selected
    }

    # Build updated payload: mark selected as enabled, others disabled
    updated_groups = []
    changes = []
    for g in groups:
        gid = str(g.get("id") or g.get("groupId") or "")
        new_enabled = gid in selected_ids
        old_enabled = bool(g.get(enabled_key))
        updated = dict(g)
        updated[enabled_key] = new_enabled
        updated_groups.append(updated)
        if new_enabled != old_enabled:
            gname = g.get("name") or g.get("groupName") or gid
            changes.append(f"  {'[green]+[/green]' if new_enabled else '[red]-[/red]'} {gname}")

    if not changes:
        console.print("[dim]No changes to apply.[/dim]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print("\n[bold]Pending changes:[/bold]")
    for c in changes:
        console.print(c)

    confirmed = questionary.confirm("Apply these changes?", default=True).ask()
    if not confirmed:
        return

    # Rebuild payload using same top-level structure as raw response
    group_key = "upmGroupList" if "upmGroupList" in raw else "groupList" if "groupList" in raw else "groups"
    payload = dict(raw)
    payload[group_key] = updated_groups

    try:
        if product == "zpa":
            client.update_zpa_entitlements(payload)
        else:
            client.update_zdx_entitlements(payload)
        console.print(f"[green]✓ {label} entitlements updated.[/green]")
        from services import audit_service
        audit_service.log(
            product="ZCC",
            operation=f"update_{product}_entitlements",
            action="UPDATE",
            status="SUCCESS",
            tenant_id=tenant.id,
            details={"changes": len(changes)},
        )
    except Exception as e:
        console.print(f"[red]✗ Error updating entitlements: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Bypass App Definitions
# Zscaler-managed (web_app_service) + user-created (custom_app_service)
# ------------------------------------------------------------------

def _custom_app_bypasses_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Bypass App Definitions",
            choices=[
                questionary.Choice("List All", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Choice("View Details", value="details"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_bypass_app_definitions(tenant)
        elif choice == "search":
            _search_bypass_app_definitions(tenant)
        elif choice == "details":
            _view_bypass_app_definition_details(tenant)
        elif choice in ("back", None):
            break


def _load_bypass_app_rows(tenant, search: str = None) -> list:
    """Load Zscaler-managed bypass app definitions (web_app_service) from DB."""
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter(
                ZCCResource.tenant_id == tenant.id,
                ZCCResource.resource_type == "web_app_service",
                ZCCResource.is_deleted == False,
            )
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {
                "name": r.name,
                "zcc_id": r.zcc_id,
                "resource_type": r.resource_type,
                "raw_config": r.raw_config or {},
            }
            for r in resources
        ]

    if search:
        sl = search.lower()
        rows = [
            r for r in rows
            if sl in (r["raw_config"].get("app_name") or r["raw_config"].get("name") or r["name"] or "").lower()
        ]

    return rows


def _bypass_row_display_name(r: dict) -> str:
    cfg = r["raw_config"]
    # web_app_service (SDK, snake_case): app_name; custom_app_service (raw API, camelCase): appName
    return cfg.get("appName") or cfg.get("app_name") or r["name"] or r["zcc_id"]


def _list_bypass_app_definitions(tenant, search: str = None):
    rows = _load_bypass_app_rows(tenant, search)

    if not rows:
        msg = (
            f"[yellow]No bypass app definitions matching '{search}'.[/yellow]" if search
            else "[yellow]No bypass app definitions in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Bypass App Definitions ({len(rows)} found)", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("ID")
    table.add_column("Protocol")
    table.add_column("Port")
    table.add_column("Active")

    for r in rows:
        cfg = r["raw_config"]
        name = _bypass_row_display_name(r)
        if r["resource_type"] == "custom_app_service":
            type_str = "[cyan]Custom[/cyan]"
        else:
            created_by = str(cfg.get("created_by") or "")
            type_str = "[dim]Zscaler[/dim]" if (not created_by or created_by.isdigit()) else "[cyan]Custom[/cyan]"
        row_id = str(cfg.get("id") or cfg.get("app_svc_id") or r["zcc_id"] or "—")
        # web_app_service: proto/port in appDataBlob (SDK snake_case: app_data_blob)
        # custom_app_service: proto/port in appData (camelCase, raw API)
        blob = cfg.get("appData") or cfg.get("appDataBlob") or cfg.get("app_data_blob") or []
        first = blob[0] if blob and isinstance(blob, list) else None
        if isinstance(first, dict):
            proto = first.get("proto") or "—"
            port = first.get("port") or "—"
        else:
            proto = cfg.get("protocol") or "—"
            port = cfg.get("port") or "—"
        active = cfg.get("active")
        active_str = "[green]Yes[/green]" if active else "[red]No[/red]"
        table.add_row(name, type_str, row_id, proto, port, active_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_bypass_app_definitions(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_bypass_app_definitions(tenant, search=search.strip())


def _view_bypass_app_definition_details(tenant):
    rows = _load_bypass_app_rows(tenant)
    if not rows:
        console.print("[yellow]No bypass app definitions in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(title=_bypass_row_display_name(r), value=r)
        for r in rows
    ]
    choices.append(questionary.Choice("← Back", value=None))

    selected = questionary.select("Select definition to view:", choices=choices, use_indicator=True).ask()
    if not isinstance(selected, dict):
        return

    import json
    from rich.syntax import Syntax
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view

    syntax = Syntax(json.dumps(selected["raw_config"], indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


# ------------------------------------------------------------------
# App Profiles (web_policy, with edit/activate/delete from DB cache)
# ------------------------------------------------------------------

def _app_profiles_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "App Profiles",
            choices=[
                questionary.Choice("List App Profiles", value="list"),
                questionary.Choice("Search by Name", value="search"),
                questionary.Choice("View Details", value="details"),
                questionary.Choice("View Traffic Profile", value="traffic_profile"),
                questionary.Choice("Manage Custom Bypass Apps", value="bypass"),
                questionary.Choice("Activate / Deactivate", value="activate"),
                questionary.Choice("Delete", value="delete"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_web_policies(tenant)
        elif choice == "search":
            _search_web_policies(tenant)
        elif choice == "details":
            _view_web_policy_details(tenant)
        elif choice == "traffic_profile":
            _view_traffic_profile(tenant)
        elif choice == "bypass":
            _select_policy_for_bypass(client, tenant)
        elif choice == "activate":
            _activate_web_policies(client, tenant)
        elif choice == "delete":
            _delete_web_policy(client, tenant)
        elif choice in ("back", None):
            break


def _load_web_app_service_rows(tenant) -> list:
    return _load_bypass_app_rows(tenant)


def _load_web_policy_rows(tenant, search: str = None) -> list:
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="web_policy", is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zcc_id": r.zcc_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        sl = search.lower()
        rows = [r for r in rows if sl in (r["name"] or "").lower()]

    return rows


def _list_web_policies(tenant, search: str = None):
    rows = _load_web_policy_rows(tenant, search)

    if not rows:
        msg = (
            f"[yellow]No app profiles matching '{search}'.[/yellow]" if search
            else "[yellow]No app profiles in local DB. Run [bold]Import Config[/bold] first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"App Profiles ({len(rows)} found)", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("ID")
    table.add_column("Platform")
    table.add_column("Active")

    _platform_labels = {
        "windows": "Windows",
        "macos": "macOS",
        "ios": "iOS",
        "android": "Android",
        "linux": "Linux",
    }

    for r in rows:
        cfg = r["raw_config"]
        name = r["name"] or cfg.get("name") or "—"
        pid = str(cfg.get("id") or r["zcc_id"] or "—")
        platform = _platform_labels.get(cfg.get("device_type", ""), cfg.get("device_type") or "—")
        active = cfg.get("active")
        active_str = "[green]Yes[/green]" if active else "[red]No[/red]"
        table.add_row(name, pid, platform, active_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _search_web_policies(tenant):
    search = questionary.text("Search (name or partial):").ask()
    if not search:
        return
    _list_web_policies(tenant, search=search.strip())


def _view_web_policy_details(tenant):
    rows = _load_web_policy_rows(tenant)
    if not rows:
        console.print("[yellow]No app profiles in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(title=r["name"] or r["zcc_id"], value=r)
        for r in rows
    ]
    choices.append(questionary.Choice("← Back", value=None))

    selected = questionary.select("Select profile to view:", choices=choices, use_indicator=True).ask()
    if not isinstance(selected, dict):
        return

    import json
    from rich.syntax import Syntax
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view

    syntax = Syntax(json.dumps(selected["raw_config"], indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


def _select_policy_for_bypass(client, tenant):
    rows = _load_web_policy_rows(tenant)
    if not rows:
        console.print("[yellow]No app profiles in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(title=r["name"] or r["zcc_id"], value=r)
        for r in rows
    ]
    choices.append(questionary.Choice("← Back", value=None))

    selected = questionary.select(
        "Select app profile to manage bypass apps:", choices=choices, use_indicator=True
    ).ask()
    if not isinstance(selected, dict):
        return

    _manage_bypass_apps(selected, client, tenant)


def _manage_bypass_apps(policy_row: dict, client, tenant):
    from services.zcc_service import ZCCService
    from services.zcc_import_service import ZCCImportService

    service = ZCCService(client, tenant_id=tenant.id)
    policy_raw = policy_row["raw_config"]
    policy_name = policy_row["name"] or policy_raw.get("name", "")
    policy_id = policy_raw.get("id") or int(policy_row["zcc_id"])

    # raw_config for web_policy uses the API's native camelCase keys
    raw_bypass_ids = policy_raw.get("bypassCustomAppIds") or policy_raw.get("bypass_custom_app_ids") or []
    current_ids = {int(x) for x in raw_bypass_ids if x is not None}

    svc_rows = _load_web_app_service_rows(tenant)
    if not svc_rows:
        console.print("[yellow]No custom app bypass services in DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    assigned = [r for r in svc_rows if r["raw_config"].get("id") in current_ids]
    unassigned = [r for r in svc_rows if r["raw_config"].get("id") not in current_ids]

    console.print(f"\n[bold]Manage Custom Bypass Apps — {policy_name}[/bold]")
    if assigned:
        console.print(f"\n[dim]Currently assigned ({len(assigned)}):[/dim]")
        for r in assigned:
            cfg = r["raw_config"]
            console.print(f"  [cyan]{cfg.get('app_name') or r['name']}[/cyan]  [dim](id: {cfg.get('id')})[/dim]")
    else:
        console.print("\n[dim]No custom bypass apps currently assigned.[/dim]")

    action = questionary.select(
        "Action:",
        choices=[
            questionary.Choice("Add bypass apps", value="add"),
            questionary.Choice("Remove bypass apps", value="remove"),
            questionary.Choice("← Back", value="back"),
        ],
    ).ask()

    if action in ("back", None):
        return

    if action == "add":
        if not unassigned:
            console.print("[yellow]All available services are already assigned.[/yellow]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return
        add_choices = [
            questionary.Choice(
                title=r["raw_config"].get("app_name") or r["name"],
                value=r["raw_config"].get("id"),
            )
            for r in unassigned
        ]
        to_add = questionary.checkbox("Select services to add:", choices=add_choices).ask()
        if not to_add:
            return
        new_ids = sorted(current_ids | {int(x) for x in to_add})
        change_desc = f"added {len(to_add)} service(s)"

    else:  # remove
        if not assigned:
            console.print("[yellow]No assigned services to remove.[/yellow]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return
        remove_choices = [
            questionary.Choice(
                title=r["raw_config"].get("app_name") or r["name"],
                value=r["raw_config"].get("id"),
            )
            for r in assigned
        ]
        to_remove = questionary.checkbox("Select services to remove:", choices=remove_choices).ask()
        if not to_remove:
            return
        new_ids = sorted(current_ids - {int(x) for x in to_remove})
        change_desc = f"removed {len(to_remove)} service(s)"

    # Keep the full raw policy dict; update bypassCustomAppIds (API native camelCase)
    updated_policy = dict(policy_raw)
    updated_policy["bypassCustomAppIds"] = new_ids
    # Remove fields not expected by the API
    updated_policy.pop("bypass_custom_app_ids", None)
    updated_policy.pop("device_type", None)

    console.print(
        f"\n[bold]Pending:[/bold] {change_desc} "
        f"({len(current_ids)} → {len(new_ids)} total)"
    )
    confirmed = questionary.confirm("Apply changes?", default=True).ask()
    if not confirmed:
        return

    with console.status("Updating app profile..."):
        try:
            service.edit_web_policy(**updated_policy)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ App profile updated ({change_desc}).[/green]")

    with console.status("Refreshing local DB..."):
        try:
            imp = ZCCImportService(client, tenant_id=tenant.id)
            imp.run(resource_types=["web_policy"])
        except Exception:
            pass

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _activate_web_policies(client, tenant):
    from services.zcc_service import ZCCService

    service = ZCCService(client, tenant_id=tenant.id)
    rows = _load_web_policy_rows(tenant)
    if not rows:
        console.print("[yellow]No app profiles in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(
            title=f"{r['name'] or r['zcc_id']}  [{'active' if r['raw_config'].get('active') else 'inactive'}]",
            value=r,
        )
        for r in rows
    ]

    selected = questionary.checkbox(
        "Select profiles to toggle (activate if inactive, deactivate if active):",
        choices=choices,
    ).ask()
    if not selected:
        return

    device_type = questionary.select(
        "Device type for activation:",
        choices=[
            questionary.Choice("Windows", value="windows"),
            questionary.Choice("macOS", value="macos"),
            questionary.Choice("iOS", value="ios"),
            questionary.Choice("Android", value="android"),
            questionary.Choice("Linux", value="linux"),
        ],
    ).ask()
    if not device_type:
        return

    confirmed = questionary.confirm(
        f"Apply activate/deactivate to {len(selected)} profile(s)?", default=True
    ).ask()
    if not confirmed:
        return

    errors = []
    for r in selected:
        cfg = r["raw_config"]
        pid = cfg.get("id") or int(r["zcc_id"])
        name = r["name"] or ""
        with console.status(f"Activating {name}..."):
            try:
                service.activate_web_policy(policy_id=pid, device_type=device_type, name=name)
                console.print(f"[green]✓ {name}[/green]")
            except Exception as e:
                errors.append(f"{name}: {e}")
                console.print(f"[red]✗ {name}: {e}[/red]")

    if errors:
        console.print(f"\n[yellow]{len(errors)} error(s) occurred.[/yellow]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_web_policy(client, tenant):
    from services.zcc_service import ZCCService
    from services.zcc_import_service import ZCCImportService

    service = ZCCService(client, tenant_id=tenant.id)
    rows = _load_web_policy_rows(tenant)
    if not rows:
        console.print("[yellow]No app profiles in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(title=r["name"] or r["zcc_id"], value=r)
        for r in rows
    ]
    choices.append(questionary.Choice("← Back", value=None))

    selected = questionary.select(
        "Select profile to delete:", choices=choices, use_indicator=True
    ).ask()
    if not isinstance(selected, dict):
        return

    cfg = selected["raw_config"]
    pid = cfg.get("id") or int(selected["zcc_id"])
    name = selected["name"] or ""

    console.print(f"\n[red]This will permanently delete:[/red] [bold]{name}[/bold] (id: {pid})")
    confirmed = questionary.confirm("Are you sure?", default=False).ask()
    if not confirmed:
        return

    with console.status("Deleting app profile..."):
        try:
            service.delete_web_policy(policy_id=pid, name=name)
        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]✓ Deleted {name}.[/green]")

    with console.status("Refreshing local DB..."):
        try:
            imp = ZCCImportService(client, tenant_id=tenant.id)
            imp.run(resource_types=["web_policy"])
        except Exception:
            pass

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# View Traffic Profile (reads from DB; requires prior Import Config)
# ------------------------------------------------------------------

def _view_traffic_profile(tenant):
    rows = _load_web_policy_rows(tenant)
    if not rows:
        console.print("[yellow]No app profiles in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(title=r["name"] or r["zcc_id"], value=r)
        for r in rows
    ]
    choices.append(questionary.Choice("← Back", value="cancel"))

    selected = questionary.select(
        "Select app profile to view traffic profile:", choices=choices, use_indicator=True
    ).ask()
    if selected == "cancel" or selected is None or not isinstance(selected, dict):
        return

    policy_raw = selected["raw_config"]
    policy_id = str(policy_raw.get("id") or selected["zcc_id"] or "")
    fp_id = str(policy_raw.get("forwardingProfileId") or "")

    from db.database import get_session
    from db.models import ZCCResource, ZIAResource

    with get_session() as session:
        fp_row = None
        if fp_id:
            fp_row = (
                session.query(ZCCResource)
                .filter_by(tenant_id=tenant.id, resource_type="forwarding_profile",
                           zcc_id=fp_id, is_deleted=False)
                .first()
            )
        raw_fp = fp_row.raw_config if fp_row else None

        pac_url = policy_raw.get("pac_url") or policy_raw.get("pacUrl") or ""
        zia_pac_file_name = None
        if pac_url:
            zia_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=tenant.id, resource_type="pac_file", is_deleted=False)
                .all()
            )
            for pac_row in zia_rows:
                rc = pac_row.raw_config or {}
                row_url = rc.get("pac_url") or rc.get("pacUrl") or rc.get("url") or ""
                if row_url and row_url == pac_url:
                    zia_pac_file_name = pac_row.name
                    break

    # Derive tunnel mode
    tunnel_mode = "Unknown"
    if raw_fp:
        actions = raw_fp.get("forwardingProfileActions") or []
        if actions and isinstance(actions[0], dict):
            first = actions[0]
            if first.get("enablePacketTunnel") is True or first.get("enablePacketTunnel") == "true":
                tunnel_mode = "Z-Tunnel 2.0"
            elif first.get("primaryTransport") == "PROXY" or first.get("systemProxy") is True:
                tunnel_mode = "Proxy"
            else:
                tunnel_mode = "Z-Tunnel 1.0"

    fp_name = (raw_fp or {}).get("name") or fp_id or "—"
    active = bool(policy_raw.get("active"))

    lines = [
        f"[bold]Policy ID:[/bold]          {policy_id}",
        f"[bold]Active:[/bold]             {'[green]Yes[/green]' if active else '[red]No[/red]'}",
        f"[bold]Tunnel Mode:[/bold]        [cyan]{tunnel_mode}[/cyan]",
        f"[bold]Forwarding Profile:[/bold] {fp_name}",
    ]
    if pac_url:
        lines.append(f"[bold]PAC URL:[/bold]            [dim]{pac_url}[/dim]")
    if zia_pac_file_name:
        lines.append(f"[bold]ZIA PAC File:[/bold]       {zia_pac_file_name}")

    pe = policy_raw.get("policyExtension") or {}
    include_routes = pe.get("packetTunnelIncludeList") or []
    exclude_routes = pe.get("packetTunnelExcludeList") or []
    dns_include = pe.get("packetTunnelDnsIncludeList") or []
    dns_exclude = pe.get("packetTunnelDnsExcludeList") or []
    port_bypasses = pe.get("sourcePortBasedBypasses") or []
    vpn_gateways = pe.get("vpnGateways") or []

    if include_routes:
        lines.append(f"[bold]Tunnel Include:[/bold]     {len(include_routes)} route(s)")
    if exclude_routes:
        lines.append(f"[bold]Tunnel Exclude:[/bold]     {len(exclude_routes)} route(s)")
    if dns_include:
        lines.append(f"[bold]DNS Include:[/bold]        {len(dns_include)} suffix(es)")
    if dns_exclude:
        lines.append(f"[bold]DNS Exclude:[/bold]        {len(dns_exclude)} suffix(es)")
    if port_bypasses:
        lines.append(f"[bold]Port Bypasses:[/bold]      {len(port_bypasses)}")
    if vpn_gateways:
        lines.append(f"[bold]VPN Gateways:[/bold]       {len(vpn_gateways)}")
    if policy_raw.get("tunnelZappTraffic"):
        lines.append("[bold]Tunnel ZApp Traffic:[/bold] [green]Yes[/green]")

    policy_name = selected["name"] or policy_id
    console.print(
        Panel(
            "\n".join(lines),
            title=f"Traffic Profile — {policy_name}",
            border_style="cyan",
        )
    )

    if include_routes or exclude_routes or dns_include or dns_exclude or port_bypasses:
        show_detail = questionary.confirm("Show route and bypass details?", default=False).ask()
        if show_detail:
            table = Table(title="Tunnel Routes & Bypasses", show_lines=False)
            table.add_column("Type")
            table.add_column("Value")
            table.add_column("Direction / Protocol")

            for cidr in include_routes:
                table.add_row("IPv4 Tunnel", cidr, "[green]include[/green]")
            for cidr in exclude_routes:
                table.add_row("IPv4 Tunnel", cidr, "[red]exclude[/red]")
            for cidr in (pe.get("packetTunnelIncludeListForIPv6") or []):
                table.add_row("IPv6 Tunnel", cidr, "[green]include[/green]")
            for cidr in (pe.get("packetTunnelExcludeListForIPv6") or []):
                table.add_row("IPv6 Tunnel", cidr, "[red]exclude[/red]")
            for s in dns_include:
                table.add_row("DNS", s, "[green]include[/green]")
            for s in dns_exclude:
                table.add_row("DNS", s, "[red]exclude[/red]")
            for pb in port_bypasses:
                if isinstance(pb, dict):
                    port = str(pb.get("port", ""))
                    proto = str(pb.get("protocol") or pb.get("proto") or "")
                    table.add_row("Port Bypass", port, proto)
            for gw in vpn_gateways:
                gw_str = gw if isinstance(gw, str) else (gw.get("gateway") or gw.get("domain") or str(gw))
                table.add_row("VPN Gateway", gw_str, "—")

            from cli.banner import capture_banner
            from cli.scroll_view import render_rich_to_lines, scroll_view
            scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())
            return

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Admin Roles (read-only, from ZCCResource DB cache)
# ------------------------------------------------------------------

def _admin_roles_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Admin Roles",
            choices=[
                questionary.Choice("List Admin Roles", value="list"),
                questionary.Choice("View Details", value="details"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_admin_roles(tenant)
        elif choice == "details":
            _view_admin_role_details(tenant)
        elif choice in ("back", None):
            break


def _load_admin_role_rows(tenant, search: str = None) -> list:
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="admin_role", is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zcc_id": r.zcc_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if search:
        sl = search.lower()
        rows = [r for r in rows if sl in (r["name"] or "").lower()]

    return rows


def _list_admin_roles(tenant, search: str = None):
    rows = _load_admin_role_rows(tenant, search)

    if not rows:
        msg = (
            f"[yellow]No admin roles matching '{search}'.[/yellow]" if search
            else "[yellow]No admin roles in local DB. Run Import Config first.[/yellow]"
        )
        console.print(msg)
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZCC Admin Roles ({len(rows)} found)", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("ID")
    table.add_column("Rank")
    table.add_column("Is Custom")

    for r in rows:
        cfg = r["raw_config"]
        name = r["name"] or cfg.get("name") or "—"
        rid = str(cfg.get("id") or r["zcc_id"] or "—")
        rank = str(cfg.get("rank") or "—")
        is_custom = cfg.get("isCustom") or cfg.get("is_custom")
        custom_str = "[green]Yes[/green]" if is_custom else "[dim]No[/dim]"
        table.add_row(name, rid, rank, custom_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _view_admin_role_details(tenant):
    rows = _load_admin_role_rows(tenant)
    if not rows:
        console.print("[yellow]No admin roles in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    choices = [
        questionary.Choice(title=r["name"] or r["zcc_id"], value=r)
        for r in rows
    ]
    choices.append(questionary.Choice("← Back", value="cancel"))

    selected = questionary.select(
        "Select role to view:", choices=choices, use_indicator=True
    ).ask()
    if selected == "cancel" or selected is None or not isinstance(selected, dict):
        return

    import json
    from rich.syntax import Syntax
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view

    syntax = Syntax(json.dumps(selected["raw_config"], indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


# ------------------------------------------------------------------
# Fail Open Policy (read-only, from ZCCResource DB cache)
# ------------------------------------------------------------------

def _fail_open_policy_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Fail Open Policy",
            choices=[
                questionary.Choice("View Policy", value="view"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "view":
            _view_fail_open_policy(tenant)
        elif choice in ("back", None):
            break


def _view_fail_open_policy(tenant):
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        resources = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="fail_open_policy", is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        rows = [
            {"name": r.name, "zcc_id": r.zcc_id, "raw_config": r.raw_config or {}}
            for r in resources
        ]

    if not rows:
        console.print("[yellow]No fail open policy in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Fail Open Policy ({len(rows)} record(s))", show_lines=False)
    table.add_column("ID")
    table.add_column("Name / Description")
    table.add_column("Fail Open")
    table.add_column("Enabled")

    for r in rows:
        cfg = r["raw_config"]
        rid = str(cfg.get("id") or r["zcc_id"] or "—")
        name = r["name"] or cfg.get("name") or cfg.get("description") or "—"
        fail_open = cfg.get("failOpen") or cfg.get("fail_open")
        enabled = cfg.get("enabled")
        fo_str = "[green]Yes[/green]" if fail_open else "[red]No[/red]"
        en_str = "[green]Yes[/green]" if enabled else "[red]No[/red]"
        table.add_row(rid, name, fo_str, en_str)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


# ------------------------------------------------------------------
# Web Privacy (singleton, read-only, from ZCCResource DB cache)
# ------------------------------------------------------------------

def _web_privacy_menu(tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "Web Privacy",
            choices=[
                questionary.Choice("View Settings", value="view"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "view":
            _view_web_privacy(tenant)
        elif choice in ("back", None):
            break


def _view_web_privacy(tenant):
    from db.database import get_session
    from db.models import ZCCResource

    with get_session() as session:
        row = (
            session.query(ZCCResource)
            .filter_by(tenant_id=tenant.id, resource_type="web_privacy", is_deleted=False)
            .first()
        )
        raw_config = row.raw_config if row else None

    if not raw_config:
        console.print("[yellow]No web privacy settings in local DB. Run Import Config first.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    import json
    from rich.syntax import Syntax
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view

    syntax = Syntax(json.dumps(raw_config, indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


# ------------------------------------------------------------------
# Snapshots submenu
# ------------------------------------------------------------------

def _zcc_snapshots_menu(client, tenant):
    while True:
        render_banner()
        choice = questionary.select(
            "ZCC Snapshots",
            choices=[
                questionary.Choice("List Snapshots", value="list"),
                questionary.Choice("Create Snapshot", value="create"),
                questionary.Choice("View Diff vs Live", value="diff"),
                questionary.Choice("Restore from Snapshot", value="restore"),
                questionary.Choice("Delete Snapshot", value="delete"),
                questionary.Separator(),
                questionary.Choice("<- Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_zcc_snapshots(tenant)
        elif choice == "create":
            _create_zcc_snapshot(client, tenant)
        elif choice == "diff":
            _diff_zcc_snapshot(client, tenant)
        elif choice == "restore":
            _restore_zcc_snapshot(client, tenant)
        elif choice == "delete":
            _delete_zcc_snapshot(tenant)
        elif choice in ("back", None):
            break


def _list_zcc_snapshots(tenant):
    from services.zcc_snapshot_service import ZCCSnapshotService
    service = ZCCSnapshotService(None, tenant.id)
    snapshots = service.list_snapshots()

    if not snapshots:
        console.print("[yellow]No snapshots found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZCC Snapshots ({len(snapshots)} found)", show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Label", style="cyan")
    table.add_column("Created", no_wrap=True)
    table.add_column("Resources")
    table.add_column("Note")

    for s in snapshots:
        created = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "—"
        table.add_row(
            str(s.id),
            s.label or "—",
            created,
            str(s.resource_count),
            s.note or "",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _create_zcc_snapshot(client, tenant):
    from services.zcc_snapshot_service import ZCCSnapshotService

    label = None
    while not label:
        label = questionary.text("Snapshot label:").ask()
        if label is None:
            return
        label = label.strip()

    note = questionary.text("Optional note (blank = none):").ask()
    if note is None:
        return
    note = note.strip() or None

    service = ZCCSnapshotService(client, tenant.id)
    with console.status("Creating snapshot..."):
        try:
            snap = service.create_snapshot(label, note)
        except Exception as e:
            console.print(f"[red]x Error: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]Snapshot created: {snap.label} ({snap.resource_count} resources)[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _diff_zcc_snapshot(client, tenant):
    from services.zcc_snapshot_service import ZCCSnapshotService

    snapshot_id = _pick_zcc_snapshot(tenant)
    if snapshot_id is None:
        return

    service = ZCCSnapshotService(client, tenant.id)
    with console.status("Computing diff..."):
        try:
            diff = service.diff_snapshot(snapshot_id)
        except Exception as e:
            console.print(f"[red]x Error: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not diff:
        console.print("[yellow]No resources in snapshot.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Diff — Snapshot {snapshot_id} vs Live", show_lines=False)
    table.add_column("Resource Type", style="cyan")
    table.add_column("Added")
    table.add_column("Removed")
    table.add_column("Changed")
    table.add_column("Unchanged")
    table.add_column("Restorable")

    for entry in diff:
        added_str = f"[yellow]{entry['added_since']}[/yellow]" if entry["added_since"] > 0 else str(entry["added_since"])
        removed_str = f"[red]{entry['removed_since']}[/red]" if entry["removed_since"] > 0 else str(entry["removed_since"])
        changed_str = f"[yellow]{entry['changed_since']}[/yellow]" if entry["changed_since"] > 0 else str(entry["changed_since"])
        restorable_str = "[green]Yes[/green]" if entry["restorable"] else "[red]No[/red]"
        table.add_row(
            entry["resource_type"],
            added_str,
            removed_str,
            changed_str,
            str(entry["unchanged"]),
            restorable_str,
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _restore_zcc_snapshot(client, tenant):
    from services.zcc_snapshot_service import ZCCSnapshotService

    snapshot_id = _pick_zcc_snapshot(tenant)
    if snapshot_id is None:
        return

    service = ZCCSnapshotService(client, tenant.id)

    with console.status("Loading diff for restore planning..."):
        try:
            diff = service.diff_snapshot(snapshot_id)
        except Exception as e:
            console.print(f"[red]x Error loading diff: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    target_choice = questionary.select(
        "Restore target:",
        choices=[
            questionary.Choice("Same tenant", value="same"),
            questionary.Choice("Different tenant", value="other"),
        ],
    ).ask()
    if target_choice is None:
        return

    target_tenant_name = None
    if target_choice == "other":
        target_tenant_name = questionary.text("Target tenant name:").ask()
        if not target_tenant_name:
            return
        target_tenant_name = target_tenant_name.strip()

    restorable_types = [e["resource_type"] for e in diff if e["restorable"]]
    if not restorable_types:
        console.print("[yellow]No restorable resource types found in this snapshot.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    type_choices = [
        questionary.Choice(rt, value=rt, checked=True)
        for rt in restorable_types
    ]
    selected_types = questionary.checkbox(
        "Select resource types to restore:",
        choices=type_choices,
    ).ask()
    if not selected_types:
        return

    dry_run = questionary.confirm("Dry run only (no changes applied)?", default=True).ask()
    if dry_run is None:
        return

    target_client = None
    target_tenant_id = None
    if target_tenant_name:
        from services.config_service import get_tenant, decrypt_secret
        from lib.auth import ZscalerAuth
        from lib.zcc_client import ZCCClient
        tgt = get_tenant(target_tenant_name)
        if not tgt:
            console.print(f"[red]x Tenant '{target_tenant_name}' not found.[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return
        tgt_auth = ZscalerAuth(
            tgt.zidentity_base_url,
            tgt.client_id,
            decrypt_secret(tgt.client_secret_enc),
            govcloud=bool(tgt.govcloud),
            gov_tier=tgt.gov_cloud_tier,
        )
        target_client = ZCCClient(tgt_auth, tgt.oneapi_base_url, tgt.zia_cloud, tgt.zia_tenant_id)
        target_tenant_id = tgt.id

    mode_label = "dry run" if dry_run else "restore"
    console.print(f"\n[bold]Starting {mode_label}...[/bold]")

    with console.status(f"Running {mode_label}..."):
        try:
            result = service.restore_snapshot(
                snapshot_id=snapshot_id,
                resource_types=selected_types,
                dry_run=dry_run,
                target_client=target_client,
                target_tenant_id=target_tenant_id,
            )
        except Exception as e:
            console.print(f"[red]x Restore failed: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    _action_styles = {
        "created": "green",
        "updated": "cyan",
        "deleted": "red",
        "skipped": "dim",
        "unrestorable": "yellow",
        "failed": "red",
    }

    results = result.get("results", [])
    summary = result.get("summary", {})

    table = Table(title=f"Restore Results {'(DRY RUN)' if dry_run else ''}", show_lines=False)
    table.add_column("Resource Type", style="cyan")
    table.add_column("Action")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Reason")

    for r in results:
        action = r["action"]
        style = _action_styles.get(action, "white")
        status_str = "[green]OK[/green]" if r["success"] else "[red]FAIL[/red]"
        table.add_row(
            r["resource_type"],
            f"[{style}]{action}[/{style}]",
            r["name"] or "—",
            status_str,
            r["reason"] or "",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())

    console.print(
        f"Created: {summary.get('created', 0)}  "
        f"Updated: {summary.get('updated', 0)}  "
        f"Deleted: {summary.get('deleted', 0)}  "
        f"Skipped: {summary.get('skipped', 0)}  "
        f"Failed: {summary.get('failed', 0)}  "
        f"Unrestorable: {summary.get('unrestorable', 0)}"
    )

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _delete_zcc_snapshot(tenant):
    from services.zcc_snapshot_service import ZCCSnapshotService

    snapshot_id = _pick_zcc_snapshot(tenant)
    if snapshot_id is None:
        return

    service = ZCCSnapshotService(None, tenant.id)
    snapshots = service.list_snapshots()
    snap = next((s for s in snapshots if s.id == snapshot_id), None)
    label = snap.label if snap else str(snapshot_id)

    confirmed = questionary.confirm(
        f"Delete snapshot '{label}'? This cannot be undone.",
        default=False,
    ).ask()
    if not confirmed:
        return

    with console.status("Deleting snapshot..."):
        try:
            service.delete_snapshot(snapshot_id)
        except Exception as e:
            console.print(f"[red]x Error: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    console.print(f"[green]Snapshot '{label}' deleted.[/green]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _pick_zcc_snapshot(tenant):
    from services.zcc_snapshot_service import ZCCSnapshotService
    service = ZCCSnapshotService(None, tenant.id)
    snapshots = service.list_snapshots()
    if not snapshots:
        console.print("[yellow]No snapshots found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    choices = [
        questionary.Choice(
            f"{s.id:4}  {s.created_at.strftime('%Y-%m-%d %H:%M')}  {s.label}  ({s.resource_count} resources)",
            value=s.id,
        )
        for s in snapshots
    ]
    choices.append(questionary.Choice("<- Cancel", value=0))

    selected = questionary.select("Select a snapshot:", choices=choices).ask()
    if selected is None or selected == 0:
        return None
    return selected
