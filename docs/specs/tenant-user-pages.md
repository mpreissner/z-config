# Spec: Tenant Dashboard and Workspace

**Feature branch**: `feature/web-frontend` (from `dev`)
**Status**: Draft — ready for implementation
**Scope**: Entitlement-gated tenant access for regular users, redesigned TenantsPage dashboard, new TenantPage workspace with ZIA and ZPA tabs.

---

## 0. Motivation and invariants

Regular (`role="user"`) accounts currently hit 403 on every tenant-related endpoint because all routes use `require_admin`. `UserTenantEntitlement` rows already exist in the DB but are never consulted by the API. This spec closes that gap and builds the workspace UI on top of it.

Hard constraints carried forward from the project rules:
- Never open a `get_session()` inside an existing `with get_session()` block. Collect audit events in a list and write them after the outer session closes.
- `client_secret` must never appear in any API response, log entry, or audit detail field.
- ZIA mutations must call `_zia_changed()` in the CLI; in the API layer, any endpoint that calls `activate()` on the service is a mutation — no mutations are introduced in this spec (all new ZIA/ZPA routes are read-only).
- ZPA `rotate_certificate` is file-path based and must not be exposed via the web — it stays CLI-only.

---

## 1. Backend: entitlement helper

### 1.1 New file: `api/auth_utils.py` addition — no. Add to `api/dependencies.py`

Add one function to `/Users/mike/Documents/CodeProjects/zs-config/api/dependencies.py`:

```python
def check_tenant_access(tenant_id: int, user: AuthUser) -> None:
    """Raise 404 if user is not admin and has no entitlement for tenant_id.

    Returns None on success (caller proceeds).  Raises HTTPException(404) on
    failure — 404 not 403, to avoid leaking tenant existence to unauthorized users.
    """
    if user.role == "admin":
        return
    from db.database import get_session
    from db.models import UserTenantEntitlement
    with get_session() as session:
        row = session.query(UserTenantEntitlement).filter_by(
            user_id=user.user_id, tenant_id=tenant_id
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
```

This function is called by every endpoint that addresses a specific tenant. It is the single point of entitlement enforcement — do not inline equivalent logic elsewhere.

---

## 2. Backend: tenants router changes

File: `/Users/mike/Documents/CodeProjects/zs-config/api/routers/tenants.py`

### 2.1 `GET /api/v1/tenants`

Change dependency from `require_admin` to `require_auth`. After fetching:

- If `user.role == "admin"`: return `[_serialize(t) for t in _list()]` (unchanged behaviour).
- Else: query `UserTenantEntitlement` rows for `user.user_id`, collect `tenant_id` values, filter the list to only those IDs.

```python
@router.get("")
def list_tenants(user: AuthUser = Depends(require_auth)):
    from services.config_service import list_tenants as _list
    all_tenants = _list()
    if user.role == "admin":
        return [_serialize(t) for t in all_tenants]
    from db.database import get_session
    from db.models import UserTenantEntitlement
    with get_session() as session:
        entitled = {
            row.tenant_id
            for row in session.query(UserTenantEntitlement).filter_by(user_id=user.user_id).all()
        }
    return [_serialize(t) for t in all_tenants if t.id in entitled]
```

### 2.2 `GET /api/v1/tenants/{tenant_id}`

Change dependency from `require_admin` to `require_auth`. After loading the tenant object, call `check_tenant_access(tenant_id, user)` before returning.

```python
@router.get("/{tenant_id}")
def get_tenant(tenant_id: int, user: AuthUser = Depends(require_auth)):
    from db.database import get_session
    from db.models import TenantConfig
    from api.dependencies import check_tenant_access
    with get_session() as session:
        t = session.query(TenantConfig).filter_by(id=tenant_id, is_active=True).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    check_tenant_access(tenant_id, user)
    return _serialize(t)
```

Note: the entitlement check happens after the DB lookup so the same 404 is returned whether the tenant doesn't exist or the user has no entitlement.

