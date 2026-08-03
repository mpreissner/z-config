"""Plugin manager API router.

Exposes the operations `cli/menus/plugin_menu.py` already offers — GitHub login,
channel switching, manifest browsing, install, branch override, uninstall — so
the web UI can manage plugins without the TUI.

Four things shape the design:

*Off unless switched on.*  The whole router is registered only when the
environment variable named by ``MANAGER_ENV`` is set (see `api/main.py`).  On a
deployment that has not set it these paths fall through to the SPA catch-all
exactly like any address that was never routed, so nothing about the manager —
not a 403, not an entry in /docs — is visible to anyone poking at the API.  The
variable is deliberately absent from the README, the compose file and the
sample env: it is a switch for whoever runs the deployment, found by reading
this file.

*Managing and using are different roles.*  Installing a plugin runs pip against
a URL and then imports the result into this process on the next start, so every
management endpoint is behind `require_plugin_admin`, including the read-only
ones.  The three paths an entitled user reaches a plugin through — `/entitled`,
`/{package}/ui` and `/{package}/actions/{key}` — are behind `require_plugin_user`,
which admins fail: an admin installs and grants plugins, they do not run them.
An account that does both holds both roles and switches between them.  Every
refusal here is a 404, so neither role learns from the shape of one what the
other would have found.

*Installing is not publishing.*  A plugin becomes usable by an account only
once an admin grants it, per user or per SCIM group — zs-config may be shared,
and the team that asked for a plugin is rarely everyone with a login.  The
grant list lives in `services/plugin_entitlement_service.py`.

*A plugin's web interface is declarative.*  A plugin describes its actions and
their parameters; it ships no markup and no JavaScript, and its `run` callables
never leave the server.  `lib/plugin_web.py` holds that contract.  Every tenant
parameter is checked against the caller's own entitlements before an action
starts, so a plugin cannot widen the reach of the account running it.  A select
whose options the plugin computes is re-resolved when the action runs and the
submitted value checked against the result, because the dropdown that offered
it is on the far side of the request and proves nothing.

*An action may produce a file.*  Anything an action returns under `file` is
moved into a per-run spool directory and served from `/downloads/{job_id}` to
the account that started the job, until it ages out on the same clock the job
store uses.  The path never reaches the browser and the job id alone is not
authority to read it.

*A GitHub auth failure is never a 401.*  The web client logs the user out when
an authenticated call comes back 401 (`web/src/api/client.ts`), and "your
GitHub token expired" has nothing to do with the zs-config session.  Those are
409, and an upstream GitHub failure is 502.

*pip mutations are serialised.*  Install, uninstall and the branch switch all
share one job key, so two pip processes can never run against the same
environment at once.

Entry points are read when the interpreter starts, so a plugin that was just
installed or removed is not live until the process restarts.  Every job that
touches pip says so in its result rather than pretending the change took
effect.
"""

import os
import shutil
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.dependencies import require_auth, check_tenant_access, AuthUser
from api.jobs import store
from lib import plugin_web

router = APIRouter(prefix="/api/v1/plugins", tags=["Plugins"])

# The switch that makes the plugin manager exist at all. Undocumented on
# purpose — see the module docstring. Set it to 1/true/yes/on before starting
# the API to expose this router.
MANAGER_ENV = "ZS_EXT_MODULES"

# One key for every pip-mutating job: install, uninstall and the branch switch
# all rewrite the same site-packages, so they queue behind each other.
_PIP_JOB_KEY = "plugin:pip"

_NOT_AUTHENTICATED = "Not authenticated to GitHub — log in first."

# Files produced by plugin actions, keyed by the job that made them, kept until
# the job itself would have aged out of the store. Held here rather than in the
# job result because the entry carries a server path and the owning account:
# neither belongs in something the browser reads, and the job store has no
# notion of who a job was for.
_ARTIFACT_TTL_SECONDS = 3600            # api.jobs._FINISHED_TTL_SECONDS
_artifacts: Dict[str, dict] = {}
_artifacts_lock = threading.Lock()


