# Changelog

All notable changes to this project will be documented in this file.

---

## [1.0.20] - 2026-04-15

### Fixed

#### ZPA Access Policy — CSV Import/Sync local DB sync
- **Reorder-only runs now trigger DB sync** — `_sync_policy_rules` previously skipped the post-mutation `ZPAImportService` call when a sync resulted in only a rule reorder (no creates/updates/deletes), leaving the local DB with stale `rule_order` values. Fixed by including `result.reordered` in the sync trigger condition.
- **DB sync failures now surfaced** — both `_sync_policy_rules` and `_bulk_create_policy_rules` now check the `SyncLog.status` returned by `ZPAImportService.run()` and display an appropriate warning or error instead of unconditionally printing success. This makes silent failures (e.g. `policy_access` auto-disabled due to a prior 401) visible to the user.

---

## [1.0.19] - 2026-04-14

### Fixed

#### ZIdentity — SDK 1.9.21 path migration
- **Updated direct HTTP base path** — `ZIdentityClient._direct_base` updated from `/zidentity/api/v1` to `/ziam/admin/api/v1` to match the ZIdentity service migration introduced in zscaler-sdk-python 1.9.21. The old path returns HTTP 401 on GovCloud and would break on commercial. Verified against both commercial and GovCloud tenants.
- **SDK floor bumped to `>=1.9.21`** — `pyproject.toml` dependency updated accordingly.

---

## [1.0.18] - 2026-04-14

### Added

#### ZIA Config Snapshots — Dedicated Restore Flow
- **Restore Snapshot redesigned** — replaced the stub that delegated to Apply Baseline with a dedicated same-tenant rollback pipeline. Key differences from Apply Baseline:
  - **Unified dry-run** — creates, updates, deletes, and skips shown together before any changes are made; single confirmation to proceed
  - **Correct execution order** — creates/updates run first, then deletes in `WIPE_ORDER` (rules before their referenced objects), eliminating dependency constraint failures
  - **Two verify passes** — pass 1 confirms creates/updates landed (with remediation offer); pass 2 confirms deleted resources are actually gone
  - **Pending-delete resources excluded from verify pass 1** — resources queued for deletion no longer appear as discrepancies after creates/updates, since they are expected to still be present at that stage
- **`classify_snapshot_deletes()`** — new `ZIAPushService` method identifying DB resources absent from the snapshot without running a redundant import
- **`verify_deleted()`** — new `ZIAPushService` method that re-imports targeted resource types and confirms deleted IDs are no longer present in the live tenant

### Known Issues (tracked for future work)

#### Cross-Cloud Baseline Push — Commercial to GovCloud
Pushing a commercial ZIA baseline JSON export to a GovCloud tenant produces errors and failures. Root causes are under investigation. Do not use Apply Baseline or Restore Snapshot for commercial → GovCloud cross-cloud pushes until this is resolved. See README Known Issues for details.

---

## [1.0.17] - 2026-04-14

### Fixed

#### ZIA Baseline Push
- **Scope-stripped rules stay DISABLED through remediation** — rules inserted as DISABLED because required scope resources (locations, groups, users, ZPA app segments) do not exist in the target tenant were being re-enabled when remediation ran. The update path now enforces `state=DISABLED` whenever scope is still stripped, matching the create-time behaviour. The rule self-heals once the admin adds the missing resource.
- **Delete dependency ordering in wipe-first mode** — `execute_deletes` now sorts by `WIPE_ORDER` so dependent rules (e.g. `url_filtering_rule`) are deleted before the objects they reference (`url_category`, `ip_source_group`). Previously, custom URL categories could fail to delete because filtering rules referencing them had not been removed yet.

### Added

#### ZIA Config Snapshots
- **Restore Snapshot** — new option in the ZIA Config Snapshots menu that applies a saved snapshot directly against its original tenant without requiring an intermediate JSON export. Reuses the full dry-run → push → verify → remediate → activate flow via the existing Apply Baseline pipeline.

### Changed

#### Startup & Tenant Switching
- **Auth check at initial launch** — selecting a tenant on first launch now runs the same credential verification, org info fetch, and subscription-change check that was previously only triggered on tenant switch.
- **Org info always displayed on activation** — the ZIA cloud, tenant ID, ZPA customer ID/cloud, and subscription retrieval status are now shown whenever a tenant is activated (launch or switch), regardless of whether the data has changed since the last check.

---

## [1.0.16] - 2026-04-06

### Fixed

#### ZPA
- **Remove stale SDK monkey-patch** — the `ServiceEdgeControllerAPI._zpa` workaround (applied when SDK 1.9.x first shipped this API) is confirmed fixed in zscaler-sdk-python 1.9.20 and has been removed.

#### ZDX
- **Migrate ZDX client to SDK** — the previous `ZDXClient` was targeting `/zdx/api/v1` which returns 404. All ZDX functionality was non-functional. Rewritten to use `sdk.zdx.*` via the OneAPI `ZscalerClient`, fixing device lookup, user lookup, app scores, and deep trace. Base URL confirmed as `/zdx/v1` against a live tenant.

### Changed

- **SDK known issues documented** — added `### SDK known issues` section to README covering all active direct-HTTP bypasses: ZIA Browser Isolation `profileSeq`, ZIA URL Categories lite, ZCC `download_disable_reasons`, ZCC entitlement updates, ZIdentity password/MFA endpoints, and ZDX model deserialization bugs.

---

## [1.0.15] - 2026-04-06

### Fixed

#### ZIA Baseline Push
- **Smart Browser Isolation — SSL Inspection rule ordering** — when the source tenant has Smart Browser Isolation enabled ("Smart Isolation One Click Rule" at order N) but the target does not (due to the API limitation), the push now detects the unprovisioned rule and renumbers the remaining SSL Inspection rules to fill the gap. Rules maintain the same relative order as the source, starting at 1.
- **Tab completion for file/path prompts** — all file and directory path prompts across ZCC, ZIA, and setup now use `questionary.path()` instead of `questionary.text()`, enabling tab-to-complete in the terminal.

