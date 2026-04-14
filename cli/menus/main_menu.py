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
    return f"  Switch Tenant  (active: {t.name})" if t else "  Switch Tenant"


def _zia_label() -> str:
    from cli.session import get_active_tenant, has_zia_pending
    t = get_active_tenant()
    if t and has_zia_pending(t.id):
        return "  ZIA ⚠  Zscaler Internet Access"
    return "  ZIA   Zscaler Internet Access"


def main_menu():
    while True:
        render_banner()

        from lib.plugin_manager import get_installed_plugins
        plugins = [p for p in get_installed_plugins() if not p.get("error")]

        choices = [
            questionary.Choice(_zia_label(), value="zia"),
            questionary.Choice("  ZPA   Zscaler Private Access", value="zpa"),
            questionary.Choice("  ZCC   Zscaler Client Connector", value="zcc"),
            questionary.Choice("  ZDX   Zscaler Digital Experience", value="zdx"),
            questionary.Choice("  ZIdentity", value="zidentity"),
        ]

        if plugins:
            choices.append(questionary.Separator())
            for p in plugins:
                choices.append(questionary.Choice(f"  {p['name']}", value=f"__plugin__{p['entry_point']}"))

        choices += [
            questionary.Separator(),
            questionary.Choice(_active_tenant_label(), value="switch_tenant"),
            questionary.Choice("  Settings", value="settings"),
            questionary.Choice("  Audit Log", value="audit"),
            questionary.Separator(),
            questionary.Choice("  Exit", value="exit"),
        ]

        q = questionary.select("Main Menu", choices=choices, use_indicator=True)

        # Inject Ctrl+] binding for the hidden plugin manager.
        # questionary.Question.application lazily creates the prompt_toolkit
        # Application; we merge in our key binding before running it.
        from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
        _plugin_kb = KeyBindings()

        @_plugin_kb.add("c-]")
        def _open_plugin_manager(event):
            event.app.exit(result="__plugins__")

        app = q.application
        app.key_bindings = merge_key_bindings(
            [app.key_bindings or KeyBindings(), _plugin_kb]
        )
        choice = app.run()

        if choice == "__plugins__":
            from cli.menus.plugin_menu import plugin_menu
            plugin_menu()
        elif isinstance(choice, str) and choice.startswith("__plugin__"):
            entry_point = choice[len("__plugin__"):]
            plugin = next((p for p in plugins if p["entry_point"] == entry_point), None)
            if plugin:
                plugin["menu"]()
        elif choice == "zpa":
            from cli.menus.zpa_menu import zpa_menu
            zpa_menu()
        elif choice == "zia":
            from cli.menus.zia_menu import zia_menu
            zia_menu()
        elif choice == "zcc":
            from cli.menus.zcc_menu import zcc_menu
            zcc_menu()
        elif choice == "zdx":
            from cli.menus.zdx_menu import zdx_menu
            zdx_menu()
        elif choice == "zidentity":
            from cli.menus.zidentity_menu import zidentity_menu
            zidentity_menu()
        elif choice == "switch_tenant":
            _switch_tenant()
        elif choice == "settings":
            settings_menu()
        elif choice == "audit":
            audit_menu()
        elif choice in ("exit", None):
            from cli.session import get_active_tenant, has_zia_pending
            t = get_active_tenant()
            if t and has_zia_pending(t.id):
                console.print(Panel(
                    "[yellow]You have unactivated ZIA changes.[/yellow]\n"
                    "Go to [bold]ZIA → Activation[/bold] to push them before exiting.",
                    border_style="yellow",
                    title="Pending Activation",
                ))
                if not questionary.confirm("Exit anyway?", default=False).ask():
                    continue
            console.print("[dim]Goodbye.[/dim]")
            break


def _test_token(zidentity_url: str, client_id: str, client_secret: str):
    """Return (True, None) on success or (False, error_str) on failure."""
    from lib.auth import ZscalerAuth
    try:
        ZscalerAuth(zidentity_url, client_id, client_secret).get_token()
        return True, None
    except Exception as e:
        return False, str(e)