def manager_enabled() -> bool:
    """Whether this deployment exposes the plugin manager."""
    return os.environ.get(MANAGER_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def require_plugin_user(user: AuthUser = Depends(require_auth)) -> AuthUser:
    """A session that may *use* a plugin, which an admin session is not.

    Admins install, grant and remove plugins; they do not run them, exactly as
    they cannot reach Templates or Scheduled Tasks.  An account that needs both
    holds both roles and switches (see `services/role_service.py`) — the admin
    role is for managing the deployment, and one session only ever holds one.

    404 like everything else here, so the refusal says nothing about what the
    account would find after switching.
    """
    if not manager_enabled() or user.role == "admin":
        raise HTTPException(status_code=404, detail="Not Found")
    return user


def require_plugin_admin(user: AuthUser = Depends(require_auth)) -> AuthUser:
    """Admin, on a deployment where the manager is switched on.

    Both failures answer 404 with FastAPI's own wording: a 403 would tell a
    non-admin that there is a plugin manager here to be refused access to.
    """
    if not manager_enabled() or user.role != "admin":
        raise HTTPException(status_code=404, detail="Not Found")
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialisable(plugin: dict) -> dict:
    """Drop the menu callable — the rest of the entry is JSON."""
    return {
        "name": plugin.get("name"),
        "package": plugin.get("package"),
        "version": plugin.get("version"),
        "entry_point": plugin.get("entry_point"),
        "has_menu": plugin.get("menu") is not None,
        "error": plugin.get("error"),
    }


def _validate_package(package: str) -> str:
    from lib.plugin_manager import is_valid_package_name

    if not is_valid_package_name(package):
        raise HTTPException(status_code=400, detail=f"Invalid package name: {package!r}")
    return package


def _require_installed(package: str) -> dict:
    from lib.plugin_manager import get_installed_plugins

    _validate_package(package)
    for plugin in get_installed_plugins():
        if plugin.get("package") == package:
            return plugin
    raise HTTPException(status_code=404, detail=f"Plugin '{package}' is not installed")


def _prune_artifacts_locked() -> None:
    """Drop spooled files past their TTL. Caller must hold the lock.

    Downloads are not deleted on read: a browser that retries, or a user who
    clicks twice, should get the file both times. Age is the only thing that
    removes one, which is also what bounds the disk this can hold.
    """
    cutoff = time.time() - _ARTIFACT_TTL_SECONDS
    for job_id in [j for j, a in _artifacts.items() if a["created_at"] < cutoff]:
        shutil.rmtree(_artifacts.pop(job_id)["spool"], ignore_errors=True)


def _register_artifact(job_id: str, spool: str, artifact: dict, user_id: int) -> None:
    with _artifacts_lock:
        _prune_artifacts_locked()
        _artifacts[job_id] = {**artifact, "spool": spool, "user_id": user_id,
                              "created_at": time.time()}


def _github_error(message: str) -> HTTPException:
    """Map a plugin_manager error string onto a status the web client can act on.

    Never 401: see the module docstring.
    """
    if "Not authenticated" in message:
        return HTTPException(status_code=409, detail=_NOT_AUTHENTICATED)
    if "token expired" in message or "revoked" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=502, detail=message)


def _audit(operation: str, action: str, status: str, package: str, **details) -> None:
    from services import audit_service

    audit_service.log(
        product=None,
        operation=operation,
        action=action,
        status=status,
        resource_type="plugin",
        resource_name=package,
        details=details or None,
    )


# ---------------------------------------------------------------------------
# Installed plugins and manager state
# ---------------------------------------------------------------------------

@router.get("")
def list_installed(user: AuthUser = Depends(require_plugin_admin)):
    """Plugins discovered via entry points in the running interpreter."""
    from lib.plugin_manager import get_installed_plugins

    return {"plugins": [_serialisable(p) for p in get_installed_plugins()]}


@router.get("/status")
def plugin_status(verify: bool = True, user: AuthUser = Depends(require_plugin_admin)):
    """Manager state: GitHub session, channel, overrides, deferred install.

    `verify=false` skips the round trip to GitHub and reports only whether a
    token is stored — for callers that poll this and do not want to spend an
    API call each time.
    """
    from lib.github_auth import get_token, verify_token
    from lib.plugin_manager import (
        get_pending_plugin_install, get_plugin_branch_overrides, get_plugin_channel,
    )

    token = get_token()
    github = {"authenticated": False, "username": None, "error": None}
    if token and not verify:
        github["authenticated"] = True
    elif token:
        valid, detail = verify_token(token)
        if valid:
            github["authenticated"] = True
            github["username"] = detail
        else:
            github["error"] = detail

    return {
        "github": github,
        "channel": get_plugin_channel(),
        "branch_overrides": get_plugin_branch_overrides(),
        "pending_install": get_pending_plugin_install(),
    }


# ---------------------------------------------------------------------------
# GitHub authentication (device flow)
# ---------------------------------------------------------------------------

