# Security Policy

## Supported Versions

Only the latest release is actively maintained.

| Version | Supported |
|---|---|
| 2.0.0 (latest) | Yes |
| 1.0.x | No |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, open a [GitHub Security Advisory](../../security/advisories/new) or contact the maintainers privately. Include as much detail as possible:

- Type of vulnerability (e.g. credential exposure, injection, path traversal)
- Steps to reproduce
- Potential impact

You can expect an acknowledgement within 72 hours and a status update within 7 days.

## Scope

### TUI (CLI)

The TUI stores Zscaler API credentials encrypted at rest using Fernet symmetric encryption. The encryption key is stored at `~/.config/zs-config/secret.key` (chmod 600) or provided via the `ZSCALER_SECRET_KEY` environment variable.

Security-relevant areas to be aware of:
- Credential storage (`services/config_service.py`, `~/.config/zs-config/secret.key`)
- File path handling in CSV import and certificate rotation flows
- API credential transmission via the zscaler-sdk-python library

### Web UI

The web UI is a Docker container intended for self-hosted deployment on a trusted network. It should not be exposed to the public internet without additional controls (VPN, reverse proxy with authentication, network firewall).

**Session model:**

- Access tokens are short-lived JWTs (default 5 minutes) signed with `JWT_SECRET + startup_nonce`
- Refresh tokens are issued as httpOnly cookies scoped to `/api/v1/auth/refresh` (default 60 minutes absolute from login — never extended by silent refresh)
- The refresh cookie TTL controls the maximum session duration; users cannot extend beyond this by staying active — they must re-authenticate
- On container restart, a new `_STARTUP_NONCE` is generated and appended to the signing key. All tokens issued in prior runs are immediately cryptographically invalid, preventing session reuse across restarts
- On idle for 15 minutes, the browser shows a 2-minute countdown warning and then calls `POST /api/v1/auth/logout`, revoking the refresh cookie server-side

**Password storage:**
- Web UI user passwords are hashed with bcrypt (cost factor 12) and never stored in plaintext
- `client_secret` for Zscaler tenants is encrypted at rest with Fernet before being written to the database

**Relevant files:**
- `api/auth_utils.py` — JWT issuance, refresh, startup nonce
- `api/routers/auth.py` — login, logout, refresh, MFA endpoints
- `api/dependencies.py` — JWT validation, role enforcement
- `web/src/context/AuthContext.tsx` — proactive refresh, idle timeout integration
- `web/src/hooks/useIdleLogout.ts` — idle timer and warning modal

**Non-negotiable rules enforced in code:**
- `client_secret` must never appear in logs, audit entries, or API responses
- All mutating ZIA API calls route through `_zia_changed()` in `zia_menu.py`
