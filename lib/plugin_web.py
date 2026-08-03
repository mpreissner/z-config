"""The contract between a plugin and the zs-config web UI.

A plugin describes its interface instead of drawing it. `register()` returns a
`web` dict listing actions; each action names its parameters and supplies the
callable that does the work. zs-config renders the form, validates what comes
back, runs the action as a background job and displays the result, so a plugin
ships no JavaScript and no HTML and cannot break the page it appears on.

    "web": {
        "description": "Optional blurb shown under the plugin heading.",
        "actions": [
            {
                "key":         "import",            # unique within the plugin
                "label":       "Import PAN config",
                "description": "Optional help text.",
                "confirm":     "Optional. Shown as a confirmation prompt.",
                "destructive": False,               # renders the button in red
                "params": [
                    {"name": "config", "label": "Config file", "type": "file"},
                    {"name": "tenant", "label": "Target tenant", "type": "tenant"},
                ],
                "run": import_pan_config,
            },
        ],
    }

The run callable is `run(params: dict, ctx: PluginContext) -> dict`. `params`
holds the validated values keyed by parameter name; a `file` parameter arrives
as a path to a temporary file that is deleted once the call returns. The return
value is JSON — `message` and `table` are rendered specially (see
`normalise_result`), anything else is shown as key/value detail.

An action that produces a document rather than a screenful returns it under
`file`, and the page shows a download button instead of trying to render it:

    return {
        "message": "Exported 1,284 resources",
        "file": {"filename": "acme-ZIA.json", "path": "/tmp/…/export.json"},
    }

`path` is handed over, not borrowed — zs-config moves the file into a spool it
owns and deletes it when the job ages out, so the plugin must not touch it
again. Small payloads can skip the temp file and pass `content` (str or bytes)
instead. See `take_artifact`.

A `select` whose options are not known until the user has filled in the rest of
the form gives `options` a callable and names what it reads:

    {"name": "snapshot", "type": "select", "options": load_snapshots,
     "depends_on": ["tenant", "product"]}

The callable is `options(params: dict) -> list`, taking the declared
dependencies as they stand and returning the same shape a static `options`
would. The page refetches whenever a dependency changes, and the router
re-resolves the list when the action runs and refuses a value that is not in
it — which is what stops a caller naming a row from a tenant they cannot reach.

Two rules the rest of the app depends on:

*Nothing here is trusted for authorisation.* A `tenant` parameter resolves to a
tenant id, and the router entitlement-checks it against the calling account
before the action ever runs. A plugin naming a tenant it was handed cannot
reach one the user could not reach themselves.

*A malformed spec disables the plugin, it does not crash the page.* `describe`
returns None and logs rather than raising, so one bad plugin costs its own nav
item and nothing else.
"""

import logging
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

#: Parameter types the UI knows how to render. A spec naming anything else is
#: rejected outright rather than guessed at — a silently mistyped field is how
#: a plugin ends up receiving a string it thought was a number.
PARAM_TYPES = (
    "text",
    "textarea",
    "password",
    "number",
    "boolean",
    "select",
    "tenant",
    "file",
)


class PluginWebError(Exception):
    """A plugin's spec or a caller's parameters are not usable.

    `status` is the HTTP code the router should answer with: 400 for input the
    caller got wrong, 500 for a spec the plugin got wrong.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class PluginContext:
    """What a running action is allowed to know about its caller.

    Deliberately narrow: the account's identity for audit and ownership, a way
    to report progress, and a way to notice it has been cancelled. No session,
    no request, no token — a plugin that wants the database opens its own.
    """

    def __init__(self, *, user_id: int, username: str, role: str, job_id: str,
                 emit=None, cancelled=None):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.job_id = job_id
        self._emit = emit
        self._cancelled = cancelled

    def progress(self, message: str) -> None:
        """Push a line to the job's event stream. Safe to call as often as you like."""
        if self._emit:
            self._emit(str(message))

    def is_cancelled(self) -> bool:
        """True once the user has asked to stop. Long actions should poll this."""
        return bool(self._cancelled and self._cancelled())


# ---------------------------------------------------------------------------
# Reading a plugin's spec
# ---------------------------------------------------------------------------