@router.post("/auth/device", status_code=202)
def start_github_login(user: AuthUser = Depends(require_plugin_admin)):
    """Begin GitHub device-flow login. Returns the code to enter, plus a job_id.

    The browser that completes this is the user's, not the server's, so the
    response carries the user code and verification URL and a background job
    does the polling.  The device code stays server-side: it is the half of the
    exchange that redeems into a token.
    """
    from lib.github_auth import poll_device_flow, start_device_flow

    flow, error = start_device_flow()
    if error:
        raise HTTPException(status_code=502, detail=error)

    job_id, created = store.create_unique("plugin:github-login")
    if not created:
        # A login is already polling; that one still holds a live code.
        return {"job_id": job_id, "already_running": True}

    device_code = flow["device_code"]
    expires_in = flow["expires_in"]
    interval = flow["interval"]

    def run():
        def on_progress(message: str) -> None:
            store.append(job_id, {"type": "progress", "message": message})

        try:
            ok, message = poll_device_flow(
                device_code,
                expires_in=expires_in,
                interval=interval,
                progress_callback=on_progress,
            )
        except Exception as exc:
            store.fail(job_id, str(exc))
            return

        if ok:
            store.complete(job_id, {"authenticated": True, "message": message})
        else:
            store.fail(job_id, message)

    threading.Thread(target=run, daemon=True).start()
    return {
        "job_id": job_id,
        "already_running": False,
        "user_code": flow["user_code"],
        "verification_uri": flow["verification_uri"],
        "expires_in": expires_in,
    }


@router.delete("/auth")
def github_logout(user: AuthUser = Depends(require_plugin_admin)):
    """Discard the stored GitHub token. Installed plugins keep working."""
    from lib.github_auth import logout

    logout()
    _audit("plugin_github_logout", "DELETE", "SUCCESS", "github")
    return {"authenticated": False}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@router.get("/available")
def list_available(user: AuthUser = Depends(require_plugin_admin)):
    """Manifest entries for the active channel, annotated with install state.

    `install_url` is the URL this host would actually use — channel and any
    per-plugin pin already applied — so the UI shows what will be installed
    rather than the stable default.

    `pinned_ref` is that plugin's own pin, `effective_ref` the ref it resolves
    to once the channel fills in for an absent pin. The two are separate because
    the UI has to distinguish "follows the channel, which happens to be dev"
    from "pinned to dev regardless of the channel".
    """
    from lib.plugin_manager import (
        effective_install_url, fetch_manifest, get_installed_plugins,
        get_manifest_ref, get_plugin_branch_overrides, get_plugin_channel,
    )

    available, error = fetch_manifest()
    if error:
        raise _github_error(error)

    channel = get_plugin_channel()
    pins = get_plugin_branch_overrides()
    installed = {p["package"]: p for p in get_installed_plugins()}
    plugins = []
    for entry in available or []:
        package = entry.get("package")
        current = installed.get(package)
        pinned = pins.get(package)
        plugins.append({
            "name": entry.get("display_name") or entry.get("name"),
            "package": package,
            "description": entry.get("description", ""),
            "version": entry.get("version", ""),
            "installed": current is not None,
            "installed_version": current.get("version") if current else None,
            "install_url": effective_install_url(entry),
            "pinned_ref": pinned,
            "effective_ref": pinned or channel,
            "has_dev": bool(entry.get("install_url_dev")),
        })
    return {"plugins": plugins, "ref": get_manifest_ref(), "channel": channel}


@router.get("/{package}/branches")
def list_branches(package: str, user: AuthUser = Depends(require_plugin_admin)):
    """Feature branches available for a plugin, for the branch override flow."""
    from lib.plugin_manager import fetch_plugin_branches

    _validate_package(package)
    branches, error = fetch_plugin_branches(package)
    if error:
        raise _github_error(error)
    return {"package": package, "branches": branches}


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class ChannelRequest(BaseModel):
    channel: str


@router.put("/channel")
def set_channel(body: ChannelRequest, user: AuthUser = Depends(require_plugin_admin)):
    """Switch between the stable and dev plugin channels.

    Takes effect on the next install — nothing already installed changes here.
    """
    from lib.plugin_manager import get_plugin_channel, set_plugin_channel

    channel = (body.channel or "").strip().lower()
    if channel not in ("stable", "dev"):
        raise HTTPException(status_code=400, detail="Channel must be 'stable' or 'dev'")

    previous = get_plugin_channel()
    set_plugin_channel(channel)
    _audit("plugin_channel", "UPDATE", "SUCCESS", "plugin_channel",
           previous=previous, channel=channel)
    return {"channel": channel, "previous": previous}


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

class InstallRequest(BaseModel):
    package: Optional[str] = None   # resolve the URL from the manifest
    url: Optional[str] = None       # or install straight from a git URL


def _resolve_install_url(body: InstallRequest) -> tuple[str, str]:
    """(install_url, package label) for an install request, or 400/404."""
    from lib.plugin_manager import effective_install_url, fetch_manifest

    if body.url:
        return body.url, (body.package or body.url)

    if not body.package:
        raise HTTPException(status_code=400, detail="Provide either 'package' or 'url'")

    _validate_package(body.package)
    available, error = fetch_manifest()
    if error:
        raise _github_error(error)

    entry = next(
        (p for p in (available or []) if p.get("package") == body.package), None
    )
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"'{body.package}' is not in the plugin manifest"
        )

    url = effective_install_url(entry)
    if not url:
        raise HTTPException(
            status_code=422, detail=f"No install URL in the manifest for '{body.package}'"
        )
    return url, body.package


