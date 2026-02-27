"""ZDX (Zscaler Digital Experience) TUI menu.

Help desk focused: device lookup, health metrics, events, app performance,
and deep trace management. All views use a configurable time window.
"""

from typing import Optional

import questionary
from rich.console import Console
from rich.table import Table

from cli.banner import render_banner
from cli.menus import get_zdx_client

console = Console()


# ------------------------------------------------------------------
# Time range picker
# ------------------------------------------------------------------

def _pick_time_range() -> int:
    """Returns hours: 2, 4, 8, or 24."""
    result = questionary.select(
        "Time window:",
        choices=[
            questionary.Choice("Last 2 hours", value=2),
            questionary.Choice("Last 4 hours", value=4),
            questionary.Choice("Last 8 hours", value=8),
            questionary.Choice("Last 24 hours", value=24),
        ],
    ).ask()
    return result if result is not None else 2


# ------------------------------------------------------------------
# Device picker helper
# ------------------------------------------------------------------

def _pick_device(client, hours: int) -> Optional[dict]:
    """Search for devices and let the user select one. Returns device dict or None."""
    search = questionary.text(
        "Search devices (hostname / email, or blank for all):"
    ).ask()
    if search is None:
        return None

    with console.status("Fetching devices..."):
        try:
            devices = client.list_devices(search=search.strip() or None, hours=hours)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch devices: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return None

    if not devices:
        console.print("[yellow]No devices found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return None

    choices = []
    for d in devices:
        name = d.get("name") or d.get("hostname") or d.get("deviceName") or "Unknown"
        user = d.get("user") or d.get("userName") or d.get("email") or ""
        label = f"{name}  [{user}]" if user else name
        choices.append(questionary.Choice(label, value=d))

    return questionary.select("Select device:", choices=choices).ask()


# ------------------------------------------------------------------
# Main ZDX menu
# ------------------------------------------------------------------

def zdx_menu():
    client, tenant = get_zdx_client()
    if client is None:
        return

    while True:
        render_banner()
        choice = questionary.select(
            "ZDX   Zscaler Digital Experience",
            choices=[
                questionary.Separator("── Device Analytics ──"),
                questionary.Choice("Device Lookup & Health", value="device_health"),
                questionary.Choice("App Performance on Device", value="app_perf"),
                questionary.Separator("── Users ──"),
                questionary.Choice("User Lookup", value="user_lookup"),
                questionary.Separator("── Applications ──"),
                questionary.Choice("Application Scores", value="app_scores"),
                questionary.Separator("── Diagnostics ──"),
                questionary.Choice("Deep Trace", value="deep_trace"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "device_health":
            _device_health_menu(client, tenant)
        elif choice == "app_perf":
            _app_performance_menu(client, tenant)
        elif choice == "user_lookup":
            _user_lookup_menu(client, tenant)
        elif choice == "app_scores":
            _app_scores_menu(client, tenant)
        elif choice == "deep_trace":
            _deep_trace_menu(client, tenant)
        elif choice in ("back", None):
            break


# ------------------------------------------------------------------
# Device Lookup & Health
# ------------------------------------------------------------------

def _device_health_menu(client, tenant):
    from services.zdx_service import ZDXService
    service = ZDXService(client, tenant_id=tenant.id)

    hours = _pick_time_range()
    device = _pick_device(client, hours)
    if not device:
        return

    device_id = str(device.get("id") or device.get("deviceId") or "")
    device_name = device.get("name") or device.get("hostname") or device_id

    with console.status(f"Fetching health data for {device_name}..."):
        try:
            summary = service.get_device_summary(device_id, hours)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch device data: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    health = summary.get("health") or {}
    events = summary.get("events") or []

    lines = []

    # --- Device info panel ---
    from rich.panel import Panel
    from rich.text import Text
    info = Text()
    info.append(f"Device: ", style="bold")
    info.append(f"{device_name}\n")
    for key in ("user", "userName", "email", "os", "platform", "zccVersion", "privateIp"):
        val = device.get(key)
        if val:
            info.append(f"{key}: ", style="dim")
            info.append(f"{val}\n")
    panel = Panel(info, title="Device Info", border_style="cyan")

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view

    all_lines = render_rich_to_lines(panel)

    # --- Health metrics table ---
    if health:
        metrics = health.get("metrics") or []
        if metrics:
            htable = Table(title="Health Metrics", show_lines=False)
            htable.add_column("Metric")
            htable.add_column("Value")
            htable.add_column("Unit", style="dim")
            for m in metrics:
                metric_name = m.get("metric") or m.get("name") or "?"
                val = str(m.get("value") or m.get("avgValue") or "—")
                unit = m.get("unit") or ""
                htable.add_row(metric_name, val, unit)
            all_lines += render_rich_to_lines(htable)
        else:
            # Show raw health as JSON if no metrics list
            import json
            from rich.syntax import Syntax
            syntax = Syntax(json.dumps(health, indent=2, default=str), "json", theme="monokai")
            all_lines += render_rich_to_lines(syntax)
    else:
        all_lines += render_rich_to_lines(
            Panel("[dim]No health metrics available for this time window.[/dim]",
                  border_style="dim")
        )

    # --- Events table ---
    if events:
        etable = Table(title=f"Events ({len(events)} total)", show_lines=False)
        etable.add_column("Timestamp", style="dim", no_wrap=True)
        etable.add_column("Type")
        etable.add_column("Severity")
        etable.add_column("Description")
        for ev in events[:100]:
            ts = str(ev.get("timestamp") or ev.get("time") or "—")
            etype = ev.get("eventType") or ev.get("type") or "—"
            severity = ev.get("severity") or "—"
            desc = str(ev.get("description") or ev.get("message") or "")[:80]
            etable.add_row(ts, etype, severity, desc)
        all_lines += render_rich_to_lines(etable)
    else:
        all_lines += render_rich_to_lines(
            Panel("[dim]No events in this time window.[/dim]", border_style="dim")
        )

    scroll_view(all_lines, header_ansi=capture_banner())


# ------------------------------------------------------------------
# App Performance on Device
# ------------------------------------------------------------------

def _app_performance_menu(client, tenant):
    hours = _pick_time_range()
    device = _pick_device(client, hours)
    if not device:
        return

    device_id = str(device.get("id") or device.get("deviceId") or "")
    device_name = device.get("name") or device.get("hostname") or device_id

    with console.status(f"Fetching apps for {device_name}..."):
        try:
            apps = client.list_device_apps(device_id, hours)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch apps: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not apps:
        console.print(f"[yellow]No apps found for '{device_name}' in this time window.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    # Show app list table
    table = Table(title=f"Apps on {device_name} — last {hours}h", show_lines=False)
    table.add_column("App Name")
    table.add_column("App ID", style="dim")
    table.add_column("ZDX Score")
    table.add_column("Status")

    choices = []
    for app in apps:
        name = app.get("name") or app.get("appName") or "?"
        app_id = str(app.get("id") or app.get("appId") or "")
        score = str(app.get("score") or app.get("zdxScore") or "—")
        status = app.get("status") or "—"
        table.add_row(name, app_id, score, status)
        choices.append(questionary.Choice(f"{name} (ID: {app_id})", value=app))

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())

    # Let user pick an app for detail view
    if not questionary.confirm("View detailed metrics for a specific app?", default=False).ask():
        return

    chosen_app = questionary.select("Select app:", choices=choices).ask()
    if not chosen_app:
        return

    app_id = str(chosen_app.get("id") or chosen_app.get("appId") or "")
    app_name = chosen_app.get("name") or chosen_app.get("appName") or app_id

    with console.status(f"Fetching {app_name} metrics..."):
        try:
            detail = client.get_device_app(device_id, app_id, hours)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch app detail: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    import json
    from rich.syntax import Syntax
    syntax = Syntax(json.dumps(detail, indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


# ------------------------------------------------------------------
# User Lookup
# ------------------------------------------------------------------

def _user_lookup_menu(client, tenant):
    from services.zdx_service import ZDXService
    service = ZDXService(client, tenant_id=tenant.id)

    query = questionary.text("Search users (email / name):").ask()
    if not query:
        return

    with console.status("Searching users..."):
        try:
            users = service.lookup_user(query.strip())
        except Exception as e:
            console.print(f"[red]✗ Could not fetch users: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not users:
        console.print("[yellow]No users found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"ZDX Users — '{query}' ({len(users)} results)", show_lines=False)
    table.add_column("Name")
    table.add_column("Email")
    table.add_column("Devices")
    table.add_column("ZDX Score")

    for u in users:
        name = u.get("name") or u.get("displayName") or "—"
        email = u.get("email") or u.get("loginName") or "—"
        device_count = str(len(u.get("devices") or []))
        score = str(u.get("score") or u.get("zdxScore") or "—")
        table.add_row(name, email, device_count, score)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


# ------------------------------------------------------------------
# Application Scores
# ------------------------------------------------------------------

def _app_scores_menu(client, tenant):
    hours = _pick_time_range()

    with console.status("Fetching application scores..."):
        try:
            apps = client.list_apps(hours=hours)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch apps: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not apps:
        console.print("[yellow]No applications found.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Application ZDX Scores — last {hours}h ({len(apps)} apps)", show_lines=False)
    table.add_column("App Name")
    table.add_column("App ID", style="dim")
    table.add_column("ZDX Score")
    table.add_column("Users Affected")
    table.add_column("Status")

    for app in apps:
        name = app.get("name") or app.get("appName") or "?"
        app_id = str(app.get("id") or app.get("appId") or "—")
        score = str(app.get("score") or app.get("zdxScore") or "—")
        affected = str(app.get("numAffectedUsers") or app.get("affectedUsers") or "—")
        status = app.get("status") or "—"
        # Color-code the score
        try:
            score_val = float(score)
            if score_val >= 80:
                score_str = f"[green]{score}[/green]"
            elif score_val >= 50:
                score_str = f"[yellow]{score}[/yellow]"
            else:
                score_str = f"[red]{score}[/red]"
        except (ValueError, TypeError):
            score_str = score
        table.add_row(name, app_id, score_str, affected, status)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


# ------------------------------------------------------------------
# Deep Trace
# ------------------------------------------------------------------

def _deep_trace_menu(client, tenant):
    hours = _pick_time_range()

    while True:
        render_banner()
        choice = questionary.select(
            "Deep Trace",
            choices=[
                questionary.Choice("List Active Traces", value="list"),
                questionary.Choice("Start New Trace", value="start"),
                questionary.Choice("View Trace Results", value="view"),
                questionary.Choice("Stop Trace", value="stop"),
                questionary.Separator(),
                questionary.Choice("← Back", value="back"),
            ],
            use_indicator=True,
        ).ask()

        if choice == "list":
            _list_deep_traces(client, tenant, hours)
        elif choice == "start":
            _start_deep_trace(client, tenant, hours)
        elif choice == "view":
            _view_deep_trace(client, tenant, hours)
        elif choice == "stop":
            _stop_deep_trace(client, tenant, hours)
        elif choice in ("back", None):
            break


def _list_deep_traces(client, tenant, hours: int):
    device = _pick_device(client, hours)
    if not device:
        return

    device_id = str(device.get("id") or device.get("deviceId") or "")
    device_name = device.get("name") or device.get("hostname") or device_id

    with console.status(f"Fetching traces for {device_name}..."):
        try:
            traces = client.list_deep_traces(device_id)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch traces: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    if not traces:
        console.print(f"[yellow]No deep traces found for '{device_name}'.[/yellow]")
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    table = Table(title=f"Deep Traces — {device_name} ({len(traces)} total)", show_lines=False)
    table.add_column("Trace ID", style="dim")
    table.add_column("Session Name")
    table.add_column("Status")
    table.add_column("Created")
    table.add_column("App")

    for t in traces:
        trace_id = str(t.get("id") or t.get("traceId") or "—")
        session = t.get("sessionName") or t.get("name") or "—"
        status = t.get("status") or "—"
        created = str(t.get("createdAt") or t.get("startTime") or "—")
        app = t.get("appName") or t.get("app") or "—"
        status_style = "green" if status == "COMPLETE" else ("yellow" if status == "RUNNING" else "dim")
        table.add_row(trace_id, session, f"[{status_style}]{status}[/{status_style}]", created, app)

    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())


def _start_deep_trace(client, tenant, hours: int):
    device = _pick_device(client, hours)
    if not device:
        return

    device_id = str(device.get("id") or device.get("deviceId") or "")
    device_name = device.get("name") or device.get("hostname") or device_id

    session_name = questionary.text(
        "Session name:",
        default=f"trace-{device_name}",
    ).ask()
    if not session_name:
        return

    # Optional app selection
    app_id = None
    if questionary.confirm("Scope trace to a specific app?", default=False).ask():
        with console.status("Fetching apps..."):
            try:
                apps = client.list_device_apps(device_id, hours)
            except Exception:
                apps = []
        if apps:
            app_choices = [
                questionary.Choice(
                    a.get("name") or a.get("appName") or str(a.get("id") or "?"),
                    value=str(a.get("id") or a.get("appId") or ""),
                )
                for a in apps
            ]
            app_id = questionary.select("Select app:", choices=app_choices).ask()

    with console.status("Starting deep trace..."):
        try:
            result = client.start_deep_trace(device_id, session_name, app_id)
        except Exception as e:
            console.print(f"[red]✗ Could not start trace: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    trace_id = result.get("id") or result.get("traceId") or "?"
    console.print(f"[green]✓ Deep trace started — ID: {trace_id}[/green]")

    from services import audit_service
    audit_service.log(
        product="ZDX",
        operation="start_deep_trace",
        action="CREATE",
        status="SUCCESS",
        tenant_id=tenant.id,
        resource_type="deep_trace",
        resource_id=str(trace_id),
        resource_name=session_name,
        details={"device_id": device_id, "device_name": device_name, "app_id": app_id},
    )

    # Poll status until complete or user exits
    if questionary.confirm("Poll trace status until complete?", default=True).ask():
        import time
        console.print("[dim]Polling every 5 seconds. Press Ctrl+C to stop polling.[/dim]")
        try:
            for _ in range(24):  # max 2 minutes
                time.sleep(5)
                trace = client.get_deep_trace(device_id, str(trace_id))
                status = trace.get("status") or "?"
                console.print(f"  Status: [cyan]{status}[/cyan]")
                if status in ("COMPLETE", "FAILED", "STOPPED"):
                    break
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped polling.[/dim]")

    questionary.press_any_key_to_continue("Press any key to continue...").ask()


def _pick_trace(client, device_id: str, device_name: str) -> Optional[dict]:
    """Fetch traces for a device and let the user pick one."""
    with console.status(f"Fetching traces for {device_name}..."):
        try:
            traces = client.list_deep_traces(device_id)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch traces: {e}[/red]")
            return None

    if not traces:
        console.print(f"[yellow]No deep traces found for '{device_name}'.[/yellow]")
        return None

    choices = [
        questionary.Choice(
            f"{t.get('sessionName') or t.get('name') or 'trace'} "
            f"[{t.get('status') or '?'}] (ID: {t.get('id') or t.get('traceId') or '?'})",
            value=t,
        )
        for t in traces
    ]
    return questionary.select("Select trace:", choices=choices).ask()


def _view_deep_trace(client, tenant, hours: int):
    device = _pick_device(client, hours)
    if not device:
        return

    device_id = str(device.get("id") or device.get("deviceId") or "")
    device_name = device.get("name") or device.get("hostname") or device_id

    trace = _pick_trace(client, device_id, device_name)
    if not trace:
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    trace_id = str(trace.get("id") or trace.get("traceId") or "")

    with console.status("Fetching trace details..."):
        try:
            detail = client.get_deep_trace(device_id, trace_id)
        except Exception as e:
            console.print(f"[red]✗ Could not fetch trace: {e}[/red]")
            questionary.press_any_key_to_continue("Press any key to continue...").ask()
            return

    import json
    from rich.syntax import Syntax
    from cli.banner import capture_banner
    from cli.scroll_view import render_rich_to_lines, scroll_view
    syntax = Syntax(json.dumps(detail, indent=2, default=str), "json", theme="monokai")
    scroll_view(render_rich_to_lines(syntax), header_ansi=capture_banner())


def _stop_deep_trace(client, tenant, hours: int):
    device = _pick_device(client, hours)
    if not device:
        return

    device_id = str(device.get("id") or device.get("deviceId") or "")
    device_name = device.get("name") or device.get("hostname") or device_id

    trace = _pick_trace(client, device_id, device_name)
    if not trace:
        questionary.press_any_key_to_continue("Press any key to continue...").ask()
        return

    trace_id = str(trace.get("id") or trace.get("traceId") or "")
    session_name = trace.get("sessionName") or trace.get("name") or trace_id

    confirmed = questionary.confirm(
        f"Stop trace '{session_name}' (ID: {trace_id})?", default=True
    ).ask()
    if not confirmed:
        return

    try:
        client.stop_deep_trace(device_id, trace_id)
        console.print(f"[green]✓ Trace '{session_name}' stopped.[/green]")
        from services import audit_service
        audit_service.log(
            product="ZDX",
            operation="stop_deep_trace",
            action="DELETE",
            status="SUCCESS",
            tenant_id=tenant.id,
            resource_type="deep_trace",
            resource_id=trace_id,
            resource_name=session_name,
        )
    except Exception as e:
        console.print(f"[red]✗ Could not stop trace: {e}[/red]")
    questionary.press_any_key_to_continue("Press any key to continue...").ask()
