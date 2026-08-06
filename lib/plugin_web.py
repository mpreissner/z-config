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
`normalize_result`), anything else is shown as key/value detail.

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

A value every action needs is declared once as page context instead of being
re-entered on each form. Actions name the ones they consume:

    "web": {
        "context": [
            {"name": "session", "label": "Migration", "type": "select",
             "options": list_sessions},
        ],
        "actions": [
            {"key": "analyze", "context": ["session"], "params": […], "run": …},
        ],
    }

The page renders those in a bar above the actions and keeps them while the user
moves around. Nothing else changes: a context parameter is folded back into the
action's own parameters before validation, so it is coerced, entitlement-checked
and re-resolved exactly as a parameter declared inline would be, and `run` sees
one flat `params` dict.

An action that creates the thing the page is about hands it back as context
instead of leaving the user to find it in a dropdown:

    return {"message": "Imported 412 rules", "context": {"session": "7"}}

The page adopts those values as its own. Only declared context names are
accepted; anything else is dropped with a warning.

A plugin whose actions are steps of one job can say so, and the page draws them
in order with the state the plugin reports:

    "workflow": {
        "steps": [{"key": "import", "label": "1 · Import", "actions": ["import_xml"]}],
        "state": session_state,   # state(context: dict) -> {step_key: {...}}
    }

`state` is advisory — it decides what the step strip looks like, never what a
caller is allowed to run. Every action is authorized on its own terms whichever
step it is drawn under.

A step is a screen, not a tab: every action a step lists is drawn on it, one
under the other. An action left out of every step is still runnable — it just
has no place of its own, which is what a gate answer wants.

*A stage that cannot go on without a decision asks for it in place.* Rather
than reporting that the user should go and find another action, the result
carries the question, and the page draws it as a form under the result that
explains it:

    return {
        "message": "Paused — 3 zones could not be classified",
        "prompt": {
            "action": "zones",              # runs when the form is submitted
            "title": "Classify these zones",
            "params": [
                {"name": "dmz", "label": "dmz", "type": "select",
                 "options": ["internal", "external"]},
            ],
        },
    }

The fields are built while the action runs — three uncertain zones make three
fields — so unlike a spec's parameters they are *data*: their options are a
plain list rather than a loader, because the run that could have answered a
loader is over. zs-config keeps its own copy of the question and checks the
answer against that, then invokes the named action with those values and the
page's context folded in. The action's own declared parameters are not part of
that call, so an action written to be prompted for reads what the prompt asked.

Answering re-runs and replaces the result in place, so a pipeline that stops
three times is still one screen. `notes[].action` is the same mechanism with
nothing to fill in.

A `selection` parameter is a checkbox grid rather than a field: the plugin
loads the rows, the user ticks some, and `run` receives the list of values.

    {"name": "units", "type": "selection", "options": load_units,
     "depends_on": ["session"], "columns": ["Rule", "Target"],
     "filters": [{"name": "target", "label": "Target", "options": [...]}]}

The loader returns a row per line — `{"value", "cells", "selected", "group",
"disabled", "note"}` — and is re-resolved on run like any other dynamic
parameter, so a value the plugin did not offer is refused.

Two rules the rest of the app depends on:

*Nothing here is trusted for authorization.* A `tenant` parameter resolves to a
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
    "selection",
    "tenant",
    "file",
)

#: How a result section, a stat or a note asks to be coloured. Anything else is
#: read as `neutral` — a plugin inventing a tone gets a plain row, not an error.
TONES = ("neutral", "good", "warn", "bad")


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