@router.post("/install", status_code=202)
def install(body: InstallRequest, user: AuthUser = Depends(require_plugin_admin)):
    """Install a plugin from the manifest or a git URL. Returns a job_id.

    Backgrounded because pip clones and builds; `install_plugin` caps it at 120
    seconds.  The URL is validated against github.com inside `install_plugin`,
    so a hand-supplied one cannot point anywhere else.
    """
    from lib.plugin_manager import install_plugin

    install_url, label = _resolve_install_url(body)

    job_id, created = store.create_unique(_PIP_JOB_KEY)
    if not created:
        return {"job_id": job_id, "already_running": True}

    def run():
        store.append(job_id, {"type": "progress", "message": f"Installing {label}..."})
        try:
            ok, message = install_plugin(install_url)
        except Exception as exc:
            store.fail(job_id, str(exc))
            _audit("plugin_install", "CREATE", "FAILED", label, error=str(exc))
            return

        if not ok:
            store.fail(job_id, message)
            _audit("plugin_install", "CREATE", "FAILED", label, error=message)
            return

        store.complete(job_id, {
            "installed": True,
            "package": label,
            "message": message,
            "restart_required": True,
        })
        _audit("plugin_install", "CREATE", "SUCCESS", label)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id, "already_running": False}


# ---------------------------------------------------------------------------
# Branch override
# ---------------------------------------------------------------------------

class BranchOverrideRequest(BaseModel):
    branch: Optional[str] = None    # 'stable' | 'dev' | a branch; None follows the channel
    reinstall: bool = True


@router.put("/{package}/branch", status_code=202)
def set_branch(
    package: str, body: BranchOverrideRequest, user: AuthUser = Depends(require_plugin_admin)
):
    """Pin one plugin to a ref — a channel name or a branch — and reinstall it.

    The pin is per plugin, so a deployment can hold one plugin on stable while
    another follows dev and a third tracks a feature branch. `branch: null`
    drops the pin and returns that plugin to the channel setting.

    Mirrors the TUI's hidden Ctrl+] flow: uninstall, record the pin, then
    install from the new ref.  The uninstall does not purge — this is a version
    switch, and the user's in-progress data belongs to the plugin either way.

    `reinstall=false` records the pin without touching pip, for pinning a
    plugin that is not installed yet.
    """
    from lib.plugin_manager import (
        clear_pending_plugin_install, fetch_manifest, get_plugin_channel,
        install_plugin, install_url_for_ref, set_pending_plugin_install,
        set_plugin_branch_override, uninstall_plugin,
    )

    _validate_package(package)
    branch = (body.branch or "").strip() or None

    if not body.reinstall:
        set_plugin_branch_override(package, branch)
        _audit("plugin_branch_override", "UPDATE", "SUCCESS", package, branch=branch)
        return {"package": package, "branch": branch, "reinstalled": False}

    _require_installed(package)

    available, error = fetch_manifest()
    if error:
        raise _github_error(error)

    entry = next(
        (p for p in (available or []) if p.get("package") == package), None
    )
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"'{package}' is not in the plugin manifest"
        )

    # A cleared pin falls back to the channel, so both cases resolve through the
    # same ref vocabulary — 'stable' and 'dev' are refs like any branch name.
    channel = get_plugin_channel()
    ref = branch or channel
    install_url = install_url_for_ref(entry, ref)
    if not install_url:
        raise HTTPException(
            status_code=422, detail=f"No install URL for '{package}' at '{ref}'"
        )

    job_id, created = store.create_unique(_PIP_JOB_KEY)
    if not created:
        return {"job_id": job_id, "already_running": True}

    label = branch or f"channel default ({channel})"

    def run():
        try:
            store.append(job_id, {"type": "progress", "message": f"Uninstalling {package}..."})
            ok, message = uninstall_plugin(package)   # never purge on a version switch
            if not ok:
                store.fail(job_id, message)
                _audit("plugin_branch_override", "UPDATE", "FAILED", package,
                       branch=branch, error=message)
                return

            set_plugin_branch_override(package, branch)
            # Recorded before the install so a failure mid-way is recoverable:
            # the next TUI launch completes the install that did not happen here.
            set_pending_plugin_install(package, install_url)

            store.append(job_id, {"type": "progress",
                                  "message": f"Installing {package} from {label}..."})
            ok, message = install_plugin(install_url)
            if not ok:
                store.fail(job_id, message)
                _audit("plugin_branch_override", "UPDATE", "FAILED", package,
                       branch=branch, error=message)
                return

            clear_pending_plugin_install()
            store.complete(job_id, {
                "package": package,
                "branch": branch,
                "reinstalled": True,
                "message": message,
                "restart_required": True,
            })
            _audit("plugin_branch_override", "UPDATE", "SUCCESS", package, branch=branch)
        except Exception as exc:
            store.fail(job_id, str(exc))
            _audit("plugin_branch_override", "UPDATE", "FAILED", package,
                   branch=branch, error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id, "already_running": False}


