# License-Based Feature Visibility

**Goal**: Conditionally hide UI sections (accordions) when the tenant lacks the required ZIA subscription.

## Current State

`TenantConfig` has a `zia_subscriptions` column (JSON, nullable) that stores the full response from `GET /subscriptions` fetched at tenant creation time. However:

- `_serialize()` in `api/routers/tenants.py` does **not** include `zia_subscriptions` in the tenant response.
- The frontend `Tenant` interface in `web/src/api/tenants.ts` has no subscription field.
- The TUI has `_is_zia_resource_na(tenant_id, resource_type)` which checks `zia_disabled_resources` — resources auto-disabled after a 401 — not subscription entitlements. These are related but separate mechanisms.

## Subscription Data Shape

The ZIA `/subscriptions` endpoint returns a JSON object. A representative payload (verify against a real tenant):

```json
{
  "featureEnabled": true,
  "subscriptionType": "ZSCALER_INTERNET_ACCESS",
  "subscriptionAddons": ["ADVANCED_FIREWALL_PROTECTION", "SSL_INSPECTION", ...],
  ...
}
```

Key fields to check (confirm exact names by logging `zia_subscriptions` for a known tenant via SQLite):

```bash
sqlite3 /app/data/config.db "SELECT json_extract(zia_subscriptions, '$') FROM tenant_config WHERE name='zsnet';"
```

## What Needs to Be Built

### 1. Expose subscriptions via the API

In `api/routers/tenants.py`, add to `_serialize()`:

```python
"zia_subscriptions": t.zia_subscriptions,  # full JSON blob, may be null
```

Add to the frontend `Tenant` interface in `web/src/api/tenants.ts`:

```typescript
zia_subscriptions: Record<string, unknown> | null;
```

### 2. Add a "Refresh Licenses" button

Add a new endpoint:

```
POST /api/v1/tenants/{tenant_id}/refresh-subscriptions
```

Implementation: call `fetch_org_info(...)` for that tenant, update `tenant.zia_subscriptions`, return the updated tenant. Wiring follows the same pattern as credential validation in `POST /api/v1/tenants/{tenant_id}/validate`.

In the frontend, add a small "Refresh Licenses" button near the tenant header or settings panel (low-prominence, e.g., next to the cloud/tenant ID metadata line). On success, invalidate the tenant query so the accordion visibility updates immediately.

### 3. Feature → subscription flag mapping

Define a mapping in the frontend (suggested location: `web/src/lib/subscriptionFeatures.ts`):

```typescript
export const SUBSCRIPTION_REQUIREMENTS: Record<string, (subs: Record<string, unknown>) => boolean> = {
  ipsRules: (subs) => {
    const addons = (subs.subscriptionAddons as string[] | undefined) ?? [];
    return addons.includes("ADVANCED_FIREWALL_PROTECTION");
  },
  // future: dnsFilterRules, sslInspection, etc.
};
```

Exact flag names must be confirmed from real subscription data (see the SQLite query above). DNS Filter Rules may be included in the base subscription; IPS Rules requires Advanced Firewall.

### 4. Conditional accordion rendering

In `TenantWorkspacePage.tsx`, before rendering each accordion:

```typescript
const canSeeIpsRules = !tenant.zia_subscriptions
  || SUBSCRIPTION_REQUIREMENTS.ipsRules(tenant.zia_subscriptions);
```

Use `!zia_subscriptions` as a fallback-to-visible: if we have no subscription data, show everything (avoids hiding features from tenants whose subscription fetch failed at creation time).

Then wrap the accordion:

```tsx
{canSeeIpsRules && (
  <Accordion title="IPS Rules" ...>
    <FirewallIpsRulesSection ... />
  </Accordion>
)}
```

## Sections That Likely Require Subscriptions

| UI Section | Likely Required Subscription Flag |
|---|---|
| IPS Rules | `ADVANCED_FIREWALL_PROTECTION` (or similar) |
| DNS Filter Rules | Base subscription (probably always visible) |
| SSL Inspection (future) | `SSL_INSPECTION` |
| CASB / SaaS Security (future) | varies |

Verify each by comparing what's visible in the ZIA admin portal for `commercial-zs2` vs `zsnet`.

## Recommended Implementation Order

1. Inspect real subscription JSON from `zsnet` and `commercial-zs2` (SQLite query above).
2. Expose `zia_subscriptions` in `_serialize()` and `Tenant` type.
3. Build the subscription requirements map with confirmed flag names.
4. Add conditional rendering for IPS Rules accordion.
5. Add "Refresh Licenses" endpoint + button.

## TUI Parallel

The TUI already handles this via `_is_zia_resource_na()` checking `zia_disabled_resources` (populated after a 401). Once subscription-based flags are confirmed, consider also populating `zia_disabled_resources` from subscription data at creation time so the TUI suppresses those menu items proactively. This is a nice-to-have, not a blocker.
