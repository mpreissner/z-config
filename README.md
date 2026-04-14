# zs-config

[![PyPI](https://img.shields.io/pypi/v/zs-config)](https://pypi.org/project/zs-config/)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

Interactive TUI for Zscaler OneAPI — manage ZPA, ZIA, ZCC, ZDX, and ZIdentity from the terminal, with a local SQLite cache for fast lookups and bulk operations.

---

## What's New — v1.0.18

- **Restore Snapshot — dedicated rollback flow** — Restore now has its own pipeline distinct from Apply Baseline. Shows a unified dry-run (creates, updates, deletes, skips) with a single confirmation, runs creates/updates first then deletes in dependency order, and performs two verification passes (creates/updates, then deletions).
- **Verify pass 1 accuracy** — resources queued for deletion are excluded from the post-push discrepancy table so the create/update result is not obscured by expected-present resources.
- **`classify_snapshot_deletes()` / `verify_deleted()`** — two new `ZIAPushService` methods powering the restore pipeline.

---

## Features

- **ZPA** — App Connectors & Connector Groups (full CRUD), Application Segments (list/search/enable-disable/bulk-create from CSV), App Segment Groups, Access Policy (list/search/export/import-sync from CSV with dry-run, bulk reorder, and orphan delete), PRA Portals & Consoles, Service Edges, Certificate Management (upload/rotate/delete), Identity & Directory (SAML Attributes, SCIM User Attributes, SCIM Groups), Policy Scoping Reference export, Apps & Groups Reference export
- **ZIA** — URL Filtering, URL Categories, Security Policy (allowlist/denylist), URL Lookup, Firewall Policy (L4 rules, DNS filter, IPS — list/search/enable-disable/export/import-sync from CSV), SSL Inspection, Traffic Forwarding, Locations, Users, DLP Engines/Dictionaries/Web Rules, Cloud App Control (full CRUD), **Apply Baseline from JSON** (wipe-first or delta push with ID remapping, cross-tenant rule ordering, scope-aware disable), Policy Activation
- **ZIA IP Groups** — Source and Destination IPv4 Groups: list, search, create, edit, delete, and bulk create from CSV
- **ZCC** — Devices (list/search/remove/OTP lookup/password lookup/CSV export), Trusted Networks, Forwarding Profiles, Admin Users, Entitlements, App Profiles (manage bypass apps/activate/delete), Bypass App Definitions
- **ZDX** — Device health, app performance, user lookup, application scores, deep trace
- **ZIdentity** — Users (list/search/reset-password/set-password/skip-MFA), Groups (list/search/members/add-remove), API Clients (list/search/secrets/delete)
- **Config Import** — 27 ZPA + 42 ZIA + 6 ZCC resource types pulled into a local SQLite cache with SHA-256 change detection
- **Config Snapshots** — save, compare (field-level diff), export, restore (ZIA only), and delete point-in-time snapshots for ZPA and ZIA
- **Audit Log** — immutable record of every operation
- **Zero-config encryption** — tenant secrets encrypted at rest; key auto-generated on first launch
- **Auto-update** — silent PyPI check on startup; shows changelog and upgrades in-place via pipx or pip
- **Plugin Manager** (`Ctrl+]`) — browse, install, and uninstall optional plugins from the private plugin repository; GitHub Device Flow OAuth with collaborator-gated access

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
├── cli/
│   ├── z_config.py    # Entry point
│   ├── banner.py
│   ├── scroll_view.py
│   ├── update_checker.py
│   └── menus/
│       ├── main_menu.py
│       ├── zpa_menu.py / zia_menu.py / zcc_menu.py / zdx_menu.py / zidentity_menu.py
│
└── api/               # FastAPI REST API (future GUI backend)
```

---

## Installation

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

**Bottom** — Activation, Import Config (37 resource types), Config Snapshots, Reset N/A Resource Types

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

### Plugin Manager

Accessed via **`Ctrl+]`** from the main menu (not listed as a visible menu item).

Plugins are pip-installable packages distributed via a private GitHub repository. Access requires a GitHub account that has been added as a collaborator on the plugin repository — contact the repository owner to request access.

**Authentication flow:**

1. Open the plugin manager (`Ctrl+]`) and select **Log in with GitHub**
2. A browser window opens — complete the Device Flow OAuth prompt (MFA supported)
3. On success, zs-config verifies your GitHub token has collaborator access to the plugin repository before saving it. If your account is not listed as a collaborator, login fails with a clear message
4. Once authenticated, **Browse available plugins** lists plugins from the manifest and offers install via pip — no SSH key or manual git configuration required

**Token storage:** `~/.config/zs-config/github_token` (chmod 600)

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

---

## Known Issues

### Smart Browser Isolation — cannot be enabled via API

**Symptom:** Pushing `browser_control_settings` with `enableSmartIsolation: true` appears to succeed (HTTP 200), but Smart Browser Isolation remains disabled on the target tenant.

**Cause:** The ZIA API accepts the payload but does not honour the `enableSmartIsolation` toggle. This is a Zscaler platform limitation — enabling Smart Browser Isolation requires a manual step in the ZIA admin console (Policy → Browser Control → Smart Isolation).

**Workaround:** After pushing a baseline that includes Smart Isolation, log in to the target tenant's ZIA admin console and enable Smart Browser Isolation manually. All other `browser_control_settings` fields (CBI profile, etc.) push correctly.

**Rule ordering:** When the source tenant has Smart Isolation enabled (and thus "Smart Isolation One Click Rule" at order 1), the push automatically detects that the rule could not be provisioned on the target and renumbers the remaining SSL Inspection rules to fill the gap — so they remain in the correct relative order starting at 1.

---

### Cross-Cloud Baseline Push — Commercial to GovCloud

**Symptom:** Pushing a commercial ZIA baseline JSON export to a GovCloud tenant (via Apply Baseline or Restore Snapshot) produces a significant number of errors and failures.

**Cause:** Under investigation. Likely contributing factors include:
- API path and payload differences between commercial and GovCloud endpoints for certain resource types
- Resource ID namespacing differences — objects referenced by ID in the commercial baseline (e.g. URL categories, IP groups, locations) may not resolve correctly against GovCloud IDs
- GovCloud-specific resource types or entitlements that have no commercial equivalent (and vice versa), causing the normalizer to generate invalid payloads

**Workaround:** Cross-cloud commercial → GovCloud baseline pushes are not currently supported. For GovCloud tenants, use Import Config to populate the local database from the GovCloud tenant directly, then use that as the baseline source.

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
`reset_password`, `update_password`, and `skip_mfa` are not implemented in the SDK. Workaround: direct HTTP against `/zidentity/api/v1/users/{id}:resetpassword`, `:updatepassword`, and `:setskipmfa`.

#### ZDX — `get_device_apps` / `get_device_app` model deserialization (`lib/zdx_client.py`)
Both endpoints return a plain JSON array, but the SDK passes the entire array to `DeviceActiveApplications` as a single object, causing all fields (`id`, `name`, `score`) to deserialize as `None`. Workaround: `list_device_apps()` and `get_device_app()` use `resp.get_body()` to access the raw response directly, bypassing the broken model.

#### ZDX — `list_devices` / `list_users` wrapped responses (`lib/zdx_client.py`)
Both methods return a single-element list containing a wrapper object (`Devices` / `ActiveUsers`) rather than iterating the item list. Workaround: unwrap via `result[0].devices` and `result[0].users` respectively before returning.