### 2.3 Import endpoints — unchanged

`POST /api/v1/tenants/{id}/import/zia` and `POST /api/v1/tenants/{id}/import/zpa` keep `require_admin`. No change.

### 2.4 Create / Update / Delete — unchanged

All three keep `require_admin`. No change.

---

## 3. Backend: ZIA router changes

File: `/Users/mike/Documents/CodeProjects/zs-config/api/routers/zia.py`

### 3.1 Add auth to all existing endpoints

All existing routes are unauthenticated. Add `require_auth` and an entitlement check by tenant name.

Rewrite `_get_service` to also accept and enforce the caller's identity:

```python
def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zia_service import ZIAService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
    )
    client = ZIAClient(auth, tenant.oneapi_base_url)
    return ZIAService(client, tenant_id=tenant.id)
```

Update each route handler to inject `user: AuthUser = Depends(require_auth)` and pass it to `_get_service`. Example:

```python
@router.get("/{tenant}/activation/status")
def get_activation_status(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).get_activation_status()
```

Apply the same pattern to: `activate`, `list_url_categories`, `url_lookup`, `list_users`, `list_locations`, and all new endpoints below.

### 3.2 `POST /{tenant}/activation/activate` — admin only

Activation is a mutation. Change its dependency to `require_admin` (not just `require_auth`):

```python
@router.post("/{tenant}/activation/activate")
def activate(tenant: str, user: AuthUser = Depends(require_admin)):
    ...
```

`_get_service` is still called with `user` — `require_admin` already implies `require_auth`, so `check_tenant_access` will pass through (admin bypass).

### 3.3 New endpoints

Add the following to `api/routers/zia.py`. Each follows the same pattern: inject `user`, call `_get_service(tenant, user)`, delegate to service.

```
GET /{tenant}/url-filtering-rules   → service.list_url_filtering_rules()
GET /{tenant}/departments           → service.list_departments()
GET /{tenant}/groups                → service.list_groups()
GET /{tenant}/allowlist             → service.get_allowlist()
GET /{tenant}/denylist              → service.get_denylist()
```

All five require only `require_auth` (read-only).

---

## 4. Backend: ZPA router changes

File: `/Users/mike/Documents/CodeProjects/zs-config/api/routers/zpa.py`

Same pattern as ZIA: rewrite `_get_service` to accept `user: AuthUser`, call `check_tenant_access`, add `user: AuthUser = Depends(require_auth)` to every route handler.

`POST /{tenant}/certificates/rotate` — keep as `require_admin` since it is a mutation and file-path based. The web UI will not call it; it is CLI-only. Consider returning `400` with `{"detail": "Certificate rotation is not supported via the web API. Use the CLI."}` to make the restriction explicit, but do not remove the endpoint (it is used by scripts).

No new ZPA endpoints are needed.

---

## 5. Backend: new ZIA schema entries

File: `/Users/mike/Documents/CodeProjects/zs-config/api/schemas/zia.py`

No new Pydantic models are required; all new endpoints are GET-only with no request bodies.

---

## 6. Frontend: API client files

### 6.1 `web/src/api/zia.ts` (new file)