def verify_and_activate_tenant(tenant) -> bool:
    """Verify credentials for *tenant* and set it as the active tenant.

    Called both from the initial launch flow (z_config.py) and from
    _switch_tenant() so the credential check is consistent in both paths.

    Returns True if the tenant was activated (credentials OK or user forced),
    False if the user cancelled or chose to edit credentials instead.
    """
    from cli.session import set_active_tenant
    from services.config_service import decrypt_secret, get_tenant as _reload_tenant

    secret = decrypt_secret(tenant.client_secret_enc)

    with console.status(f"[cyan]Verifying credentials for {tenant.name}...[/cyan]"):
        ok, err = _test_token(tenant.zidentity_base_url, tenant.client_id, secret)

    if not ok:
        console.print(f"[red]✗ Token failed for {tenant.name}:[/red] {err}")
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("Edit credentials", value="edit"),
                questionary.Choice("Continue anyway (credentials may be a transient issue)", value="force"),
                questionary.Choice("Cancel", value="cancel"),
            ],
        ).ask()
        if action == "edit":
            _edit_tenant_credentials(tenant.name)
        elif action == "force":
            set_active_tenant(tenant)
            console.print(f"[yellow]⚠ Active tenant set to [bold]{tenant.name}[/bold] (token unverified)[/yellow]")
            return True
        return False

    console.print("[green]✓ Credentials verified.[/green]")

    _, subs_changed = _fetch_and_apply_org_info(
        tenant.name,
        tenant.zidentity_base_url,
        tenant.client_id,
        secret,
        old_tenant=tenant,
        oneapi_base_url=tenant.oneapi_base_url,
        force_show=True,
    )

    # Reload from DB so the active tenant reflects the freshly written org info fields
    set_active_tenant(_reload_tenant(tenant.name) or tenant)
    console.print(f"[green]✓ Active tenant: [bold]{tenant.name}[/bold][/green]")

    if subs_changed:
        console.print(Panel(
            "[yellow]Subscription changes detected for this tenant.[/yellow]\n"
            "Features or products may have been added or removed.\n\n"
            "[bold]Recommendation:[/bold] Run [cyan]Import Config[/cyan] for ZIA, ZPA, and ZCC "
            "to ensure your local database reflects the current tenant state.",
            title="[bold yellow]⚠ Subscriptions Changed[/bold yellow]",
            border_style="yellow",
        ))

    return True


