"""GitHub Device Flow OAuth for plugin manager authentication.

Token is stored at ~/.config/zs-config/github_token (chmod 600).
The client_id is the registered zs-config GitHub OAuth App — not a secret.
"""

import time
import webbrowser
from pathlib import Path
from typing import Callable, Optional

import requests

_CLIENT_ID    = "Ov23liBDXNJZC4YC0jnE"
_TOKEN_FILE   = Path.home() / ".config" / "zs-config" / "github_token"
_DEVICE_URL   = "https://github.com/login/device/code"
_TOKEN_URL    = "https://github.com/login/oauth/access_token"
_SCOPE        = "repo"
_API_URL      = "https://api.github.com"
_PLUGINS_REPO = "mpreissner/zs-plugins"  # private repo; access = authorised user


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

def get_token() -> Optional[str]:
    """Return the stored GitHub access token, or None if not authenticated."""
    if _TOKEN_FILE.exists():
        token = _TOKEN_FILE.read_text().strip()
        return token or None
    return None


def is_authenticated() -> bool:
    return get_token() is not None


def save_token(token: str) -> None:
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token)
    _TOKEN_FILE.chmod(0o600)


def logout() -> None:
    if _TOKEN_FILE.exists():
        _TOKEN_FILE.unlink()


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

def verify_token(token: str) -> tuple[bool, str]:
    """Check token against the GitHub API.

    Returns (valid, github_username) on success or (False, error_message) on failure.
    """
    try:
        resp = requests.get(
            f"{_API_URL}/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return True, resp.json().get("login", "unknown")
        if resp.status_code == 401:
            return False, "token expired or revoked"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Repo access check
# ---------------------------------------------------------------------------

def has_repo_access(token: str) -> tuple[bool, str]:
    """Check whether the token holder can access the plugin repository.

    Uses the repo metadata endpoint — private repos are hidden as 404 to
    anyone without explicit collaborator access, so a 200 means authorised.

    Returns (True, "") on success or (False, reason) on failure.
    """
    try:
        resp = requests.get(
            f"{_API_URL}/repos/{_PLUGINS_REPO}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return True, ""
        if resp.status_code == 404:
            return False, "account is not a collaborator on the plugin repository"
        if resp.status_code == 401:
            return False, "token invalid or expired"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Device Flow authentication
# ---------------------------------------------------------------------------

def authenticate(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """Run GitHub Device Flow OAuth.

    Opens the browser, displays the user code, and polls until the user
    completes authentication (including MFA) in the browser.

    Args:
        progress_callback: called with status strings during the polling loop.

    Returns:
        (True, "Authenticated as <username>") on success.
        (False, error_message) on failure.
    """

    # ── Step 1: request device + user codes ─────────────────────────────
    try:
        resp = requests.post(
            _DEVICE_URL,
            data={"client_id": _CLIENT_ID, "scope": _SCOPE},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return False, f"Failed to reach GitHub: {exc}"

    device_code = data.get("device_code")
    user_code   = data.get("user_code")
    verify_url  = data.get("verification_uri", "https://github.com/login/device")
    expires_in  = int(data.get("expires_in", 900))
    interval    = int(data.get("interval", 5))

    if not device_code or not user_code:
        return False, f"Unexpected response from GitHub: {data}"

    if progress_callback:
        progress_callback(
            f"Opening browser...\n"
            f"  URL  : {verify_url}\n"
            f"  Code : {user_code}\n"
            f"  (enter the code in the browser if it doesn't auto-fill)"
        )

    try:
        webbrowser.open(verify_url)
    except Exception:
        pass  # not fatal — user can navigate manually

    # ── Step 2: poll until authorised or expired ─────────────────────────
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)

        try:
            poll = requests.post(
                _TOKEN_URL,
                data={
                    "client_id":   _CLIENT_ID,
                    "device_code": device_code,
                    "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            poll.raise_for_status()
            result = poll.json()
        except Exception as exc:
            return False, f"Polling error: {exc}"

        error = result.get("error")

        if not error:
            token = result.get("access_token")
            if token:
                _, username = verify_token(token)
                ok, access_err = has_repo_access(token)
                if not ok:
                    return False, (
                        f"GitHub authentication succeeded (as {username}) but your "
                        f"account does not have access to the plugin repository. "
                        f"Contact your administrator to be added as a collaborator.\n"
                        f"  ({access_err})"
                    )
                save_token(token)
                return True, f"Authenticated as {username}"

        elif error == "authorization_pending":
            if progress_callback:
                progress_callback("Waiting for browser authorization...")

        elif error == "slow_down":
            interval += 5

        elif error == "expired_token":
            return False, "Authorization code expired — please try again."

        elif error == "access_denied":
            return False, "Authorization was denied."

        else:
            return False, f"GitHub error: {error}"

    return False, "Authorization timed out."
