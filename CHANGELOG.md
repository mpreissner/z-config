# Changelog

All notable changes to this project will be documented in this file.

---

## [0.8.0] - 2026-02-27

### Changed

#### ZIA — Apply Baseline: delta-only push strategy
- Before pushing anything, a full ZIA import is now run against the target tenant
  to capture its current state
- Each baseline entry is compared (after stripping read-only fields such as
  `id`, `lastModifiedTime`, etc.) to the freshly imported record:
  - **Identical** → skipped; no API call made
  - **Changed** → updated directly using the known target ID
  - **Not found** → created
- Eliminates redundant pushes of unchanged resources (e.g. all 110 predefined
  URL categories that exist in every tenant were previously pushed and 409'd on
  every run)
- `SKIP_IF_PREDEFINED` covers `url_category`, `dlp_engine`, `dlp_dictionary`,
  `network_service` — predefined resources in these types are always skipped
  regardless of content; Zscaler manages their lifecycle independently
- Push classification is now done upfront; `_push_one` no longer uses speculative
  create → 409 → name-lookup for known resources (409 fallback kept as safety net
  for edge cases where the import snapshot is stale)
- Menu prompt updated: "Import target state + push deltas" — shows import progress
  (`Syncing: <type> N/M`) followed by push progress (`[Pass N] <type> — <name>`)
  in a single combined status display

### Added

#### ZIA — Import Gaps Filled (27 → 35 resource types)
- `dlp_web_rule` — DLP Web Rules via `zia.dlp_web_rules.list_rules()`
- `nat_control_rule` — NAT Control Policy via `zia.nat_control_policy.list_rules()`
- `bandwidth_class` — Bandwidth Classes via `zia.bandwidth_classes.list_classes()`
- `bandwidth_control_rule` — Bandwidth Control Rules via `zia.bandwidth_control_rules.list_rules()`
- `traffic_capture_rule` — Traffic Capture Rules via `zia.traffic_capture.list_rules()`
- `workload_group` — Workload Groups via `zia.workload_groups.list_groups()`
- `network_app` — Network Apps (read-only) via `zia.cloud_firewall.list_network_apps()`
- `network_app_group` — Network App Groups via `zia.cloud_firewall.list_network_app_groups()`

#### ZIA — DLP Web Rules submenu
- New **DLP Web Rules** entry under the `── DLP ──` section
- Submenu: List All (ordered by policy order), Search by Name, View Details (JSON scroll view)

#### ZIA — Apply Baseline from JSON (Push)
- New `── Baseline ──` section in the ZIA menu with **Apply Baseline from JSON**
- Reads a ZIA snapshot export JSON (must have `product: "ZIA"` and `resources` key)
- Shows a summary table (resource type | count) before pushing
- Runs ordered passes with retry until the error set stabilises
- On HTTP 409: looks up existing resource by name in the target env and updates it
- ID remapping: as objects are created/located, a `source_id → target_id` table is
  built and applied to all subsequent payloads, handling cross-environment references
- Push order: rule_label → time_interval → workload_group → bandwidth_class → URL/firewall
  objects → locations → all rule types → allowlist/denylist
- Skips env-specific types: `user`, `group`, `department`, `admin_user`, `admin_role`,
  `location_group`, `network_app`, `cloud_app_policy`, `cloud_app_ssl_policy`
- Skips predefined/system resources within `dlp_engine`, `dlp_dictionary`,
  `url_category`, `network_service`
- Allowlist/denylist: merge only (add entries, never replace existing list)
- Final results table: type | created | updated | skipped | failed
- Failure detail list for any resources that could not be pushed
- Prompts to activate ZIA changes if anything was created or updated

#### ZIA Client — write methods (~40 new)
New `create_*` / `update_*` / `delete_*` methods for: `rule_label`, `time_interval`,
`location`, `url_filtering_rule`, `firewall_rule`, `firewall_dns_rule`, `firewall_ips_rule`,
`ssl_inspection_rule`, `forwarding_rule`, `ip_destination_group`, `ip_source_group`,
`network_service`, `network_svc_group`, `network_app_group`, `dlp_web_rule`,
`nat_control_rule`, `bandwidth_class`, `bandwidth_control_rule`, `traffic_capture_rule`,
`workload_group`

