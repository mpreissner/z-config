# ZIA CRUD Parity — Web Frontend

**Branch:** `feature/web-frontend`
**Status:** Spec — not yet implemented

---

## Overview

The ZIA section of the web frontend currently has list + toggle for seven resource types but is
missing create, edit, and delete. This spec describes the minimum changes required to bring all
seven to full CRUD parity with the TUI, staying true to the "quick config tool" scope (not a full
admin portal replacement).

Resource types in scope:

| # | Resource | DB type key | Service state | Router state | `api/zia.ts` state |
|---|----------|-------------|---------------|--------------|--------------------|
| 1 | URL Filtering Rules | `url_filtering_rule` | Full CRUD | Full CRUD | No create/update/delete |
| 2 | URL Categories | `url_category` | Full CRUD | Full CRUD | No create/update/delete |
| 3 | Firewall Rules | `firewall_rule` | list + toggle only | list + PATCH state | No CRUD |
| 4 | SSL Inspection Rules | `ssl_inspection_rule` | list + toggle only | list + PATCH state | No CRUD |
| 5 | Traffic Forwarding Rules | `forwarding_rule` | list + toggle only | list + PATCH state | No CRUD |
| 6 | DLP Web Rules | `dlp_web_rule` | list + toggle only | list + PATCH state | No CRUD |
| 7 | DLP Engines | `dlp_engine` | list only | list only | No CRUD |

---

## Layer-by-layer summary of changes

### `services/zia_service.py`

- Resources 1 and 2: no changes needed; service methods already exist.
- Resources 3–7: add `get_`, `create_`, `update_`, and `delete_` service methods following the
  exact pattern of the existing URL filtering rule methods.

### `api/routers/zia.py`

- Resources 1 and 2: no changes needed; endpoints already exist.
- Resources 3–7: add `GET /{tenant}/<resource>/{id}`, `POST /{tenant}/<resource>`,
  `PUT /{tenant}/<resource>/{id}`, and `DELETE /{tenant}/<resource>/{id}` endpoints following
  the URL filtering rules section.

### `web/src/api/zia.ts`

- Resources 1 and 2: add `createUrlFilteringRule`, `updateUrlFilteringRule`,
  `deleteUrlFilteringRule`, `createUrlCategory`, `updateUrlCategory`, `deleteUrlCategory`
  functions. Interfaces already exist.
- Resources 3–7: add full CRUD client functions plus extended TypeScript interfaces where needed.

### `web/src/pages/TenantWorkspacePage.tsx`

All seven sections get inline-row edit (click to expand) and a top-of-section "New" button that
opens a small form panel. The pattern follows the existing `UrlCategoryRow` expand/collapse
pattern. No separate modal component is needed for forms of this complexity. A shared
`ConfirmDialog` is already available for delete confirmations.

---

## Per-resource detail

### 1. URL Filtering Rules

#### What exists
- Service: `list_url_filtering_rules`, `create_url_filtering_rule`, `update_url_filtering_rule`,
  `delete_url_filtering_rule`
- Router: `GET /url-filtering-rules`, `GET /url-filtering-rules/{id}`, `POST /url-filtering-rules`,
  `PUT /url-filtering-rules/{id}`, `DELETE /url-filtering-rules/{id}`, `PATCH .../state`
- `api/zia.ts`: `fetchUrlFilteringRules`, `fetchUrlFilteringRule`, `patchUrlFilteringRuleState`

#### What to add
`api/zia.ts` only. Add three client functions:

```ts
createUrlFilteringRule(tenant, body)   // POST /url-filtering-rules
updateUrlFilteringRule(tenant, id, body)  // PUT /url-filtering-rules/{id}
deleteUrlFilteringRule(tenant, id)     // DELETE /url-filtering-rules/{id}
```

#### UI form fields
The ZIA API requires `name`, `order`, `action`, `state`, and `protocols` at minimum. Optional
high-value fields: `description`, `urlCategories` (array of category IDs), `requestMethods`.

