# zs-config

[![PyPI](https://img.shields.io/pypi/v/zs-config)](https://pypi.org/project/zs-config/)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

Automation toolset for Zscaler OneAPI — interactive TUI with a local DB cache for fast lookups and bulk operations.

---

## Features

- **Interactive TUI** — Rich terminal UI with a persistent banner, full-screen scrollable table views, and keyboard-driven navigation
- **ZPA** — App Connectors (list/search/enable-disable/rename/delete), Connector Groups (full CRUD), Application Segments (list/search/enable-disable/bulk-create from CSV), App Segment Groups (list/search), Access Policy (list/search), PRA Portals (full CRUD), PRA Consoles (list/search/enable-disable/delete), Service Edges (list/search/enable-disable), Certificate Management (upload/rotate/delete)
- **ZPA Config Import** — pull a full snapshot of 25 resource types into a local SQLite cache for fast lookups
- **ZIA** — URL Filtering (list/search/enable-disable), URL Categories (list/search/add-remove URLs), Security Policy Settings (allowlist/denylist view and edit), URL Lookup, Firewall Policy (L4 rules, DNS filter rules, IPS rules), SSL Inspection (list/search/enable-disable), Traffic Forwarding (list/search), Locations (list/search), Users (list/search), DLP Engines (full CRUD + JSON import), DLP Dictionaries (full CRUD + JSON/CSV import), DLP Web Rules (list/search/view), Cloud Applications (list/search policy and SSL-policy apps), Cloud App Control (full CRUD by rule type), **Apply Baseline from JSON** (fresh import → delta detection → push only changed/new resources; ID remapping for cross-tenant pushes), Policy Activation
- **ZIA Config Import** — pull a full snapshot of 35 resource types into a local SQLite cache
- **ZCC Device Management** — list, search, and view enrolled devices; soft and force remove; OTP lookup; app profile password lookup; CSV exports for devices and service status
- **ZCC Config Import** — sync devices, trusted networks, forwarding profiles, and admin users into a local SQLite cache
- **ZCC Configuration** — Trusted Networks (list/search), Forwarding Profiles (list/search), Admin Users (list/search), Entitlements (view and manage ZPA and ZDX group access)
- **ZDX** — Device lookup and health metrics, app performance on device, user lookup, application scores, deep trace management (list/start/view/stop)
- **ZIdentity User Management** — list and search users; full profile with group membership and service entitlements; reset password, set password, and skip MFA
- **ZIdentity Group Management** — list and search groups; view members; add and remove users
- **ZIdentity API Client Management** — list and search clients; view details and scopes; manage secrets with expiry; delete clients
- **Config Snapshots** — save, compare (field-level diff), export, and delete point-in-time snapshots for ZPA and ZIA
- **Audit Log** — immutable record of every operation with local-timezone timestamps
- **Zero-config encryption** — tenant secrets encrypted at rest; key auto-generated on first launch

---

## Architecture

```
zs-config/
│
├── lib/               # Low-level API clients
│   ├── auth.py          # OAuth2 client_credentials token manager
│   ├── zpa_client.py    # ZPA API methods
│   ├── zia_client.py    # ZIA API methods
│   ├── zcc_client.py        # ZCC API methods
│   ├── zdx_client.py        # ZDX API methods (direct HTTP — no SDK module)
│   ├── zidentity_client.py  # ZIdentity API methods
│   └── conf_writer.py       # zscaler-oneapi.conf writer (chmod 600)
│
├── db/                # Database layer (SQLAlchemy + SQLite by default)
│   ├── models.py      # TenantConfig, AuditLog, Certificate, ZPAResource, ZIAResource, ZCCResource, SyncLog, RestorePoint
│   └── database.py    # Engine setup, session context manager, auto-migrations
│
├── services/          # Business logic — shared by CLI and API
│   ├── config_service.py        # Tenant CRUD with encrypted secret storage
│   ├── audit_service.py         # Operation audit logging
│   ├── zpa_service.py           # ZPA workflows (cert rotation, etc.)
│   ├── zpa_import_service.py    # ZPA config import (25 resource types)
│   ├── zpa_segment_service.py   # App segment bulk-create logic
│   ├── zia_service.py           # ZIA workflows
│   ├── zia_import_service.py    # ZIA config import (35 resource types)
│   ├── zia_push_service.py      # ZIA baseline push engine (multi-pass, ID remap)
│   ├── zcc_service.py           # ZCC workflows (device management, secrets)
│   ├── zcc_import_service.py    # ZCC config import (devices, networks, profiles, admins)
│   ├── zdx_service.py           # ZDX workflows (device health, deep trace)
│   └── zidentity_service.py     # ZIdentity workflows (users, groups, API clients)
│
├── cli/               # Interactive Rich TUI
│   ├── zscaler-cli.py
│   ├── banner.py
│   ├── session.py
│   ├── scroll_view.py     # Full-screen scrollable table viewer
│   └── menus/
│       ├── main_menu.py   # Main menu, settings, audit log viewer
│       ├── zpa_menu.py         # ZPA menus
│       ├── zia_menu.py         # ZIA menus
│       ├── zcc_menu.py         # ZCC menus
│       ├── zdx_menu.py         # ZDX menus
│       └── zidentity_menu.py   # ZIdentity menus
│
├── api/               # FastAPI REST API (future GUI backend)
│
└── data/              # SQLite database (git-ignored)
    └── zscaler.db
```

---

## Installation

### Recommended — pipx (isolated, `zs-config` available system-wide)

```bash
pipx install zs-config
```

### Alternative — pip

```bash
pip install zs-config
```

Then launch from anywhere:

```bash
zs-config
```

On first launch an encryption key is generated automatically and saved to `~/.config/zs-config/secret.key`. No manual setup required.

Go to **Settings → Add Tenant** to register your first Zscaler tenant, then **ZIA → Import Config** or **ZPA → Import Config** to pull your tenant's configuration into the local cache.

> **Key override:** set `ZSCALER_SECRET_KEY` in your environment to use a specific Fernet key instead of the auto-generated one.

> **Database override:** set `ZSCALER_DB_URL` to use PostgreSQL or another SQLAlchemy-compatible database instead of the default SQLite file (`~/.local/share/zs-config/zscaler.db`).

---

## Development Setup

```bash
git clone https://github.com/mpreissner/zs-config.git
cd zs-config
pip install -e .
zs-config
```

---

## CLI Reference

### Main Menu

| Option | Description |
|---|---|
| ZIA | Zscaler Internet Access management |
| ZPA | Zscaler Private Access management |
| ZCC | Zscaler Client Connector management |
| ZDX | Zscaler Digital Experience — device health, app performance, deep trace |
| ZIdentity | User, group, and API client management |
| Switch Tenant | Switch active tenant (shows current tenant name) |
| Settings | Add / list / remove tenants; clear imported data |
| Audit Log | Scrollable viewer of all recorded operations |
| Exit | Quit |

---

### ZPA Menu

Entries are grouped into labeled sections.

**Infrastructure**

| Option | Description |
|---|---|
| App Connectors | List, search, enable/disable, rename, and delete App Connectors; full CRUD for Connector Groups |
| Service Edges | List, search, and enable/disable Service Edges |

**Applications**

| Option | Description |
|---|---|
| Application Segments | List, search, enable/disable, and bulk create from CSV |
| App Segment Groups | List and search Segment Groups |

**Policy**

| Option | Description |
|---|---|
| Access Policy | List and search access policy rules |

**PRA**

| Option | Description |
|---|---|
| Privileged Remote Access | PRA Portals (full CRUD) and PRA Consoles (list/search/enable-disable/delete) |

**Certificates**

| Option | Description |
|---|---|
| Certificate Management | List, rotate, and delete certificates |

**Bottom section**

| Option | Description |
|---|---|
| Import Config | Pull a full ZPA config snapshot (25 resource types) into the local DB |
| Config Snapshots | Save, compare, export, and delete point-in-time config snapshots |
| Reset N/A Resource Types | Clear the list of auto-disabled resource types so they are retried on the next import |

---

### ZPA — Import Config

Fetches 25 resource types from your ZPA tenant and stores each as a `ZPAResource` row in the local DB. Uses SHA-256 comparison so re-runs only write rows whose content has changed.

Resource types that return 401 (not entitled for your tenant) are automatically recorded as N/A and skipped on subsequent imports. Use **Reset N/A Resource Types** if your entitlements change.

**Run Import Config before using any feature that reads from the local DB** (List Segments, Search by Domain, Bulk Create dependency resolution, etc.).

---

### ZPA — Application Segments

| Option | Description |
|---|---|
| List Segments | Scrollable table of all imported segments — filter by All / Enabled / Disabled |
| Search by Domain | Find segments by FQDN substring match |
| Enable / Disable | Spacebar multi-select; enable or disable any number of segments in one operation |
| Bulk Create from CSV | Import new segments from a CSV file (see below) |
| Export CSV Template | Write a ready-to-edit template to disk |
| CSV Field Reference | In-tool scrollable reference for every CSV column |

#### Enable / Disable

Use **Space** to select one or more segments (current state shown as ✓/✗), then choose Enable or Disable. The local DB is updated immediately after each successful API call — no re-import needed.

---

### ZPA — Bulk Create from CSV

The workflow runs in stages:

1. **Parse & validate** — checks required fields and port format; invalid rows are shown with specific error messages. You can abort or skip invalid rows and continue.
2. **Dry run** — resolves segment group and server group names against the local DB. Each row is tagged:
   - `READY` — all dependencies found, will be created
   - `MISSING_DEPENDENCY` — a segment group or server group name was not found in the DB
3. **Fix missing groups** *(optional)* — create missing segment groups and server groups directly from the CLI. A targeted re-import runs automatically so the new groups are available immediately. Server groups created this way have no connector groups assigned — assign them in the ZPA portal afterwards.
4. **Confirm & create** — shows a count of READY rows. Confirm to proceed.
5. **Progress bar** — segments are created one at a time; failures are collected without aborting the batch.
6. **Summary** — `✓ Created X  ✗ Failed Y  — Skipped Z` with per-row error details for failures.
7. **Re-import** — newly created segments are synced into the local DB automatically.

Every created resource is written to the audit log.

---

### CSV Format

Use **Export CSV Template** to get a pre-filled starting point, or build your own. The in-tool **CSV Field Reference** lists every column with accepted values and defaults.

#### Required columns

| Column | Description |
|---|---|
| `name` | Segment name — must be unique within the tenant |
| `domain_names` | Semicolon-separated FQDNs, e.g. `app.example.com;*.internal.example.com` |
| `segment_group` | Exact name of an existing Segment Group (must be in local DB) |
| `server_groups` | Semicolon-separated Server Group names, e.g. `SG-East;SG-West` |
| `tcp_ports` | Required if `udp_ports` is blank — see port format below |
| `udp_ports` | Required if `tcp_ports` is blank — see port format below |

#### Optional columns

| Column | Default | Accepted values |
|---|---|---|
| `description` | *(blank)* | Any string |
| `enabled` | `true` | `true` / `false` |
| `app_type` | *(blank)* | Leave blank for standard segments. `BROWSER_ACCESS` \| `SIPA` \| `INSPECT` \| `SECURE_REMOTE_ACCESS` — only applies to clientless/browser-based types |
| `bypass_type` | `NEVER` | `NEVER` \| `ALWAYS` \| `ON_NET` |
| `double_encrypt` | `false` | `true` / `false` |
| `health_check_type` | `DEFAULT` | `DEFAULT` \| `NONE` |
| `health_reporting` | `ON_ACCESS` | `NONE` \| `ON_ACCESS` \| `CONTINUOUS` |
| `icmp_access_type` | `NONE` | `NONE` \| `PING` \| `PING_TRACEROUTING` |
| `passive_health_enabled` | `true` | `true` / `false` |
| `is_cname_enabled` | `true` | `true` / `false` |
| `select_connector_close_to_app` | `false` | `true` / `false` |

#### Port format

| Example | Meaning |
|---|---|
| `443` | Single port |
| `8080-8090` | Range (inclusive) |
| `80;443;8080-8090` | Multiple entries, semicolon-separated |

---

### ZPA — Certificate Management

| Option | Description |
|---|---|
| List Certificates | Show all certificates in the tenant |
| Rotate Certificate for Domain | Provide an existing cert and key file — the tool uploads the new cert to ZPA, updates all matching App Segments and PRA Portals, and deletes the old cert |
| Delete Certificate | Remove a certificate by selection |

---

### ZIA Menu

Entries are grouped into labeled sections.

**Web & URL Policy**

| Option | Description |
|---|---|
| URL Filtering | List, search, and enable/disable URL filtering rules |
| URL Categories | List and search custom categories; add and remove URLs per category |
| Security Policy Settings | View, add to, and remove URLs from the global allowlist and denylist |
| URL Lookup | Look up the category classification of one or more URLs |

**Network Security**

| Option | Description |
|---|---|
| Firewall Policy | List, search, and enable/disable L4 Firewall Rules, DNS Filter Rules, and IPS rules |
| SSL Inspection | List, search, and enable/disable SSL inspection rules |
| Traffic Forwarding | List and search forwarding rules |

**Identity & Access**

| Option | Description |
|---|---|
| Users | List and search users |
| Locations | List and search locations; list location groups |

**DLP**

| Option | Description |
|---|---|
| DLP Engines | List, search, view details, create from JSON file, edit from JSON file, delete |
| DLP Dictionaries | List, search, view details, create from JSON or CSV file, edit, delete |

**Cloud Apps**

| Option | Description |
|---|---|
| Cloud Applications | List and search apps associated with DLP/CAC policy rules or SSL policy rules |
| Cloud App Control | Full CRUD for web application rules, grouped by rule type (AI & ML, Webmail, Streaming Media, etc.) |

**Bottom section**

| Option | Description |
|---|---|
| Activation | View activation status; push pending ZIA policy changes |
| Import Config | Pull a full ZIA config snapshot (27 resource types) into the local DB |
| Config Snapshots | Save, compare, export, and delete point-in-time config snapshots |
| Reset N/A Resource Types | Clear the list of auto-disabled resource types so they are retried on the next import |

---

### ZCC Menu

Entries are grouped into labeled sections.

**Devices**

| Option | Description |
|---|---|
| Devices | List, search by username, view details, soft remove, force remove |

**Device Credentials**

| Option | Description |
|---|---|
| OTP Lookup | Fetch a one-time password for a specific device UDID |
| App Profile Passwords | Look up profile passwords for a user/OS combination |

**Configuration**

| Option | Description |
|---|---|
| Trusted Networks | List and search defined trusted networks (DNS servers and search domains) |
| Forwarding Profiles | List and search forwarding profiles |
| Admin Users | List and search ZCC admin users |
| Entitlements | View and manage ZPA and ZDX group access entitlements |

**Bottom section**

| Option | Description |
|---|---|
| Export Devices CSV | Download enrolled device list as CSV, filterable by OS and registration state |
| Export Service Status CSV | Download per-device service status as CSV, same filters |
| Import Config | Sync devices, trusted networks, forwarding profiles, and admin users into the local DB |
| Reset N/A Resource Types | Clear the list of auto-disabled resource types so they are retried on the next import |

#### Devices submenu

| Option | Description |
|---|---|
| List Devices | Paginated table filtered by OS type (iOS / Android / Windows / macOS / Linux) |
| Search by Username | Filter device list by username |
| Device Details | Full device record by username or UDID |
| Soft Remove Device | Mark device as Removal Pending — unenrolled on next connection |
| Force Remove Device | Immediately remove a Registered or Removal Pending device |

---

### ZDX Menu

Time window is selected on entry (Last 2 / 4 / 8 / 24 hours) and applied to all data queries.

**Device Analytics**

| Option | Description |
|---|---|
| Device Lookup & Health | Search by hostname or email; select device; view health metrics and events table |
| App Performance on Device | Search device → select app → view score and metric trend |

**Users**

| Option | Description |
|---|---|
| User Lookup | Search by email or name; view associated devices and per-device ZDX score |

**Applications**

| Option | Description |
|---|---|
| Application Scores | List all monitored apps with ZDX scores (color-coded) |

**Diagnostics**

| Option | Description |
|---|---|
| Deep Trace | List active traces; start new trace (device + optional app + session name); view results; stop trace |

---

### ZIdentity Menu

| Option | Description |
|---|---|
| Users | List, search, view details, reset password, set password, skip MFA |
| Groups | List, search, view members, add/remove users |
| API Clients | List, search, view details and secrets, add/delete secrets, delete client |

#### Users

| Option | Description |
|---|---|
| List Users | Full user list (up to 500) |
| Search Users | Filter by login name, display name, or email (partial match on each) |
| User Details | Profile panel with group membership and service entitlements |
| Reset Password | Trigger a password reset for the selected user |
| Set Password | Set a specific password; option to force reset on next login |
| Skip MFA | Bypass MFA for 1 / 4 / 8 / 24 / 72 hours |

#### Groups

| Option | Description |
|---|---|
| List Groups | All groups with type (Static / Dynamic) |
| Search Groups | Filter by name (partial match) |
| Group Members | View all members of a selected group |
| Add User to Group | Two-step: pick group → pick user |
| Remove User from Group | Pick group → pick from current members |

#### API Clients

| Option | Description |
|---|---|
| List API Clients | All clients with status |
| Search API Clients | Filter by name (partial match) |
| Client Details & Secrets | Profile panel (name, status, scopes, token lifetime) plus secrets list |
| Add Secret | Generate a new secret with optional expiry; secret value shown once |
| Delete Secret | Pick from existing secrets by ID and expiry |
| Delete API Client | Permanently remove a client |

---

### Settings

| Option | Description |
|---|---|
| Add Tenant | Register a new Zscaler tenant (vanity domain, client ID/secret, ZPA customer ID) |
| List Tenants | Show all configured tenants |
| Remove Tenant | Delete a tenant and its encrypted credentials |
| Clear Imported Data & Audit Log | Delete all imported resources, sync logs, and audit entries (tenant config is preserved) |

---

### Audit Log

Displays up to 500 recent operations in a scrollable full-screen viewer. Timestamps are shown in the local timezone of the machine running the tool.

**Navigation:** ↑↓ / j k one line · PageDown/PageUp half page · g/G top/bottom · q exit

---

## Database

SQLite by default at `data/zscaler.db` (git-ignored). Override with:

```bash
export ZSCALER_DB_URL="postgresql://user:pass@host/dbname"
```

| Table | Contents |
|---|---|
| `TenantConfig` | Connection details per Zscaler tenant (client secret encrypted at rest) |
| `AuditLog` | Immutable record of every operation performed |
| `Certificate` | Lifecycle tracking for certs managed by this toolset |
| `ZPAResource` | Full JSON snapshot of every ZPA resource (`tenant × type × id`); SHA-256 hash enables fast change detection on re-import |
| `ZIAResource` | Full JSON snapshot of every ZIA resource (`tenant × type × id`); same SHA-256 change-detection pattern as ZPA |
| `ZCCResource` | Full JSON snapshot of every ZCC resource (`tenant × type × id`); same SHA-256 change-detection pattern |
| `SyncLog` | Outcome of each import run (status, counters, errors) — shared by ZPA, ZIA, and ZCC imports |
| `RestorePoint` | Point-in-time config snapshots for pre/post-change diffing and export |

---

## Encryption Key

Tenant secrets are encrypted with [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption.

- **Auto-managed:** on first launch a key is generated and saved to `~/.config/zs-config/secret.key` (chmod 600)
- **Env var override:** set `ZSCALER_SECRET_KEY` to use a specific key
- **Rotation:** rotating the key makes previously saved tenant secrets unreadable — re-add tenants after rotating

---

## Extending

- **New ZPA endpoint** → add a method to `lib/zpa_client.py`
- **New CLI menu** → add a file under `cli/menus/`, wire into `main_menu.py`
- **New product** (ZDX, ZTW, etc.) → add `lib/<product>_client.py` + `services/<product>_service.py` + `cli/menus/<product>_menu.py`; add a `get_<product>_client()` factory to `cli/menus/__init__.py`
- **Reusable table view** → call `scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())` from `cli/scroll_view.py` and `cli/banner.py`
