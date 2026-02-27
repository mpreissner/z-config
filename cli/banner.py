"""Z-Config banner — logo, version, and screen-clear/redraw helper.

Call render_banner() at the top of every menu loop instead of a bare
console.clear() so the logo is always visible above the prompt.
"""

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

VERSION = "0.6.1"

# Generate the logo once at import time using pyfiglet (slant font).
# Falls back to the hand-drawn art if pyfiglet isn't installed.
try:
    import pyfiglet
    _LOGO_TEXT = pyfiglet.figlet_format("zs-Config", font="slant").rstrip()
except Exception:
    _LOGO_TEXT = (
        "                   ______            _____      \n"
        " ____  _____      / ____/___  ____  / __(_)___ _\n"
        "/_  / / ___/_____/ /   / __ \\/ __ \\/ /_/ / __ `/\n"
        " / /_(__  )_____/ /___/ /_/ / / / / __/ / /_/ / \n"
        "/___/____/      \\____/\\____/_/ /_/_/ /_/\\__, /  \n"
        "                                       /____/"
    )


def _build_banner_panel():
    from cli.session import get_active_tenant

    tenant = get_active_tenant()
    subtitle = (
        f"Active: {tenant.name}  |  v{VERSION}  |  Zscaler OneAPI Automation"
        if tenant
        else f"v{VERSION}  |  Zscaler OneAPI Automation"
    )

    _lines = _LOGO_TEXT.split("\n")
    _w = max(len(l) for l in _lines)
    _logo = "\n".join(l.ljust(_w) for l in _lines)

    return Panel(
        Align(Text(_logo, style="bold cyan", no_wrap=True), align="center"),
        subtitle=subtitle,
        border_style="cyan",
        padding=(0, 4),
    )


def render_banner() -> None:
    """Clear the screen and redraw the Z-Config logo panel."""
    console.clear()
    console.print(_build_banner_panel())


def capture_banner() -> str:
    """Render the banner to an ANSI string (for embedded scroll views)."""
    import shutil
    from io import StringIO

    buf = StringIO()
    cap = Console(file=buf, width=shutil.get_terminal_size().columns,
                  force_terminal=True, highlight=False)
    cap.print(_build_banner_panel())
    return buf.getvalue()