Create form fields (inline panel above table):
- Name (text, required)
- Action (select: `ALLOW` / `CAUTION` / `BLOCK_OVERRIDE` / `BLOCK`)
- Order (number, required — user sets position)
- Protocols (multi-select: `HTTP_RULE` / `HTTPS_RULE` / `FTP_RULE` — default both HTTP+HTTPS)
- State (toggle: ENABLED / DISABLED, default ENABLED)
- Description (text, optional)

Edit: clicking a row expands it. The expanded area shows current values in a form. Edit uses the
same fields. "Save" calls PUT; "Delete" shows a `ConfirmDialog` then calls DELETE.

Delete: confirm-dialog guard required (ZIA API does not soft-delete filtering rules).

---

### 2. URL Categories

#### What exists
- Service: `create_url_category`, `update_url_category`, `get_url_category`,
  `add_urls_to_category`, `remove_urls_from_category`
- Router: `POST /url-categories`, `PUT /url-categories/{id}`, `GET /url-categories/{id}`,
  `POST /url-categories/{id}/urls`, `DELETE /url-categories/{id}/urls`
- `api/zia.ts`: `fetchUrlCategoryDetail`, `addUrlsToCategory`, `removeUrlsFromCategory`

#### What to add
`api/zia.ts` only. Add:

```ts
createUrlCategory(tenant, body)          // POST /url-categories
updateUrlCategory(tenant, id, body)      // PUT /url-categories/{id}
deleteUrlCategory(tenant, id)            // DELETE /url-categories/{id}  (needs router endpoint too — see below)
```

The router is missing a `DELETE /url-categories/{id}` endpoint. Add it following the pattern of
`delete_url_filtering_rule`; call `client.delete_url_category(category_id)`. Check whether
`ZIAClient.delete_url_category` exists — if not, add it (it is a standard SDK call:
`self._sdk.zia.url_categories.delete_url_category(category_id)`).

#### UI form fields
Only custom categories (`type == "URL_CATEGORY"` with a `configuredName`) are editable. Predefined
categories are read-only.

Create form: "New Custom Category" button above the table. Fields:
- Name / Configured Name (text, required)
- Description (text, optional)
- URLs (textarea, one per line, optional at creation)

Edit (inline expand — already partially done for URL management): extend the existing expand panel
to add Name and Description fields above the URL list. "Rename" saves a PUT with the updated name/
description. Delete button appears only for custom categories; guarded by `ConfirmDialog`.

---

### 3. Firewall Rules

#### What to add — Service

```python
def get_firewall_rule(self, rule_id: str) -> Dict
def create_firewall_rule(self, config: Dict, auto_activate: bool = True) -> Dict
def update_firewall_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict
def delete_firewall_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None
```

Pattern: mirror `create_url_filtering_rule` / `update_url_filtering_rule` /
`delete_url_filtering_rule`. For update, pass config through `_prepare_rule_for_update()` before
calling `self.client.update_firewall_rule(rule_id, cleaned)`. On success, call
`self._upsert_one("firewall_rule", rule_id, result)` for create/update and
`self._reimport(["firewall_rule"])` for delete.

Audit log fields: `product="ZIA"`, `resource_type="firewall_rule"`, action CREATE/UPDATE/DELETE.

#### What to add — Router

```
GET    /{tenant}/firewall-rules/{rule_id}
POST   /{tenant}/firewall-rules
PUT    /{tenant}/firewall-rules/{rule_id}
DELETE /{tenant}/firewall-rules/{rule_id}
```

All follow the URL filtering rules pattern: accept `Dict[str, Any]` body, wrap in try/except,
return 500 on error. DELETE returns `{"deleted": True}`.

#### What to add — `api/zia.ts`

```ts
getFirewallRule(tenant, ruleId)           // GET  /firewall-rules/{id}
createFirewallRule(tenant, body)          // POST /firewall-rules
updateFirewallRule(tenant, ruleId, body)  // PUT  /firewall-rules/{id}
deleteFirewallRule(tenant, ruleId)        // DELETE /firewall-rules/{id}
```

