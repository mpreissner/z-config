"""Update checker — silently checks PyPI for a newer zs-config version on startup."""

import os
import re
import shutil
import subprocess
import sys
from typing import Optional

import requests
from rich.console import Console
from rich.panel import Panel

import questionary

PYPI_URL = "https://pypi.org/pypi/zs-config/json"
CHANGELOG_URL = "https://raw.githubusercontent.com/mpreissner/zs-config/main/CHANGELOG.md"
PACKAGE_NAME = "zs-config"
REQUEST_TIMEOUT = 4          # version check (PyPI)
CHANGELOG_TIMEOUT = 10       # changelog fetch (raw.githubusercontent.com — can be slower)

console = Console()


def _parse_ver(v: str) -> tuple:
    v = v.lstrip("v")
    return tuple(int(x) for x in v.split("."))


def _fetch_latest_version() -> Optional[str]:
    try:
        resp = requests.get(PYPI_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception:
        return None


def _fetch_changelog() -> Optional[str]:
    try:
        resp = requests.get(CHANGELOG_URL, timeout=CHANGELOG_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _extract_changelog_sections(changelog: str, from_ver: str, to_ver: str) -> str:
    pattern = re.compile(r"^## \[(\d+[\.\d]+)\]", re.MULTILINE)
    matches = list(pattern.finditer(changelog))

    from_parsed = _parse_ver(from_ver)
    to_parsed = _parse_ver(to_ver)

    sections = []
    for i, match in enumerate(matches):
        ver_str = match.group(1)
        try:
            ver = _parse_ver(ver_str)
        except ValueError:
            continue
        if from_parsed < ver <= to_parsed:
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(changelog)
            section = changelog[start:end].strip()
            section = re.sub(r"\n+---\s*$", "", section).strip()
            sections.append(section)

    return "\n\n---\n\n".join(sections)


def _detect_install_method() -> tuple:
    if "pipx" in os.path.abspath(sys.executable).lower():
        pipx_cmd = shutil.which("pipx")
        return ("pipx", [pipx_cmd, "upgrade", PACKAGE_NAME])
    return ("pip", [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME])


def check_for_updates() -> bool:
    """Check PyPI for a newer zs-config version.

    Returns True if an update was found (regardless of whether the user
    accepted it), False otherwise.  Callers use the return value to decide
    whether to skip downstream checks (e.g. plugin updates) until next launch.
    """
    from cli.banner import VERSION

    latest = _fetch_latest_version()
    if latest is None:
        return False

    try:
        if _parse_ver(latest) <= _parse_ver(VERSION):
            return False
    except Exception:
        return False

    console.print(
        Panel(
            f"Update available: v{VERSION} → v{latest}",
            border_style="yellow",
        )
    )

    changelog = _fetch_changelog()
    if changelog is None:
        console.print("[dim]Could not fetch changelog (network timeout).[/dim]")
    elif changelog:
        sections = _extract_changelog_sections(changelog, VERSION, latest)
        if sections:
            questionary.press_any_key_to_continue("Press any key to view changelog...").ask()
            from rich.markdown import Markdown
            from cli.scroll_view import render_rich_to_lines, scroll_view
            scroll_view(render_rich_to_lines(Markdown(sections)))

    method, cmd = _detect_install_method()
    cmd_str = " ".join(str(c) for c in cmd)

    answer = questionary.confirm(
        f"Update now using {method}?  [{cmd_str}]",
        default=True,
    ).ask()

    if not answer:
        console.print("[dim]Skipping update. You can update manually later.[/dim]")
        return True

    result = subprocess.run(cmd)

    if result.returncode == 0:
        console.print(
            Panel(
                f"[green]✓ Updated to v{latest}! Please re-launch zs-config.[/green]",
                border_style="green",
            )
        )
        sys.exit(0)
    else:
        console.print(
            Panel(
                f"[red]Update failed. Update manually:[/red]\n{cmd_str}",
                border_style="red",
            )
        )
    return True


def check_plugin_updates() -> None:
    """Check the plugin manifest for newer versions of installed plugins.

    Skipped entirely if:
    - No plugins are installed
    - No GitHub token is present
    - The manifest cannot be fetched

    Runs silently when everything is current.
    """
    from lib.plugin_manager import get_installed_plugins, fetch_manifest, install_plugin, effective_install_url
    from lib.github_auth import get_token
    from rich.table import Table

    # Skip if no plugins installed
    installed = get_installed_plugins()
    if not installed:
        return

    # Skip if not authenticated
    if not get_token():
        return

    # Fetch manifest — skip silently on any error
    manifest_plugins, error = fetch_manifest()
    if error or not manifest_plugins:
        return

    # Build map of package → manifest entry for installed packages
    installed_map = {p["package"]: p for p in installed if not p.get("error")}
    manifest_map  = {p["package"]: p for p in manifest_plugins}

    updates = []
    for pkg, inst in installed_map.items():
        manifest = manifest_map.get(pkg)
        if not manifest:
            continue
        avail_ver = manifest.get("version", "")
        inst_ver  = inst.get("version", "")
        try:
            if avail_ver and _parse_ver(avail_ver) > _parse_ver(inst_ver):
                updates.append({
                    "display_name": manifest.get("display_name", pkg),
                    "package":      pkg,
                    "installed":    inst_ver,
                    "available":    avail_ver,
                    "install_url":  effective_install_url(manifest),
                })
        except Exception:
            continue

    if not updates:
        return

    # Show what's available
    table = Table(show_header=True, show_lines=False, box=None, padding=(0, 2))
    table.add_column("Plugin")
    table.add_column("Installed")
    table.add_column("Available")
    for u in updates:
        table.add_row(u["display_name"], u["installed"], f"[green]{u['available']}[/green]")

    noun = "update" if len(updates) == 1 else "updates"
    console.print(
        Panel(
            table,
            title=f"[yellow]Plugin {noun} available[/yellow]",
            border_style="yellow",
        )
    )

    answer = questionary.confirm(
        f"Update {len(updates)} plugin {noun} now?",
        default=True,
    ).ask()

    if not answer:
        console.print("[dim]Skipping plugin updates.[/dim]")
        return

    any_updated = False
    for u in updates:
        with console.status(f"[cyan]Updating {u['display_name']}...[/cyan]"):
            ok, msg = install_plugin(u["install_url"])
        if ok:
            console.print(f"[green]✓ {u['display_name']} updated to v{u['available']}[/green]")
            any_updated = True
        else:
            console.print(f"[red]✗ {u['display_name']} update failed:[/red] {msg}")

    if any_updated:
        console.print(
            Panel(
                "[green]Plugin update complete.[/green] Re-launch zs-config to load the updated plugin(s).",
                border_style="green",
            )
        )
