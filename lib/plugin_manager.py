"""Plugin manager — entry point discovery, manifest fetch, install/uninstall.

Plugins are pip-installable packages that declare themselves via:

    [project.entry-points."zs_config.plugins"]
    my-plugin = "my_package.plugin:register"

The register() function must return:
    {"name": "Display Name", "menu": callable}

Available plugins are listed in manifest.json in the private manifest repo,
fetched via the GitHub API using the authenticated token.
"""

import os
import re
import stat
import subprocess
import sys
import tempfile
from importlib.metadata import entry_points
from typing import Optional

import requests

from lib.github_auth import get_token

# PEP 508 package name: letters, digits, hyphens, underscores, dots.
_SAFE_PACKAGE_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')

# Allowed install URL patterns — must point to github.com via HTTPS or SSH.
_ALLOWED_URL_RE = re.compile(
    r'^git\+(?:https://(?:[^@/]+@)?|ssh://git@)github\.com/'
)

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

def get_manifest_ref() -> str:
    """Return the git ref to fetch the manifest from based on the active channel."""
    return "dev" if get_plugin_channel() == "dev" else "main"


def fetch_manifest(ref: Optional[str] = None) -> tuple[Optional[list], Optional[str]]:
    """Fetch the plugin manifest from the private GitHub manifest repo.

    Returns (plugins_list, None) on success or (None, error_message) on failure.

    Each manifest entry:
        name            display name
        description     short description
        package         pip package name (for uninstall / version comparison)
        version         latest available version string
        install_url     pip-compatible git URL
        install_url_dev pip-compatible git URL for the dev branch (optional)
    """
    token = get_token()
    if not token:
        return None, "Not authenticated — log in first."

    resolved_ref = ref if ref is not None else get_manifest_ref()
    url = (
        f"https://api.github.com/repos/{_MANIFEST_REPO}"
        f"/contents/{_MANIFEST_FILE}"
        f"?ref={resolved_ref}"
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
    """Normalise a git+ssh GitHub URL to a bare git+https URL (no token).

    The token is injected at install time via GIT_ASKPASS rather than embedded
    in the URL, so it never appears in process listings.
    """
    return re.sub(
        r"^git\+ssh://git@github\.com/",
        "git+https://github.com/",
        url,
    )


def _askpass_env(token: str) -> tuple[dict, str]:
    """Return (env_dict, temp_script_path) for GIT_ASKPASS-based auth.

    Writes a minimal executable Python helper that echoes the token when git
    asks for credentials.  The token is passed via an env var rather than baked
    into the script, keeping it out of the script file itself.

    Caller is responsible for deleting the temp file after use.
    """
    script = (
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "p = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "print('x-access-token' if 'sername' in p else os.environ.get('_ZS_GIT_TOKEN', ''))\n"
    )
    fd, path = tempfile.mkstemp(prefix="_zs_askpass_", suffix=".py")
    try:
        os.write(fd, script.encode())
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRWXU)   # 700 — owner execute only

    env = os.environ.copy()
    env["GIT_ASKPASS"]        = path
    env["_ZS_GIT_TOKEN"]      = token
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env, path


def install_plugin(install_url: str) -> tuple[bool, str]:
    """Install a plugin using pip.

    Validates that the URL points to github.com, then installs with the GitHub
    token passed via GIT_ASKPASS so it does not appear in the process listing.

    Returns (True, success_message) or (False, error_output).
    """
    if not _ALLOWED_URL_RE.match(install_url):
        return False, f"Install URL must point to github.com: {install_url!r}"

    url   = _to_https_url(install_url)
    token = get_token()
    env, askpass_path = _askpass_env(token) if token else (None, None)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", url],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode == 0:
            return True, "Plugin installed successfully."
        output = (result.stderr or result.stdout).strip()
        return False, output or "pip exited with a non-zero status."
    except subprocess.TimeoutExpired:
        return False, "Installation timed out after 120 seconds."
    except Exception as exc:
        return False, str(exc)
    finally:
        if askpass_path:
            try:
                os.unlink(askpass_path)
            except OSError:
                pass


def get_plugin_channel() -> str:
    """Return the active plugin channel: 'stable' (default) or 'dev'."""
    from db.database import get_setting
    return get_setting("plugin_channel", default="stable") or "stable"


def set_plugin_channel(channel: str) -> None:
    """Persist the plugin channel ('stable' or 'dev')."""
    from db.database import set_setting
    set_setting("plugin_channel", channel)


def effective_install_url(plugin_entry: dict) -> str:
    """Return the install URL for the current channel.

    Falls back to install_url when install_url_dev is absent or the channel
    is stable.
    """
    if get_plugin_channel() == "dev":
        return plugin_entry.get("install_url_dev") or plugin_entry.get("install_url", "")
    return plugin_entry.get("install_url", "")


def uninstall_plugin(package_name: str) -> tuple[bool, str]:
    """Uninstall a plugin using pip.

    Returns (True, success_message) or (False, error_output).
    """
    if not _SAFE_PACKAGE_RE.match(package_name):
        return False, f"Invalid package name: {package_name!r}"
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