Extend `FirewallRule` interface:
```ts
nwServices?: Array<{id: number; name: string}>;
srcIpGroups?: Array<{id: number; name: string}>;
destIpGroups?: Array<{id: number; name: string}>;
locations?: Array<{id: number; name: string}>;
```

#### UI form fields

The ZIA API requires `name`, `order`, `action`, and `state`. All other fields are optional.

Create form fields:
- Name (text, required)
- Action (select: `ALLOW` / `BLOCK` / `BLOCK_ICMP` — these are the standard L4 actions)
- Order (number, required)
- State (toggle: ENABLED / DISABLED, default ENABLED)
- Description (text, optional)

Edit (row expand): same fields. Predefined/system rules (where `predefined: true`) should show
fields read-only and suppress Save/Delete buttons.

Delete: `ConfirmDialog` guard. Do not allow delete of predefined rules (check `rule.predefined`).

---

### 4. SSL Inspection Rules

#### What to add — Service

```python
def get_ssl_inspection_rule(self, rule_id: str) -> Dict
def create_ssl_inspection_rule(self, config: Dict, auto_activate: bool = True) -> Dict
def update_ssl_inspection_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict
def delete_ssl_inspection_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None
```

For update: pass config through `_prepare_rule_for_update()` before calling
`self.client.update_ssl_inspection_rule(rule_id, cleaned)`. On read-back, apply
`_normalize_ssl_rules([result])` to flatten the `action` field before returning. On success,
call `self._upsert_one("ssl_inspection_rule", rule_id, result)` or
`self._reimport(["ssl_inspection_rule"])` for delete.

#### What to add — Router

```
GET    /{tenant}/ssl-inspection-rules/{rule_id}
POST   /{tenant}/ssl-inspection-rules
PUT    /{tenant}/ssl-inspection-rules/{rule_id}
DELETE /{tenant}/ssl-inspection-rules/{rule_id}
```

#### What to add — `api/zia.ts`

```ts
getSslInspectionRule(tenant, ruleId)
createSslInspectionRule(tenant, body)
updateSslInspectionRule(tenant, ruleId, body)
deleteSslInspectionRule(tenant, ruleId)
```

Extend `SslInspectionRule` interface:
```ts
urlCategories?: string[];
departments?: Array<{id: number; name: string}>;
groups?: Array<{id: number; name: string}>;
```

#### UI form fields

The ZIA API requires `name`, `order`, `action`, and `state`. The `action` field on SSL rules is
stored as `{type: "INSPECT"}` in the API but normalized to a plain string (`"INSPECT"`) by
`_normalize_ssl_rules` in the service layer. The frontend should always send a plain string in the
body; the service or router does not need to re-wrap it on the way in (the API accepts a plain
string on write).

Create form fields:
- Name (text, required)
- Action (select: `INSPECT` / `BYPASS` / `DECRYPT`)
- Order (number, required)
- State (toggle: ENABLED / DISABLED, default ENABLED)
- Description (text, optional)

Edit (row expand): same fields. Suppress Save/Delete for predefined rules.

---

### 5. Traffic Forwarding Rules

#### What to add — Service

```python
def get_forwarding_rule(self, rule_id: str) -> Dict
def create_forwarding_rule(self, config: Dict, auto_activate: bool = True) -> Dict
def update_forwarding_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict
def delete_forwarding_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None
```

For update: pass config through `_prepare_forwarding_rule_for_update()` (the specialized helper,
not the generic `_prepare_rule_for_update`). This is mandatory — standard PUT will be rejected
by the API if any ref-list fields contain full objects instead of `{id, name}` stubs.

On success, call `self._upsert_one("forwarding_rule", rule_id, result)` for create/update and
`self._reimport(["forwarding_rule"])` for delete.

Note: `ZIAClient.get_forwarding_rule` already exists (`lib/zia_client.py:474`). The service-layer
`get_forwarding_rule` only needs to wrap it with a DB-first read and audit log.