def _normalize_options(options: Any) -> List[dict]:
    """`[{"value", "label"}]` from any shape a plugin may offer.

    Accepts both `["a", "b"]` and `[{"value": "a", "label": "A"}]` so a plugin
    with nothing to say about labels does not have to repeat itself.

    A `selection` grid's rows come through here too — an option carrying `cells`
    keeps its row fields alongside `value` and `label`, so everything that reads
    an offered list by value, the router's check included, works on a grid row
    without knowing it is one.
    """
    if not isinstance(options, (list, tuple)):
        raise PluginWebError("options must be a list", 500)
    out = []
    for o in options:
        if not isinstance(o, dict):
            out.append({"value": str(o), "label": str(o)})
            continue
        if "value" not in o:
            raise PluginWebError("an option is missing 'value'", 500)
        if "cells" not in o:
            out.append({"value": str(o["value"]), "label": str(o.get("label", o["value"]))})
            continue

        cells = [("" if c is None else str(c)) for c in (o.get("cells") or [])]
        out.append({
            "value": str(o["value"]),
            "label": str(o.get("label") or (cells[0] if cells else o["value"])),
            "cells": cells,
            "selected": bool(o.get("selected", False)),
            "disabled": bool(o.get("disabled", False)),
            "group": str(o["group"]) if o.get("group") else None,
            "note": str(o["note"]) if o.get("note") else None,
        })
    return out


def _describe_filter(raw: Any, name: str) -> dict:
    """One column filter offered above a selection grid."""
    if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
        raise PluginWebError(f"param '{name}': each filter needs a 'name'", 500)
    key = str(raw["name"]).strip()
    return {
        "name": key,
        "label": str(raw.get("label") or key),
        "options": _normalize_options(raw.get("options") or []),
    }


def _describe_param(raw: Any, action_key: str, *, literal: bool = False) -> dict:
    """One parameter, described for the page.

    `literal` describes a parameter that is *data*, not spec — the fields of a
    follow-up prompt, which the plugin builds while it runs. Those cannot load
    anything later: the run that produced them is over, and there is no form for
    a loader to read. So their options are a plain list, given here, and are the
    list the value is checked against when the prompt is submitted.
    """
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

    if literal and (raw.get("depends_on") or []):
        raise PluginWebError(
            f"action '{action_key}', param '{name}': a prompt's fields cannot "
            "depend on anything — there is nothing left to read", 500
        )

    if ptype == "select":
        options = raw.get("options") or []
        depends = raw.get("depends_on") or []

        if callable(options) and literal:
            raise PluginWebError(
                f"action '{action_key}', param '{name}': a prompt's options must be "
                "a list, not a callable", 500
            )

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
            out["options"] = _normalize_options(options)

    if ptype == "selection":
        # A grid is always loaded, never declared: its rows are the plugin's
        # current state — which rules exist, which are already ticked — and a
        # literal list in a spec could only ever be stale.
        loader = raw.get("options")
        if literal:
            # A prompt's grid is already loaded — the rows are the ones the run
            # that emitted it found. There is nothing to call and nothing to
            # call it with.
            if not isinstance(loader, (list, tuple)):
                raise PluginWebError(
                    f"action '{action_key}', param '{name}': a prompt's selection "
                    "needs its rows as a list", 500
                )
        elif not callable(loader):
            raise PluginWebError(
                f"action '{action_key}', param '{name}': selection needs a callable "
                "'options' that loads its rows", 500
            )
        depends = raw.get("depends_on") or []
        if not isinstance(depends, (list, tuple)):
            raise PluginWebError(
                f"action '{action_key}', param '{name}': 'depends_on' must be a list", 500
            )
        columns = raw.get("columns") or []
        if not isinstance(columns, (list, tuple)) or not columns:
            raise PluginWebError(
                f"action '{action_key}', param '{name}': selection needs 'columns'", 500
            )
        filters = raw.get("filters") or []
        if not isinstance(filters, (list, tuple)):
            raise PluginWebError(
                f"action '{action_key}', param '{name}': 'filters' must be a list", 500
            )
        out["dynamic"] = not literal
        out["depends_on"] = [str(d) for d in depends]
        out["options"] = _normalize_options(loader) if literal else []
        out["columns"] = [str(c) for c in columns]
        out["filters"] = [_describe_filter(f, name) for f in filters]

        # A filter narrows on one of the grid's columns. Naming a column that is
        # not there gives a dropdown that hides every row whatever is picked.
        headings = {c.lower() for c in out["columns"]}
        for f in out["filters"]:
            if f["name"].lower() not in headings:
                raise PluginWebError(
                    f"action '{action_key}', param '{name}': filter '{f['name']}' "
                    "does not name one of the declared columns", 500
                )

    # A file has nowhere sensible to put a default, and a password default
    # would be a credential sitting in a GET response.
    if ptype not in ("file", "password") and raw.get("default") is not None:
        out["default"] = raw["default"]

    return out