---

## [1.0.14] - 2026-04-05

### Fixed

#### Security
- **Dependency updates** — bumped to secure versions: `requests>=2.33.0` (CVE-2026-25645), `zscaler-sdk-python>=1.9.20`, `cryptography>=46.0.6` (CVE-2026-34073).

---

## [1.0.13] - 2026-04-02

### Added

#### GovCloud Support
- **GovCloud tenant flag** — `TenantConfig` now has a `govcloud` boolean column. Existing tenants are unaffected (migrated to `govcloud=False`).
- **GovCloud ZIdentity URL** — `build_zidentity_url()` now accepts `govcloud=True`, producing `https://<vanity>.zidentitygov.us` instead of `.zslogin.net`.
- **GovCloud oneapi URL default** — `GOVCLOUD_ONEAPI_URL` constant (`https://api.zscalergov.net`) added to `lib/conf_writer.py`; MOD-tier confirmed. User can override at add time.
- **Add/Edit tenant prompts** — adding a GovCloud tenant prompts for confirmation, shows the correct `.zidentitygov.us` subdomain hint, and presents an editable oneapi URL. Editing an existing tenant includes a GovCloud toggle.
- **Tenant list GovCloud column** — the tenant table now shows a `"Gov"` badge for GovCloud tenants.
- **API response** — the `/api/v1/tenants` endpoint now includes `govcloud` in each tenant object.
- **ZPA GovCloud routing** — `ZPAClient` accepts `govcloud_cloud` (e.g. `ZPAGOV_US` for MOD tier) and passes it to the ZscalerClient SDK config. Value is sourced from `orgInformation.zpaTenantCloud` at tenant creation time.

#### ZIA GovCloud Import
- **Full ZIA import support for GovCloud tenants** — all 42 ZIA resource types now work against GovCloud endpoints. The `ZscalerClient` SDK is not GovCloud-aware (it builds the token URL as `{vanity}.zslogin.net`), so every SDK-backed ZIA method falls back to direct HTTP when `govcloud=True`, using the confirmed GovCloud API paths:
  - `nat_control_rule` → `/zia/api/v1/dnatRules`
  - `location_group` → `/zia/api/v1/locations/groups`
  - `cloud_app_control_rule` → `/zia/api/v1/webApplicationRules/{rule_type}`
  - `sandbox_rule` → `/zia/api/v1/sandboxRules`
  - `dlp_web_rule` → `/zia/api/v1/webDlpRules`
  - All other resource types follow standard OneAPI camelCase path conventions.
- **`zia_delete()` helper** — added to `ZIAClient` alongside the existing `zia_get/put/post` helpers; used by all GovCloud delete fallbacks.
- **Allowlist/denylist GovCloud write** — GovCloud fallbacks for `add_to_allowlist`, `remove_from_allowlist`, `add_to_denylist`, `remove_from_denylist` use GET-merge/filter-PUT against `/zia/api/v1/security` and `/zia/api/v1/security/advanced`.
- **`traffic_capture_rule`** — import correctly attempts `/zia/api/v1/trafficCaptureRules`; returns 403 on tenants without the entitlement (logged as a non-fatal error, import continues).

---

## [1.0.12] - 2026-03-27

### Added