#### What to add — Router

```
GET    /{tenant}/forwarding-rules/{rule_id}
POST   /{tenant}/forwarding-rules
PUT    /{tenant}/forwarding-rules/{rule_id}
DELETE /{tenant}/forwarding-rules/{rule_id}
```

#### What to add — `api/zia.ts`

```ts
getForwardingRule(tenant, ruleId)
createForwardingRule(tenant, body)
updateForwardingRule(tenant, ruleId, body)
deleteForwardingRule(tenant, ruleId)
```

The existing `ForwardingRule` interface captures only `id`, `name`, `order`, `type`, `state`,
`description`. No extension required for the minimal create/edit form.

#### UI form fields

The ZIA API requires `name`, `type` (forwarding type), and `state`. Order is optional on create
(ZIA assigns it). Common `type` values: `DIRECT`, `PROXYCHAIN`, `ZIA_DEFINED`, `ZPA` — but ZPA
type requires ZPA application segment references which are out of scope for this quick config tool.
Scope this form to `DIRECT` and `PROXYCHAIN` only; display other types as read-only.

Create form fields:
- Name (text, required)
- Type (select: `DIRECT` / `PROXYCHAIN`)
- Description (text, optional)
- State (toggle: ENABLED / DISABLED, default ENABLED)

Edit (row expand): show current type read-only if it is `ZPA` or `ZIA_DEFINED` (those require
additional fields not surfaced in this tool). For `DIRECT` and `PROXYCHAIN` rules, allow name,
description, and state edits. Delete is available for all non-predefined rules.

---

### 6. DLP Web Rules

#### What to add — Service

```python
def get_dlp_web_rule(self, rule_id: str) -> Dict
def create_dlp_web_rule(self, config: Dict, auto_activate: bool = True) -> Dict
def update_dlp_web_rule(self, rule_id: str, config: Dict, auto_activate: bool = True) -> Dict
def delete_dlp_web_rule(self, rule_id: str, rule_name: str, auto_activate: bool = True) -> None
```

For update: pass config through `_prepare_rule_for_update()`. On success, call
`self._upsert_one("dlp_web_rule", rule_id, result)` or `self._reimport(["dlp_web_rule"])` for
delete.

Note: `ZIAClient.get_dlp_web_rule`, `create_dlp_web_rule`, `update_dlp_web_rule`, and
`delete_dlp_web_rule` all already exist in `lib/zia_client.py:826–849`.

#### What to add — Router

```
GET    /{tenant}/dlp-web-rules/{rule_id}
POST   /{tenant}/dlp-web-rules
PUT    /{tenant}/dlp-web-rules/{rule_id}
DELETE /{tenant}/dlp-web-rules/{rule_id}
```

#### What to add — `api/zia.ts`

```ts
getDlpWebRule(tenant, ruleId)
createDlpWebRule(tenant, body)
updateDlpWebRule(tenant, ruleId, body)
deleteDlpWebRule(tenant, ruleId)
```

Extend `DlpWebRule` interface:
```ts
description?: string;
protocols?: string[];
dlpEngines?: Array<{id: number; name: string}>;
```

#### UI form fields

The ZIA API requires `name`, `order`, `action`, `state`, and `protocols` at minimum. DLP web
rules also require at least one of: `dlpEngines`, `dlpDictionaries`, or `icapServer`. For the
quick config tool, surface engine assignment (which maps to existing data already loaded in the
DLP Engines section).

Create form fields:
- Name (text, required)
- Action (select: `ALLOW` / `BLOCK` / `ALLOW_ZSCALER_ENCRYPTION` / `BLOCK_INTERNATIONAL`)
- Order (number, required)
- Protocols (multi-select: `FTP_RULE` / `HTTPS_RULE` / `HTTP_RULE`)
- State (toggle: ENABLED / DISABLED, default ENABLED)
- DLP Engines (multi-select from loaded DLP engines, optional)
- Description (text, optional)