def _describe_action(raw: Any, context_names: Tuple[str, ...] = ()) -> dict:
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

    wanted = raw.get("context") or []
    if not isinstance(wanted, (list, tuple)):
        raise PluginWebError(f"action '{key}': 'context' must be a list", 500)
    wanted = [str(c) for c in wanted]
    for name in wanted:
        if name not in context_names:
            raise PluginWebError(
                f"action '{key}': context names '{name}', which the plugin does "
                "not declare under 'web.context'", 500
            )

    described = [_describe_param(p, key) for p in params]
    names = [p["name"] for p in described]
    if len(names) != len(set(names)):
        raise PluginWebError(f"action '{key}': duplicate param names", 500)

    # A parameter shadowing a context value would be filled in twice from two
    # different places, and which one reached `run` would come down to ordering.
    clash = set(names) & set(wanted)
    if clash:
        raise PluginWebError(
            f"action '{key}': {sorted(clash)[0]!r} is both a context value and a "
            "parameter of this action", 500
        )

    # A dependency naming a parameter that does not exist would never fire, and
    # the symptom is a dropdown that stays empty forever with nothing to read.
    visible = set(names) | set(wanted)
    for p in described:
        for dep in p.get("depends_on") or []:
            if dep not in visible:
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
        "context": wanted,
        "params": described,
    }


