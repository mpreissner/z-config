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

# Keyword used to filter feature branches per plugin package.
# Branches under feature/ are included only if the keyword appears in the name.
# Add an entry here whenever a new plugin is added to zs-plugins.
_PLUGIN_BRANCH_FILTERS: dict[str, str] = {
    "palo-tools":          "pan",
    "snapshot-tools":      "snap",
}


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


def fetch_plugin_branches(package_name: str) -> tuple[list[str], Optional[str]]:
    """Fetch feature branches for a plugin from the zs-plugins repo.

    Filters to branches starting with 'feature/' and containing the keyword
    defined in _PLUGIN_BRANCH_FILTERS for the given package.  If no keyword is
    defined the full feature/* list is returned unfiltered.

    Returns (sorted_branch_list, None) on success or ([], error_message) on failure.
    """
    token = get_token()
    if not token:
        return [], "Not authenticated — log in first."

    keyword = _PLUGIN_BRANCH_FILTERS.get(package_name)

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{_MANIFEST_REPO}/branches",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/vnd.github+json",
            },
            params={"per_page": 100},
            timeout=10,
        )
        if resp.status_code == 401:
            return [], "GitHub token expired or revoked — please re-authenticate."
        if resp.status_code == 403:
            return [], "Access denied — you may not have access to this plugin repository."
        if resp.status_code == 404:
            return [], "Repository not found."
        resp.raise_for_status()

        branches = [b["name"] for b in resp.json() if b["name"].startswith("feature/")]
        if keyword:
            branches = [b for b in branches if keyword in b]
        return sorted(branches), None
    except Exception as exc:
        return [], f"Failed to fetch branches: {exc}"


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def _pip_install_args() -> list[str]:
    """Return extra pip args for plugin install. Adds --user in container mode."""
    if os.environ.get("ZS_CONTAINER_MODE") == "1":
        return ["--user"]
    return []


def _pip_uninstall_args() -> list[str]:
    return []


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
            [sys.executable, "-m", "pip", "install", *_pip_install_args(), url],
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


def get_plugin_branch_overrides() -> dict:
    """Return per-package branch overrides: {package_name: branch_name}."""
    import json
    from db.database import get_setting
    raw = get_setting("plugin_branch_overrides")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def get_pending_plugin_install() -> Optional[dict]:
    """Return a pending deferred plugin install as {package, url}, or None."""
    import json
    from db.database import get_setting
    raw = get_setting("plugin_pending_install")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def set_pending_plugin_install(package: str, url: str) -> None:
    """Store a plugin install to be completed on the next launch."""
    import json
    from db.database import set_setting
    set_setting("plugin_pending_install", json.dumps({"package": package, "url": url}))


def clear_pending_plugin_install() -> None:
    """Clear any pending plugin install record."""
    from db.database import set_setting
    set_setting("plugin_pending_install", None)


def set_plugin_branch_override(package_name: str, branch: Optional[str]) -> None:
    """Set or clear a branch override for a specific package.

    When set, the override takes precedence over the active channel when
    constructing install URLs via url_for_branch().
    Pass branch=None to clear the override.
    """
    import json
    from db.database import set_setting
    overrides = get_plugin_branch_overrides()
    if branch:
        overrides[package_name] = branch
    else:
        overrides.pop(package_name, None)
    set_setting("plugin_branch_overrides", json.dumps(overrides))


def url_for_branch(base_url: str, branch: str) -> str:
    """Return a pip git URL with the specified branch injected.

    git+https://github.com/org/repo.git#sub        → …@branch#sub
    git+https://github.com/org/repo.git@dev#sub     → …@branch#sub
    """
    # Strip any existing @ref before the fragment (handles both https and ssh URLs).
    # SSH URLs contain 'git@github.com' so the pattern anchors past that literal.
    stripped = re.sub(
        r'(git\+(?:https://(?:[^@/]+@)?|ssh://git@)github\.com/[^@#]+)@[^#]+',
        r'\1',
        base_url,
    )
    if '#' in stripped:
        base, fragment = stripped.split('#', 1)
        return f"{base}@{branch}#{fragment}"
    return f"{stripped}@{branch}"


def effective_install_url(plugin_entry: dict) -> str:
    """Return the install URL for the current channel and any branch override.

    Priority: per-package branch override > channel setting > stable.
    """
    package   = plugin_entry.get("package", "")
    overrides = get_plugin_branch_overrides()

    if package in overrides:
        branch   = overrides[package]
        base_url = plugin_entry.get("install_url_dev") or plugin_entry.get("install_url", "")
        return url_for_branch(base_url, branch) if base_url else ""

    if get_plugin_channel() == "dev":
        return plugin_entry.get("install_url_dev") or plugin_entry.get("install_url", "")
    return plugin_entry.get("install_url", "")