Edit (row expand): same fields. Predefined rules are read-only.

---

### 7. DLP Engines

#### What to add — Service

```python
def get_dlp_engine(self, engine_id: str) -> Dict
def create_dlp_engine(self, config: Dict, auto_activate: bool = True) -> Dict
def update_dlp_engine(self, engine_id: str, config: Dict, auto_activate: bool = True) -> Dict
def delete_dlp_engine(self, engine_id: str, engine_name: str, auto_activate: bool = True) -> None
```

All four corresponding `ZIAClient` methods already exist (`lib/zia_client.py:563–586`). Wrap them
in the standard service pattern with audit logging and `auto_activate`. On success, call
`self._upsert_one("dlp_engine", engine_id, result)` for create/update and
`self._reimport(["dlp_engine"])` for delete.

#### What to add — Router

```
GET    /{tenant}/dlp-engines/{engine_id}
POST   /{tenant}/dlp-engines
PUT    /{tenant}/dlp-engines/{engine_id}
DELETE /{tenant}/dlp-engines/{engine_id}
```

#### What to add — `api/zia.ts`

```ts
getDlpEngine(tenant, engineId)
createDlpEngine(tenant, body)
updateDlpEngine(tenant, engineId, body)
deleteDlpEngine(tenant, engineId)
```

The `DlpEngine` interface already covers the required fields.

#### UI form fields

The ZIA API requires `name` and `engineExpression` for custom engines. Predefined engines
(`predefinedEngine: true`) cannot be mutated.

Create form fields (only for custom engines):
- Name (text, required)
- Engine Expression (textarea, required — the logical expression using `D{id}` dictionary refs)
- Description (text, optional)
- Custom DLP Engine toggle (checkbox, default true — sets `customDlpEngine: true` in payload)

Edit (row expand): extend the existing `DlpEngineRow` expand to add edit fields for custom engines
only. The dictionary-expression resolver already rendered in the current expand panel should remain
visible above the edit fields. Predefined engines show read-only. Delete with `ConfirmDialog`.

---

## Gotchas and cross-cutting concerns

### `_prepare_rule_for_update` vs `_prepare_forwarding_rule_for_update`

These are two distinct helpers in `services/zia_service.py` (lines 46–58 and 70–127).

- **Firewall rules, SSL inspection rules, DLP web rules**: use `_prepare_rule_for_update`. It strips
  read-only camelCase and snake_case fields and empty arrays.
- **Forwarding rules**: always use `_prepare_forwarding_rule_for_update`. It additionally reduces all
  ref-list fields (locations, groups, nw_services, etc.) to `{id, name}` stubs and handles the
  `zpa_app_segments` / `zpa_gateway` special cases. Failure to use the right helper will result in
  ZIA API 400 "Request body is invalid" errors.

### `_normalize_ssl_rules` on reads

The `action` field on SSL inspection rules is returned from the ZIA API as `{type: "INSPECT"}` but
the service normalizes it to a plain string via `_normalize_ssl_rules`. The service's
`list_ssl_inspection_rules` already applies this normalization. The new `get_ssl_inspection_rule`
service method must also apply it. The frontend should send action as a plain string on PUT/POST —
the API accepts both forms on write.

### Activation after every mutation

Every mutating service method (create, update, delete) must call `self.activate()` when
`auto_activate=True`. This is the same pattern as all existing service CRUD methods. Callers
(router endpoints) do not call `activate()` themselves.

### No `delete_url_category` in `ZIAClient`

Before implementing the URL category delete router endpoint, verify whether
`ZIAClient.delete_url_category` exists. If it does not, add it:

```python
def delete_url_category(self, category_id: str) -> None:
    if self._govcloud:
        self.zia_delete(f"/zia/api/v1/urlCategories/{category_id}")
        return
    result, resp, err = self._sdk.zia.url_categories.delete_url_category(category_id)
    _unwrap(result, resp, err)
```