```typescript
import { apiFetch } from "./client";

export interface ActivationStatus {
  status: string;   // "ACTIVE" | "PENDING"
}

export interface UrlCategory {
  id: string;
  name: string;
  type: string;
  urlCount?: number;
}

export interface UrlLookupResult {
  url: string;
  urlClassifications: string[];
  urlClassificationsWithSecurityAlert: string[];
}

export interface UrlFilteringRule {
  id: number;
  name: string;
  order: number;
  action: string;
  state: string;
}

export interface ZiaUser {
  id: number;
  name: string;
  email: string;
  department?: { name: string };
}

export interface ZiaLocation {
  id: number;
  name: string;
  country?: string;
  ipAddresses?: string[];
}

export interface ZiaDepartment {
  id: number;
  name: string;
}

export interface ZiaGroup {
  id: number;
  name: string;
}

export interface AllowDenyList {
  blacklistUrls?: string[];
  whitelistUrls?: string[];
}

const base = (tenant: string) => `/api/v1/zia/${encodeURIComponent(tenant)}`;

export const fetchActivationStatus = (tenant: string): Promise<ActivationStatus> =>
  apiFetch<ActivationStatus>(`${base(tenant)}/activation/status`);

export const activateTenant = (tenant: string): Promise<unknown> =>
  apiFetch<unknown>(`${base(tenant)}/activation/activate`, { method: "POST" });

export const fetchUrlCategories = (tenant: string): Promise<UrlCategory[]> =>
  apiFetch<UrlCategory[]>(`${base(tenant)}/url-categories`);

export const lookupUrls = (tenant: string, urls: string[]): Promise<UrlLookupResult[]> =>
  apiFetch<UrlLookupResult[]>(`${base(tenant)}/url-lookup`, {
    method: "POST",
    body: JSON.stringify({ urls }),
  });

export const fetchUrlFilteringRules = (tenant: string): Promise<UrlFilteringRule[]> =>
  apiFetch<UrlFilteringRule[]>(`${base(tenant)}/url-filtering-rules`);

export const fetchUsers = (tenant: string, name?: string): Promise<ZiaUser[]> =>
  apiFetch<ZiaUser[]>(`${base(tenant)}/users${name ? `?name=${encodeURIComponent(name)}` : ""}`);

export const fetchLocations = (tenant: string): Promise<ZiaLocation[]> =>
  apiFetch<ZiaLocation[]>(`${base(tenant)}/locations`);

export const fetchDepartments = (tenant: string): Promise<ZiaDepartment[]> =>
  apiFetch<ZiaDepartment[]>(`${base(tenant)}/departments`);

export const fetchGroups = (tenant: string): Promise<ZiaGroup[]> =>
  apiFetch<ZiaGroup[]>(`${base(tenant)}/groups`);

export const fetchAllowlist = (tenant: string): Promise<AllowDenyList> =>
  apiFetch<AllowDenyList>(`${base(tenant)}/allowlist`);

export const fetchDenylist = (tenant: string): Promise<AllowDenyList> =>
  apiFetch<AllowDenyList>(`${base(tenant)}/denylist`);
```

### 6.2 `web/src/api/zpa.ts` (new file)

```typescript
import { apiFetch } from "./client";

export interface ZpaCertificate {
  id: string;
  name: string;
  description?: string;
  issuedTo?: string;
  issuedBy?: string;
  expireTime?: string;   // epoch seconds as string per SDK
  status?: string;
}

export interface ZpaApplication {
  id: string;
  name: string;
  enabled: boolean;
  applicationType?: string;
  domainNames?: string[];
}

export interface ZpaPraPortal {
  id: string;
  name: string;
  domain?: string;
  certificateId?: string;
  certificateName?: string;
}

const base = (tenant: string) => `/api/v1/zpa/${encodeURIComponent(tenant)}`;

export const fetchCertificates = (tenant: string): Promise<ZpaCertificate[]> =>
  apiFetch<ZpaCertificate[]>(`${base(tenant)}/certificates`);

export const fetchApplications = (tenant: string, appType = "BROWSER_ACCESS"): Promise<ZpaApplication[]> =>
  apiFetch<ZpaApplication[]>(`${base(tenant)}/applications?app_type=${encodeURIComponent(appType)}`);

export const fetchPraPortals = (tenant: string): Promise<ZpaPraPortal[]> =>
  apiFetch<ZpaPraPortal[]>(`${base(tenant)}/pra-portals`);
```

---

## 7. Frontend: routing changes

File: `/Users/mike/Documents/CodeProjects/zs-config/web/src/App.tsx`

Add one new route and remove the now-redundant stub pages:

```typescript
import TenantPage from "./pages/TenantPage";   // new

// inside <Routes>:
<Route path="/tenants" element={<TenantsPage />} />
<Route path="/tenants/:id" element={<TenantPage />} />  // new
// Remove or redirect /zia/:tenant and /zpa/:tenant to /tenants once TenantPage is live.
// Keep them for now as empty redirects to avoid broken bookmarks:
<Route path="/zia/:tenant" element={<Navigate to="/tenants" replace />} />
<Route path="/zpa/:tenant" element={<Navigate to="/tenants" replace />} />
```

`ZiaPage.tsx` and `ZpaPage.tsx` are superseded by sections inside `TenantPage`. They should be left in place but not imported by `App.tsx`. They can be deleted in a follow-up cleanup commit.

---

## 8. Frontend: TenantsPage dashboard redesign

File: `/Users/mike/Documents/CodeProjects/zs-config/web/src/pages/TenantsPage.tsx`

### 8.1 View toggle

Add a state variable `view: "grid" | "list"` initialized from `localStorage.getItem("tenants_view") ?? "grid"`. Persist on change: `localStorage.setItem("tenants_view", view)`.

Place a toggle control (two small icon buttons) in the page header row, to the left of the "Add Tenant" button.

### 8.2 Search bar

Add a `search` state string. Render an `<input>` below the header row. Filter `tenants` client-side: `tenants.filter(t => t.name.toLowerCase().includes(search.toLowerCase()))`. Apply this to both card and list views.

### 8.3 Card view

Each card:
- Clickable card body navigates to `/tenants/${t.id}` via `useNavigate`.
- Tenant name in `font-semibold`.
- `ValidationBadge` (reuse the existing component).
- ZIA cloud in `font-mono text-xs text-gray-500` (omit the field if null).
- GovCloud badge: small `bg-yellow-100 text-yellow-800` chip reading "GovCloud" — only rendered when `t.govcloud === true`.
- Notes excerpt: first 80 characters of `t.notes`, text-gray-400, only rendered when notes is non-empty.
- Admin-only `...` (kebab) button in the top-right corner of the card. Clicking it opens an inline dropdown (or toggles a `menuOpen` state per card) with: Import, Edit, Delete. This avoids having admin UI cluttering the card body for non-admin users.

Cards render in a `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4`.

### 8.4 List view

The existing table, with these changes:
- Tenant name column becomes a link: `<Link to={/tenants/${t.id}}>{t.name}</Link>`.
- Admin actions column (Import / Edit / Delete) moves into a `...` dropdown (same kebab pattern as cards) to reduce column noise.
- The `isAdmin &&` column guard is preserved — the kebab column is only rendered for admins.

### 8.5 Preserve existing modals

`CreateModal`, `EditModal`, `DeleteModal`, `ImportModal` remain unchanged and are still opened from the kebab menu.

---

## 9. Frontend: TenantPage (new file)

File: `/Users/mike/Documents/CodeProjects/zs-config/web/src/pages/TenantPage.tsx`

### 9.1 Route and data loading

Route: `/tenants/:id` where `id` is a numeric string.

On mount, call `fetchTenant(Number(id))` from `web/src/api/tenants.ts` (already exists). The `tenant.name` string is then used for all ZIA/ZPA API calls.

If the fetch returns 404, display "Tenant not found" and a back link to `/tenants`.

### 9.2 Page header

```
← Tenants    [tenant.name]   [ValidationBadge]   [zia_cloud mono chip]   [GovCloud chip?]
```

Back arrow is a `<Link to="/tenants">` with a left-chevron. The header is static once loaded — it does not refresh when tab content loads.

### 9.3 Tab bar

Two tabs: **ZIA** and **ZPA**.

ZPA tab is hidden (not rendered at all) when `tenant.zpa_customer_id` is null or empty. If ZPA tab is hidden, ZIA tab is always the active default.

Active tab state: `useState<"zia" | "zpa">("zia")`.

### 9.4 ZIA tab

Each section is an accordion/collapsible. Default state: all sections collapsed except Activation (which opens by default).

Accordion state: `useState<Record<string, boolean>>` keyed by section name, with `{ activation: true }` as the initial value.

