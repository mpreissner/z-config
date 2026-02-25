# z-config

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

Automation toolset for Zscaler OneAPI — interactive TUI with a local DB cache for fast lookups and bulk operations.

---

## Features

- **Interactive TUI** — Rich terminal UI with a persistent banner, full-screen scrollable table views, and keyboard-driven navigation
- **ZPA Application Segments** — list, search, bulk enable/disable, and bulk create from CSV with dry-run and dependency resolution
- **ZPA Certificate Management** — upload, rotate across all matching resources, and delete certificates
- **ZPA Connectors** — list, search, enable/disable, rename, and delete App Connectors; full CRUD for Connector Groups
- **ZPA Privileged Remote Access** — PRA Portal list, search, create, enable/disable, and delete
- **ZPA Config Import** — pull a full snapshot of 18 resource types into a local SQLite cache for fast lookups
- **ZIA Firewall Policy** — list, search, and enable/disable L4 Firewall Rules and DNS Filter Rules; IPS subscription-awareness
- **ZIA Locations** — list and search locations and location groups
- **ZIA SSL Inspection** — list, search, and enable/disable SSL inspection rules
- **ZIA Config Import** — pull a full snapshot of 19 resource types into a local SQLite cache
- **Audit Log** — immutable record of every operation with local-timezone timestamps
- **Zero-config encryption** — tenant secrets encrypted at rest; key auto-generated on first launch

---

## Architecture

```
z-config/
│
├── lib/               # Low-level API clients
│   ├── auth.py          # OAuth2 client_credentials token manager
│   ├── zpa_client.py    # ZPA API methods
│   ├── zia_client.py    # ZIA API methods
│   └── conf_writer.py   # zscaler-oneapi.conf writer (chmod 600)
│
├── db/                # Database layer (SQLAlchemy + SQLite by default)
│   ├── models.py      # TenantConfig, AuditLog, Certificate, ZPAResource, SyncLog
│   └── database.py    # Engine setup, session context manager
│
├── services/          # Business logic — shared by CLI and API
│   ├── config_service.py        # Tenant CRUD with encrypted secret storage
│   ├── audit_service.py         # Operation audit logging
│   ├── zpa_service.py           # ZPA workflows (cert rotation, etc.)
│   ├── zpa_import_service.py    # ZPA config import (pulls live config into DB)
│   ├── zpa_segment_service.py   # App segment bulk-create logic
│   ├── zia_service.py           # ZIA workflows
│   └── zia_import_service.py    # ZIA config import (pulls live config into DB)
│
├── cli/               # Interactive Rich TUI
│   ├── zscaler-cli.py
│   ├── banner.py
│   ├── session.py
│   ├── scroll_view.py     # Full-screen scrollable table viewer
│   └── menus/
│       ├── main_menu.py   # Main menu, settings, audit log viewer
│       ├── zpa_menu.py    # ZPA menus
│       └── zia_menu.py    # ZIA menus
│
├── api/               # FastAPI REST API (future GUI backend)
│
└── data/              # SQLite database (git-ignored)
    └── zscaler.db
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Launch the CLI

```bash
python cli/z_config.py
```

On first launch an encryption key is generated automatically and saved to `~/.config/zscaler-cli/secret.key`. No manual setup required.

Go to **Settings → Manage Tenants → Add Tenant** to register your first Zscaler tenant, then **ZPA → Import Config** to pull your tenant's configuration into the local cache.

> **Key override:** set `ZSCALER_SECRET_KEY` in your environment to use a specific Fernet key instead of the auto-generated one.

> **Database override:** set `ZSCALER_DB_URL` to use PostgreSQL or another SQLAlchemy-compatible database instead of the default SQLite file.

---

## CLI Reference

### Main Menu

| Option | Description |
|---|---|
| ZPA | Zscaler Private Access management |
| ZIA | Zscaler Internet Access management |
| Switch Tenant | Change the active tenant for the session |
| Settings | Tenant management, encryption key, credentials file, data reset |
| Audit Log | Scrollable viewer of all recorded operations |
| Exit | Quit |

---

### ZPA Menu

| Option | Description |
|---|---|
| Application Segments | Segment list, search, enable/disable, bulk create; App Segment Groups *(coming soon)* |
| Certificate Management | List, rotate, and delete certificates |
| Connectors | List, search, enable/disable, rename, and delete App Connectors; full CRUD for Connector Groups |
| Privileged Remote Access | PRA Portals — list, search, create, enable/disable, delete; PRA Consoles *(coming soon)* |
| Access Policy | *(coming soon)* |
| Import Config | Pull a full ZPA config snapshot into the local DB |
| Reset N/A Resource Types | Clear the list of auto-disabled resource types so they are retried on the next import |

---

### ZPA — Import Config

Fetches 18 resource types from your ZPA tenant and stores each as a `ZPAResource` row in the local DB. Uses SHA-256 comparison so re-runs only write rows whose content has changed.

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

| Option | Description |
|---|---|
| SSL Inspection | List, search, and enable/disable SSL inspection rules |
| Locations | List and search locations; list location groups |
| Firewall Policy | List, search, and enable/disable L4 Firewall Rules and DNS Filter Rules; IPS subscription-awareness |
| URL Lookup | Look up the category classification of one or more URLs |
| Security Policy Settings | *(coming soon)* |
| URL Categories | *(coming soon)* |
| URL Filtering | *(coming soon)* |
| Traffic Forwarding | *(coming soon)* |
| Activation | View activation status; push pending ZIA policy changes |
| Import Config | Pull a full ZIA config snapshot (19 resource types) into the local DB |
| Reset N/A Resource Types | Clear the list of auto-disabled resource types so they are retried on the next import |

---

### Settings

| Option | Description |
|---|---|
| Manage Tenants | Add, list, or remove tenants |
| Generate Encryption Key | Rotate the Fernet key — **warning: invalidates all saved tenant secrets** |
| Configure Server Credentials File | Write `zscaler-oneapi.conf` (chmod 600) for use with server-side tooling |
| Clear Imported Data & Audit Log | Delete all ZPA resources, sync logs, and audit entries (tenant config is preserved) |

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
| `SyncLog` | Outcome of each import run (status, counters, errors) — shared by ZPA and ZIA imports |

---

## Encryption Key

Tenant secrets are encrypted with [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption.

- **Auto-managed:** on first launch a key is generated and saved to `~/.config/z-config/secret.key` (chmod 600)
- **Env var override:** set `ZSCALER_SECRET_KEY` to use a specific key
- **Rotation:** go to **Settings → Generate Encryption Key** — warning: rotating the key makes previously saved tenant secrets unreadable; re-add tenants after rotating

---

## Extending

- **New ZPA endpoint** → add a method to `lib/zpa_client.py`
- **New CLI menu** → add a file under `cli/menus/`, wire into `main_menu.py`
- **New product** (ZCC, ZDX, etc.) → add `lib/<product>_client.py` + `services/<product>_service.py`
- **Reusable table view** → call `scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())` from `cli/scroll_view.py` and `cli/banner.py`