#### ZPA — Access Policy
- **`posture_profiles` CSV column** — access policy CSV import/export now supports posture profile scoping. Values are resolved by name to the profile's `posture_udid` used in ZPA policy conditions.
- **`risk_factor_types` CSV column** — access policy CSV import/export now supports Zscaler risk score scoping. Accepted values: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` (comma-separated).
- **`scim_attributes` CSV column** — access policy CSV import/export now supports SCIM individual attribute scoping (`AttributeName=Value` format). Was previously unsupported despite being a valid ZPA condition type (`object_type: SCIM`).
- **Policy Scoping Reference export** — new "Export Policy Scoping Reference" option under the Access Policy menu. Generates a markdown file listing all available values per scoping criteria category: Client Types, Platforms, Risk Factor Types, Identity Providers, SAML Attributes, SCIM User Attributes, SCIM Groups, Machine Groups, Trusted Networks, Posture Profiles, and Country Codes.

#### ZPA — Application Segments
- **Apps & Groups Reference export** — new "Export Apps & Groups Reference" option under the App Segments menu. Generates a markdown file listing all imported Application Segments and Segment Groups with their IDs.

#### ZPA — Identity & Directory
- **SAML Attributes view** — new entry in the ZPA main menu showing all imported SAML attributes with name, IdP, and SAML attribute name.
- **SCIM User Attributes view** — new entry in the ZPA main menu showing all imported SCIM user attributes with name, IdP (resolved via DB lookup), and data type.
- **SCIM Groups view** — new entry in the ZPA main menu showing all imported SCIM groups with name and IdP (resolved via DB lookup from `idp_id`).

#### ZPA — Import
- **`posture_profile` resource type** — posture profiles are now imported and stored; uses `posture_udid` as the stored resource ID to match ZPA policy condition format.
- **`scim_attribute` resource type** — SCIM user attributes are now imported across all configured IdPs.

### Fixed

#### ZPA — Access Policy
- **SCIM_GROUP decode** — SCIM_GROUP policy condition operands always return `name: null` from the ZPA API. Decode now uses a `scim_group_map` (built from the DB, keyed by group ID) to correctly render group names as `IdpName:GroupName` in the CSV.
- **SCIM_GROUP build** — `_build_conditions` was incorrectly passing `lhs=group_id` for SCIM_GROUP conditions. Corrected to `lhs=idp_id, rhs=group_id` as required by the ZPA API.

---

## [1.0.11] - 2026-03-26

### Added

#### ZIA — Internet Access
- **`browser_control_settings` import and push** — Smart Browser Isolation settings are now imported as a resource and can be pushed cross-tenant. Includes CBI profile remapping by name and resolution of scoped users/groups.
- **One-click rule provisioning during push** — when a one-click governed rule (CIPA Compliance Rule, O365/UCaaS/Smart Isolation One Click rules) is enabled in the source but absent from the target, the push service now re-imports the affected rule types after pushing settings singletons, resolves the newly provisioned rules, and updates them in a second pass. Rules that remain absent after the re-import are marked `skipped:one_click_not_provisioned` rather than failing.

### Fixed

#### ZIA / ZPA — All Products
- **Rule list display order** — rules with negative positions (default/catch-all rules) were sorted to the top of every list. All rule list views now display positive positions ascending first, then negative positions descending, matching the Zscaler admin console order.

#### ZIA — Internet Access
- **CIPA Compliance Rule detection** — rules with `ciparule: true` are now correctly identified as Zscaler-managed and treated as read-only in the push service; their state is managed via the `enableCIPACompliance` toggle in URL/cloud app settings.
- **One-click rule state equivalence** — `toggle=OFF / rule absent` is now treated as functionally equivalent to `toggle=OFF / rule disabled`; no spurious create attempts are made for rules the target tenant has never provisioned.

---

## [1.0.10] - 2026-03-24

### Changed

#### Core
- Internal improvements.

---

## [1.0.9] - 2026-03-23

### Fixed

#### Core
- **Banner version** — version string in `cli/banner.py` was not bumped during the 1.0.8 release; corrected to stay in sync with `pyproject.toml`.

---

## [1.0.8] - 2026-03-23

### Added

#### ZCC — Zscaler Client Connector
- **Export Disable Reasons CSV** — new export option under the ZCC menu. Prompts for a required date range (`startDate`/`endDate`), optional OS type filter, and IANA timezone (applied to the "Disable Time" column). Downloads the report directly from the API and saves as CSV. Columns: User, UDID, Platform, Service, Disable Time, Disable Reason.

### Fixed

#### ZCC — Zscaler Client Connector
- **Disable Reasons endpoint** — the SDK's `download_disable_reasons` wrapper is broken: it validates the response for an unrelated CSV format and strips the date range parameters. The implementation now bypasses the SDK, using direct HTTP with the correct required parameters (`startDate`, `endDate`) and optional `Time-Zone` header.

---

## [1.0.7] - 2026-03-23

### Added

#### Core
- **Default working directory** — `~/Documents/zs-config` is created automatically on first launch. All file export and import prompts now default to this directory, so users no longer need to type a path for every operation.

#### Plugin Manager
- **Exit after plugin install or update** — installing or updating a plugin now exits zs-config immediately after success (same behaviour as the self-update flow), ensuring the updated plugin code is active on the next launch rather than requiring a manual restart.

---

## [1.0.6] - 2026-03-22

### Added

#### Plugin Manager
- **Plugin channel selection** — users can now switch between `stable` (default) and `dev` plugin channels from the Plugin Manager (Ctrl+]). The active channel is persisted in the local database. A disclaimer is shown when switching to the dev channel.
- **Dev channel manifest fetch** — when the dev channel is active, the plugin manifest is fetched from the `dev` branch of the plugin repository rather than `main`, enabling independent versioning and update detection for pre-release builds.
- **Immediate update check on channel switch** — switching channels triggers an update check inline so dev builds are offered immediately without requiring a restart.
- **App settings store** — new `app_settings` table added to the local database for persisting application-level preferences (key/value). Existing databases are updated automatically on first launch.

---

## [1.0.5] - 2026-03-21

### Security

#### Core / Plugin Manager
- **Database file permissions** — SQLite database is now created with `chmod 600` (owner read/write only). Previously world-readable (644), exposing tenant metadata, client IDs, and audit logs to other local users. Existing installations are corrected automatically on first launch after upgrade.
- **Plugin install URL validation** — install URLs from the manifest are validated against a GitHub HTTPS/SSH allowlist before being passed to pip. Arbitrary domains and local filesystem paths are rejected.
- **GitHub token removed from process listing** — token is now passed to git via a short-lived `GIT_ASKPASS` temp script rather than embedded in the install URL, preventing exposure via `ps aux` during the install window.
- **Uninstall package name validation** — package names are validated against PEP 508 before being passed to pip, preventing argument injection via malicious manifest entries.

---

## [1.0.4] - 2026-03-21

### Added

#### Plugin Manager
- **Plugin entries in main menu** — installed plugins now appear as selectable entries in the main menu, visually separated from the core product list. The menu is rebuilt on each loop iteration so plugins installed or removed via the plugin manager (Ctrl+]) are reflected immediately without a restart. Plugins that failed to load are excluded.

---

## [1.0.3] - 2026-03-17

### Added

#### Plugin Manager
- **Startup plugin update check** — on launch, after the zs-config self-update check, installed plugins are compared against the manifest in the plugin repository. If updates are available they are shown in a table and the user is offered the option to update all of them in one step. The check is skipped entirely if no plugins are installed, no GitHub token is present, or the manifest cannot be reached. If the zs-config self-update check finds a pending update, the plugin check is deferred to the next launch.

---

## [1.0.2] - 2026-03-17

### Fixed

#### Plugin Manager
- **Entry point group rename** — plugin group renamed from `zs-config.plugins` to `zs_config.plugins` to comply with the stricter `python-entrypoint-group` format validation enforced by setuptools on Python 3.14+. Plugins using the old group name will need to update their `pyproject.toml` accordingly.

---

## [1.0.1] - 2026-03-17

### Added

#### Core
- **SSL inspection support** — startup injects the OS native trust store via `truststore` so corporate SSL inspection certificates (pushed by MDM/GPO/Jamf) are automatically honoured across all HTTP clients without any user configuration. A custom CA bundle can also be placed at `~/.config/zs-config/ca-bundle.pem`; if present at startup it is set as `REQUESTS_CA_BUNDLE`.

### Fixed

#### Plugin Manager
- **Repo access gate at login** — GitHub Device Flow authentication now verifies that the authenticated user has collaborator access to the plugin repository before saving the token. Users who complete GitHub auth but are not listed as collaborators receive a clear error message at login time rather than discovering the restriction when browsing plugins.
- **SSH install URL conversion** — plugin install URLs using `git+ssh://git@github.com/` are automatically rewritten to `git+https://x-access-token:{token}@github.com/` at install time, using the already-authenticated GitHub token. Eliminates SSH host-key verification failures and SSH key requirements on machines that have never connected to GitHub.