# ---------------------------------------------------------------------------
# Entitlements
#
# Declared before DELETE /{package} for the same reason as the section below:
# /entitlements/{id} is two segments and safe, but keeping the whole literal
# family above the wildcard means a later addition cannot be swallowed by it.
# ---------------------------------------------------------------------------

class EntitlementGrant(BaseModel):
    package: str
    user_ids: List[int] = []
    group_ids: List[int] = []


@router.get("/entitled")
def my_plugins(user: AuthUser = Depends(require_plugin_user)):
    """Which plugins the calling account may use, and which of those it can open.

    It answers only about the caller, and an account with no grants gets an
    empty list — the same answer as a deployment with no plugins at all, which
    is why the nav can ask this without first establishing that the manager is
    switched on.

    `plugins` is the nav: entitled *and* installed *and* offering a usable web
    spec.  A grant for something not installed yet, or installed but with no
    web interface, is real but has nowhere to point, so it is left out rather
    than rendered as a link to a dead page.  `packages` is the raw grant list.

    `entitled_packages` returns None for an unrestricted account, but no admin
    session reaches this endpoint, so the list here is always a real one.
    """
    from lib.plugin_manager import get_installed_plugins
    from lib import plugin_web
    from services import plugin_entitlement_service

    packages = plugin_entitlement_service.entitled_packages(user.user_id, user.role) or []

    plugins = []
    for plugin in get_installed_plugins():
        package = plugin.get("package")
        if package not in packages:
            continue
        spec = plugin_web.describe(plugin)
        if not spec:
            continue
        plugins.append({
            "package": package,
            "name": plugin.get("name"),
            "version": plugin.get("version"),
        })
    plugins.sort(key=lambda p: (p["name"] or "").lower())

    return {"packages": packages, "plugins": plugins}


def _entitled_plugin(package: str, user: AuthUser) -> dict:
    """The installed plugin this account is allowed to open, or 404.

    Not being entitled answers exactly as not being installed does.  A user who
    was never granted a plugin has no way to learn from the API that it exists
    on this deployment, which is the same reasoning behind `require_plugin_admin`
    and `require_plugin_user` answering 404 rather than 403.
    """
    from services import plugin_entitlement_service

    _validate_package(package)
    if not plugin_entitlement_service.may_use(user.user_id, user.role, package):
        raise HTTPException(status_code=404, detail=f"Plugin '{package}' is not installed")
    return _require_installed(package)


@router.get("/{package}/ui")
def plugin_ui(package: str, user: AuthUser = Depends(require_plugin_user)):
    """The declarative description of one plugin's web interface.

    Everything the page needs to draw itself: the actions, their parameters and
    how to label them.  The `run` callables never leave the server.
    """
    from lib import plugin_web

    plugin = _entitled_plugin(package, user)
    spec = plugin_web.describe(plugin)
    if not spec:
        raise HTTPException(
            status_code=404, detail=f"Plugin '{package}' has no web interface"
        )
    return spec


def _resolve_action(package: str, action_key: str, user: AuthUser) -> tuple[dict, dict, dict]:
    """`(plugin, described action, raw action)` for a package the caller may use.

    Both actions come back with the plugin's page-level context folded in as
    ordinary parameters, so a value the user entered once at the top of the page
    is coerced, entitlement-checked and re-resolved on exactly the same path as
    one typed into the action's own form.
    """
    plugin = _entitled_plugin(package, user)
    described = plugin_web.describe(plugin)
    action = next(
        (a for a in (described or {}).get("actions", []) if a["key"] == action_key), None
    )
    if not action:
        raise HTTPException(status_code=404, detail=f"Unknown action '{action_key}'")

    raw_action = plugin_web.find_action(plugin, action_key)
    if not raw_action or not callable(raw_action.get("run")):
        raise HTTPException(status_code=500, detail=f"Action '{action_key}' has no runnable")

    bound = plugin_web.bind_context(described, action)
    return plugin, bound, plugin_web.bind_raw_context(plugin, raw_action, action)


def _described(package: str, user: AuthUser) -> tuple[dict, dict]:
    """`(plugin, described spec)` for a package the caller may use."""
    plugin = _entitled_plugin(package, user)
    described = plugin_web.describe(plugin)
    if not described:
        raise HTTPException(
            status_code=404, detail=f"Plugin '{package}' has no web interface"
        )
    return plugin, described


