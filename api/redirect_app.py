"""Minimal HTTP-to-HTTPS redirect ASGI app.
Runs on port 8000 when SSL is enabled; main app runs on 8443.

Redirects to the domain stored in the DB (set and cert-validated at upload time),
not to whatever hostname the incoming request used. The port, unlike the
hostname, is derived from the request — see _origin().
"""
import os
from typing import Optional

from db.database import get_setting as _get_setting

# Read once at process startup; guaranteed set before this process is spawned.
_SSL_DOMAIN: str = _get_setting("ssl_domain") or "localhost"
_PUBLIC_ORIGIN: str = os.environ.get("ZS_PUBLIC_ORIGIN", "").strip().rstrip("/")


def _request_port(scope) -> Optional[str]:
    """Port named by the request's Host header.

    "" when the header is present but names no port, None when there is no
    usable header at all — the two mean different things to _origin().
    """
    for name, value in scope.get("headers", []):
        if name == b"host":
            host = value.decode("latin-1").strip()
            break
    else:
        return None
    if not host:
        return None
    if host.startswith("["):  # IPv6 literal: [::1] or [::1]:8000
        _, _, rest = host.partition("]")
        return rest.lstrip(":")
    _, sep, port = host.partition(":")
    return port if sep else ""


def _origin(scope) -> str:
    """The HTTPS origin to send this client to.

    The hostname stays pinned to the cert-validated DB domain — taking it from
    the Host header would turn this into an open redirect. Only the port
    follows the request, and that is the part that was broken: hardcoding
    ':8443' stranded everyone behind ZPA Browser Access or a reverse proxy,
    which publish us on 443. They were redirected to a port nothing listens on
    and the browser hung until it timed out.

    Port 8000 is our own plaintext listener, so a client that names it reached
    us directly and belongs on 8443. A Host header naming any other port, or
    none, means something fronted us on a standard port and its TLS side is
    443. A missing Host header is not evidence of a proxy, so it keeps the
    direct-access port rather than guessing.
    """
    if _PUBLIC_ORIGIN:
        return _PUBLIC_ORIGIN
    port = _request_port(scope)
    suffix = ":8443" if port is None or port == "8000" else ""
    return f"https://{_SSL_DOMAIN}{suffix}"


async def redirect_app(scope, receive, send):
    if scope["type"] != "http":
        return

    path = scope.get("path", "/")

    if path == "/health":
        body = b'{"status":"redirect_active"}'
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    query = scope.get("query_string", b"").decode()
    location = f"{_origin(scope)}{path}"
    if query:
        location = f"{location}?{query}"

    await send({
        "type": "http.response.start",
        "status": 301,
        "headers": [
            [b"location", location.encode()],
            [b"content-length", b"0"],
            # Cache the redirect so repeat HTTP visits skip this round-trip, but
            # briefly: a 301 with no max-age is cached indefinitely, and when the
            # target was wrong that turned a misconfiguration into an outage the
            # server could no longer correct.
            [b"cache-control", b"max-age=300"],
        ],
    })
    await send({"type": "http.response.body", "body": b""})
