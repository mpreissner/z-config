# zs-config

[![PyPI](https://img.shields.io/pypi/v/zs-config)](https://pypi.org/project/zs-config/)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

Interactive TUI and browser-based UI for Zscaler OneAPI — manage ZPA, ZIA, ZCC, ZDX, and ZIdentity from the terminal or a self-hosted web interface, with a local SQLite cache for fast lookups and bulk operations.

---

## Web UI — v2.0.0

zs-config v2.0.0 ships a browser-based management UI alongside the existing TUI. It runs as a self-contained Docker container with a FastAPI backend and a React + Tailwind frontend.

### Deploy

Requires Docker with Compose v2. Download and run the deploy script — it handles cloning, secret generation, volumes, build, and startup automatically.

```bash
curl -fsSL https://raw.githubusercontent.com/mpreissner/zs-config/main/deploy.sh -o deploy.sh
bash deploy.sh
```

Or if you already have the repo cloned:

```bash
./deploy.sh
```

The script will:
- Clone the repo if not already present (into `./zs-config`)
- Generate a `JWT_SECRET` and save it to `.env` if one does not already exist
- Create the persistent Docker volumes for the database and plugins
- Build the image and start the container
- Run a health check and print the URL when ready

On first boot the container seeds an `admin` account with a random temporary password and prints it to the container log:

```
docker compose logs | grep "Initial password"
```

You will be prompted to set a permanent password on first login.

**Subsequent deploys** (pull latest and rebuild):

```bash
./deploy.sh
```

### Web UI Features

The web UI covers all major Zscaler product areas across multiple tenants simultaneously. All data is read from the local SQLite cache; use **Import** in any product tab to refresh from the live API.

**ZIA — Internet Access**
- Activation — push pending changes and view current activation status
- URL Filtering Rules — list, search, enable/disable
- URL Categories — list, view URL counts, add/remove custom URLs
- URL Lookup — real-time URL categorization check
- Cloud App Instances — list and search cloud application inventory
- Tenancy Restrictions — view Microsoft 365 and Google tenant restriction profiles
- Cloud App Rules — list, search, enable/disable by rule type
- URL & Cloud App Control Advanced Settings — view and toggle global policy settings
- Allow / Deny Lists — view and edit the global security allowlist and denylist
- Firewall Policy — list, search, enable/disable; CSV export and import/sync
- SSL Inspection — list, search, enable/disable
- Forwarding Rules — list and search
- Users, Locations, Departments, Groups — read from local DB
- DLP Engines — list, search, view; edit expression and confidence
- DLP Dictionaries — list, search, view; edit confidence threshold
- DLP Web Rules — list, search, enable/disable
- Config Snapshots — save, list, delete point-in-time snapshots
- Apply Snapshot from Other Tenant — delta or wipe-first push with preview

**ZPA — Private Access**
- App Connectors — list and search
- Service Edges — list and search
- Application Segments — list and search
- Segment Groups — list and search
- Browser Access Certificates — list
- PRA Portals — list and search

**ZDX — Digital Experience**
- Device Search — look up devices by hostname or email, view health metrics
- User Lookup — search users, view ZDX score and device count

**ZCC — Client Connector**
- All Devices — list, search, OTP lookup
- Trusted Networks — list and search
- Forwarding Profiles — list and search
- App Profiles (Web Policies) — list and view
- Bypass App Services — list and view

**ZIdentity**
- Users — list and search
- Groups — list, search, view members
- API Clients — list, search, view details and secrets

**Admin (admin-only)**
- User Management — create/edit/delete web UI users; assign roles and tenant access
- Entitlements — control which tenants each non-admin user can see
- System Settings — session timeout, max login attempts, audit log retention, IdP (OIDC/SAML), SSL mode

### Session Security

- Sessions use a short-lived JWT (5 min) renewed silently against an httpOnly refresh cookie (60 min absolute expiry, never extended)
- All tokens are invalidated immediately on container restart — prior-session cookies are cryptographically rejected
- Idle timeout: 15 minutes of inactivity triggers a 2-minute countdown warning, then automatic logout
- The session timeout setting controls the maximum session duration from login; users will also be logged out after 15 minutes of inactivity regardless of the remaining session time

### Migrating from TUI v1.x

If you have an existing TUI install, you can import your database and encryption key via **Admin → Settings → Import Database** in the web UI. Use the export script to package both files from your local install:

```bash
./scripts/export_tui_db.sh ~/zs-config-export
```

Then upload `zscaler.db` and `secret.key` from that directory. All schema migrations are applied automatically on import.

---

## What's New — v1.1.0

- **ZIA — Apply Snapshot from Another Tenant** — push any saved ZIA snapshot from another configured tenant directly to the active tenant, using the same wipe-or-delta workflow as a standard restore. No file export or import required; snapshots are read directly from the local database.
- **ZPA Access Policy CSV sync — reorder-only runs now trigger DB sync** — previously, a sync that resulted in only a rule reorder (no creates/updates/deletes) skipped the post-mutation local DB refresh, leaving cached `rule_order` values stale. Fixed.
- **ZPA Access Policy CSV sync — DB sync failures now surfaced** — both the import-sync and bulk-create flows now check the `SyncLog` status returned by `ZPAImportService` and display a warning or error on failure, instead of silently printing success when the underlying sync job failed (e.g. `policy_access` auto-disabled after a prior 401).

---

## TUI Features

- **ZPA** — App Connectors & Connector Groups (full CRUD), Application Segments (list/search/enable-disable/bulk-create from CSV), App Segment Groups, Access Policy (list/search/export/import-sync from CSV with dry-run, bulk reorder, and orphan delete), PRA Portals & Consoles, Service Edges, Certificate Management (upload/rotate/delete), Identity & Directory (SAML Attributes, SCIM User Attributes, SCIM Groups), Policy Scoping Reference export, Apps & Groups Reference export
- **ZIA** — URL Filtering, URL Categories, Security Policy (allowlist/denylist), URL Lookup, Firewall Policy (L4 rules, DNS filter, IPS — list/search/enable-disable/export/import-sync from CSV), SSL Inspection, Traffic Forwarding, Locations, Users, DLP Engines/Dictionaries/Web Rules, Cloud App Control (full CRUD), **Apply Snapshot from Another Tenant** (wipe-first or delta push with ID remapping, cross-tenant rule ordering, scope-aware disable), Policy Activation
- **ZIA IP Groups** — Source and Destination IPv4 Groups: list, search, create, edit, delete, and bulk create from CSV
- **ZCC** — Devices (list/search/remove/OTP lookup/password lookup/CSV export), Trusted Networks, Forwarding Profiles, Admin Users, Entitlements, App Profiles (manage bypass apps/activate/delete), Bypass App Definitions
- **ZDX** — Device health, app performance, user lookup, application scores, deep trace
- **ZIdentity** — Users (list/search/reset-password/set-password/skip-MFA), Groups (list/search/members/add-remove), API Clients (list/search/secrets/delete)
- **Config Import** — 27 ZPA + 42 ZIA + 6 ZCC resource types pulled into a local SQLite cache with SHA-256 change detection
- **Config Snapshots** — save, compare (field-level diff), restore (ZIA only — wipe-or-delta, including cross-tenant), and delete point-in-time snapshots for ZPA and ZIA
- **Audit Log** — immutable record of every operation
- **Zero-config encryption** — tenant secrets encrypted at rest; key auto-generated on first launch
- **Auto-update** — silent PyPI check on startup; shows changelog and upgrades in-place via pipx or pip

---

## Architecture

```
zs-config/
├── lib/               # Low-level API clients (no business logic, no DB)
│   ├── auth.py
│   ├── zpa_client.py
│   ├── zia_client.py
│   ├── zcc_client.py
│   ├── zdx_client.py
│   └── zidentity_client.py
│
├── db/
│   ├── models.py      # TenantConfig, AuditLog, Certificate, ZPAResource, ZIAResource, ZCCResource, SyncLog, RestorePoint
│   └── database.py    # Engine, session manager, auto-migrations
│
├── services/          # Business logic — shared by CLI and API
│   ├── config_service.py
│   ├── audit_service.py
│   ├── zpa_service.py / zpa_import_service.py / zpa_segment_service.py / zpa_policy_service.py
│   ├── zia_service.py / zia_import_service.py / zia_push_service.py / zia_firewall_service.py
│   ├── zcc_service.py / zcc_import_service.py
│   ├── zdx_service.py
│   └── zidentity_service.py
│
├── cli/               # TUI entry point and menus
│   ├── z_config.py
│   ├── banner.py
│   ├── scroll_view.py
│   ├── update_checker.py
│   └── menus/
│       ├── main_menu.py
│       ├── zpa_menu.py / zia_menu.py / zcc_menu.py / zdx_menu.py / zidentity_menu.py
│
├── api/               # FastAPI REST backend
│   ├── main.py
│   ├── auth_utils.py
│   ├── dependencies.py
│   └── routers/
│       ├── auth.py / tenants.py / zia.py / zpa.py / zcc.py / zdx.py / zid.py
│       └── system.py / users.py / audit.py
│
└── web/               # React + Vite + Tailwind frontend
    └── src/
        ├── api/       # Typed fetch wrappers per product
        ├── components/ # Shared UI components
        ├── context/   # AuthContext, ActiveTenantContext
        ├── hooks/     # useIdleLogout, useJobStream, etc.
        └── pages/     # TenantWorkspacePage, AdminSettingsPage, etc.
```

---

## Installation (TUI)

```bash
pipx install zs-config   # recommended (isolated)
# or
pip install zs-config

zs-config
```

On first launch an encryption key is generated at `~/.config/zs-config/secret.key` and a default working directory is created at `~/Documents/zs-config`. File export and import prompts default to this directory. Go to **Settings → Add Tenant** to register a tenant, then run **Import Config** under ZIA or ZPA to populate the local cache.

**Dev setup:**
```bash
git clone https://github.com/mpreissner/zs-config.git
cd zs-config
pip install -e .
zs-config
```

**Environment overrides:**

| Variable | Default | Purpose |
|---|---|---|
| `ZSCALER_SECRET_KEY` | auto-generated | Fernet key for secret encryption |
| `ZSCALER_DB_URL` | `~/.local/share/zs-config/zscaler.db` | SQLAlchemy DB URL (e.g. PostgreSQL) |
| `REQUESTS_CA_BUNDLE` | system trust store | Path to a PEM CA bundle for all outbound HTTPS requests |

**SSL inspection:** zs-config automatically uses the OS native trust store (macOS Keychain, Windows Certificate Store) via `truststore`, so corporate inspection certificates pushed by MDM/GPO/Jamf are trusted without any configuration. Alternatively, drop a PEM file at `~/.config/zs-config/ca-bundle.pem` and it will be used automatically.

---

## CLI Reference

### Main Menu

| Option | Description |
|---|---|
| ZIA | Zscaler Internet Access |
| ZPA | Zscaler Private Access |
| ZCC | Zscaler Client Connector |
| ZDX | Zscaler Digital Experience |
| ZIdentity | Identity and directory management |
| Switch Tenant | Change active tenant |
| Settings | Manage tenants; clear data |
| Audit Log | Scrollable operation history |

---

### ZPA

**Infrastructure** — App Connectors (list/search/enable-disable/rename/delete), Connector Groups (full CRUD), Service Edges (list/search/enable-disable)

**Applications** — Application Segments (list/search/enable-disable/bulk-create from CSV/export template/Apps & Groups Reference export), App Segment Groups (list/search)

**Policy** — Access Policy: list, search, export to CSV, import/sync from CSV (dry-run preview → update/create/delete/reorder in one atomic operation), Policy Scoping Reference export

**PRA** — PRA Portals (full CRUD), PRA Consoles (list/search/enable-disable/delete)

**Certificates** — list, rotate (upload new cert → update all matching segments and portals → delete old), delete

**Identity & Directory** — SAML Attributes (list/search), SCIM User Attributes (list/search), SCIM Groups (list/search)

**Bottom** — Import Config (27 resource types), Config Snapshots, Reset N/A Resource Types

#### Access Policy CSV sync

The sync workflow: parse CSV → classify (UPDATE / CREATE / DELETE / SKIP / MISSING_DEP / REORDER) → show dry-run table → confirm → apply → reorder.

CSV columns: `id` (blank = new rule), `name`, `action`, `description`, `rule_order` (informational; row order is authoritative), `app_groups`, `applications`, `saml_attributes`, `scim_attributes`, `scim_groups`, `client_types`, `machine_groups`, `trusted_networks`, `platforms`, `country_codes`, `idp_names`, `posture_profiles`, `risk_factor_types`

Rules missing from the CSV are deleted. The final `bulk_reorder_rules()` call makes row sequence the authoritative order.

---

### ZIA

**Web & URL Policy** — URL Filtering (list/search/enable-disable), URL Categories (add/remove URLs), Security Policy Settings (allowlist/denylist), URL Lookup

**Network Security** — Firewall Policy (L4 rules / DNS filter / IPS — list/search/enable-disable/export/import-sync from CSV), SSL Inspection (list/search/enable-disable), Traffic Forwarding

**Identity & Access** — Users (list/search), Locations (list/search/groups)

**DLP** — Engines, Dictionaries, Web Rules (list/search/view; Engines and Dictionaries support full CRUD + JSON/CSV import)

**Cloud Apps** — Cloud Applications (list/search), Cloud App Control (full CRUD by rule type)

**Bottom** — Activation, Import Config (37 resource types), Config Snapshots (save / compare / restore / cross-tenant apply / delete), Reset N/A Resource Types

#### Firewall Rule CSV sync

Same Option C algorithm as ZPA. Reorder is handled via individual PUTs in descending order (ZIA has no bulk-reorder endpoint). Rows referencing groups, services, or locations not found in the local DB are flagged MISSING_DEP — use **Source/Dest IPv4 Group Management** to bulk-create missing groups first.

CSV columns: `id`, `name`, `order`, `action`, `state`, `description`, `src_ips`, `src_ip_groups`, `dest_addresses`, `dest_ip_groups`, `nw_services`, `nw_service_groups`, `locations`, `enable_full_logging`

#### IP Group Management

**Source IPv4 Group Management** and **Dest IPv4 Group Management** are full CRUD submenus: list, search, create (prompted fields), edit (blank = keep current), delete, and bulk create from CSV. Destination groups require a `type` (`DSTN_IP` / `DSTN_FQDN` / `DSTN_DOMAIN` / `DSTN_OTHER`). Local DB is re-synced after every mutation so groups are immediately available for firewall rule sync.

---

### ZCC

**Devices** — list (filtered by OS), search by username, view details, soft remove, force remove

**Device Credentials** — OTP lookup, App Profile password lookup

**Configuration** — Trusted Networks, Forwarding Profiles, Admin Users, Entitlements (ZPA/ZDX group access), App Profiles (manage bypass apps / activate / delete), Bypass App Definitions

**Bottom** — Export Devices CSV, Export Service Status CSV, Import Config, Reset N/A Resource Types

---

### ZDX

Select a time window (2 / 4 / 8 / 24 hours) on entry. Sections: Device Lookup & Health, App Performance on Device, User Lookup, Application Scores, Deep Trace (list/start/view/stop).

---

### ZIdentity

**Users** — list, search, view details (groups + entitlements), reset password, set password, skip MFA

**Groups** — list, search, view members, add/remove users

**API Clients** — list, search, view details and secrets, add/delete secrets, delete client

---

### Settings

| Option | Description |
|---|---|
| Add Tenant | Register tenant; credentials verified immediately |
| Edit Tenant | Update subdomain/client ID/secret; live token test |
| List Tenants | All tenants with ZIA cloud, tenant ID, ZPA cloud |
| Remove Tenant | Delete tenant and credentials |
| Clear Imported Data & Audit Log | Wipe resources/sync logs/audit (tenant config preserved) |

---

## Database

| Table | Contents |
|---|---|
| `TenantConfig` | Connection details per tenant (client secret encrypted) |
| `AuditLog` | Immutable operation record |
| `Certificate` | Cert lifecycle tracking |
| `ZPAResource` | Full JSON snapshot of ZPA resources; SHA-256 change detection |
| `ZIAResource` | Full JSON snapshot of ZIA resources; SHA-256 change detection |
| `ZCCResource` | Full JSON snapshot of ZCC resources; SHA-256 change detection |
| `SyncLog` | Import run outcomes (status, counters, errors) |
| `RestorePoint` | Point-in-time config snapshots |
| `WebUser` | Web UI users (username, bcrypt hash, role) |
| `Setting` | Key/value store for admin-configurable settings |

---

## Known Issues

### Smart Browser Isolation — cannot be enabled via API

**Symptom:** Pushing `browser_control_settings` with `enableSmartIsolation: true` appears to succeed (HTTP 200), but Smart Browser Isolation remains disabled on the target tenant.

**Cause:** The ZIA API accepts the payload but does not honour the `enableSmartIsolation` toggle. This is a Zscaler platform limitation — enabling Smart Browser Isolation requires a manual step in the ZIA admin console (Policy → Browser Control → Smart Isolation).

**Workaround:** After pushing a baseline that includes Smart Isolation, log in to the target tenant's ZIA admin console and enable Smart Browser Isolation manually. All other `browser_control_settings` fields (CBI profile, etc.) push correctly.

**Rule ordering:** When the source tenant has Smart Isolation enabled (and thus "Smart Isolation One Click Rule" at order 1), the push automatically detects that the rule could not be provisioned on the target and renumbers the remaining SSL Inspection rules to fill the gap — so they remain in the correct relative order starting at 1.

---

### Cross-Cloud Baseline Push — Commercial to GovCloud

**Symptom:** Pushing a commercial ZIA baseline to a GovCloud tenant (via Restore Snapshot or cross-tenant apply) produces a significant number of errors and failures.

**Cause:** Under investigation. Likely contributing factors include:
- API path and payload differences between commercial and GovCloud endpoints for certain resource types
- Resource ID namespacing differences — objects referenced by ID in the commercial baseline (e.g. URL categories, IP groups, locations) may not resolve correctly against GovCloud IDs
- GovCloud-specific resource types or entitlements that have no commercial equivalent (and vice versa), causing the normalizer to generate invalid payloads

**Workaround:** Cross-cloud commercial → GovCloud pushes are not currently supported. For GovCloud tenants, use Import Config to populate the local database from the GovCloud tenant directly, then use that as the snapshot source.

**Status:** Tracked for a future release. Same-cloud pushes (commercial → commercial, GovCloud → GovCloud) are unaffected.

---

### SDK known issues (zscaler-sdk-python)

The following SDK limitations affect this project. Workarounds are in place for each and will be revisited as the SDK is updated.

#### ZIA — Browser Isolation `profileSeq` missing (`lib/zia_client.py`)
`CBIProfileAPI.list_profiles()` returns objects that omit the `profileSeq` field. This field is required to set `smartIsolationProfileId` when remapping CBI profiles cross-tenant. Workaround: `list_browser_isolation_profiles()` uses direct HTTP against `/zia/api/v1/browserIsolation/profiles`.

#### ZIA — URL Categories lite endpoint missing (`lib/zia_client.py`)
The SDK has no `/urlCategories/lite` equivalent. Workaround: `list_url_categories_lite()` uses direct HTTP.

#### ZCC — `download_disable_reasons` content-type validation (`lib/zcc_client.py`)
`DevicesAPI.download_disable_reasons()` raises if the API response `Content-Type` is not `application/octet-stream` and the CSV header does not start with `"User","Device type"`. The actual response columns are `User, UDID, Platform, Service, Disable Time, Disable Reason`. Workaround: `download_disable_reasons()` uses direct HTTP and writes raw bytes.

#### ZCC — Entitlement update methods accept no payload (`lib/zcc_client.py`)
`EntitlementAPI.update_zpa_group_entitlement()` and `update_zdx_group_entitlement()` send an empty body (`{}`). Workaround: `update_zpa_entitlements()` / `update_zdx_entitlements()` use direct HTTP PUT with the actual payload.

#### ZIdentity — Password and MFA endpoints not in SDK (`lib/zidentity_client.py`)
`reset_password`, `update_password`, and `skip_mfa` are not implemented in the SDK. Workaround: direct HTTP against `/ziam/admin/api/v1/users/{id}:resetpassword`, `:updatepassword`, and `:setskipmfa`. (Path updated from `/zidentity/api/v1` in v1.0.19 to match the 1.9.21 SDK migration.)

#### ZDX — `get_device_apps` / `get_device_app` model deserialization (`lib/zdx_client.py`)
Both endpoints return a plain JSON array, but the SDK passes the entire array to `DeviceActiveApplications` as a single object, causing all fields (`id`, `name`, `score`) to deserialize as `None`. Workaround: `list_device_apps()` and `get_device_app()` use `resp.get_body()` to access the raw response directly, bypassing the broken model.

#### ZDX — `list_devices` / `list_users` wrapped responses (`lib/zdx_client.py`)
Both methods return a single-element list containing a wrapper object (`Devices` / `ActiveUsers`) rather than iterating the item list. Workaround: unwrap via `result[0].devices` and `result[0].users` respectively before returning.