def _authorised_options(
    action: dict, raw_action: dict, param: str, supplied: Dict[str, Any], user: AuthUser
) -> List[dict]:
    """The current options for one dynamic select, with its tenant checked first.

    The only value a plugin gets to see here is one the caller was already
    entitled to, so a loader that scopes its query by tenant — which is the
    whole reason a snapshot list is per-tenant — cannot be pointed at a tenant
    the account could not have opened itself.
    """
    if param not in plugin_web.dynamic_params(action):
        raise HTTPException(status_code=404, detail=f"'{param}' has no options to load")

    try:
        params = plugin_web.coerce_params(action, supplied, partial=True)
    except plugin_web.PluginWebError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))

    for name in plugin_web.tenant_params(action):
        if params.get(name) is not None:
            check_tenant_access(int(params[name]), user)

    try:
        return plugin_web.resolve_options(raw_action, param, params)
    except plugin_web.PluginWebError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    except Exception as exc:
        # A plugin that throws while listing its own options is a broken
        # plugin, not a broken request — 502 keeps that distinction, and the
        # message lands next to the empty dropdown it explains.
        raise HTTPException(status_code=502, detail=f"Could not load options: {exc}")


class OptionsRequest(BaseModel):
    params: Dict[str, Any] = {}


@router.post("/{package}/actions/{action_key}/options/{param}")
def plugin_action_options(
    package: str,
    action_key: str,
    param: str,
    body: OptionsRequest,
    user: AuthUser = Depends(require_plugin_user),
):
    """The options for one dynamic select, given the form as it stands.

    POST rather than GET because the answer depends on a body of arbitrary
    parameter values, and because a tenant id has no business in a URL that
    ends up in an access log.
    """
    _, action, raw_action = _resolve_action(package, action_key, user)
    options = _authorised_options(action, raw_action, param, body.params, user)
    return {"options": options}


@router.post("/{package}/context/options/{param}")
def plugin_context_options(
    package: str,
    param: str,
    body: OptionsRequest,
    user: AuthUser = Depends(require_plugin_user),
):
    """The options for one page-level context value.

    The context bar is drawn before any action has been chosen, so it cannot ask
    through an action's endpoint. The synthetic action it resolves against holds
    the context parameters and nothing else, which keeps the coercion and the
    tenant check identical to every other option load.
    """
    plugin, described = _described(package, user)
    action = plugin_web.context_action(described)
    raw_action = plugin_web.raw_context_action(plugin)
    options = _authorised_options(action, raw_action, param, body.params, user)
    return {"options": options}