#### New file: `services/zia_push_service.py`
- `ZIAPushService` — push engine with multi-pass retry, ID remapping, and per-record reporting
- `PushRecord` dataclass — tracks per-resource outcome (created / updated / skipped / failed)
- `PUSH_ORDER`, `SKIP_TYPES`, `SKIP_IF_PREDEFINED`, `READONLY_FIELDS` constants

---

## [0.7.0] - 2026-02-27

### Added

#### ZIA — Cloud Applications (read-only catalog)
- New `── Cloud Apps ──` section in the ZIA menu
- **Cloud Applications** — list all apps associated with DLP/CAC policy rules or SSL policy rules; search by name across either policy set; data populated via Import Config
- Table shows: app name, parent category, ID

#### ZIA — Cloud App Control (full CRUD)
- **Cloud App Control** — browse rules by rule type; type list derived from DB after import
- Per-type submenu: list rules, view details (JSON scroll view), create from JSON file, edit from JSON file, duplicate rule (prompts for new name), delete rule (with confirmation)
- All mutations audit-logged, re-sync DB automatically, and remind user to activate changes in ZIA
- Rules stored in DB via Import Config; list sorted by order/rank

#### ZIA Import (`services/zia_import_service.py`)
- Added `cloud_app_policy`, `cloud_app_ssl_policy`, and `cloud_app_control_rule` to `RESOURCE_DEFINITIONS` (import count: 24 → 27)
- `list_all_cloud_app_rules()` iterates 18 known rule types (hardcoded — SDK's `form_response_body` mangles `UPPER_SNAKE` keys via `pydash.camel_case`, making `get_rule_type_mapping()` unusable as a driver)

#### ZIA Client (`lib/zia_client.py`)
- `list_cloud_app_policy`, `list_cloud_app_ssl_policy`
- `list_all_cloud_app_rules`, `get_cloud_app_rule_types`, `list_cloud_app_rules`, `get_cloud_app_rule`
- `create_cloud_app_rule`, `update_cloud_app_rule`, `delete_cloud_app_rule`, `duplicate_cloud_app_rule`

### Fixed
- **ZCC Entitlements**: base URL corrected to `/zcc/papi/public/v1` (was `/mobileadmin/v1`); GET methods use direct HTTP against the correct endpoint
- **ZIA URL Lookup**: missing `press_any_key_to_continue` on error/empty paths caused errors to be wiped by `render_banner()` before user could read them; empty result set now handled gracefully
- **ZIA URL Lookup**: SDK method name corrected to `lookup` (was `url_lookup`); return value correctly unpacked as 2-tuple `(result, error)`

---

## [0.6.1] - 2026-02-27

### Fixed
- **ZIA — DLP Engines / Dictionaries list**: rows were sorted alphabetically by name; now sorted numerically by ZIA ID
- **ZCC Entitlements / ZDX — 401 Unauthorized**: direct-HTTP token requests (`_get_token`) were missing the `audience: https://api.zscaler.com` body parameter required by the Zscaler OneAPI token endpoint; the Postman collection's collection-level OAuth2 config reveals this as mandatory. Added to `lib/zcc_client.py` and `lib/zdx_client.py`.

---

## [0.6.0] - 2026-02-27

### Added

#### ZIA — DLP CRUD
- **DLP Engines** — list, search, view details (JSON scroll view), create from JSON file, edit from JSON file, delete; all mutations remind the user to activate changes in ZIA
- **DLP Dictionaries** — same CRUD operations plus CSV-based creation and editing; CSV format: one value per row (header optional); phrases and patterns are supported separately
- Both DLP submenus are accessible under a new `── DLP ──` section in the ZIA menu, inserted after `── Identity & Access ──`
- DB is re-synced automatically after every create/update/delete via a targeted `ZIAImportService.run(resource_types=[...])` call

#### ZIA Client (`lib/zia_client.py`)
- `get_dlp_engine`, `create_dlp_engine`, `update_dlp_engine`, `delete_dlp_engine`
- `get_dlp_dictionary`, `create_dlp_dictionary`, `update_dlp_dictionary`, `delete_dlp_dictionary`

#### ZCC — Entitlements
- **Entitlements** added to the `── Configuration ──` section of the ZCC menu
- **View ZPA / ZDX Entitlements** — fetches live data and renders a group access table (or raw JSON if structure is non-standard)
- **Manage ZPA / ZDX Group Access** — checkbox multi-select to toggle group access; confirms changes before PUT; audit-logged

#### ZCC Client (`lib/zcc_client.py`)
- OAuth2 direct-HTTP token management (same 30 s early-refresh pattern as `zidentity_client.py`)
- `get_zpa_entitlements`, `get_zdx_entitlements` — GET from `mobileadmin/v1/getZpaGroupEntitlements` and `getZdxGroupEntitlements`
- `update_zpa_entitlements`, `update_zdx_entitlements` — PUT to corresponding update endpoints

#### ZDX — Help Desk Module (new product area)
- **Main menu** — `ZDX  Zscaler Digital Experience` added between ZCC and ZIdentity
- **Time window picker** — 2 / 4 / 8 / 24 hours, shown at menu entry or per-action as needed
- **Device Lookup & Health** — hostname/email search → device picker → health metrics table + events table in a single scroll view
- **App Performance on Device** — search device → list apps with ZDX scores → optional drill into a single app for detailed JSON metrics
- **User Lookup** — email/name search → users table with device count and ZDX score
- **Application Scores** — all apps with color-coded ZDX scores (green ≥80, yellow ≥50, red <50) and affected user count
- **Deep Trace** — list traces per device; start new trace (device picker → optional app scope → session name → POST → status poll); view trace results (JSON); stop trace (DELETE)
- All READ operations audit-logged with `product="ZDX"`; CREATE/DELETE mutations audit-logged with resource details

#### New Files
- `lib/zdx_client.py` — direct-HTTP ZDX client with OAuth2 token caching
- `services/zdx_service.py` — thin service layer with audit logging
- `cli/menus/zdx_menu.py` — full ZDX TUI menu

#### Infrastructure
- `cli/menus/__init__.py` — `get_zdx_client()` factory added

---

## [0.5.0] - 2026-02-27

### Added

#### ZPA — Menu Expansion
- **App Segment Groups** — list and search from local DB cache (group name, enabled state, config space, application count)
- **PRA Consoles** — list, search, enable/disable, and delete; follows same pattern as PRA Portals
- **Service Edges** — new top-level ZPA submenu; list and search (name, group, channel status, private IP, version, enabled), enable/disable via API with immediate DB update
- **Access Policy** — replaces [coming soon] stub; list and search policy_access rules from DB cache (name, action type, description)

#### ZIA — Menu Expansion
- **Security Policy Settings** — view, add to, and remove URLs from the allowlist and denylist
- **URL Categories** — list all categories with ID, type, and URL count; search by name; add/remove custom URLs per category
- **URL Filtering** — list and search rules (order, name, action, state); enable/disable checkbox multi-select
- **Traffic Forwarding** — list and search forwarding rules (read-only DB view: name, type, description)
- **Users** — list and search from DB cache (username, email, department, group count)

#### ZCC — Menu Expansion
- **Import Config** — sync ZCC device inventory, trusted networks, forwarding profiles, and admin users into local DB
- **Reset N/A Resource Types** — clear auto-disabled ZCC resource types so they are retried on the next import
- **Trusted Networks** — list and search from DB cache (name, network ID)
- **Forwarding Profiles** — list and search from DB cache (name, profile type)
- **Admin Users** — list and search from DB cache (username, role, email)

#### Config Import Expansion (Priorities 1–2)

**ZPA** — 7 new resource types added to the import service:
`pra_console`, `service_edge_group`, `service_edge`, `server`, `machine_group`, `trusted_network`, `lss_config`

**ZIA** — 5 new resource types:
`user`, `dlp_engine`, `dlp_dictionary`, `allowlist` (singleton), `denylist` (singleton)

**ZCC** — full new import service (`services/zcc_import_service.py`):
`device`, `trusted_network`, `forwarding_profile`, `admin_user`
Auto-disables resource types on 401 or 403; `ZCCResource` DB model mirrors ZPA/ZIA pattern.

#### ZIA Client (`lib/zia_client.py`)
- `list_dlp_engines`, `list_dlp_dictionaries`
- `list_allowlist`, `list_denylist` (singleton wrappers for the import service)
- `add_to_allowlist`, `remove_from_allowlist`, `add_to_denylist`, `remove_from_denylist`
- `get_url_filtering_rule`, `update_url_filtering_rule`
- `add_urls_to_category`, `remove_urls_from_category`

#### ZPA Client (`lib/zpa_client.py`)
- `get_policy_rule`, `update_policy_rule`
- PRA Console CRUD: `list_pra_consoles`, `get_pra_console`, `create_pra_console`, `update_pra_console`, `delete_pra_console`
- `list_service_edge_groups`, `list_service_edges`, `get_service_edge`, `update_service_edge`
- `list_servers`, `list_machine_groups`, `list_trusted_networks`, `list_lss_configs`

#### ZCC Client (`lib/zcc_client.py`)
- `list_trusted_networks`, `list_forwarding_profiles`, `list_admin_users`

#### Database
- `ZCCResource` model (`db/models.py`) with `zcc_id` unique key and standard `raw_config` / `config_hash` / `is_deleted` columns
- `zcc_disabled_resources` JSON column on `TenantConfig`
- SQLite migration applied automatically on next launch

---

## [0.4.1] - 2026-02-26

### Fixed
- **ZCC — List Devices**: removed `page` query parameter from default request; the ZCC API rejected it with a 400, likely treating it as invalid for this endpoint. `pageSize` alone is sufficient.
- **ZIdentity — List Users / Groups / API Clients**: the ZIdentity SDK returns model wrapper objects (`Users`, `Groups`, `APIClients`) rather than plain lists. The shared `_to_dicts` helper tried to call `vars()` on these objects, causing `attribute name must be string, not 'int'`. Replaced with a dedicated `_zid_list` extractor that unpacks the wrapper via `as_dict()` and pulls the first list-valued field.

---

## [0.4.0] - 2026-02-26

### Added

#### ZCC — Zscaler Client Connector
- **lib/zcc_client.py** — thin SDK adapter wrapping `_sdk.zcc.devices` and `_sdk.zcc.secrets`; includes `OS_TYPE_LABELS` and `REGISTRATION_STATE_LABELS` integer-to-string mappings
- **services/zcc_service.py** — business logic layer with audit logging for all mutating and sensitive read operations
- **Devices** — list (filterable by OS type), search by username, full device detail panel (username, device name, OS, ZCC version, registration state, UDID, last seen, location)
- **Soft Remove Device** — marks device as Removal Pending; unenrolled on next ZCC connection
- **Force Remove Device** — immediately removes a Registered or Removal Pending device; extra confirmation warning
- **OTP Lookup** — fetch a one-time password by UDID; shown in a yellow panel with single-use warning
- **App Profile Password Lookup** — retrieve profile passwords (exit, logout, uninstall, per-service disable) for a user/OS combination
- **Export Devices CSV** — download enrolled device list with OS type and registration state filters
- **Export Service Status CSV** — download per-device service status with same filters

#### ZIdentity
- **lib/zidentity_client.py** — SDK adapter for `_sdk.zidentity.users`, `.groups`, `.api_client`, `.user_entitlement`; three endpoints not yet in the SDK (`resetpassword`, `updatepassword`, `setskipmfa`) implemented via direct HTTP with a cached OAuth2 token (30 s early-refresh)
- **services/zidentity_service.py** — business logic layer with audit logging for all mutating operations
- **Users — List / Search** — filterable by login name, display name, email (partial match on each)
- **User Details** — profile panel with group membership and service entitlements in a single view
- **Reset Password** — trigger a password reset for the selected user
- **Set Password** — set a specific password with optional force-reset-on-login flag
- **Skip MFA** — bypass MFA for 1 / 4 / 8 / 24 / 72 hours; converts duration to UTC Unix timestamp
- **Groups — List / Search** — with Static / Dynamic type indicator and optional dynamic-group exclusion filter
- **Group Members** — full member table for any selected group
- **Add User to Group** — two-step flow: pick group → search and pick user
- **Remove User from Group** — pick group → select from current member list
- **API Clients — List / Search** — with status, description, and ID
- **Client Details & Secrets** — profile panel (name, status, scopes, token lifetime) plus secrets table (ID, expiry)
- **Add Secret** — generate a new secret with no-expiry / 90 / 180 / 365-day options; secret value shown once in a copy-now panel
- **Delete Secret** — select by ID and expiry from the client's current secrets
- **Delete API Client** — with confirmation (default: No)

### Changed

#### CLI / UX
- Main menu: "Switch Tenant" renamed to "Tenant Management"; now opens the full tenant management submenu (add / list / remove / switch)
- "Switch Tenant" moved into the Tenant Management submenu as the first option
- Settings menu: removed "Generate Encryption Key" and "Configure Server Credentials File" options (no longer needed)

---

## [0.3.0] - 2026-02-25

### Added

#### Config Snapshots (ZPA + ZIA)
- **Save Snapshot** — captures the full local DB state for a tenant into a `restore_points` table; auto-named by timestamp, optional comment
- **List Snapshots** — scrollable table showing name, comment, resource count, and local-timezone timestamp
- **Compare Snapshot to Current DB** — field-level summary table or full JSON diff (with `+`/`-` highlighting) between any saved snapshot and the current DB state
- **Compare Two Snapshots** — same diff view between any two saved snapshots
- **Export Snapshot to JSON** — writes a portable JSON envelope (product, tenant, resources) to a user-chosen directory
- **Delete Snapshot** — with confirmation prompt
- Snapshot saves are recorded in the Audit Log
- Available under both ZPA and ZIA menus

### Changed

#### zs-config rename
- All `z-config` references updated across source, docs, and filesystem paths
- Encryption key path moved from `~/.config/z-config/secret.key` to `~/.config/zs-config/secret.key`; existing key migrated automatically on first launch
- Database path moved from `~/.local/share/z-config/zscaler.db` to `~/.local/share/zs-config/zscaler.db`; existing DB moved automatically on first launch
- Windows conf file default path updated from `%APPDATA%\z-config\` to `%APPDATA%\zs-config\`
- GitHub repository renamed to `mpreissner/zs-config`

---

## [0.2.0] - 2026-02-25

### Added

#### ZIA — Import Config
- Pulls 19 resource types from the ZIA API into a new `ZIAResource` local DB table
- SHA-256 change detection — re-runs only write rows whose content has changed
- Automatic N/A detection — resource types that return 401 or `NOT_SUBSCRIBED` (403) are skipped and recorded per tenant
- **Reset N/A Resource Types** — clear the auto-disabled list so they are retried on the next import

#### ZIA — Firewall Policy
- **List / Search Firewall Rules** — scrollable table: Order, Name, Action, State (green ENABLED / red DISABLED), Description
- **Enable / Disable Firewall Rules** — checkbox multi-select; patches `state` via API and updates local DB immediately
- **List / Search DNS Filter Rules** — same table layout as firewall rules
- **Enable / Disable DNS Rules** — checkbox multi-select
- **List / Search IPS Rules** — shows subscription-not-available message when `firewall_ips_rule` is marked N/A for the tenant

#### ZIA — Locations
- **List Locations** — scrollable table: Name, Country, Timezone, Sub-location flag, VPN flag
- **Search Locations** — partial name match
- **List Location Groups** — table: Name, Type, Location count

#### ZIA — SSL Inspection
- **List Rules** — scrollable table: Order, Name, Action (extracts `type` from nested action object), State, Description
- **Search Rules** — partial name match
- **Enable / Disable** — checkbox multi-select; patches `state` via API and updates local DB immediately

#### ZPA — Menu restructure
- **Privileged Remote Access** replaces the old "PRA Portals" top-level item — new parent submenu containing PRA Portals (active) and PRA Consoles (coming soon)
- **Access Policy** coming-soon stub added to ZPA menu
- **App Segment Groups** coming-soon stub added to the App Segments submenu

### Changed
- Main menu: ZIA moved above ZPA
- ZIA menu order: SSL Inspection → Locations → Firewall Policy → URL Lookup *(active section)* · coming-soon stubs *(middle section)* · Activation → Import Config → Reset N/A → Back *(bottom section)*

### Fixed
- SSL Inspection list/search crash — `action` field in SSL rules is a nested object; now extracts `action["type"]` for display
- ZIA Import: `url_categories` SDK method corrected (`list_categories` not `list_url_categories`); `url_filtering` corrected (`list_rules` not `list_url_filtering_rules`)
- ZIA Import: `NOT_SUBSCRIBED` (403) errors now treated identically to 401 — resource type is auto-disabled and skipped on future runs
- Admin & Roles removed from ZIA menu — the ZIA admin users endpoint returns an empty list for tenants using ZIdentity; will be revisited under the ZIdentity product area

---

## [0.1.0] - 2026-02-25

### Added

#### ZPA — Connectors
- **List Connectors** — scrollable table showing Name, Group, Control Channel Status (green if authenticated), Private IP, Version, and Enabled state
- **Search Connectors** — partial name match, same table columns
- **Enable / Disable** — checkbox multi-select; patches `enabled` via API and updates local DB immediately
- **Rename Connector** — select connector, enter new name, confirms with old → new display; updates API and local DB
- **Delete Connector** — confirmation prompt (default: No); marks `is_deleted` in local DB on success

#### ZPA — Connector Groups
- **List Connector Groups** — scrollable table showing Name, Location, member Connector count (from local DB), and Enabled state
- **Search Connector Groups** — partial name match
- **Create Connector Group** — name + optional description; targeted re-import syncs new group into local DB automatically
- **Enable / Disable Group** — checkbox multi-select; patches `enabled` via API and updates local DB immediately
- **Delete Connector Group** — API rejection (e.g. group has members) is surfaced cleanly; local DB updated only on success

#### ZPA — PRA Portals
- **List PRA Portals** — scrollable table with domain, enabled state, and certificate name
- **Search by Domain** — partial domain match
- **Create Portal** — name, domain, certificate selection from local DB, enabled flag, optional user notification
- **Enable / Disable** — checkbox multi-select
- **Delete Portal** — confirmation prompt (default: No)

### Changed
- Connectors and PRA Portals promoted from stubs into the top section of the ZPA menu (alongside Application Segments and Certificate Management)
- ZPA menu order: Application Segments → Certificate Management → Connectors → PRA Portals → *(separator)* → Import Config → Reset N/A Resource Types

---

## [0.0.2] - 2026-02-24

### Fixed
- Windows compatibility — all `chmod` / `os.chmod` calls are now guarded with `sys.platform != "win32"` so the tool runs on Windows without raising `NotImplementedError`
- Platform-aware default credentials file path — Windows now defaults to `%APPDATA%\z-config\zscaler-oneapi.conf` instead of `/etc/zscaler-oneapi.conf`

### Changed
- Entry point renamed from `cli/zscaler-cli.py` to `cli/z_config.py` to match the repository name (`z-config`)
- Encryption key path moved from `~/.config/zscaler-cli/secret.key` to `~/.config/z-config/secret.key`; existing keys at the old location are migrated automatically on first launch

---

## [0.0.1] - 2026-02-24

Initial release.

### ZPA — Application Segments
- List Segments — table view of all imported segments with All / Enabled / Disabled filter
- Search by Domain — FQDN substring search across the local DB cache
- Enable / Disable — spacebar multi-select checkbox to toggle any number of segments in a single bulk operation; local DB updated immediately after each successful API call, no re-import required
- Bulk Create from CSV — parse & validate → dry-run with dependency resolution → optional auto-create of missing segment groups and server groups → progress bar → per-row error reporting → automatic re-import of newly created segments
- Export CSV Template — writes a two-row pre-filled template to any path
- CSV Field Reference — in-tool scrollable reference listing every column, accepted values, and defaults

### ZPA — Certificate Management
- List Certificates
- Rotate Certificate for Domain — upload new PEM cert+key, update all matching app segments and PRA portals, delete the old cert
- Delete Certificate

### ZPA — Config Import
- Pulls 18 resource types from the ZPA API into the local SQLite cache
- SHA-256 change detection for fast re-imports
- Automatic N/A detection — resource types that return 401 (not entitled) are skipped and recorded per tenant

### ZIA
- Policy activation
- URL category lookup

### CLI
- Full-screen scrollable viewer for all table views — Z-Config banner pinned at top, content scrolls with ↑↓ / j k / PageDown / PageUp / g / G, status bar with row range and scroll %, q to exit
- Auto-generated encryption key on first launch — saved to `~/.config/z-config/secret.key`, no manual setup required
- Tenant management — add, list, remove; client secrets encrypted at rest with Fernet
- Audit log viewer — all operations recorded with product, operation, resource, status, and local-timezone timestamp
- Settings — manage tenants, rotate encryption key, configure server credentials file, clear imported data