Each section fetches its data lazily — only when first expanded. Use `enabled: sectionOpen` on React Query `useQuery` calls.

#### Section 1: Activation

Query key: `["zia-activation", tenant.name]`
Fetch: `fetchActivationStatus(tenant.name)`

Display:
- Status badge: `ACTIVE` → green, `PENDING` → yellow.
- Admin-only "Activate Now" button. On click, call `activateTenant(tenant.name)` and invalidate `["zia-activation", tenant.name]`.

#### Section 2: URL Categories

Query key: `["zia-url-categories", tenant.name]`
Fetch: `fetchUrlCategories(tenant.name)`

Display: a table with columns: ID, Name, Type. Add a text filter input above the table that filters by name client-side.

#### Section 3: URL Lookup

No query on mount. User pastes URLs (one per line) into a `<textarea>`. "Lookup" button calls `lookupUrls(tenant.name, urls)` as a mutation. Results rendered in a table: URL | Classifications | Security Alerts. Show a spinner while in-flight; show an error message if the mutation fails.

#### Section 4: URL Filtering Rules

Query key: `["zia-url-filtering-rules", tenant.name]`
Fetch: `fetchUrlFilteringRules(tenant.name)`

Display: table columns: Order, Name, Action, State.

#### Section 5: Users

Query key: `["zia-users", tenant.name]`
Fetch: `fetchUsers(tenant.name)`

Display: table columns: Name, Email, Department (extracted from `user.department?.name`). Add a text filter input above the table for name/email client-side filtering.

#### Section 6: Locations

Query key: `["zia-locations", tenant.name]`
Fetch: `fetchLocations(tenant.name)`

Display: table columns: Name, Country, IP Addresses (join with `, `, truncate at 3 with `+N more` if there are more).

#### Section 7: Allow / Deny Lists

Two parallel queries:
- `["zia-allowlist", tenant.name]` → `fetchAllowlist(tenant.name)`
- `["zia-denylist", tenant.name]` → `fetchDenylist(tenant.name)`

Both load when this section is expanded (use `enabled: sectionOpen["allowdeny"]`).

Display side-by-side (flex row on desktop, stacked on mobile):
- Left: "Allowlist" heading + scrollable list of `whitelistUrls` entries.
- Right: "Denylist" heading + scrollable list of `blacklistUrls` entries.

### 9.5 ZPA tab

Same accordion pattern. All sections collapsed by default.

#### Section 1: Certificates

Query key: `["zpa-certificates", tenant.name]`
Fetch: `fetchCertificates(tenant.name)`

Display: table columns: Name, Issued To, Expires, Status (derive from `expireTime` — show "Expired" in red if epoch is in the past, otherwise "Valid" in green).

Include a static note below the table: "Certificate rotation is only available via the CLI (`zs-config`)."

#### Section 2: Applications

Query key: `["zpa-applications", tenant.name]`
Fetch: `fetchApplications(tenant.name)` (default `appType="BROWSER_ACCESS"`)

Display: table columns: Name, Type, Domains (join first 3, `+N more`), Enabled (Yes/No badge). Add client-side text filter by name.

#### Section 3: PRA Portals

Query key: `["zpa-pra-portals", tenant.name]`
Fetch: `fetchPraPortals(tenant.name)`

Display: table columns: Name, Domain, Certificate Name.

---

## 10. Component reuse and shared patterns

### 10.1 Accordion component

Extract a reusable `Accordion` component if more than two usages exist across tabs. Signature:

```typescript
interface AccordionProps {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}
```

Renders a header bar with a disclosure triangle and the children in a collapsible div.

### 10.2 SearchableTable pattern

Several sections need a local text filter + table. Do not create a new abstraction for this — inline the filter `<input>` above each table directly. Each table section is small enough that the duplication is preferable to a generic component that adds complexity.

### 10.3 LoadingSpinner and ErrorMessage