def uninstall_plugin(package_name: str, purge_data: bool = False) -> tuple[bool, str]:
    """Uninstall a plugin using pip.

    When purge_data is True, the plugin's tables and rows are removed first —
    see purge_plugin_data(). It defaults to False because the branch/channel
    switch flow also calls this to uninstall before reinstalling from another
    ref; purging there would destroy the user's in-progress work. Only a genuine
    user-initiated uninstall opts in.

    Returns (True, success_message) or (False, error_output).
    """
    if not _SAFE_PACKAGE_RE.match(package_name):
        return False, f"Invalid package name: {package_name!r}"

    # Before pip removes the package — register() must still be importable.
    # A failed purge aborts the uninstall rather than leaving the plugin
    # half-removed with its data stranded.
    if purge_data:
        ok, msg = purge_plugin_data(package_name)
        if not ok:
            return False, f"Data removal failed, plugin not uninstalled:\n{msg}"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "--yes", *_pip_uninstall_args(), package_name],
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


# ---------------------------------------------------------------------------
# Plugin data teardown
# ---------------------------------------------------------------------------

# Plugin-declared table names are interpolated into DDL, so they are validated
# against this before use — never trusted as-is.
_SAFE_TABLE_RE = re.compile(r'^[a-zA-Z0-9_]+$')


def _plugin_entry(package_name: str) -> Optional[dict]:
    """Return the register() payload for an installed package, or None."""
    for p in get_installed_plugins():
        if p.get("package") == package_name:
            return p
    return None


def _owned_tables(package_name: str) -> tuple[list[str], Optional[str]]:
    """Resolve a plugin's declared tables to ones that are safe to drop.

    Returns (tables, error). Rejects names that are malformed or that belong to
    core's own schema; silently skips ones that do not exist in the database.
    """
    entry = _plugin_entry(package_name)
    if entry is None:
        return [], f"Plugin {package_name!r} is not installed or failed to load."

    declared = entry.get("owns_tables") or []
    if not isinstance(declared, (list, tuple)):
        return [], "owns_tables must be a list of table names."

    from db.database import get_engine
    from db.models import Base
    from sqlalchemy import inspect

    core_tables = set(Base.metadata.tables)
    existing = set(inspect(get_engine()).get_table_names())

    tables = []
    for name in declared:
        if not isinstance(name, str) or not _SAFE_TABLE_RE.match(name):
            return [], f"Refusing unsafe table name: {name!r}"
        if name in core_tables:
            return [], f"Refusing to drop core table: {name!r}"
        if name in existing:
            tables.append(name)
    return tables, None


def plugin_data_summary(package_name: str) -> dict:
    """Read-only count of what purge_plugin_data() would remove.

    Returns {"tables": [...], "rows": int, "candidates": int, "error": str|None}
    so the caller can name the damage before asking for confirmation.
    """
    summary = {"tables": [], "rows": 0, "candidates": 0, "error": None}

    tables, err = _owned_tables(package_name)
    if err:
        summary["error"] = err
        return summary
    summary["tables"] = tables

    from db.database import get_engine
    from sqlalchemy import text

    try:
        with get_engine().connect() as conn:
            for name in tables:
                summary["rows"] += conn.execute(
                    text(f'SELECT COUNT(*) FROM "{name}"')  # name validated above
                ).scalar() or 0

            # Unpushed migration candidates in core tables. Pushed objects have
            # source reverted to 'tenant' and are deliberately not counted.
            for core in ("zia_resources", "zpa_resources"):
                summary["candidates"] += conn.execute(
                    text(f"SELECT COUNT(*) FROM {core} WHERE source = :s"),
                    {"s": "palo"},
                ).scalar() or 0
    except Exception as exc:
        summary["error"] = str(exc)
    return summary


def purge_plugin_data(package_name: str) -> tuple[bool, str]:
    """Remove a plugin's tables and its rows in core tables.

    The plugin's optional teardown(session) hook runs first, for row-level
    cleanup in tables it does not own; then core drops the tables it declared.
    Both happen in one transaction — if anything raises, nothing is removed.

    Objects the plugin already pushed to a tenant are untouched: on a successful
    push source reverts to 'tenant', making them indistinguishable from natively
    imported config.
    """
    tables, err = _owned_tables(package_name)
    if err:
        return False, err

    entry = _plugin_entry(package_name)
    teardown = (entry or {}).get("teardown")
    if teardown is not None and not callable(teardown):
        return False, "teardown must be callable."

    from db.database import get_session
    from sqlalchemy import text

    try:
        with get_session() as session:
            if teardown is not None:
                # The hook must not commit or open its own session — it shares
                # this transaction so a later failure rolls its work back too.
                teardown(session)
                session.flush()

            for name in tables:
                session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    except Exception as exc:
        return False, str(exc)

    dropped = f"{len(tables)} table(s)" if tables else "no tables"
    return True, f"Removed plugin data ({dropped})."
