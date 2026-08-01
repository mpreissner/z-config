"""Just enough of the Cloudflare DNS API to solve ACME dns-01 challenges.

Kept deliberately small: verify a token, find the zone that owns a hostname,
and add/remove TXT records. Nothing here ever logs or returns the API token.
"""
import requests

API_BASE = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 20

# Short, because the record only has to survive one validation round trip and a
# long TTL would keep a stale value cached into the next issuance.
CHALLENGE_TTL = 60


class CloudflareError(Exception):
    pass


def _call(method: str, path: str, token: str, **kwargs):
    """Issue an authenticated call and unwrap Cloudflare's envelope."""
    try:
        resp = requests.request(
            method,
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as e:
        raise CloudflareError(f"Could not reach the Cloudflare API: {e}") from e

    if resp.status_code in (401, 403):
        raise CloudflareError(
            "Cloudflare rejected the API token. It needs Zone:Read and DNS:Edit "
            "permissions on the zone that hosts this domain."
        )

    try:
        body = resp.json()
    except ValueError:
        raise CloudflareError(
            f"Cloudflare returned a non-JSON response (HTTP {resp.status_code})."
        )

    if not body.get("success"):
        errors = body.get("errors") or []
        detail = "; ".join(
            str(e.get("message") or e) for e in errors
        ) or f"HTTP {resp.status_code}"
        raise CloudflareError(f"Cloudflare API error: {detail}")

    return body.get("result")


def verify_token(token: str) -> None:
    """Raise CloudflareError unless the token is live and active."""
    result = _call("GET", "/user/tokens/verify", token) or {}
    if result.get("status") != "active":
        raise CloudflareError(
            f"The Cloudflare API token is not active (status: {result.get('status')})."
        )


def find_zone(token: str, fqdn: str) -> tuple:
    """Return (zone_id, zone_name) for the zone that holds ``fqdn``.

    Walks up the label list because the zone boundary is not something we can
    infer from the name alone — ``a.b.example.com`` may sit in a zone named
    ``b.example.com`` or ``example.com``, and only Cloudflare knows which.
    """
    labels = fqdn.strip(".").split(".")
    if len(labels) < 2:
        raise CloudflareError(f"'{fqdn}' is not a fully qualified domain name.")

    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        zones = _call("GET", "/zones", token, params={"name": candidate}) or []
        if zones:
            return zones[0]["id"], zones[0]["name"]

    raise CloudflareError(
        f"No Cloudflare zone in this account covers '{fqdn}'. Check that the "
        "domain is hosted on Cloudflare and the token can read that zone."
    )


def find_txt_records(token: str, zone_id: str, name: str) -> list:
    """Return the IDs of existing TXT records at ``name``."""
    records = _call(
        "GET", f"/zones/{zone_id}/dns_records", token,
        params={"type": "TXT", "name": name},
    ) or []
    return [r["id"] for r in records]


def create_txt(token: str, zone_id: str, name: str, value: str) -> str:
    """Create a TXT record and return its ID."""
    record = _call(
        "POST", f"/zones/{zone_id}/dns_records", token,
        json={"type": "TXT", "name": name, "content": value, "ttl": CHALLENGE_TTL},
    ) or {}
    record_id = record.get("id")
    if not record_id:
        raise CloudflareError("Cloudflare accepted the TXT record but returned no ID.")
    return record_id


def delete_record(token: str, zone_id: str, record_id: str) -> None:
    _call("DELETE", f"/zones/{zone_id}/dns_records/{record_id}", token)