Only custom categories (`type == "URL_CATEGORY"`, non-system) can be deleted. The service layer
does not need to enforce this (the ZIA API will reject predefined deletions), but the UI should
suppress the delete action for non-custom categories.

### DB cache invalidation

The DB-first read pattern means mutations must update the local cache. The rule is:
- Create/update a single resource: `self._upsert_one(resource_type, resource_id, result)`
- Delete any resource: `self._reimport([resource_type])` (full reimport of the type)

`_upsert_one` runs a single DB write without triggering a full API call. `_reimport` triggers a
background fetch of the full list from ZIA and replaces the DB rows. All existing service methods
follow this pattern; new methods must too.

### SQLite write-lock

The non-negotiable constraint: never call `audit_service.log()` or open a `get_session()` block
inside an existing `with get_session()` block. All new service methods follow the pattern already
established: all DB operations (audit log, upsert) happen outside the session context. The
`_upsert_one` method opens its own session internally — it is safe to call after the main
operation completes.

### DLP engines: no `state` field

Unlike rule types, DLP engines have no `state` / enabled-disabled toggle. The `DlpEnginesSection`
in the UI has no toggle column and no toggle mutation. The new DLP engine CRUD should not add one.
Activation is still required after create/update/delete because changes must propagate.

### Predefined resource protection

Several resource types contain Zscaler-managed predefined records that must not be mutated. The
patterns to check in the UI:

| Resource | Predefined check |
|----------|-----------------|
| Firewall rules | `rule.predefined === true` |
| SSL inspection rules | `rule.predefined === true` |
| Forwarding rules | `rule.type === "ZIA_DEFINED"` or `rule.predefined === true` |
| DLP web rules | `rule.predefined === true` |
| DLP engines | `engine.predefinedEngine === true` |
| URL categories | `category.type !== "URL_CATEGORY"` or `!category.configuredName` |

In all cases: suppress the Edit and Delete actions in the UI for predefined resources. The ZIA
API will also return an error if a predefined resource is mutated, but the UI should not even
offer the option.

### Forwarding rules with `type=ZPA` or `type=ZIA_DEFINED`

These require ZPA application segment references or ZIA-internal settings that cannot be expressed
in the minimal form. The create form should not offer `ZPA` or `ZIA_DEFINED` as type options.
For existing rules of those types in the edit expand, show fields read-only and suppress Save.

### URL filtering rules: `urlCategories` field

The `urlCategories` field is an array of category ID strings (e.g. `["CUSTOM_01"]`), not a numeric
ID array. The service's `_apply_id_remap` logic in the push service treats it specially. For the
simple create/edit form in the web UI, a plain text field accepting comma-separated category IDs
is sufficient. Full category-picker UI is out of scope.

---

## Implementation order (recommended)

1. Resources 1 and 2 (`api/zia.ts` additions only — no backend changes).
2. Resource 7 (DLP Engines) — simplest new backend work; no toggle, no state.
3. Resources 3 and 4 (Firewall, SSL) — `_prepare_rule_for_update` path; very similar to each other.
4. Resource 6 (DLP Web Rules) — same path as firewall/SSL; adds engine multi-select in UI.
5. Resource 5 (Forwarding Rules) — last because `_prepare_forwarding_rule_for_update` is the most
   sensitive helper and the `ZPA`/`ZIA_DEFINED` type restriction adds UI complexity.

---

## Files to touch

| File | Resources affected |
|------|--------------------|
| `services/zia_service.py` | 3, 4, 5, 6, 7 (add CRUD methods) |
| `lib/zia_client.py` | 2 only if `delete_url_category` is missing |
| `api/routers/zia.py` | 2 (delete endpoint), 3, 4, 5, 6, 7 |
| `web/src/api/zia.ts` | All 7 (add client functions; extend interfaces for 3, 4, 6) |
| `web/src/pages/TenantWorkspacePage.tsx` | All 7 (add create form panels + edit/delete in row expand) |

Do not touch `cli/` — these changes are API/web-only.
