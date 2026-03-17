"""Plugin manager — entry point discovery, manifest fetch, install/uninstall.

Plugins are pip-installable packages that declare themselves via:

    [project.entry-points."zs_config.plugins"]
    my-plugin = "my_package.plugin:register"

The register() function must return:
    {"name": "Display Name", "menu": callable}

Available plugins are listed in manifest.json in the private manifest repo,
fetched via the GitHub API using the authenticated token.
"""

import re
import subprocess
import sys
from importlib.metadata import entry_points
from typing import Optional

import requests

from lib.github_auth import get_token

_PLUGIN_GROUP   = "zs_config.plugins"
_MANIFEST_REPO  = "mpreissner/zs-plugins"
_MANIFEST_FILE  = "manifest.json"


# ---------------------------------------------------------------------------
# Installed plugins (entry point discovery)
# ---------------------------------------------------------------------------

def get_installed_plugins() -> list[dict]:
    """Return all installed plugins discovered via entry points.

    Each entry:
        name        display name from register()
        package     pip package name
        version     installed version
        menu        callable that launches the plugin's TUI menu
        entry_point entry point key
        error       set if the plugin failed to load
    """
    plugins = []
    for ep in entry_points(group=_PLUGIN_GROUP):
        base = {
            "entry_point": ep.name,
            "package":     ep.dist.name    if ep.dist else ep.name,
            "version":     ep.dist.version if ep.dist else "unknown",
        }
        try:
            info = ep.load()()   # call register()
            plugins.append({
                **base,
                "name":  info.get("name", ep.name),
                "menu":  info.get("menu"),
            })
        except Exception as exc:
            plugins.append({
                **base,
                "name":  ep.name,
                "menu":  None,
                "error": str(exc),
            })
    return plugins


# ---------------------------------------------------------------------------
# Available plugins (manifest from GitHub)
# ---------------------------------------------------------------------------

def fetch_manifest() -> tuple[Optional[list], Optional[str]]:
    """Fetch the plugin manifest from the private GitHub manifest repo.

    Returns (plugins_list, None) on success or (None, error_message) on failure.

    Each manifest entry:
        name            display name
        description     short description
        package         pip package name (for uninstall / version comparison)
        version         latest available version string
        install_url     pip-compatible git URL
    """
    token = get_token()
    if not token:
        return None, "Not authenticated — log in first."

    url = (
        f"https://api.github.com/repos/{_MANIFEST_REPO}"
        f"/contents/{_MANIFEST_FILE}"
    )
    try:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/vnd.github.raw+json",
            },
            timeout=10,
        )
        if resp.status_code == 401:
            return None, "GitHub token expired or revoked — please re-authenticate."
        if resp.status_code == 403:
            return None, "Access denied — you may not have access to this plugin repository."
        if resp.status_code == 404:
            return None, "Plugin manifest not found — contact your administrator."
        resp.raise_for_status()
        data = resp.json()
        return data.get("plugins", []), None
    except Exception as exc:
        return None, f"Failed to fetch manifest: {exc}"


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def _to_https_url(url: str) -> str:
    """Convert a git+ssh GitHub URL to git+https with token auth.

    Manifests may use SSH URLs (git+ssh://git@github.com/...) which require a
    pre-configured SSH key.  We already hold a GitHub token, so rewrite to
    HTTPS instead — no SSH key required on the client machine.
    """
    token = get_token()
    if not token:
        return url
    return re.sub(
        r"^git\+ssh://git@github\.com/",
        f"git+https://x-access-token:{token}@github.com/",
        url,
    )


def install_plugin(install_url: str) -> tuple[bool, str]:
    """Install a plugin using pip.

    Returns (True, success_message) or (False, error_output).
    """
    url = _to_https_url(install_url)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", url],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, "Plugin installed successfully."
        output = (result.stderr or result.stdout).strip()
        return False, output or "pip exited with a non-zero status."
    except subprocess.TimeoutExpired:
        return False, "Installation timed out after 120 seconds."
    except Exception as exc:
        return False, str(exc)


def uninstall_plugin(package_name: str) -> tuple[bool, str]:
    """Uninstall a plugin using pip.

    Returns (True, success_message) or (False, error_output).
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "--yes", package_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, "Plugin uninstalled successfully."
        output = (result.stderr or result.stdout).strip()
        return False, output or "pip exited with a non-zero status."
    except Exception as exc:
        return False, str(exc)