def _normalise_options(options: Any) -> List[dict]:
    """`[{"value", "label"}]` from either shape a plugin may offer.

    Accepts both `["a", "b"]` and `[{"value": "a", "label": "A"}]` so a plugin
    with nothing to say about labels does not have to repeat itself.
    """
    if not isinstance(options, (list, tuple)):
        raise PluginWebError("options must be a list", 500)
    out = []
    for o in options:
        if isinstance(o, dict):
            if "value" not in o:
                raise PluginWebError("an option is missing 'value'", 500)
            out.append({"value": str(o["value"]), "label": str(o.get("label", o["value"]))})
        else:
            out.append({"value": str(o), "label": str(o)})
    return out


def _describe_param(raw: Any, action_key: str) -> dict:
    if not isinstance(raw, dict):
        raise PluginWebError(f"action '{action_key}': each param must be a dict", 500)

    name = str(raw.get("name") or "").strip()
    if not name:
        raise PluginWebError(f"action '{action_key}': a param is missing 'name'", 500)

    ptype = str(raw.get("type") or "text").strip()
    if ptype not in PARAM_TYPES:
        raise PluginWebError(
            f"action '{action_key}', param '{name}': unknown type {ptype!r}", 500
        )

    out = {
        "name": name,
        "label": str(raw.get("label") or name),
        "type": ptype,
        "required": bool(raw.get("required", True)),
        "help": raw.get("help") or None,
        "placeholder": raw.get("placeholder") or None,
    }

    if ptype == "select":
        options = raw.get("options") or []
        depends = raw.get("depends_on") or []

        if callable(options):
            # The list does not exist yet — it is whatever the plugin computes
            # from the values the user has filled in so far. Described as empty
            # and fetched per request; see `resolve_options`.
            if not isinstance(depends, (list, tuple)):
                raise PluginWebError(
                    f"action '{action_key}', param '{name}': 'depends_on' must be a list", 500
                )
            out["dynamic"] = True
            out["depends_on"] = [str(d) for d in depends]
            out["options"] = []
        else:
            if not isinstance(options, (list, tuple)) or not options:
                raise PluginWebError(
                    f"action '{action_key}', param '{name}': select needs a non-empty "
                    "'options' list or a callable", 500
                )
            out["dynamic"] = False
            out["depends_on"] = []
            out["options"] = _normalise_options(options)

    # A file has nowhere sensible to put a default, and a password default
    # would be a credential sitting in a GET response.
    if ptype not in ("file", "password") and raw.get("default") is not None:
        out["default"] = raw["default"]

    return out