---

## [1.0.0] - 2026-03-16

### Added

#### PAN Migration Plugin — Push Bridge
- **Programmatic baseline push from palo-tools** — `apply_baseline_menu` now accepts optional `baseline=` and `baseline_path=` kwargs so the palo-tools plugin can hand off a just-converted baseline directly, without requiring the user to navigate separately to ZIA → Apply Baseline from JSON.

### Fixed

#### ZIA — Apply Baseline from JSON
- **Within-baseline ID remap type coercion** — string-keyed source IDs (e.g. PAN object names) are now correctly coerced to integers when resolving to target-tenant IDs. Previously `_remap_value` and `_ref_resolved` preserved the string type, causing ZIA API rejections.

---

## [0.11.4] - 2026-03-16

### Added

#### Plugin Manager
- **GitHub OAuth authentication** — Device Flow OAuth (no password prompt; supports MFA) via a classic OAuth App. Token stored at `~/.config/zs-config/github_token` (chmod 600). Login/logout available from the plugin manager.
- **Plugin discovery and install** — fetches `manifest.json` from the private `mpreissner/zs-plugins` repo via GitHub API. Lists available plugins not yet installed, installs via `pip install git+...` from the manifest `install_url`.
- **Installed plugin listing** — shows currently installed plugins discovered via `zs-config.plugins` entry points.
- **Uninstall support** — uninstalls a selected plugin via `pip uninstall`.
- **Hidden `Ctrl+]` key binding** — opens the plugin manager from the main menu without exposing it as a visible menu item.
- **Cancel navigation fix** — resolved crash when selecting "← Cancel" in install/uninstall selects (questionary returning title string instead of `None` for `value=None` choices).

---

## [0.11.3] - 2026-03-16

### Added

#### ZIA — Apply Baseline from JSON
- **`device_group` cross-tenant ID remapping** — ZIA device groups (Windows, iOS, Android, etc.) now have their source IDs remapped to the corresponding target-tenant IDs at classify time using name-based lookup. Rules that reference device groups are pushed with the correct tenant-specific IDs rather than the source tenant's IDs.
- **`sandbox_rule` full support** — ZIA Behavioral Analysis (Sandbox) rules are now imported, classified, and pushed cross-tenant. The `Default BA Rule` is automatically detected and skipped (Zscaler-managed). Normalizer handles URL category remapping, time windows, location/group/department/user scope resolution, and empty-field stripping.
- **`firewall_ips_rule` ordering and normalizer** — Firewall IPS Control rules are now treated as an ordered (first-match) policy engine: creates use the insertion-point stacking mechanism, updates are processed ascending, and delta-mode updates preserve correct ordering. A full normalizer handles cross-tenant ID remapping for locations, location groups, groups, departments, users, source/dest IP groups, network services, device groups, threat categories, and ZPA app segments.
- **Post-push consistency check with auto-remediation** — after every push, the target tenant state is re-imported and re-classified against the baseline. Any remaining creates, updates, or deletes (e.g. ordering constraint failures, missed deletes) are shown in a discrepancy table. The user is offered an auto-remediation pass before being prompted to activate. The activate default reflects whether the check passed cleanly.

#### ZIA — Import Config
- **`location_lite` resource type** — predefined ZIA locations (Road Warrior, Mobile Users, etc.) are now imported from `/locations/lite` and stored in the DB. These are not exposed in the Locations menu and are never pushed cross-tenant; they exist solely so their IDs are available for reference resolution when applying a baseline to a target tenant.
- **`device_group` resource type** — ZIA device groups are now imported (41 resource types total) and stored for cross-tenant ID remapping. They are never pushed.
- **`sandbox_rule` resource type** — ZIA Behavioral Analysis rules are now imported via the SDK sandbox rules endpoint.

---

## [0.11.2] - 2026-03-16

### Added

#### ZIA — Import Config
- **`location_lite` resource type** — predefined ZIA locations (Road Warrior, Mobile Users, etc.) are now imported from `/locations/lite` and stored in the DB. These are not exposed in the Locations menu and are never pushed cross-tenant; they exist solely so their IDs are available for reference resolution when applying a baseline to a target tenant.

---

## [0.11.1] - 2026-03-14

### Changed

#### ZIA — Apply Baseline from JSON
- **Delta mode is now non-destructive** — creates and updates only; resources present in the tenant but absent from the baseline are shown in the dry-run summary as informational only, with a note to use wipe-first if removal is needed. The deferred delete confirmation step has been removed from delta mode entirely.
- **Failed deletes surface as warnings, not failures** — if a delete fails (e.g. a Zscaler-managed resource slips through classification), the result is recorded as a manual-action warning rather than a hard failure, so it appears in the Manual Action Required section instead of the Failures table.

---

## [0.11.0] - 2026-03-14

### Added

