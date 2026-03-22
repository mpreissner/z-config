"""Plugin manager TUI — accessed via Ctrl+\\ from the main menu.

Not listed in the main menu.  Allows authenticated users to browse
available plugins from the private manifest repo and install/uninstall them.
"""

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
        from lib.plugin_manager import get_installed_plugins, get_plugin_channel

        installed = get_installed_plugins()
        channel   = get_plugin_channel()

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

        console.print(Panel(
            auth_line + "\n" + channel_line,
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

        action = questionary.select("Plugin Manager", choices=choices).ask()

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
            "[dim]Restart zs-config to activate the plugin.[/dim]"
        )
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