def _switch_tenant():
    from cli.menus import select_tenant
    from cli.session import get_active_tenant, has_zia_pending
    from services.config_service import list_tenants

    current = get_active_tenant()
    if current and has_zia_pending(current.id):
        console.print(Panel(
            "[yellow]You have unactivated ZIA changes for the current tenant.[/yellow]\n"
            "Go to [bold]ZIA → Activation[/bold] to push them first.",
            border_style="yellow",
            title="Pending Activation",
        ))
        if not questionary.confirm("Switch tenant anyway?", default=False).ask():
            return

    if not list_tenants():
        console.print("[yellow]No tenants configured yet.[/yellow]")
        if questionary.confirm("Add a tenant now?", default=True).ask():
            _add_tenant()
        return

    tenant = select_tenant()
    if not tenant:
        return

    verify_and_activate_tenant(tenant)
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def settings_menu():
    while True:
        render_banner()
        choice = questionary.select(
            "Settings",
            choices=[
                questionary.Choice("Add Tenant", value="add"),
                questionary.Choice("Edit Tenant", value="edit"),
                questionary.Choice("Edit Tenant Metadata", value="edit_meta"),
                questionary.Choice("List Tenants", value="list"),
                questionary.Choice("Remove Tenant", value="remove"),
                questionary.Separator(),
                questionary.Choice("Clear Imported Data & Audit Log", value="cleardata"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
        ).ask()

        if choice == "add":
            _add_tenant()
        elif choice == "edit":
            _pick_and_edit_tenant()
        elif choice == "edit_meta":
            _pick_and_edit_tenant_metadata()
        elif choice == "list":
            _list_tenants()
        elif choice == "remove":
            _remove_tenant()
        elif choice == "cleardata":
            _clear_imported_data()
        elif choice in ("back", None):
            break



def _fetch_and_apply_org_info(
    tenant_name: str,
    zidentity_url: str,
    client_id: str,
    client_secret: str,
    old_tenant=None,
    oneapi_base_url: str = "https://api.zsapi.net",
    force_show: bool = False,
) -> tuple:
    """Fetch orgInformation + subscriptions and persist to DB.

    Returns (success: bool, subscriptions_changed: bool).

    Prints a summary table when any field is first populated or has changed,
    or unconditionally when force_show=True (e.g. on tenant activation).
    Pass old_tenant (TenantConfig) to enable change detection; omit for add/edit flows
    where the summary should always be shown.
    """
    import json
    from services.config_service import fetch_org_info, update_tenant

    with console.status("[cyan]Fetching org information...[/cyan]"):
        org_info, subscriptions, err = fetch_org_info(zidentity_url, client_id, client_secret, oneapi_base_url)

    if err or not org_info:
        console.print(f"[yellow]⚠ Could not fetch org information: {err or 'empty response'}[/yellow]")
        console.print("[dim]Tenant saved without org metadata. Re-run Edit Tenant to retry.[/dim]")
        return False, False

    _zpa_raw = org_info.get("zpaTenantId")
    zpa_customer_id = str(_zpa_raw) if _zpa_raw else None
    zpa_tenant_cloud = org_info.get("zpaTenantCloud") or None
    # pdomain arrives as "<numericId>.<cloud>" — store only the numeric prefix
    pdomain_raw = org_info.get("pdomain") or ""
    zia_tenant_id = pdomain_raw.split(".")[0] or None
    zia_cloud = org_info.get("cloudName") or None

    old_subs = old_tenant.zia_subscriptions if old_tenant else None
    subscriptions_changed = (
        old_subs is not None
        and subscriptions is not None
        and json.dumps(old_subs, sort_keys=True) != json.dumps(subscriptions, sort_keys=True)
    )

    # Show summary when called from add/edit (no old_tenant) or when anything is new/changed
    first_time = old_tenant is None or old_tenant.zia_tenant_id is None
    org_changed = old_tenant is not None and (
        old_tenant.zia_tenant_id != zia_tenant_id
        or old_tenant.zia_cloud != zia_cloud
        or old_tenant.zpa_customer_id != zpa_customer_id
        or old_tenant.zpa_tenant_cloud != zpa_tenant_cloud
    )
    show_summary = force_show or first_time or org_changed or subscriptions_changed

    update_tenant(
        name=tenant_name,
        zpa_customer_id=zpa_customer_id,
        zpa_tenant_cloud=zpa_tenant_cloud,
        zia_tenant_id=zia_tenant_id,
        zia_cloud=zia_cloud,
        zia_subscriptions=subscriptions,
    )

    if show_summary:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column()
        table.add_row("ZIA Cloud", zia_cloud or "[dim]—[/dim]")
        table.add_row("ZIA Tenant ID", zia_tenant_id or "[dim]—[/dim]")
        table.add_row("ZPA Customer ID", zpa_customer_id or "[dim]—[/dim]")
        table.add_row("ZPA Cloud", zpa_tenant_cloud or "[dim]—[/dim]")
        if subscriptions is not None:
            sub_label = "[yellow]changed[/yellow]" if subscriptions_changed else "[green]stored[/green]"
            table.add_row("Subscriptions", sub_label)
        console.print(table)

    return True, subscriptions_changed


def _add_tenant():
    from lib.conf_writer import build_zidentity_url, GOVCLOUD_ONEAPI_URL

    console.print("\n[bold]Add Tenant[/bold]")
    name = questionary.text("Friendly name (e.g. prod, staging):").ask()
    if not name:
        return

    is_govcloud = questionary.confirm("Is this a GovCloud tenant?", default=False).ask()
    if is_govcloud is None:
        return

    subdomain_hint = (
        "e.g.  acme  →  https://acme.zidentitygov.us"
        if is_govcloud else
        "e.g.  acme  →  https://acme.zslogin.net"
    )
    subdomain = questionary.text("Vanity subdomain:", instruction=subdomain_hint).ask()
    if not subdomain:
        return
    subdomain = subdomain.strip().lower()
    zidentity_url = build_zidentity_url(subdomain, govcloud=is_govcloud)
    console.print(f"  [dim]ZIdentity URL: {zidentity_url}[/dim]")

    if is_govcloud:
        oneapi_base_url = questionary.text(
            "OneAPI base URL:",
            default=GOVCLOUD_ONEAPI_URL,
            instruction="MOD tier default shown; HIGH tier may differ",
        ).ask()
        if not oneapi_base_url:
            return
        oneapi_base_url = oneapi_base_url.strip()
    else:
        oneapi_base_url = "https://api.zsapi.net"

    client_id = questionary.text("Client ID:").ask()
    client_secret = questionary.password("Client Secret:").ask()
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
            oneapi_base_url=oneapi_base_url,
            govcloud=is_govcloud,
            notes=notes or None,
        )
        console.print(f"[green]✓ Tenant '[bold]{name}[/bold]' added.[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    with console.status("[cyan]Verifying credentials...[/cyan]"):
        ok, err = _test_token(zidentity_url, client_id, client_secret)

    if not ok:
        console.print(f"[red]✗ Token failed:[/red] {err}")
        console.print("[dim]Tenant was saved. You can edit credentials from Settings → Edit Tenant.[/dim]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    console.print("[green]✓ Token obtained — credentials verified.[/green]")
    _fetch_and_apply_org_info(name, zidentity_url, client_id, client_secret, oneapi_base_url=oneapi_base_url)
    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _pick_and_edit_tenant():
    from services.config_service import list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print("[yellow]No tenants configured.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    tenant = questionary.select(
        "Select tenant to edit:",
        choices=[questionary.Choice(t.name, value=t) for t in tenants],
    ).ask()
    if tenant:
        _edit_tenant_credentials(tenant.name)


def _edit_tenant_credentials(tenant_name: str):
    from lib.conf_writer import build_zidentity_url, GOVCLOUD_ONEAPI_URL
    from services.config_service import decrypt_secret, get_tenant, update_tenant

    tenant = get_tenant(tenant_name)
    if not tenant:
        console.print(f"[red]Tenant '{tenant_name}' not found.[/red]")
        return

    current_subdomain = tenant.zidentity_base_url.split("//")[-1].split(".")[0]

    console.print(f"\n[bold]Edit Credentials — {tenant.name}[/bold]")
    console.print(f"  [dim]Current ZIdentity URL: {tenant.zidentity_base_url}[/dim]")
    console.print(f"  [dim]Current Client ID:     {tenant.client_id}[/dim]")
    if tenant.govcloud:
        console.print("  [cyan]GovCloud tenant[/cyan]")
    console.print("[dim]Press Enter to keep the current value for each field.[/dim]\n")

    is_govcloud = questionary.confirm("GovCloud tenant?", default=bool(tenant.govcloud)).ask()
    if is_govcloud is None:
        return

    subdomain = questionary.text(
        "Vanity subdomain:",
        default=current_subdomain,
    ).ask()
    if subdomain is None:
        return
    subdomain = subdomain.strip().lower() or current_subdomain
    zidentity_url = build_zidentity_url(subdomain, govcloud=is_govcloud)

    if is_govcloud:
        current_oneapi = tenant.oneapi_base_url if tenant.govcloud else GOVCLOUD_ONEAPI_URL
        oneapi_base_url = questionary.text(
            "OneAPI base URL:",
            default=current_oneapi,
            instruction="MOD tier default shown; HIGH tier may differ",
        ).ask()
        if oneapi_base_url is None:
            return
        oneapi_base_url = oneapi_base_url.strip() or current_oneapi
    else:
        oneapi_base_url = "https://api.zsapi.net"

    client_id = questionary.text("Client ID:", default=tenant.client_id).ask()
    if client_id is None:
        return
    client_id = client_id.strip() or tenant.client_id

    client_secret = questionary.password(
        "Client Secret (leave blank to keep existing):"
    ).ask()
    if client_secret is None:
        return

    test_secret = client_secret if client_secret else decrypt_secret(tenant.client_secret_enc)

    with console.status("[cyan]Verifying credentials...[/cyan]"):
        ok, err = _test_token(zidentity_url, client_id, test_secret)

    if not ok:
        console.print(f"[red]✗ Token failed:[/red] {err}")
        if not questionary.confirm("Save credentials anyway?", default=False).ask():
            return

    update_tenant(
        name=tenant_name,
        zidentity_base_url=zidentity_url,
        oneapi_base_url=oneapi_base_url,
        client_id=client_id,
        client_secret=client_secret if client_secret else None,
        govcloud=is_govcloud,
    )
    console.print(f"[green]✓ Credentials updated for '[bold]{tenant_name}[/bold]'.[/green]")

    if ok:
        _fetch_and_apply_org_info(tenant_name, zidentity_url, client_id, test_secret, old_tenant=tenant, oneapi_base_url=oneapi_base_url)

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _pick_and_edit_tenant_metadata():
    from services.config_service import list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print("[yellow]No tenants configured.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    tenant = questionary.select(
        "Select tenant to edit metadata:",
        choices=[questionary.Choice(t.name, value=t) for t in tenants],
    ).ask()
    if tenant:
        _edit_tenant_metadata(tenant.name)


def _edit_tenant_metadata(tenant_name: str):
    from services.config_service import get_tenant, set_tenant_metadata

    tenant = get_tenant(tenant_name)
    if not tenant:
        console.print(f"[red]Tenant '{tenant_name}' not found.[/red]")
        return

    console.print(f"\n[bold]Edit Org Metadata — {tenant.name}[/bold]")
    console.print("[dim]These values are normally auto-fetched. Override here if the API returned incorrect values.[/dim]")
    console.print("[dim]Press Enter to keep the current value. Clear the field to set it to blank.[/dim]\n")

    zpa_customer_id = questionary.text(
        "ZPA Customer ID:",
        default=tenant.zpa_customer_id or "",
    ).ask()
    if zpa_customer_id is None:
        return

    zpa_tenant_cloud = questionary.text(
        "ZPA Tenant Cloud:",
        default=tenant.zpa_tenant_cloud or "",
        instruction="e.g. ZPATWO_NET",
    ).ask()
    if zpa_tenant_cloud is None:
        return

    zia_tenant_id = questionary.text(
        "ZIA Tenant ID:",
        default=tenant.zia_tenant_id or "",
    ).ask()
    if zia_tenant_id is None:
        return

    zia_cloud = questionary.text(
        "ZIA Cloud:",
        default=tenant.zia_cloud or "",
        instruction="e.g. zscloud.net",
    ).ask()
    if zia_cloud is None:
        return

    set_tenant_metadata(
        name=tenant_name,
        zpa_customer_id=zpa_customer_id.strip() or None,
        zpa_tenant_cloud=zpa_tenant_cloud.strip() or None,
        zia_tenant_id=zia_tenant_id.strip() or None,
        zia_cloud=zia_cloud.strip() or None,
    )
    console.print(f"[green]✓ Metadata updated for '[bold]{tenant_name}[/bold]'.[/green]")
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
    table.add_column("GovCloud")
    table.add_column("ZIdentity URL")
    table.add_column("ZIA Cloud")
    table.add_column("ZIA Tenant ID")
    table.add_column("ZPA Customer ID")
    table.add_column("ZPA Cloud")
    table.add_column("Notes")

    for t in tenants:
        # zia_tenant_id is stored as the numeric prefix; guard against legacy full-domain values
        zia_id = (t.zia_tenant_id or "").split(".")[0] or None
        govcloud_label = "[cyan]Gov[/cyan]" if t.govcloud else "[dim]—[/dim]"
        table.add_row(
            t.name,
            govcloud_label,
            t.zidentity_base_url,
            t.zia_cloud or "[dim]—[/dim]",
            zia_id or "[dim]—[/dim]",
            t.zpa_customer_id or "[dim]—[/dim]",
            t.zpa_tenant_cloud or "[dim]—[/dim]",
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