#### ZIA — Apply Baseline from JSON
- **Wipe-first push mode** — new mode selection before each baseline apply: _Wipe-first_ deletes all resources absent from the baseline before pushing (target mirrors baseline exactly); _Delta-only_ retains the existing push-then-confirm-deletes flow
- **`advanced_settings` pushed cross-tenant** — ZIA advanced settings (`/zia/api/v1/advancedSettings`) are now imported and pushed as a singleton resource in tier 2.5 (after URL categories, before rules), syncing toggles such as `logInternalIp`, `enablePolicyForUnauthenticatedTraffic`, and `blockNonCompliantHttpRequestOnHttpPorts`
- **`tenancy_restriction_profile` pushed cross-tenant** — Microsoft 365 and Google tenancy restriction profiles are imported and pushed as a tier-0 resource; `cloud_app_control_rule` entries that reference tenant profiles are now fully remapped rather than stripped
- **Scope-stripped rules inserted as DISABLED** — when a newly created rule references tenant-specific resources (locations, location groups, groups, departments, users, devices, ZPA app segments) that don't exist in the target tenant, the rule is inserted in `DISABLED` state and a manual-action warning is written to the push log and shown in the menu
- **Manual-action warnings in push log** — scope-stripped rules and other items requiring follow-up are captured in a `=== Manual Action Required ===` section of the push log file

#### ZIA — Import Config
- `advanced_settings` and `tenancy_restriction_profile` added to `RESOURCE_DEFINITIONS` (37 resource types total)

### Fixed

#### ZIA — Apply Baseline from JSON
- **Rule ordering for incremental pushes** — creates are stacked at the insertion point (descending) first; updates then move to their exact baseline positions (ascending); eliminates ordering constraint failures when rules share adjacent positions
- **DLP engine ID filter** — predefined engines (IDs 60–64, `custom_dlp_engine: false`) were incorrectly excluded from `_usable_dlp_engine_ids`; rules referencing them (e.g. PCI engine) now push with all engines intact
- **`cloud_app_control_rule` — predefined One-Click rules** — rules with `predefined: true` are provisioned by `url_filter_cloud_app_settings` and are now skipped during classification rather than failing with 404 (multiple rules share the same name across type buckets, making name-only lookup ambiguous)
- **`cloud_app_control_rule` — empty `applications` field** — rules with `applications: []` ("Any" in the UI) now omit the field entirely; sending `[]` or `["ANY"]` was rejected by the API
- **`_do_create_with_rank_fallback`** — "rank required" errors no longer trigger the rank-strip retry; only explicit "rank not allowed" errors retry without rank

### Changed
- `update_checker`: `CHANGELOG_TIMEOUT` (10 s) separated from version-check timeout (4 s); shows a message when changelog fetch times out

---

## [0.10.9] - 2026-03-13

### Added

#### Settings — Edit Tenant Metadata
- New **Edit Tenant Metadata** option in Settings menu — allows manual override of org metadata fields that are normally auto-fetched from `orgInformation`
- Editable fields: ZPA Customer ID, ZPA Tenant Cloud, ZIA Tenant ID, ZIA Cloud
- Pre-filled with current stored values; blank entry clears the field
- Introduced to handle cases where `orgInformation.zpaTenantId` returns `0` for valid tenants (confirmed Zscaler API behaviour on certain new tenants)
- `set_tenant_metadata()` added to `services/config_service.py` — unconditionally writes all four fields, unlike `update_tenant()` which skips `None` args

### Fixed

- `orgInformation.zpaTenantId` integer `0` was being stored as the string `"0"` rather than `None`; `str(0)` is truthy so the `or None` guard was bypassed — now evaluates the raw value before stringifying, in both `_fetch_and_apply_org_info` and `backfill_org_info_for_tenant`

---

## [0.10.8] - 2026-03-12

### Changed

#### ZIA — Apply Baseline from JSON
- `location` added to `SKIP_TYPES` — locations are tenant-specific (IPs must be provisioned by Zscaler per-org) and cannot be safely pushed as part of a cross-tenant golden baseline; they are now silently skipped during classification rather than attempted and failed

---

## [0.10.7] - 2026-03-12

### Fixed
- Bump version string in `cli/banner.py` and `pyproject.toml` to 0.10.7 (0.10.6 was published to PyPI without these updated)

---

## [0.10.6] - 2026-03-12

### Fixed

#### ZIA — Apply Baseline from JSON

- **`rank` now included in POST/PUT payloads** — `rank` was incorrectly listed in `READONLY_FIELDS` under a "server-assigned" assumption. ZIA requires it in all rule creates and updates. Removing it caused `"Rule must have a rank specified"` failures across `url_filtering_rule`, `firewall_rule`, `firewall_dns_rule`, `ssl_inspection_rule`, and `forwarding_rule` (21 failures)
- **`configVersion` injected from target on updates** — `configVersion` is no longer stripped globally. During classification, the target tenant's `configVersion` is stored alongside each queued update and injected into the payload before the API call. Fixes `STALE_CONFIGURATION_ERROR` on `bandwidth_control_rule` (3 failures)
- **Predefined DLP dictionaries no longer attempted as updates** — dictionaries with `predefined: true` were being queued for update when their `accessControl` was `READ_WRITE` and baseline patterns differed. The API refuses pattern edits on predefined dictionaries regardless. These are now treated as read-only and skipped (5 failures: `CUI_LEAKAGE`, `EUIBAN_LEAKAGE`, `NDIU_LEAKAGE`, `RUN_LEAKAGE`, `SSN`)
- **`CIPA Compliance Rule` added to `SKIP_NAMED`** — Zscaler reserves this name; any create or rename attempt returns `INVALID_OPERATION`. The rule is now skipped during classification (1 failure)
- **`_classify_error` false-positive on resource IDs containing "403"** — error classification previously used bare substring matching (`"403" in exc_str`), which matched resource IDs like `/firewallFilteringRules/326403` in SSL/connection error strings. Errors are now classified permanent only when the ZIA JSON payload contains `"status": 400/403/404`. SSL and connection errors are correctly treated as transient and retried (1 failure: `Recommended Firewall Rule`)

