"""Plugin manager TUI — accessed via Ctrl+\\ from the main menu.

Not listed in the main menu.  Allows authenticated users to browse
available plugins from the private manifest repo and install/uninstall them.
"""

import sys

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.banner import render_banner

console = Console()


def plugin_menu() -> None:
    while True:
        render_banner()

        from lib.github_auth import get_token, is_authenticated, verify_token
        from lib.plugin_manager import (
            get_installed_plugins, get_plugin_channel, get_plugin_branch_overrides,
        )

        installed  = get_installed_plugins()
        channel    = get_plugin_channel()
        overrides  = get_plugin_branch_overrides()
        palo_branch = overrides.get("palo-tools")

        # ── Auth status header ────────────────────────────────────────────
        token = get_token()
        if token:
            valid, username = verify_token(token)
            if valid:
                auth_line = f"[green]● Authenticated as [bold]{username}[/bold][/green]"
            else:
                auth_line = f"[yellow]● Token invalid ({username}) — please re-authenticate[/yellow]"
                valid = False
        else:
            auth_line = "[dim]● Not authenticated[/dim]"
            valid = False

        if channel == "dev":
            channel_line = "[yellow]⚠  Channel: [bold]dev[/bold] — pre-release builds active[/yellow]"
        else:
            channel_line = "[dim]Channel: stable[/dim]"

        if palo_branch:
            override_line = f"\n[magenta]⚙  palo-tools branch override: [bold]{palo_branch}[/bold][/magenta]"
        else:
            override_line = ""

        console.print(Panel(
            auth_line + "\n" + channel_line + override_line,
            title="Plugin Manager",
            border_style="cyan",
        ))

        # ── Installed plugins summary ─────────────────────────────────────
        if installed:
            table = Table(show_header=True, box=None, padding=(0, 2))
            table.add_column("Plugin",  style="bold cyan")
            table.add_column("Package", style="dim")
            table.add_column("Version", style="dim")
            table.add_column("Status")
            for p in installed:
                status = "[red]load error[/red]" if p.get("error") else "[green]active[/green]"
                table.add_row(p["name"], p["package"], p["version"], status)
            console.print(table)
        else:
            console.print("[dim]  No plugins installed.[/dim]\n")

        # ── Menu choices ──────────────────────────────────────────────────
        choices = []
        if valid:
            choices.append(questionary.Choice("  Browse available plugins", value="browse"))
        if installed:
            choices.append(questionary.Choice("  Uninstall a plugin",       value="uninstall"))
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("  Switch plugin channel",        value="channel"))
        choices.append(questionary.Separator())
        if valid:
            choices.append(questionary.Choice("  Log out of GitHub",        value="logout"))
        else:
            choices.append(questionary.Choice("  Log in with GitHub",       value="login"))
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("  ← Back",                       value="back"))

        q = questionary.select("Plugin Manager", choices=choices)

        # Inject Ctrl+] binding for the hidden palo-tools branch toggle.
        from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
        _branch_kb = KeyBindings()

        @_branch_kb.add("c-]")
        def _branch_toggle_key(event):
            event.app.exit(result="__branch_toggle__")

        app = q.application
        app.key_bindings = merge_key_bindings(
            [app.key_bindings or KeyBindings(), _branch_kb]
        )
        action = app.run()

        if action == "browse":
            _browse_plugins()
        elif action == "install":
            _install_plugin_by_url()
        elif action == "uninstall":
            _uninstall_plugin(installed)
        elif action == "channel":
            _switch_channel(channel)
        elif action == "login":
            _login()
        elif action == "logout":
            _logout()
        elif action == "__branch_toggle__":
            _toggle_palo_branch(palo_branch)
        elif action in ("back", None):
            break


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _login() -> None:
    from lib.github_auth import authenticate, is_authenticated

    if is_authenticated():
        console.print("[yellow]Already authenticated. Log out first to switch accounts.[/yellow]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    console.print()
    console.print("[bold]GitHub Authentication[/bold]")
    console.print(
        "[dim]A browser window will open. Complete authentication there "
        "(including MFA if required), then return here.[/dim]\n"
    )

    messages = []

    def _progress(msg: str) -> None:
        messages.append(msg)
        console.print(f"  {msg}")

    with console.status("[cyan]Waiting for GitHub authorization...[/cyan]"):
        success, message = authenticate(progress_callback=_progress)

    if success:
        console.print(f"\n[green]✓ {message}[/green]")
    else:
        console.print(f"\n[red]✗ {message}[/red]")

    questionary.press_any_key_to_continue("Press any key...").ask()


def _logout() -> None:
    from lib.github_auth import logout

    confirmed = questionary.confirm(
        "Log out of GitHub? Installed plugins will continue to work.",
        default=False,
    ).ask()
    if confirmed:
        logout()
        console.print("[green]✓ Logged out.[/green]")
        questionary.press_any_key_to_continue("Press any key...").ask()


def _switch_channel(current: str) -> None:
    from lib.plugin_manager import set_plugin_channel

    target = "stable" if current == "dev" else "dev"

    console.print()
    if target == "dev":
        console.print(
            Panel(
                "[yellow][bold]Warning — dev channel[/bold]\n\n"
                "Dev builds are pre-release and may contain incomplete features, "
                "breaking changes, or unexpected behaviour.\n\n"
                "Do not use dev builds in production environments.[/yellow]",
                border_style="yellow",
            )
        )

    confirmed = questionary.confirm(
        f"Switch plugin channel from '{current}' to '{target}'?",
        default=False,
    ).ask()

    if not confirmed:
        return

    set_plugin_channel(target)
    console.print(f"[green]✓ Plugin channel set to [bold]{target}[/bold].[/green]\n")

    from cli.update_checker import check_plugin_updates
    check_plugin_updates()
    questionary.press_any_key_to_continue("Press any key...").ask()


def _browse_plugins() -> None:
    from lib.plugin_manager import fetch_manifest, get_installed_plugins, install_plugin

    console.print()
    with console.status("[cyan]Fetching available plugins...[/cyan]"):
        available, error = fetch_manifest()

    if error:
        console.print(f"[red]✗ {error}[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    if not available:
        console.print("[yellow]No plugins available in the manifest.[/yellow]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    installed_packages = {p["package"] for p in get_installed_plugins()}

    # ── Display available plugins ─────────────────────────────────────────
    table = Table(title="Available Plugins", show_lines=True)
    table.add_column("Plugin",      style="bold cyan")
    table.add_column("Description")
    table.add_column("Version")
    table.add_column("Status")
    for p in available:
        status = (
            "[green]installed[/green]"
            if p.get("package") in installed_packages
            else "[dim]not installed[/dim]"
        )
        table.add_row(
            p.get("display_name") or p.get("name", ""),
            p.get("description", ""),
            p.get("version", ""),
            status,
        )
    console.print(table)
    console.print()

    # ── Offer install for any not yet installed ───────────────────────────
    not_installed = [
        p for p in available
        if p.get("package") not in installed_packages
    ]
    if not not_installed:
        console.print("[green]All available plugins are already installed.[/green]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    choices = [
        questionary.Choice(
            f"{p.get('display_name') or p.get('name')}  —  {p.get('description', '')}",
            value=p,
        )
        for p in not_installed
    ]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("← Cancel", value="__cancel__"))

    plugin = questionary.select("Select a plugin to install:", choices=choices).ask()
    if not plugin or plugin == "__cancel__":
        return

    _do_install(plugin)


def _do_install(plugin: dict) -> None:
    from lib.plugin_manager import install_plugin, effective_install_url

    install_url = effective_install_url(plugin) if plugin.get("install_url") else None
    if not install_url:
        console.print("[red]✗ No install URL in manifest entry.[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    name = plugin.get("display_name") or plugin.get("name", "plugin")
    console.print(f"\nInstalling [bold]{name}[/bold]...")
    console.print(f"[dim]  {install_url}[/dim]\n")

    with console.status(f"[cyan]Running pip install...[/cyan]"):
        success, message = install_plugin(install_url)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        console.print(
            Panel(
                "[green]Plugin installed.[/green] zs-config will now exit — "
                "please re-launch to activate the new plugin.",
                border_style="green",
            )
        )
        questionary.press_any_key_to_continue("Press any key to exit...").ask()
        sys.exit(0)
    else:
        console.print(f"[red]✗ Installation failed:[/red]\n{message}")
        questionary.press_any_key_to_continue("Press any key...").ask()


def _install_plugin_by_url() -> None:
    """Fallback: install directly from a git URL (no manifest needed)."""
    url = questionary.text(
        "Enter pip-compatible install URL:",
        instruction="e.g. git+ssh://git@github.com/org/repo.git#subdirectory=plugin_name",
    ).ask()
    if not url:
        return
    _do_install({"install_url": url, "name": url})


def _toggle_palo_branch(current_override: str | None) -> None:
    """Secret Ctrl+] handler: toggle palo-tools between dev and dev-overhaul."""
    from lib.plugin_manager import (
        fetch_manifest, get_plugin_channel, install_plugin,
        set_plugin_branch_override, url_for_branch,
    )

    # Determine target branch
    if current_override == "dev-overhaul":
        target_branch = "dev"
        label = "dev-overhaul  →  dev"
    else:
        target_branch = "dev-overhaul"
        label = f"{'override: ' + current_override if current_override else 'channel: ' + get_plugin_channel()}  →  dev-overhaul"

    console.print()
    console.print(Panel(
        f"[bold]palo-tools branch toggle[/bold]\n\n"
        f"[dim]{label}[/dim]\n\n"
        "This will reinstall palo-tools from the target branch and exit zs-config.",
        border_style="magenta",
        title="Developer — Branch Override",
    ))

    confirmed = questionary.confirm(
        f"Switch palo-tools to '{target_branch}' and reinstall?",
        default=False,
    ).ask()
    if not confirmed:
        return

    # Fetch manifest to get the base install URL
    console.print()
    with console.status("[cyan]Fetching manifest...[/cyan]"):
        available, error = fetch_manifest()

    if error:
        console.print(f"[red]✗ {error}[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    palo_entry = next(
        (p for p in (available or []) if p.get("package") == "palo-tools"),
        None,
    )
    if not palo_entry:
        console.print("[red]✗ palo-tools not found in manifest.[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    base_url = palo_entry.get("install_url_dev") or palo_entry.get("install_url", "")
    if not base_url:
        console.print("[red]✗ No install URL in manifest for palo-tools.[/red]")
        questionary.press_any_key_to_continue("Press any key...").ask()
        return

    install_url = url_for_branch(base_url, target_branch)
    console.print(f"[dim]  {install_url}[/dim]\n")

    with console.status(f"[cyan]Installing palo-tools @ {target_branch}...[/cyan]"):
        success, message = install_plugin(install_url)

    if success:
        set_plugin_branch_override("palo-tools", target_branch)
        console.print(f"[green]✓ {message}[/green]")
        console.print(Panel(
            f"[green]palo-tools switched to [bold]{target_branch}[/bold].[/green] "
            "zs-config will now exit — please re-launch to activate the update.",
            border_style="green",
        ))
        questionary.press_any_key_to_continue("Press any key to exit...").ask()
        sys.exit(0)
    else:
        console.print(f"[red]✗ Installation failed:[/red]\n{message}")
        questionary.press_any_key_to_continue("Press any key...").ask()


def _uninstall_plugin(installed: list[dict]) -> None:
    from lib.plugin_manager import uninstall_plugin

    choices = [
        questionary.Choice(f"{p['name']}  ({p['package']} {p['version']})", value=p)
        for p in installed
    ]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("← Cancel", value="__cancel__"))

    plugin = questionary.select("Select plugin to uninstall:", choices=choices).ask()
    if not plugin or plugin == "__cancel__":
        return

    confirmed = questionary.confirm(
        f"Uninstall '{plugin['name']}'? This cannot be undone without reinstalling.",
        default=False,
    ).ask()
    if not confirmed:
        return

    with console.status(f"[cyan]Uninstalling {plugin['package']}...[/cyan]"):
        success, message = uninstall_plugin(plugin["package"])

    if success:
        console.print(f"[green]✓ {message}[/green]")
        console.print("[dim]Restart zs-config to fully remove the plugin.[/dim]")
    else:
        console.print(f"[red]✗ {message}[/red]")

    questionary.press_any_key_to_continue("Press any key...").ask()
