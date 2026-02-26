import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.banner import render_banner
from cli.menus import select_tenant

console = Console()


def _active_tenant_label() -> str:
    from cli.session import get_active_tenant
    t = get_active_tenant()
    return f"  Tenant Management  (active: {t.name})" if t else "  Tenant Management"


def main_menu():
    while True:
        render_banner()
        choice = questionary.select(
            "Main Menu",
            choices=[
                questionary.Choice("  ZIA   Zscaler Internet Access", value="zia"),
                questionary.Choice("  ZPA   Zscaler Private Access", value="zpa"),
                questionary.Separator(),
                questionary.Choice(_active_tenant_label(), value="tenant_mgmt"),
                questionary.Choice("  Settings", value="settings"),
                questionary.Choice("  Audit Log", value="audit"),
                questionary.Separator(),
                questionary.Choice("  Exit", value="exit"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "zpa":
            from cli.menus.zpa_menu import zpa_menu
            zpa_menu()
        elif choice == "zia":
            from cli.menus.zia_menu import zia_menu
            zia_menu()
        elif choice == "tenant_mgmt":
            tenant_management_menu()
        elif choice == "settings":
            settings_menu()
        elif choice == "audit":
            audit_menu()
        elif choice in ("exit", None):
            console.print("[dim]Goodbye.[/dim]")
            break


def _switch_tenant():
    from cli.menus import select_tenant
    from cli.session import set_active_tenant
    from services.config_service import list_tenants

    if not list_tenants():
        console.print("[yellow]No tenants configured yet.[/yellow]")
        if questionary.confirm("Add a tenant now?", default=True).ask():
            _add_tenant()
        return

    tenant = select_tenant()
    if tenant:
        set_active_tenant(tenant)
        console.print(f"[green]✓ Active tenant: [bold]{tenant.name}[/bold][/green]")


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def settings_menu():
    while True:
        render_banner()
        choice = questionary.select(
            "Settings",
            choices=[
                questionary.Choice("Manage Tenants", value="tenants"),
                questionary.Separator(),
                questionary.Choice("Clear Imported Data & Audit Log", value="cleardata"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "tenants":
            tenant_management_menu()
        elif choice == "cleardata":
            _clear_imported_data()
        elif choice in ("back", None):
            break


def tenant_management_menu():
    while True:
        render_banner()
        choice = questionary.select(
            "Manage Tenants",
            choices=[
                questionary.Choice("Switch Tenant", value="switch"),
                questionary.Separator(),
                questionary.Choice("Add Tenant", value="add"),
                questionary.Choice("List Tenants", value="list"),
                questionary.Choice("Remove Tenant", value="remove"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "switch":
            _switch_tenant()
        elif choice == "add":
            _add_tenant()
        elif choice == "list":
            _list_tenants()
        elif choice == "remove":
            _remove_tenant()
        elif choice in ("back", None):
            break


def _add_tenant():
    console.print("\n[bold]Add Tenant[/bold]")
    name = questionary.text("Friendly name (e.g. prod, staging):").ask()
    if not name:
        return

    subdomain = questionary.text(
        "Vanity subdomain:",
        instruction="e.g.  acme  →  https://acme.zslogin.net",
    ).ask()
    if not subdomain:
        return
    subdomain = subdomain.strip().lower()
    zidentity_url = f"https://{subdomain}.zslogin.net"
    console.print(f"  [dim]ZIdentity URL: {zidentity_url}[/dim]")

    client_id = questionary.text("Client ID:").ask()
    client_secret = questionary.password("Client Secret:").ask()
    customer_id = questionary.text(
        "ZPA Customer ID (leave blank if not using ZPA):"
    ).ask()
    notes = questionary.text("Notes (optional):").ask()

    if not all([name, zidentity_url, client_id, client_secret]):
        console.print("[red]Cancelled — required fields missing.[/red]")
        return

    try:
        from services.config_service import add_tenant
        add_tenant(
            name=name,
            zidentity_base_url=zidentity_url,
            client_id=client_id,
            client_secret=client_secret,
            oneapi_base_url="https://api.zsapi.net",
            zpa_customer_id=customer_id or None,
            notes=notes or None,
        )
        console.print(f"[green]✓ Tenant '[bold]{name}[/bold]' added.[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _list_tenants():
    from services.config_service import list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print("[yellow]No tenants configured.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title="Configured Tenants", show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("ZIdentity URL")
    table.add_column("OneAPI URL")
    table.add_column("ZPA Customer ID")
    table.add_column("Notes")

    for t in tenants:
        table.add_row(
            t.name,
            t.zidentity_base_url,
            t.oneapi_base_url,
            t.zpa_customer_id or "[dim]—[/dim]",
            t.notes or "[dim]—[/dim]",
        )

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _remove_tenant():
    from services.config_service import deactivate_tenant, list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print("[yellow]No tenants configured.[/yellow]")
        return

    tenant = questionary.select(
        "Select tenant to remove:",
        choices=[questionary.Choice(t.name, value=t) for t in tenants],
    ).ask()

    if not tenant:
        return

    confirmed = questionary.confirm(
        f"Remove tenant '{tenant.name}'? This cannot be undone.", default=False
    ).ask()

    if confirmed:
        deactivate_tenant(tenant.name)
        console.print(f"[green]✓ Tenant '{tenant.name}' removed.[/green]")


def _configure_conf_file():
    from lib.conf_writer import DEFAULT_CONF_PATH, build_zidentity_url, test_credentials, write_conf

    console.print("\n[bold]Configure Server Credentials File[/bold]")
    console.print("[dim]Writes zscaler-oneapi.conf with chmod 600 for use with server-deployed scripts.[/dim]\n")

    subdomain = questionary.text(
        "Vanity subdomain:",
        instruction="e.g.  acme  →  https://acme.zslogin.net",
    ).ask()
    if not subdomain:
        return

    subdomain = subdomain.strip().lower()
    console.print(f"  [dim]ZIdentity URL: {build_zidentity_url(subdomain)}[/dim]\n")

    client_id = questionary.text("Client ID:").ask()
    if not client_id:
        return

    client_secret = questionary.password("Client Secret:").ask()
    if not client_secret:
        return

    customer_id = questionary.text(
        "ZPA Customer ID:",
        instruction="Press Enter to skip if not using ZPA",
    ).ask()

    conf_path = questionary.text(
        "Output path:",
        default=DEFAULT_CONF_PATH,
    ).ask()
    if not conf_path:
        return

    if questionary.confirm("Test credentials before writing?", default=True).ask():
        with console.status("Verifying credentials with ZIdentity..."):
            try:
                test_credentials(subdomain, client_id, client_secret)
                console.print("[green]✓ Credentials verified[/green]\n")
            except Exception as e:
                console.print(f"[red]✗ Credential test failed:[/red] {e}\n")
                if not questionary.confirm("Write configuration anyway?", default=False).ask():
                    return

    try:
        written_path = write_conf(
            path=conf_path,
            vanity_subdomain=subdomain,
            client_id=client_id,
            client_secret=client_secret,
            zpa_customer_id=customer_id or None,
        )
        console.print(f"\n[green]✓ Written:[/green]      {written_path}")
        console.print("[green]✓ Permissions:[/green]  600 (owner read/write only)")
    except PermissionError:
        console.print(
            f"[red]✗ Permission denied writing to {conf_path}[/red]\n"
            "[yellow]Tip: run the CLI with sudo, or choose a path you own.[/yellow]"
        )
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _generate_key():
    from services.config_service import generate_key, _KEY_FILE

    confirmed = questionary.confirm(
        "Generate a new encryption key? This will replace the existing key and make "
        "any previously saved tenant secrets unreadable.",
        default=False,
    ).ask()
    if not confirmed:
        return

    key = generate_key()
    console.print(
        Panel(
            f"[bold yellow]{key}[/bold yellow]",
            title="New Encryption Key Generated",
            subtitle=f"Saved to {_KEY_FILE}",
            border_style="yellow",
        )
    )
    console.print(
        f"[green]✓ Key saved to[/green] [cyan]{_KEY_FILE}[/cyan]\n"
        "[dim]To override with an env var instead: "
        f"export ZSCALER_SECRET_KEY={key}[/dim]"
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Clear imported data
# ------------------------------------------------------------------

def _clear_imported_data():
    console.print(
        "\n[bold]Clear Imported Data & Audit Log[/bold]\n"
        "[dim]Deletes all ZPA resources, sync logs, and audit log entries.\n"
        "Tenant configuration is preserved.[/dim]\n"
    )
    confirmed = questionary.confirm(
        "This cannot be undone. Proceed?", default=False
    ).ask()
    if not confirmed:
        return

    from db.database import get_session
    from db.models import AuditLog, SyncLog, ZPAResource

    with get_session() as session:
        zpa_count  = session.query(ZPAResource).delete()
        sync_count = session.query(SyncLog).delete()
        audit_count = session.query(AuditLog).delete()

    console.print(
        f"[green]✓ Cleared:[/green] "
        f"{zpa_count} ZPA resources, "
        f"{sync_count} sync logs, "
        f"{audit_count} audit entries."
    )
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Audit Log
# ------------------------------------------------------------------

def audit_menu():
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    from services import audit_service

    with console.status("Loading audit log..."):
        logs = audit_service.get_recent(limit=500)

    if not logs:
        console.print("[yellow]No audit log entries yet.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(
        title=f"Audit Log — {len(logs)} entries, newest first",
        show_lines=False,
    )
    table.add_column("Timestamp", style="dim", no_wrap=True)
    table.add_column("Product", style="cyan")
    table.add_column("Operation")
    table.add_column("Resource")
    table.add_column("Status")

    from datetime import timezone as _tz
    for entry in logs:
        status_style = "green" if entry.status == "SUCCESS" else "red"
        resource = f"{entry.resource_type or ''} {entry.resource_name or ''}".strip()
        # Timestamps are stored as UTC naive datetimes — convert to local time
        ts = entry.timestamp.replace(tzinfo=_tz.utc).astimezone()
        table.add_row(
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            entry.product or "",
            entry.operation or "",
            resource or "[dim]—[/dim]",
            f"[{status_style}]{entry.status or ''}[/{status_style}]",
        )

    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())