Both already exist at `web/src/components/LoadingSpinner.tsx` and `web/src/components/ErrorMessage.tsx`. Use them for all section-level loading and error states.

---

## 11. File change summary

| File | Action | Notes |
|------|--------|-------|
| `api/dependencies.py` | Edit | Add `check_tenant_access()` |
| `api/routers/tenants.py` | Edit | `list_tenants` and `get_tenant` → `require_auth` + entitlement filter |
| `api/routers/zia.py` | Edit | Add `require_auth` + 5 new GET endpoints |
| `api/routers/zpa.py` | Edit | Add `require_auth` to all routes |
| `web/src/api/zia.ts` | Create | Typed wrappers for all ZIA endpoints |
| `web/src/api/zpa.ts` | Create | Typed wrappers for all ZPA endpoints |
| `web/src/App.tsx` | Edit | Add `/tenants/:id` route; redirect `/zia/:tenant` and `/zpa/:tenant` |
| `web/src/pages/TenantsPage.tsx` | Edit | Grid/list toggle, search bar, card view, kebab menu |
| `web/src/pages/TenantPage.tsx` | Create | Full workspace with ZIA and ZPA tab accordions |

`ZiaPage.tsx` and `ZpaPage.tsx` are no longer imported but are left on disk. They can be deleted in a cleanup pass.

---

## 12. Constraints and edge cases

### 12.1 Tenant name with special characters

ZIA and ZPA router paths use `{tenant}` as a string path parameter. `encodeURIComponent` is applied in both `zia.ts` and `zpa.ts` API client functions. FastAPI decodes path parameters automatically. No additional escaping is needed in the backend.

### 12.2 ZPA tab visibility

`TenantPage` receives the full `Tenant` object from `fetchTenant`. If `tenant.zpa_customer_id` is falsy, the ZPA tab button is not rendered and the ZPA sections are never mounted. This avoids a spurious 400 error from `_get_service` in the ZPA router.

### 12.3 Activation permission on the ZIA tab

The "Activate Now" button is only rendered when `isAdmin` is true (from `useAuth()`). Regular users see the status but cannot trigger activation. The backend `POST /{tenant}/activation/activate` also enforces `require_admin` as a second layer.

### 12.4 Lazy section loading

All section data fetches use `enabled: isExpanded` in their `useQuery` call. This avoids a burst of parallel Zscaler API calls when the TenantPage first mounts. The user controls the load rate by expanding sections.

### 12.5 `check_tenant_access` receives tenant_id (integer)

The ZIA and ZPA routers receive `{tenant}` as a name string. `_get_service` calls `get_tenant(tenant_name)` which returns a `TenantConfig` object. The integer `tenant.id` is extracted and passed to `check_tenant_access`. This lookup is inside the same helper so no extra DB round-trip is needed.

### 12.6 SQLite session constraint

`check_tenant_access` opens its own `with get_session()` block. It must never be called from inside an existing session. All callsites in the routers call it after the outer session (if any) has closed. This is already satisfied by the router structure — each router function opens sessions in separate `with` blocks, not nested.

### 12.7 `_serialize` does not expose `client_secret_enc`

The existing `_serialize` function in `tenants.py` already omits `client_secret_enc` and exposes only `has_credentials: bool`. No change needed. The ZIA and ZPA service layer calls `decrypt_secret` internally and the decrypted value never touches a response.

---

## 13. Out of scope

- ZIA write operations (create/edit URL categories, update users, etc.) — read-only display only.
- ZPA write operations other than the existing `delete_certificate` endpoint — not surfaced in the web UI.
- Pagination — all list endpoints return full collections. Zscaler's OneAPI lite endpoints are designed for full-list returns; client-side filtering is sufficient for MVP.
- ZPA `list_applications` with `app_type` selector UI — the web always fetches `BROWSER_ACCESS`. A dropdown to switch type can be added later.
- Snapshot and restore flows — covered by a separate spec.
- Audit log per-tenant filtering on the TenantPage — the existing `/audit` page can be linked from the TenantPage header as a follow-up.