def _describe_action(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise PluginWebError("each action must be a dict", 500)

    key = str(raw.get("key") or "").strip()
    if not key:
        raise PluginWebError("an action is missing 'key'", 500)
    if not callable(raw.get("run")):
        raise PluginWebError(f"action '{key}': 'run' must be callable", 500)

    params = raw.get("params") or []
    if not isinstance(params, (list, tuple)):
        raise PluginWebError(f"action '{key}': 'params' must be a list", 500)

    described = [_describe_param(p, key) for p in params]
    names = [p["name"] for p in described]
    if len(names) != len(set(names)):
        raise PluginWebError(f"action '{key}': duplicate param names", 500)

    # A dependency naming a parameter that does not exist would never fire, and
    # the symptom is a dropdown that stays empty forever with nothing to read.
    for p in described:
        for dep in p.get("depends_on") or []:
            if dep not in names:
                raise PluginWebError(
                    f"action '{key}', param '{p['name']}': depends_on names "
                    f"'{dep}', which is not a parameter of this action", 500
                )
            if dep == p["name"]:
                raise PluginWebError(
                    f"action '{key}', param '{p['name']}': depends on itself", 500
                )

    return {
        "key": key,
        "label": str(raw.get("label") or key),
        "description": raw.get("description") or None,
        "confirm": raw.get("confirm") or None,
        "destructive": bool(raw.get("destructive", False)),
        "params": described,
    }


def describe(plugin: dict) -> Optional[dict]:
    """The JSON-safe description of one plugin's web interface, or None.

    None means the plugin has no web interface or its spec is unusable — the
    caller treats both the same way, because in both cases there is nothing to
    render. A broken spec is logged with the package name so it is findable.
    """
    spec = (plugin or {}).get("web")
    if not isinstance(spec, dict):
        return None

    raw_actions = spec.get("actions") or []
    if not isinstance(raw_actions, (list, tuple)):
        log.warning("plugin %s: 'web.actions' must be a list", plugin.get("package"))
        return None

    try:
        actions = [_describe_action(a) for a in raw_actions]
    except PluginWebError as exc:
        log.warning("plugin %s: unusable web spec — %s", plugin.get("package"), exc)
        return None

    keys = [a["key"] for a in actions]
    if len(keys) != len(set(keys)):
        log.warning("plugin %s: duplicate action keys", plugin.get("package"))
        return None
    if not actions:
        return None

    return {
        "name": plugin.get("name"),
        "package": plugin.get("package"),
        "version": plugin.get("version"),
        "description": spec.get("description") or None,
        "actions": actions,
    }


def find_action(plugin: dict, key: str) -> Optional[dict]:
    """The raw action dict — including the `run` callable — for one key."""
    spec = (plugin or {}).get("web")
    if not isinstance(spec, dict):
        return None
    for raw in spec.get("actions") or []:
        if isinstance(raw, dict) and str(raw.get("key") or "") == key:
            return raw
    return None


# ---------------------------------------------------------------------------
# Validating what the caller sent
# ---------------------------------------------------------------------------


def _coerce_one(spec: dict, value: Any) -> Any:
    name, ptype = spec["name"], spec["type"]

    if ptype == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    if ptype == "number":
        try:
            text = str(value).strip()
            return int(text) if text.lstrip("-").isdigit() else float(text)
        except (TypeError, ValueError):
            raise PluginWebError(f"'{spec['label']}' must be a number")

    if ptype == "tenant":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise PluginWebError(f"'{spec['label']}' must be a tenant id")

    if ptype == "select":
        text = str(value)
        # A dynamic select has no list to check against here — its options do
        # not exist until the plugin is asked for them, which the router does
        # separately once the tenant among the params has been authorised.
        if spec.get("dynamic"):
            return text
        allowed = {o["value"] for o in spec.get("options", [])}
        if text not in allowed:
            raise PluginWebError(f"'{spec['label']}' is not one of the offered options")
        return text

    return str(value)


def coerce_params(
    action: dict, supplied: Dict[str, Any], *, partial: bool = False
) -> Dict[str, Any]:
    """Validate the caller's values against a described action's parameters.

    Only declared parameters survive — anything extra the caller sent is
    dropped rather than passed through, so a plugin's `run` only ever sees the
    keys it asked for.

    `partial` lets a half-filled form through, for resolving a dynamic select
    while the user is still working: the form is by definition incomplete at
    that point, and refusing it would mean the dropdown could never populate.
    Never use it for a run.
    """
    out: Dict[str, Any] = {}
    for spec in action.get("params", []):
        name = spec["name"]
        raw = supplied.get(name)
        missing = raw is None or (isinstance(raw, str) and not raw.strip())

        if missing:
            if "default" in spec:
                out[name] = spec["default"]
                continue
            if spec["required"] and not partial:
                raise PluginWebError(f"'{spec['label']}' is required")
            # An unsupplied optional boolean is false, not absent — an
            # unchecked box sends nothing at all.
            out[name] = False if spec["type"] == "boolean" else None
            continue

        out[name] = _coerce_one(spec, raw)
    return out


def tenant_params(action: dict) -> List[str]:
    """Names of the action's tenant parameters, for the router to authorise."""
    return [p["name"] for p in action.get("params", []) if p["type"] == "tenant"]


def file_params(action: dict) -> List[str]:
    """Names of the action's file parameters, for the router to receive."""
    return [p["name"] for p in action.get("params", []) if p["type"] == "file"]


def dynamic_params(action: dict) -> List[str]:
    """Names of the action's dynamically-populated selects, for the router to check."""
    return [p["name"] for p in action.get("params", []) if p.get("dynamic")]


def depends_on(action: dict, param_name: str) -> List[str]:
    """What one dynamic parameter reads. Empty for anything else."""
    for p in action.get("params", []):
        if p["name"] == param_name:
            return list(p.get("depends_on") or [])
    return []


def resolve_options(raw_action: dict, param_name: str, params: Dict[str, Any]) -> List[dict]:
    """Ask the plugin for one dynamic select's current options.

    Called twice for every value that reaches a plugin: once to draw the
    dropdown, and again when the action runs, to check the value came from it.
    The second call is the one that matters — the first is a convenience, and
    nothing stops a caller POSTing a value the dropdown never offered.

    `params` should already be coerced and, for any tenant among them,
    entitlement-checked: a plugin resolving options for a tenant id is trusted
    to have been handed one the caller can reach.
    """
    for raw in raw_action.get("params") or []:
        if not isinstance(raw, dict) or str(raw.get("name") or "") != param_name:
            continue
        loader = raw.get("options")
        if not callable(loader):
            raise PluginWebError(f"'{param_name}' does not load its options dynamically", 400)
        return _normalise_options(loader(dict(params)))
    raise PluginWebError(f"unknown parameter '{param_name}'", 400)


# ---------------------------------------------------------------------------
# Reading back what the action returned
# ---------------------------------------------------------------------------


#: Result key an action puts a downloadable document under. Consumed by
#: `take_artifact` before the rest of the result is rendered, so it never
#: reaches the browser as detail — the value holds a server path.
ARTIFACT_KEY = "file"


def safe_filename(raw: Any, fallback: str = "download") -> str:
    """A filename that is safe to write and safe to name in a header.

    Basename only, and nothing outside a conservative alphabet: the plugin
    chose this string, and on plenty of paths the user chose it for the plugin.
    A name that reduces to nothing falls back rather than producing an empty
    `filename=""` for the browser to guess at.
    """
    name = os.path.basename(str(raw or "")).strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return name[:120] or fallback


def take_artifact(value: Any, spool: str) -> Tuple[Any, Optional[dict]]:
    """Split a downloadable file off an action's result, if it returned one.

    Returns `(rest, artifact)` where `artifact` is
    `{"path", "filename", "content_type", "size"}` and `rest` is the result
    with the `file` key removed — the path is a server filesystem location and
    has no business being rendered as a detail row.

    A `path` is *moved* into `spool`, which the caller owns and eventually
    deletes: the plugin cannot know when the download happens, so it cannot be
    responsible for cleaning up after it. `content` is written out instead,
    which also gets a large payload out of the job result and off the heap.
    """
    if not isinstance(value, dict) or ARTIFACT_KEY not in value:
        return value, None

    spec = value[ARTIFACT_KEY]
    rest = {k: v for k, v in value.items() if k != ARTIFACT_KEY}
    if spec is None:
        return rest, None
    if not isinstance(spec, dict):
        raise PluginWebError(f"'{ARTIFACT_KEY}' must be a dict", 500)

    dest = os.path.join(spool, "artifact")
    source, content = spec.get("path"), spec.get("content")

    if source:
        try:
            shutil.move(str(source), dest)
        except OSError as exc:
            raise PluginWebError(f"could not read the file the action produced: {exc}", 500)
    elif content is not None:
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        with open(dest, "wb") as fh:
            fh.write(data)
    else:
        raise PluginWebError(f"'{ARTIFACT_KEY}' needs either 'path' or 'content'", 500)

    return rest, {
        "path": dest,
        "filename": safe_filename(spec.get("filename")),
        "content_type": str(spec.get("content_type") or "application/octet-stream"),
        "size": os.path.getsize(dest),
    }


def normalise_result(value: Any) -> dict:
    """Shape whatever an action returned into what the page renders.

    `message` is a headline, `table` is `{columns, rows}` rendered as a grid,
    and everything else lands in `details` as key/value pairs. An action that
    returns nothing at all still succeeded — it just has nothing to show.

    `download` is always present and always None here: only the router knows
    whether an artifact survived to be served, so it fills this in. Declaring
    it means the result shape is one thing, described in one place.
    """
    if value is None:
        return {"message": "Done.", "table": None, "details": {}, "download": None}
    if not isinstance(value, dict):
        return {"message": str(value), "table": None, "details": {}, "download": None}

    table = value.get("table")
    if isinstance(table, dict):
        columns = [str(c) for c in (table.get("columns") or [])]
        rows = [list(r) for r in (table.get("rows") or [])]
        table = {"columns": columns, "rows": rows} if columns else None
    else:
        table = None

    details = {
        k: v for k, v in value.items()
        if k not in ("message", "table", ARTIFACT_KEY) and _jsonable(v)
    }
    return {
        "message": str(value.get("message") or "Done."),
        "table": table,
        "details": details,
        "download": None,
    }


def _jsonable(value: Any) -> bool:
    """Whether a value survives the trip to the browser without a custom encoder."""
    return isinstance(value, (str, int, float, bool, list, dict)) or value is None