def _describe_context(raw: Any) -> List[dict]:
    """The page-level values, described as ordinary parameters.

    Same shape and same validation as an action's own — the only difference is
    where they are drawn and that they outlive the form.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise PluginWebError("'web.context' must be a list", 500)

    described = [_describe_param(p, "context") for p in raw]
    names = [p["name"] for p in described]
    if len(names) != len(set(names)):
        raise PluginWebError("duplicate context param names", 500)
    for p in described:
        if p["type"] in ("file", "selection"):
            raise PluginWebError(
                f"context '{p['name']}': a {p['type']} cannot be page context", 500
            )
        for dep in p.get("depends_on") or []:
            if dep not in names or dep == p["name"]:
                raise PluginWebError(
                    f"context '{p['name']}': depends_on names '{dep}', which is not "
                    "another context value", 500
                )
    return described


def _describe_workflow(raw: Any, action_keys: Tuple[str, ...]) -> Optional[dict]:
    """The ordered steps the actions belong to, or None if the plugin is flat.

    `stateful` tells the page whether asking for per-step state is worth a
    request. The `state` callable itself stays on the server.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PluginWebError("'web.workflow' must be a dict", 500)

    steps = raw.get("steps") or []
    if not isinstance(steps, (list, tuple)) or not steps:
        raise PluginWebError("'web.workflow' needs a non-empty 'steps' list", 500)

    out = []
    for step in steps:
        if not isinstance(step, dict):
            raise PluginWebError("each workflow step must be a dict", 500)
        key = str(step.get("key") or "").strip()
        if not key:
            raise PluginWebError("a workflow step is missing 'key'", 500)
        keys = step.get("actions") or []
        if not isinstance(keys, (list, tuple)) or not keys:
            raise PluginWebError(f"workflow step '{key}': needs an 'actions' list", 500)
        for a in keys:
            if str(a) not in action_keys:
                raise PluginWebError(
                    f"workflow step '{key}': names action '{a}', which does not exist", 500
                )
        out.append({
            "key": key,
            "label": str(step.get("label") or key),
            "description": step.get("description") or None,
            "actions": [str(a) for a in keys],
        })

    step_keys = [s["key"] for s in out]
    if len(step_keys) != len(set(step_keys)):
        raise PluginWebError("duplicate workflow step keys", 500)

    return {"steps": out, "stateful": callable(raw.get("state"))}


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
        context = _describe_context(spec.get("context"))
        names = tuple(c["name"] for c in context)
        actions = [_describe_action(a, names) for a in raw_actions]
    except PluginWebError as exc:
        log.warning("plugin %s: unusable web spec — %s", plugin.get("package"), exc)
        return None

    keys = [a["key"] for a in actions]
    if len(keys) != len(set(keys)):
        log.warning("plugin %s: duplicate action keys", plugin.get("package"))
        return None
    if not actions:
        return None

    # A broken workflow costs the step strip, not the plugin: the actions are
    # all still individually runnable, and a flat tab strip is what the page
    # falls back to anyway.
    try:
        workflow = _describe_workflow(spec.get("workflow"), tuple(keys))
    except PluginWebError as exc:
        log.warning("plugin %s: ignoring unusable workflow — %s", plugin.get("package"), exc)
        workflow = None

    return {
        "name": plugin.get("name"),
        "package": plugin.get("package"),
        "version": plugin.get("version"),
        "description": spec.get("description") or None,
        "context": context,
        "workflow": workflow,
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


def find_workflow_state(plugin: dict) -> Optional[Any]:
    """The plugin's per-step state callable, if it declared one."""
    spec = (plugin or {}).get("web")
    if not isinstance(spec, dict):
        return None
    workflow = spec.get("workflow")
    if not isinstance(workflow, dict):
        return None
    state = workflow.get("state")
    return state if callable(state) else None


def bind_context(described: dict, action: dict) -> dict:
    """One action with the context values it named folded in as parameters.

    Everything downstream — coercion, the tenant check, re-resolving a dynamic
    option list — reads an action's `params`, and a context value has to be
    subject to all three. Folding it in here means none of that code learns
    there is such a thing as context, and no path can validate an inline
    parameter one way and a page-level one another.
    """
    wanted = action.get("context") or []
    if not wanted:
        return action
    by_name = {c["name"]: c for c in described.get("context") or []}
    extra = [by_name[n] for n in wanted if n in by_name]
    return {**action, "params": extra + list(action.get("params") or [])}


def bind_raw_context(plugin: dict, raw_action: dict, action: dict) -> dict:
    """The same folding against the raw spec, so option loaders stay reachable.

    `resolve_options` looks a parameter up by name in the raw action it was
    handed; a context parameter lives in the raw spec's `context` list instead,
    and would otherwise be unknown to it.
    """
    wanted = action.get("context") or []
    if not wanted:
        return raw_action
    spec = (plugin or {}).get("web") or {}
    raw_context = [
        c for c in (spec.get("context") or [])
        if isinstance(c, dict) and str(c.get("name") or "") in wanted
    ]
    return {**raw_action, "params": raw_context + list(raw_action.get("params") or [])}


def context_action(described: dict) -> dict:
    """A synthetic action holding just the page's context values.

    Lets the state endpoint validate and authorize a set of context values with
    the same code an action's parameters go through, without inventing a second
    path that could drift from it.
    """
    return {
        "key": "__context__",
        "label": "context",
        "params": list(described.get("context") or []),
    }


def raw_context_action(plugin: dict) -> dict:
    """The raw counterpart of `context_action`, for resolving option loaders."""
    spec = (plugin or {}).get("web") or {}
    raw = [c for c in (spec.get("context") or []) if isinstance(c, dict)]
    return {"key": "__context__", "params": raw}


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
        # separately once the tenant among the params has been authorized.
        if spec.get("dynamic"):
            return text
        allowed = {o["value"] for o in spec.get("options", [])}
        if text not in allowed:
            raise PluginWebError(f"'{spec['label']}' is not one of the offered options")
        return text

    if ptype == "selection":
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
            raise PluginWebError(f"'{spec['label']}' must be a list of values")
        # Order is the user's, duplicates are not meaningful, and the values a
        # grid offered are checked by the router once its dependencies have been
        # authorized — same as any other dynamic parameter.
        seen, out = set(), []
        for v in value:
            text = str(v)
            if text not in seen:
                seen.add(text)
                out.append(text)
        if not spec.get("dynamic"):
            # A prompt's grid carries its rows with it, so the check the router
            # does by re-loading a dynamic grid happens here instead.
            allowed = {o["value"] for o in spec.get("options", [])}
            for text in out:
                if text not in allowed:
                    raise PluginWebError(
                        f"'{spec['label']}' includes a row that was not offered"
                    )
        return out

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
        missing = (
            raw is None
            or (isinstance(raw, str) and not raw.strip())
            # Nothing ticked is a grid with no answer in it, not a grid the
            # caller left alone — a required selection has to say so.
            or (spec["type"] == "selection" and isinstance(raw, (list, tuple)) and not raw)
        )

        if missing:
            if "default" in spec:
                out[name] = spec["default"]
                continue
            if spec["required"] and not partial:
                raise PluginWebError(f"'{spec['label']}' is required")
            # An unsupplied optional boolean is false, not absent — an
            # unchecked box sends nothing at all.
            if spec["type"] == "boolean":
                out[name] = False
            elif spec["type"] == "selection":
                out[name] = []
            else:
                out[name] = None
            continue

        out[name] = _coerce_one(spec, raw)
    return out


def tenant_params(action: dict) -> List[str]:
    """Names of the action's tenant parameters, for the router to authorize."""
    return [p["name"] for p in action.get("params", []) if p["type"] == "tenant"]


def file_params(action: dict) -> List[str]:
    """Names of the action's file parameters, for the router to receive."""
    return [p["name"] for p in action.get("params", []) if p["type"] == "file"]


def dynamic_params(action: dict) -> List[str]:
    """Names of the action's dynamically-populated selects, for the router to check."""
    return [p["name"] for p in action.get("params", []) if p.get("dynamic")]


def submitted_values(action: dict, param_name: str, value: Any) -> List[str]:
    """The values of one parameter to check against what the plugin offered.

    A select contributes the one thing it holds; a selection grid contributes
    every row that was ticked. Returning a list either way keeps the router's
    check one loop rather than a type switch.
    """
    if value is None:
        return []
    for p in action.get("params", []):
        if p["name"] == param_name and p["type"] == "selection":
            return [str(v) for v in value]
    return [str(value)]


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
        return _normalize_options(loader(dict(params)))
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


def _tone(value: Any) -> str:
    tone = str(value or "neutral")
    return tone if tone in TONES else "neutral"


def _cells(row: Any) -> List[str]:
    if isinstance(row, (list, tuple)):
        return [("" if c is None else str(c)) for c in row]
    return ["" if row is None else str(row)]


def _describe_section(raw: Any) -> Optional[dict]:
    """One block of a rich result, or None if it is not one this page can draw.

    Skipped rather than raised on: the action has already run and its work is
    done, and losing the whole result over a mislabelled section would throw
    away the part that was fine.
    """
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    title = str(raw["title"]) if raw.get("title") else None
    subtitle = str(raw["subtitle"]) if raw.get("subtitle") else None
    base = {"kind": kind, "title": title, "subtitle": subtitle}

    if kind == "stats":
        items = [
            {
                "label": str(i.get("label") or ""),
                "value": i.get("value") if _jsonable(i.get("value")) else str(i.get("value")),
                "tone": _tone(i.get("tone")),
                "detail": str(i["detail"]) if i.get("detail") else None,
            }
            for i in (raw.get("items") or []) if isinstance(i, dict)
        ]
        return {**base, "items": items} if items else None

    if kind == "table":
        columns = [str(c) for c in (raw.get("columns") or [])]
        if not columns:
            return None
        return {
            **base,
            "columns": columns,
            "rows": [_cells(r) for r in (raw.get("rows") or [])],
            "tone_column": raw.get("tone_column") if isinstance(raw.get("tone_column"), int) else None,
        }

    if kind == "groups":
        groups = []
        for g in raw.get("groups") or []:
            if not isinstance(g, dict):
                continue
            groups.append({
                "key": str(g.get("key") or g.get("title") or len(groups)),
                "title": str(g.get("title") or ""),
                "subtitle": str(g["subtitle"]) if g.get("subtitle") else None,
                "badge": str(g["badge"]) if g.get("badge") else None,
                "tone": _tone(g.get("tone")),
                "columns": [str(c) for c in (g.get("columns") or [])],
                "rows": [_cells(r) for r in (g.get("rows") or [])],
            })
        return {**base, "groups": groups} if groups else None

    if kind == "notes":
        notes = []
        for n in raw.get("notes") or []:
            if not isinstance(n, dict) or not n.get("text"):
                continue
            # A note may point at the action that resolves it. It carries no
            # authority — the page prefills that form, and running it is
            # checked exactly as it would be if the user had navigated there.
            action = n.get("action")
            notes.append({
                "tone": _tone(n.get("tone")),
                "text": str(n["text"]),
                "action": {
                    "key": str(action.get("key") or ""),
                    "label": str(action.get("label") or "Resolve"),
                } if isinstance(action, dict) and action.get("key") else None,
            })
        return {**base, "notes": notes} if notes else None

    return None


def _result_context(raw: Any, context_names: Tuple[str, ...]) -> Dict[str, str]:
    """The page context an action asked to change, keeping only declared names.

    An action that creates the thing the page is about — the import that makes
    the migration the rest of the workflow runs against — says so in its result
    rather than leaving the user to find it in a dropdown that has not heard of
    it yet. Values are strings because that is what a context value is: it comes
    back off the query string on the next reload either way.
    """
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        name = str(key)
        if name not in context_names:
            log.warning("plugin result sets context '%s', which it does not declare", name)
            continue
        out[name] = "" if value is None else str(value)
    return out


def _describe_prompt(raw: Any, action_keys: Tuple[str, ...]) -> Optional[dict]:
    """The follow-up question an action stopped on, or None if it is unusable.

    This is what keeps a workflow on one screen: a stage that cannot go on
    without a decision returns the decision as a form, rendered under the result
    that explains it, and answering it runs the named action. The fields are
    built while the action runs — three uncertain zones make three fields — so
    they are `literal` parameters and are checked against the list they carry.

    The action named here is invoked by key, so it must exist; it does not have
    to appear anywhere in the workflow, and a gate answer generally should not.

    Dropped rather than raised on, like a section: the run itself succeeded, and
    the message explaining what it is waiting for is worth more than a 500.
    """
    if not isinstance(raw, dict):
        return None

    key = str(raw.get("action") or "").strip()
    if key not in action_keys:
        log.warning("plugin result prompts for action '%s', which does not exist", key)
        return None

    params = raw.get("params") or []
    if not isinstance(params, (list, tuple)):
        log.warning("plugin prompt for '%s': 'params' must be a list", key)
        return None

    try:
        described = [_describe_param(p, f"prompt:{key}", literal=True) for p in params]
    except PluginWebError as exc:
        log.warning("plugin prompt for '%s' is unusable — %s", key, exc)
        return None

    names = [p["name"] for p in described]
    if len(names) != len(set(names)):
        log.warning("plugin prompt for '%s': duplicate param names", key)
        return None

    return {
        "action": key,
        "title": str(raw["title"]) if raw.get("title") else None,
        "help": str(raw["help"]) if raw.get("help") else None,
        "submit": str(raw.get("submit") or "Continue"),
        "params": described,
    }


def prompt_action(described: dict, action: dict, prompt: dict) -> dict:
    """The action a prompt submits to, described as the form the user answered.

    The target action's own parameters are deliberately dropped: what the user
    filled in is the prompt, which the plugin composed for this one pause, and
    the values are checked against that. What stays is the page context the
    action named — it is validated, entitlement-checked and re-resolved on the
    same path as any other run, because the browser is the one supplying it.
    """
    wanted = action.get("context") or []
    by_name = {c["name"]: c for c in described.get("context") or []}
    context = [by_name[n] for n in wanted if n in by_name]

    # A field sharing a context value's name would be filled in from two places
    # and coerced against whichever spec came first. Context wins: it is the
    # thing the rest of the workflow is keyed on, and a prompt asking for it
    # again is the plugin repeating itself.
    taken = {c["name"] for c in context}
    fields = []
    for p in prompt.get("params") or []:
        if p["name"] in taken:
            log.warning(
                "plugin prompt for '%s': field '%s' shadows page context — ignored",
                action.get("key"), p["name"],
            )
            continue
        fields.append(p)
    return {**action, "params": context + fields}


#: Result keys with a rendering of their own, kept out of the key/value detail.
_RESERVED_RESULT_KEYS = ("message", "table", "sections", "context", "prompt", ARTIFACT_KEY)


def normalize_result(
    value: Any,
    *,
    context_names: Tuple[str, ...] = (),
    action_keys: Tuple[str, ...] = (),
) -> dict:
    """Shape whatever an action returned into what the page renders.

    `message` is a headline, `table` is `{columns, rows}` rendered as a grid,
    `sections` is an ordered list of richer blocks — stat tiles, grouped rows,
    callouts — and everything else lands in `details` as key/value pairs. An
    action that returns nothing at all still succeeded, it just has nothing to
    show.

    `context` is what the page should adopt as its own — the migration an import
    just created — and `prompt` is a follow-up form to draw under the result,
    both checked against what the plugin declared.

    `download` is always present and always None here: only the router knows
    whether an artifact survived to be served, so it fills this in. Declaring
    it means the result shape is one thing, described in one place.
    """
    empty = {
        "message": "Done.",
        "table": None,
        "sections": [],
        "details": {},
        "download": None,
        "context": {},
        "prompt": None,
    }
    if value is None:
        return empty
    if not isinstance(value, dict):
        return {**empty, "message": str(value)}

    table = value.get("table")
    if isinstance(table, dict):
        columns = [str(c) for c in (table.get("columns") or [])]
        rows = [list(r) for r in (table.get("rows") or [])]
        table = {"columns": columns, "rows": rows} if columns else None
    else:
        table = None

    raw_sections = value.get("sections")
    sections = []
    if isinstance(raw_sections, (list, tuple)):
        sections = [s for s in (_describe_section(s) for s in raw_sections) if s]

    details = {
        k: v for k, v in value.items()
        if k not in _RESERVED_RESULT_KEYS and _jsonable(v)
    }
    return {
        "message": str(value.get("message") or "Done."),
        "table": table,
        "sections": sections,
        "details": details,
        "download": None,
        "context": _result_context(value.get("context"), tuple(context_names)),
        "prompt": (
            _describe_prompt(value["prompt"], tuple(action_keys))
            if value.get("prompt") is not None
            else None
        ),
    }


#: How a workflow step reports itself. Anything else is read as `pending`.
STEP_STATUSES = ("pending", "current", "complete", "blocked")


def normalize_state(value: Any, workflow: Optional[dict]) -> dict:
    """One entry per declared step, whatever the plugin actually returned.

    Filled in for steps the plugin said nothing about, so the page never has to
    reason about a missing key, and keyed only by steps that exist — a state for
    a step that was never declared has nothing to attach itself to.
    """
    steps = (workflow or {}).get("steps") or []
    reported = value if isinstance(value, dict) else {}
    out = {}
    for step in steps:
        raw = reported.get(step["key"])
        raw = raw if isinstance(raw, dict) else {}
        status = str(raw.get("status") or "pending")
        out[step["key"]] = {
            "status": status if status in STEP_STATUSES else "pending",
            "detail": str(raw["detail"]) if raw.get("detail") else None,
        }
    return out


def _jsonable(value: Any) -> bool:
    """Whether a value survives the trip to the browser without a custom encoder."""
    return isinstance(value, (str, int, float, bool, list, dict)) or value is None