---

## [0.10.5] - 2026-03-07

### Added

#### ZIA — Apply Baseline from JSON — push log
- A timestamped log file is written to `~/.local/share/zs-config/logs/zia-push-<timestamp>.log` after every baseline push (Windows: `%APPDATA%\zs-config\logs\`)
- Log includes: tenant name/ID, baseline file path, dry-run classification counts, full push results per resource, and **untruncated** error messages for all failures (the on-screen failure table truncates at 80 characters)
- Resources in `to_delete` that were not executed (user declined or skipped) are listed separately so they remain visible for review

### Fixed
- `pyproject.toml` `license` field changed from deprecated TOML table form (`{text = "MIT"}`) to plain SPDX string (`"MIT"`) — required by setuptools ≥ 77

---

## [0.10.4] - 2026-03-07

### Fixed

#### ZIA — Apply Baseline from JSON (cross-tenant push)
- Replaced narrow `SKIP_IF_PREDEFINED` type gating with universal `_is_zscaler_managed()` detection applied to every resource type. Signals: `predefined:true`, `defaultRule:true`, `type:"PREDEFINED"`, and url_category-specific checks. Zscaler-managed resources now always remap IDs correctly instead of slipping through as false user-defined creates
- Added `defaultRule:true` as a managed-resource signal — catches Zscaler's built-in default firewall, forwarding, and other rule types whose numeric IDs differ across tenants
- Writable managed resources (`accessControl:"READ_WRITE"`) that differ from the baseline are now updated via the existing target-tenant ID rather than attempted as creates (which fail with 400/INVALID_INPUT_ARGUMENT or 409/STALE_CONFIGURATION_ERROR in cross-tenant pushes)
- Read-only managed resources (`accessControl` absent or not `"READ_WRITE"`) are remapped and skipped — no API call issued

### Changed

#### ZIA — Apply Baseline from JSON — delete confirmation
- Deletes are no longer executed automatically as part of the push. After all creates and updates complete, any resources present in the target tenant but absent from the baseline are presented as a separate list requiring explicit confirmation (default: No) before any destructive action is taken
- `push_classified()` no longer executes deletes; new `execute_deletes()` method on `ZIAPushService` handles confirmed deletes, called only from the menu after user approval

---

## [0.10.3] - 2026-03-06

### Fixed

#### ZIA — Apply Baseline from JSON
- `DUPLICATE_ITEM` (400) responses from ZIA now trigger the fallback-to-update path instead of being treated as permanent failures — previously caused false failures for `network_service`, `url_category`, `dlp_engine`, `dlp_dictionary`, and `network_app_group`
- Added `bandwidth_class` to `SKIP_IF_PREDEFINED`; built-in bandwidth classes (`BANDWIDTH_CAT_*`) were being attempted and failing
- Improved predefined detection for `url_category`: fixed `customCategory == False` check (was `is False`, missed SDK-serialized values); added non-numeric ID detection (Zscaler-defined categories have string IDs like `ADULT_SEX_EDUCATION`, custom categories always have numeric IDs)
- Added `type: "PREDEFINED"` detection to `_is_predefined()` — network services and bandwidth classes carry this field instead of a `predefined: true` boolean, causing them to slip through the predefined check
- Added `rank`, `defaultRule`, `accessControl`, `configVersion`, `managedBy` to `READONLY_FIELDS` — server-computed fields returned in GET responses but rejected by POST/PUT; `rank` was the likely cause of "Request body is invalid." on `firewall_dns_rule`, `ssl_inspection_rule`, and `forwarding_rule`
- Config comparison now normalizes list field ordering before comparing — ZIA returns port range arrays in non-deterministic order between API calls, causing false-positive update detections
- `allowlist`/`denylist` no longer queue as updates when the URL list is empty; fixed URL key lookup to handle both snake_case (`whitelist_urls`) and camelCase (`whitelistUrls`) variants

---

## [0.10.2] - 2026-03-06

### Fixed

#### ZIA — Activation
- `get_activation_status()` was calling the wrong SDK method (`get_activation_status` → `status()`), causing the Activation menu to immediately show an error and return without activating
- Removed the intermediate `questionary.confirm` in the activation flow — it was silently consuming the buffered Enter keypress from the preceding menu selection, causing activation to be skipped with no feedback
- Removed `console.status()` spinner from the activation call — output printed inside the context manager was being wiped when the spinner exited
- Activation result is now stored and displayed on the next render loop (after the status re-fetch) so it cannot be cleared by `render_banner()`

#### ZIA — Pending activation tracking
- `_zia_pending` session flag per tenant ID — set on every ZIA mutation, cleared on successful activation
- `⚠ Changes pending activation` shown at the top of the ZIA menu and Activation submenu when flag is set
- Main menu ZIA entry shows `⚠` in the label when changes are pending
- Exit and Switch Tenant prompt with a yellow panel and "proceed anyway?" (default: No) when pending changes exist

---

## [0.10.1] - 2026-03-06

### Added

#### ZIA — Source and Destination IPv4 Group CRUD
- **Source IPv4 Group Management** and **Dest IPv4 Group Management** are now full submenus replacing the previous bulk-CSV-only entry
- **List All** — scrollable table showing ID, Name, IP/address count, and Description
- **Search by Name** — partial match filter
- **Create** — prompted fields: name, description, and semicolon-separated addresses; type selector (DSTN_IP / DSTN_FQDN / DSTN_DOMAIN / DSTN_OTHER) for destination groups
- **Edit** — pick from local DB; blank input keeps the current value; updates via API and re-syncs DB
- **Delete** — confirmation prompt (default: No)
- **Bulk Create from CSV** — existing CSV import functionality retained, now nested inside each submenu

---

## [0.10.0] - 2026-03-06

### Added

#### ZPA — Access Policy Import / Sync from CSV
- **Export Existing Rules to CSV** — writes all `policy_access` rules to CSV with `id` as the first column; decodes all condition fields (app_groups, applications, saml_attributes, scim_groups, client_types, machine_groups, trusted_networks, platforms, country_codes, idp_names) into readable semicolon-separated values
- **Import / Sync from CSV** (replaces "Bulk Create from CSV") — full Option C mirror sync:
  - Rows with `id` → PUT update (config diff check; skipped if unchanged)
  - Rows without `id` → POST create, captures returned ID
  - Existing rules whose ID is absent from the CSV → DELETE
  - All surviving IDs in CSV row order → `bulk_reorder_rules()` atomic reorder
- **Dry-run preview table** — shows UPDATE / CREATE / DELETE / SKIP / MISSING_DEP / REORDER classification before any API calls; MISSING_DEP rows highlighted in red with dependency issue detail
- **CSV scoping fields** — `machine_groups`, `trusted_networks`, `platforms`, `country_codes`, `idp_names` added to the CSV schema; all are ignore-if-empty; at least one of `app_groups` or `applications` is required per rule
- **Validation** — platform values validated against `{ios, android, mac_os, windows, linux, chrome_os}`; unresolved machine groups, trusted networks, or IdPs are flagged as MISSING_DEP and excluded from sync

#### ZIA — Firewall Rule Export and Import / Sync from CSV
- **Export Firewall Rules to CSV** — writes all `firewall_rule` entries sorted by order; decodes group/service/location references by name from local DB; literal IPs/addresses written as-is
- **Import / Sync Firewall Rules** — same Option C algorithm as ZPA (update / create / delete / reorder); reorder implemented as individual PUTs in descending order (no ZIA bulk-reorder endpoint)
- **MISSING_DEP validation** — rows referencing `src_ip_groups`, `dest_ip_groups`, `nw_services`, `nw_service_groups`, or `locations` not present in the local DB are classified MISSING_DEP and excluded from sync with a hint to create missing groups first
- **Source IPv4 Group Management** — sub-menu (Import from CSV / Export Template / Cancel); CSV columns: `name`, `description`, `ip_addresses`; bulk creates groups via ZIA API with progress bar and per-row error reporting; local DB re-synced on completion
- **Dest IPv4 Group Management** — same pattern; CSV columns: `name`, `type`, `description`, `ip_addresses`; `type` accepts `DSTN_IP`, `DSTN_FQDN`, `DSTN_DOMAIN`, `DSTN_OTHER`

#### ZPA Client (`lib/zpa_client.py`)
- `update_access_rule(rule_id, name, action, **kwargs)` — PUT to `policies.update_rule("access", ...)`
- `bulk_reorder_access_rules(rule_ids)` — calls `policies.bulk_reorder_rules("access", rule_ids)`

#### New / updated service files
- `services/zpa_policy_service.py` — `SyncResult`, `SyncClassification`, `classify_sync()`, `sync_policy()`, `_build_conditions()`, `_decode_conditions()`, `_is_row_unchanged()`; all 10 condition field types supported
- `services/zia_firewall_service.py` (new) — `parse_csv()`, `export_rules_to_csv()`, `resolve_dependencies()`, `classify_sync()`, `sync_rules()`; `parse_ip_source_group_csv()`, `parse_ip_dest_group_csv()`, `bulk_create_ip_source_groups()`, `bulk_create_ip_dest_groups()`

### Fixed

#### ZPA — Access Policy search
- Sort and display key corrected from `ruleOrder` (camelCase) to `rule_order` (snake_case, matching SDK storage)

---

## [0.9.2] - 2026-03-05

### Added

#### Tenant Management — org info auto-fetch
- `TenantConfig`: 4 new columns — `zia_tenant_id` (numeric prefix from `orgInformation.pdomain`), `zia_cloud` (from `cloudName`), `zpa_tenant_cloud` (from `zpaTenantCloud`), `zia_subscriptions` (JSON from `GET /subscriptions`)
- `fetch_org_info()` in `services/config_service.py` — calls `GET /zia/api/v1/orgInformation` and `GET /zia/api/v1/subscriptions`; populates all four columns
- **Add Tenant / Edit Tenant**: ZPA Customer ID prompt removed — `zpa_customer_id` now auto-populated from `orgInformation.zpaTenantId`
- **Switch Tenant**: always refreshes org info on successful auth; shows a summary table on first-time fetch or any field change; yellow subscription-change panel if subscriptions differ between tenants
- **Startup**: `_run_data_migrations()` — runs pending data migrations with Rich progress bar and per-tenant result table; backfills org info for all tenants missing `zia_tenant_id`
- **List Tenants**: table now includes ZIA Cloud, ZIA Tenant ID (numeric), and ZPA Cloud columns
- DB auto-migrations for the four new `TenantConfig` columns added to `db/database.py`

---

## [0.9.1] - 2026-03-04

### Fixed
- Banner version string was not updated from 0.8.5 to 0.9.0

---

## [0.9.0] - 2026-03-04

### Added

#### ZCC — App Profiles (web policies)
- **App Profiles** added to the `── Configuration ──` section of the ZCC menu
- **List App Profiles** — table shows Name, ID, Platform (Windows / macOS / iOS / Android / Linux), and Active state; data from local DB after Import Config
- **Search by Name** — partial name match
- **View Details** — full JSON scroll view of the stored policy record
- **Manage Custom Bypass Apps** — select a profile to view its currently assigned bypass app services; add or remove services via checkbox multi-select; change is applied immediately via `web/policy/edit` API and the local DB is refreshed
- **Activate / Deactivate** — checkbox multi-select across profiles; choose target platform; activates or deactivates each selected profile via `web/policy/activate`
- **Delete** — select profile, confirm (default No), delete via API, and re-import to refresh DB

#### ZCC — Bypass App Definitions (web app services)
- **Bypass App Definitions** added to the `── Configuration ──` section of the ZCC menu (renamed from "Custom App Bypasses" to clarify this is a library of available definitions, not what is actively bypassed per profile)
- **List All** — table shows Name, Type (Zscaler vs Custom), Svc ID, Active, Version; Type is determined by `createdBy` — numeric values indicate Zscaler-managed definitions
- **Search by Name** — partial name match
- **View Details** — full JSON scroll view

#### ZCC Import — new resource types
- `web_app_service` — bypass app service definitions synced via `webAppService/listByCompany`
- `web_policy` — app profiles synced per platform (Windows / macOS / iOS / Android / Linux) and deduplicated; stored in camelCase (API-native) format for round-trip edit compatibility

#### ZCC Client (`lib/zcc_client.py`)
- `_to_camel_dict()` — recursive helper that converts SDK `ZscalerObject` instances to camelCase plain dicts using `request_format()`; avoids the `ZscalerCollection.form_list` in-place mutation bug that causes `resp.get_body()` to contain non-JSON-serialisable SDK model objects
- `list_web_app_services()` — lists bypass app service definitions
- `list_web_policies()` — fetches policies for all 5 platforms, deduplicates by ID, injects `device_type` for display
- `edit_web_policy(**kwargs)` — PUT to `web/policy/edit`
- `activate_web_policy(policy_id, device_type)` — PUT to `web/policy/activate`
- `delete_web_policy(policy_id)` — DELETE to `web/policy/{id}/delete`

#### ZCC Service (`services/zcc_service.py`)
- Audit-logged wrappers for all five new client methods above

### Fixed

#### ZCC menu — "← Back" crash in selection prompts
- `questionary.select` with `value=None` returns the title string in some versions rather than `None`; replaced `if not selected` guards with `if not isinstance(selected, dict)` in all affected detail/delete/manage prompts

---

## [0.8.5] - 2026-03-04

### Fixed

#### Update checker — changelog prompt UX
- Added a `Press any key to view changelog...` pause between the update panel and the scroll viewer so the notification is readable before the alternate screen opens

---

## [0.8.4] - 2026-03-04

### Fixed

#### Update checker — NameError crash on startup
- `Markdown` was accidentally dropped from imports when refactoring to `scroll_view`; moved to a local import inside the branch that uses it
- Fixes `NameError: name 'Markdown' is not defined` crash whenever an update was available

---

## [0.8.3] - 2026-03-04

### Fixed

#### Update checker — changelog scroll UX
- Changelog now opens in the full-screen scroll viewer (↑↓ / j k / PgDn / PgUp / g / G / q) instead of printing inline
- Fixes the update panel being pushed off screen by long changelogs; the panel reappears after exiting the viewer since scroll_view uses the alternate screen buffer

---

## [0.8.2] - 2026-03-04

### Added

#### Auto-update checker
- On startup (after the banner), zs-config silently checks PyPI for a newer version
- If an update is available, a yellow panel shows the version delta (`v0.8.1 → v0.8.2`)
- Relevant CHANGELOG sections are fetched from GitHub and rendered inline so you can review what changed before upgrading
- A `questionary.confirm` prompt (default: Yes) offers to upgrade immediately using the detected install method (`pipx upgrade zs-config` or `pip install --upgrade zs-config`)
- If confirmed, the upgrade runs live in the terminal; on success a green panel is shown and the process exits so you re-launch the updated binary
- If declined or if the upgrade fails, the tool continues normally; a red panel with the manual upgrade command is shown on failure
- All network requests use a 4-second timeout — startup is unaffected on slow or offline networks
- New file: `cli/update_checker.py`

---

## [0.8.1] - 2026-03-02

### Added

#### Credential verification on tenant add and switch
- `ZscalerAuth.get_token()` — direct OAuth2 `client_credentials` POST to
  `{zidentity_base_url}/oauth2/v1/token`; raises on failure (also fixes a latent
  bug where `conf_writer.test_credentials` called this method before it existed)
- **Add Tenant**: immediately tests credentials after saving; shows ✓ on success
  or ✗ with a pointer to Settings → Edit Tenant on failure (tenant is saved either way)
- **Switch Tenant**: verifies token with a spinner before activating the session;
  on failure offers three options — Edit credentials / Switch anyway / Cancel
- **Settings → Edit Tenant** (new): pick a tenant, edit vanity subdomain, client ID,
  and/or client secret (blank = keep existing); live token test before saving;
  "Save anyway?" offered if test fails

---

## [0.8.0] - 2026-02-27

### Fixed

#### ZIA — Apply Baseline: skip `ZSCALER_PROXY_NW_SERVICES`
- Added `SKIP_NAMED` constant — a per-type dict of resource names that are system-managed
  but lack a `predefined:true` flag in their API response (e.g. `ZSCALER_PROXY_NW_SERVICES`
  returns a 403 `EDIT_INTERNAL_DATA_NOT_ALLOWED` on any write attempt)
- `_is_predefined()` now checks `SKIP_NAMED` in addition to the `predefined` boolean and
  the `url_category` type-field heuristics; these resources are silently skipped during
  classification and never queued for push

### Changed

#### ZIA — Apply Baseline: dry-run comparison before push
- `classify_baseline()` is now a standalone phase: runs a full import of the target tenant
  and classifies each baseline entry as **create / update / skip** — no API writes
- `push_classified()` accepts the `DryRunResult` returned by `classify_baseline()` and
  executes the actual multi-pass push
- `apply_baseline_menu()` now shows a **Comparison Result** table after classification
  (type | Create | Update | Skip) plus a per-resource list of pending creates and updates
  (capped at 30 each), then asks for confirmation before issuing any API calls
- If the target is already in sync (0 creates, 0 updates), the user is informed and the
  menu returns without making any API calls

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