@router.post("/{package}/state")
def plugin_workflow_state(
    package: str,
    body: OptionsRequest,
    user: AuthUser = Depends(require_plugin_user),
):
    """How far along each declared step is, for the context the caller names.

    Advisory only: it decides what the step strip looks like, never what may be
    run. A step the plugin calls blocked is still an action the caller can post
    to directly, and it is authorised there on its own terms.
    """
    plugin, described = _described(package, user)
    workflow = described.get("workflow")
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Plugin '{package}' has no workflow")

    state_fn = plugin_web.find_workflow_state(plugin)
    if not state_fn:
        return {"state": plugin_web.normalise_state(None, workflow)}

    action = plugin_web.context_action(described)
    try:
        params = plugin_web.coerce_params(action, body.params, partial=True)
    except plugin_web.PluginWebError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))

    for name in plugin_web.tenant_params(action):
        if params.get(name) is not None:
            check_tenant_access(int(params[name]), user)

    try:
        return {"state": plugin_web.normalise_state(state_fn(dict(params)), workflow)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read plugin state: {exc}")


async def _collect_params(request, action: dict) -> tuple[dict, Optional[str]]:
    """Pull the caller's values off the request, saving uploads to disk.

    Two shapes, because a file cannot ride in a JSON body: a plain JSON object,
    or multipart with the non-file values as a JSON string in `params` and each
    file under its own parameter name. Returns the raw values and the temp
    directory to delete once the action has finished with them.
    """
    import json
    import shutil
    import tempfile
    from pathlib import Path

    wanted_files = plugin_web.file_params(action)
    content_type = request.headers.get("content-type", "")

    if not content_type.startswith("multipart/form-data"):
        try:
            supplied = await request.json()
        except Exception:
            supplied = {}
        if not isinstance(supplied, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object")
        return supplied, None

    form = await request.form()
    try:
        supplied = json.loads(form.get("params") or "{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="'params' is not valid JSON")
    if not isinstance(supplied, dict):
        raise HTTPException(status_code=400, detail="'params' must be a JSON object")

    tmpdir = None
    for name in wanted_files:
        upload = form.get(name)
        if upload is None or not hasattr(upload, "filename"):
            continue
        if tmpdir is None:
            tmpdir = tempfile.mkdtemp(prefix=".zs-plugin-")
        # The plugin gets a path it can open, never the client's own filename —
        # that string is attacker-controlled and has no business on this disk.
        dest = Path(tmpdir) / f"{name}.upload"
        with open(dest, "wb") as fh:
            shutil.copyfileobj(upload.file, fh)
        supplied[name] = str(dest)

    return supplied, tmpdir


@router.post("/{package}/actions/{action_key}", status_code=202)
async def run_plugin_action(
    package: str,
    action_key: str,
    request: Request,
    user: AuthUser = Depends(require_plugin_user),
):
    """Run one of a plugin's declared actions. Returns a job_id.

    Backgrounded unconditionally: a plugin action is arbitrary work of unknown
    length, and the job store already gives the page progress and cancellation
    for free.

    Every tenant parameter is checked against the caller's own entitlements
    before the action starts. A plugin cannot widen the reach of the account
    running it, whatever tenant id it was handed.
    """
    _, action, raw_action = _resolve_action(package, action_key, user)

    supplied, tmpdir = await _collect_params(request, action)
    try:
        try:
            params = plugin_web.coerce_params(action, supplied)
        except plugin_web.PluginWebError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc))

        # No admin exemption, unlike the tenant routers: an admin session cannot
        # reach this endpoint at all, so every caller here is entitlement-checked.
        for name in plugin_web.tenant_params(action):
            if params.get(name) is not None:
                check_tenant_access(int(params[name]), user)

        # A dynamic select was validated against nothing when it was coerced —
        # its options did not exist yet. Ask for them now that the tenant among
        # the params has been checked, and refuse anything the plugin would not
        # have offered. Without this, the dropdown is the only thing stopping a
        # caller naming a row belonging to someone else's tenant.
        for name in plugin_web.dynamic_params(action):
            # Nothing supplied and nothing ticked both mean there is no value to
            # check, and loading a grid's rows to validate an empty list is work
            # for its own sake.
            if not params.get(name):
                continue
            allowed = {
                o["value"]
                for o in _authorised_options(action, raw_action, name, supplied, user)
            }
            # A selection grid submits many values; each one has to have been on
            # the list the plugin just produced, not merely most of them.
            for value in plugin_web.submitted_values(action, name, params[name]):
                if value not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"'{name}' is not one of the offered options",
                    )
    except Exception:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    job_id = store.create(key=f"plugin:{package}:{action_key}")
    run_callable = raw_action["run"]
    label = action["label"]

    def run():
        ctx = plugin_web.PluginContext(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            job_id=job_id,
            emit=lambda m: store.append(
                job_id, {"type": "progress", "phase": "plugin", "message": m}
            ),
            cancelled=lambda: store.is_cancel_requested(job_id),
        )
        store.append(job_id, {"type": "progress", "phase": "plugin", "message": f"{label}..."})
        try:
            result = run_callable(params, ctx)
        except Exception as exc:
            store.fail(job_id, str(exc))
            _audit("plugin_action", "EXECUTE", "FAILED", package,
                   plugin_action=action_key, by=user.username, error=str(exc))
            return
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        import tempfile

        # Its own directory per run, so pruning one artifact cannot touch another
        # and a plugin that names its file anything at all cannot collide.
        spool = tempfile.mkdtemp(prefix="zs-plugin-dl-")
        try:
            rest, artifact = plugin_web.take_artifact(result, spool)
        except plugin_web.PluginWebError as exc:
            shutil.rmtree(spool, ignore_errors=True)
            store.fail(job_id, str(exc))
            _audit("plugin_action", "EXECUTE", "FAILED", package,
                   plugin_action=action_key, by=user.username, error=str(exc))
            return

        payload = plugin_web.normalise_result(rest)
        if artifact:
            _register_artifact(job_id, spool, artifact, user.user_id)
            payload["download"] = {
                "filename": artifact["filename"],
                "content_type": artifact["content_type"],
                "size": artifact["size"],
            }
        else:
            shutil.rmtree(spool, ignore_errors=True)

        store.complete(job_id, payload)
        _audit("plugin_action", "EXECUTE", "SUCCESS", package,
               plugin_action=action_key, by=user.username)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id, "already_running": False}


@router.get("/downloads/{job_id}")
def download_artifact(job_id: str, user: AuthUser = Depends(require_plugin_user)):
    """The file one of this account's plugin runs produced.

    Owned by the account that started the job, not by whoever holds the id: a
    job id is short and appears in the SSE stream, and an export is a whole
    tenant's configuration. Someone else's artifact answers exactly as an
    expired one does.

    Declared after the `/{package}/…` routes but never shadowed by them — the
    two-segment ones all end in a literal, and a job id is twelve hex digits.
    """
    with _artifacts_lock:
        _prune_artifacts_locked()
        entry = _artifacts.get(job_id)
        if not entry or entry["user_id"] != user.user_id:
            raise HTTPException(status_code=404, detail="No download for that job")
        path, filename, content_type = (
            entry["path"], entry["filename"], entry["content_type"]
        )

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No download for that job")
    return FileResponse(path, media_type=content_type, filename=filename)


