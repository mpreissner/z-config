"""Update checker — silently checks PyPI for a newer zs-config version on startup."""

import os
import re
import shutil
import subprocess
import sys
from typing import Optional

import requests
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

import questionary

PYPI_URL = "https://pypi.org/pypi/zs-config/json"
CHANGELOG_URL = "https://raw.githubusercontent.com/mpreissner/zs-config/main/CHANGELOG.md"
PACKAGE_NAME = "zs-config"
REQUEST_TIMEOUT = 4

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
        resp = requests.get(CHANGELOG_URL, timeout=REQUEST_TIMEOUT)
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


def check_for_updates() -> None:
    from cli.banner import VERSION

    latest = _fetch_latest_version()
    if latest is None:
        return

    try:
        if _parse_ver(latest) <= _parse_ver(VERSION):
            return
    except Exception:
        return

    console.print(
        Panel(
            f"Update available: v{VERSION} → v{latest}",
            border_style="yellow",
        )
    )

    changelog = _fetch_changelog()
    if changelog:
        sections = _extract_changelog_sections(changelog, VERSION, latest)
        if sections:
            console.print("\n[bold]Changes in this update:[/bold]")
            console.print(Markdown(sections))

    method, cmd = _detect_install_method()
    cmd_str = " ".join(str(c) for c in cmd)

    answer = questionary.confirm(
        f"Update now using {method}?  [{cmd_str}]",
        default=True,
    ).ask()

    if not answer:
        console.print("[dim]Skipping update. You can update manually later.[/dim]")
        return

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