@router.get("/entitlements")
def list_entitlements(package: Optional[str] = None,
                      user: AuthUser = Depends(require_plugin_admin)):
    """Every plugin grant, or those for one package."""
    from services import plugin_entitlement_service

    if package:
        _validate_package(package)
    return {"entitlements": plugin_entitlement_service.list_entitlements(package)}


@router.post("/entitlements", status_code=201)
def grant_entitlement(body: EntitlementGrant,
                      user: AuthUser = Depends(require_plugin_admin)):
    """Grant a plugin to users and/or SCIM groups.

    Granting does not require the plugin to be installed — an admin can line
    up access for a package before or after the install job finishes, and a
    branch switch briefly uninstalls the very plugin being granted.
    """
    from services import plugin_entitlement_service

    package = _validate_package(body.package)
    try:
        result = plugin_entitlement_service.grant(
            package,
            user_ids=body.user_ids,
            group_ids=body.group_ids,
            granted_by=user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result["granted"]:
        _audit("plugin_entitlement", "CREATE", "SUCCESS", package,
               user_ids=[e["user_id"] for e in result["granted"] if e["user_id"]],
               group_ids=[e["group_id"] for e in result["granted"] if e["group_id"]])
    return result


@router.delete("/entitlements/{entitlement_id}", status_code=204)
def revoke_entitlement(entitlement_id: int,
                       user: AuthUser = Depends(require_plugin_admin)):
    """Revoke one grant. Takes effect on the holder's next request."""
    from services import plugin_entitlement_service

    rows = plugin_entitlement_service.list_entitlements()
    row = next((r for r in rows if r["id"] == entitlement_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Entitlement not found")

    plugin_entitlement_service.revoke(entitlement_id)
    _audit("plugin_entitlement", "DELETE", "SUCCESS", row["package"],
           user_id=row["user_id"], group_id=row["group_id"])


# ---------------------------------------------------------------------------
# Deferred install
#
# Declared before DELETE /{package}: FastAPI matches in declaration order, and
# the literal path would otherwise be swallowed as a package name.
# ---------------------------------------------------------------------------

@router.delete("/pending-install")
def clear_pending(user: AuthUser = Depends(require_plugin_admin)):
    """Drop a deferred install left behind by a failed branch switch.

    Without this, a pending record that can never succeed would be retried on
    every TUI launch.
    """
    from lib.plugin_manager import clear_pending_plugin_install, get_pending_plugin_install

    pending = get_pending_plugin_install()
    clear_pending_plugin_install()
    return {"cleared": pending is not None, "pending_install": pending}


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

@router.get("/{package}/data")
def plugin_data(package: str, user: AuthUser = Depends(require_plugin_admin)):
    """What a purging uninstall of this plugin would remove.

    Read-only.  The UI shows this before asking to confirm, so the damage is
    named before it is offered.
    """
    from lib.plugin_manager import plugin_data_summary

    _require_installed(package)
    summary = plugin_data_summary(package)
    return {"package": package, **summary}


@router.delete("/{package}", status_code=202)
def uninstall(
    package: str, purge_data: bool = False, user: AuthUser = Depends(require_plugin_admin)
):
    """Uninstall a plugin, optionally removing its data. Returns a job_id.

    `purge_data` drops the tables the plugin declares and runs its teardown
    hook, and revokes every grant for the package; objects it already pushed to
    a tenant are untouched, because a successful push reverts them to ordinary
    tenant config.  A plain uninstall keeps the grants, so reinstalling or
    switching branch does not make the admin re-entitle everyone.
    """
    from lib.plugin_manager import uninstall_plugin

    _require_installed(package)

    job_id, created = store.create_unique(_PIP_JOB_KEY)
    if not created:
        return {"job_id": job_id, "already_running": True}

    def run():
        store.append(job_id, {"type": "progress", "message": f"Uninstalling {package}..."})
        try:
            ok, message = uninstall_plugin(package, purge_data=purge_data)
        except Exception as exc:
            store.fail(job_id, str(exc))
            _audit("plugin_uninstall", "DELETE", "FAILED", package,
                   purge_data=purge_data, error=str(exc))
            return

        if not ok:
            store.fail(job_id, message)
            _audit("plugin_uninstall", "DELETE", "FAILED", package,
                   purge_data=purge_data, error=message)
            return

        revoked = 0
        if purge_data:
            from services import plugin_entitlement_service
            revoked = plugin_entitlement_service.revoke_package(package)

        store.complete(job_id, {
            "uninstalled": True,
            "package": package,
            "purged_data": purge_data,
            "revoked_entitlements": revoked,
            "message": message,
            "restart_required": True,
        })
        _audit("plugin_uninstall", "DELETE", "SUCCESS", package,
               purge_data=purge_data, revoked_entitlements=revoked)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id, "already_running": False}
