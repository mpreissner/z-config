import { apiFetch } from "./client";

export interface ActivationStatus {
  status: string;
}

export interface UrlCategory {
  id: string;
  name: string;
  configuredName?: string;
  type: string;
  urlCount?: number;
}

export interface UrlCategoryDetail {
  id: string;
  configuredName?: string;
  name?: string;
  type: string;
  urls?: string[];
  dbCategorizedUrls?: string[];
  customCategory?: boolean;
  superCategory?: string;
  description?: string;
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

// ── Mutations ─────────────────────────────────────────────────────────────────

export const createUrlCategory = (tenant: string, body: unknown): Promise<UrlCategory> =>
  apiFetch<UrlCategory>(`${base(tenant)}/url-categories`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateUrlCategory = (
  tenant: string,
  categoryId: string,
  body: unknown
): Promise<UrlCategory> =>
  apiFetch<UrlCategory>(`${base(tenant)}/url-categories/${encodeURIComponent(categoryId)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const createUrlFilteringRule = (tenant: string, body: unknown): Promise<UrlFilteringRule> =>
  apiFetch<UrlFilteringRule>(`${base(tenant)}/url-filtering-rules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateUrlFilteringRule = (
  tenant: string,
  ruleId: number,
  body: unknown
): Promise<UrlFilteringRule> =>
  apiFetch<UrlFilteringRule>(`${base(tenant)}/url-filtering-rules/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteUrlFilteringRule = (
  tenant: string,
  ruleId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/url-filtering-rules/${ruleId}`, {
    method: "DELETE",
  });

export const patchUrlFilteringRuleState = (
  tenant: string,
  ruleId: number,
  state: string
): Promise<UrlFilteringRule> =>
  apiFetch<UrlFilteringRule>(`${base(tenant)}/url-filtering-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

export const fetchUrlFilteringRule = (tenant: string, ruleId: number): Promise<Record<string, unknown>> =>
  apiFetch<Record<string, unknown>>(`${base(tenant)}/url-filtering-rules/${ruleId}`);

export const fetchUrlCategoryDetail = (tenant: string, categoryId: string): Promise<UrlCategoryDetail> =>
  apiFetch<UrlCategoryDetail>(`${base(tenant)}/url-categories/${categoryId}`);

export const addUrlsToCategory = (tenant: string, categoryId: string, urls: string[]): Promise<UrlCategoryDetail> =>
  apiFetch<UrlCategoryDetail>(`${base(tenant)}/url-categories/${categoryId}/urls`, {
    method: "POST",
    body: JSON.stringify({ urls }),
  });

export const removeUrlsFromCategory = (tenant: string, categoryId: string, urls: string[]): Promise<UrlCategoryDetail> =>
  apiFetch<UrlCategoryDetail>(`${base(tenant)}/url-categories/${categoryId}/urls`, {
    method: "DELETE",
    body: JSON.stringify({ urls }),
  });

export const createZiaUser = (tenant: string, body: unknown): Promise<ZiaUser> =>
  apiFetch<ZiaUser>(`${base(tenant)}/users`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateZiaUser = (
  tenant: string,
  userId: number,
  body: unknown
): Promise<ZiaUser> =>
  apiFetch<ZiaUser>(`${base(tenant)}/users/${userId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteZiaUser = (
  tenant: string,
  userId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/users/${userId}`, {
    method: "DELETE",
  });

export const updateAllowlist = (tenant: string, urls: string[]): Promise<AllowDenyList> =>
  apiFetch<AllowDenyList>(`${base(tenant)}/allowlist`, {
    method: "PUT",
    body: JSON.stringify({ whitelistUrls: urls }),
  });

export const updateDenylist = (tenant: string, urls: string[]): Promise<AllowDenyList> =>
  apiFetch<AllowDenyList>(`${base(tenant)}/denylist`, {
    method: "PUT",
    body: JSON.stringify({ blacklistUrls: urls }),
  });

// ── Firewall ──────────────────────────────────────────────────────────────────

export interface FirewallRule {
  id: number;
  name: string;
  order: number;
  action: string;
  state: string;
  description?: string;
}

export const fetchFirewallRules = (tenant: string): Promise<FirewallRule[]> =>
  apiFetch<FirewallRule[]>(`${base(tenant)}/firewall-rules`);

export const patchFirewallRuleState = (tenant: string, ruleId: number, state: string): Promise<FirewallRule> =>
  apiFetch<FirewallRule>(`${base(tenant)}/firewall-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

// ── SSL Inspection ────────────────────────────────────────────────────────────

export interface SslInspectionRule {
  id: number;
  name: string;
  order: number;
  action: string;
  state: string;
  description?: string;
}

export const fetchSslInspectionRules = (tenant: string): Promise<SslInspectionRule[]> =>
  apiFetch<SslInspectionRule[]>(`${base(tenant)}/ssl-inspection-rules`);

export const patchSslRuleState = (tenant: string, ruleId: number, state: string): Promise<SslInspectionRule> =>
  apiFetch<SslInspectionRule>(`${base(tenant)}/ssl-inspection-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

// ── Traffic Forwarding ────────────────────────────────────────────────────────

export interface ForwardingRule {
  id: number;
  name: string;
  order: number;
  type: string;
  state: string;
  description?: string;
}

export const fetchForwardingRules = (tenant: string): Promise<ForwardingRule[]> =>
  apiFetch<ForwardingRule[]>(`${base(tenant)}/forwarding-rules`);

// ── DLP ───────────────────────────────────────────────────────────────────────

export interface DlpEngine {
  id: number;
  name: string;
  description?: string;
  predefinedEngine?: boolean;
}

export interface DlpDictionary {
  id: number;
  name: string;
  type?: string;
  description?: string;
}

export interface DlpWebRule {
  id: number;
  name: string;
  order: number;
  action: string;
  state: string;
}

export const fetchDlpEngines = (tenant: string): Promise<DlpEngine[]> =>
  apiFetch<DlpEngine[]>(`${base(tenant)}/dlp-engines`);

export const fetchDlpDictionaries = (tenant: string): Promise<DlpDictionary[]> =>
  apiFetch<DlpDictionary[]>(`${base(tenant)}/dlp-dictionaries`);

export const fetchDlpWebRules = (tenant: string): Promise<DlpWebRule[]> =>
  apiFetch<DlpWebRule[]>(`${base(tenant)}/dlp-web-rules`);

// ── Cloud App Controls ────────────────────────────────────────────────────────

export interface CloudAppSetting {
  id?: number;
  name?: string;
  state?: string;
  action?: string;
  [key: string]: unknown;
}

export const fetchCloudAppSettings = (tenant: string): Promise<CloudAppSetting[]> =>
  apiFetch<CloudAppSetting[]>(`${base(tenant)}/cloud-app-settings`);

// ── Snapshots ─────────────────────────────────────────────────────────────────

export interface ConfigSnapshot {
  id: number;
  label: string | null;
  product: string;
  created_at: string | null;
  resource_count: number;
}

export const fetchSnapshots = (tenant: string, product = "ZIA"): Promise<ConfigSnapshot[]> =>
  apiFetch<ConfigSnapshot[]>(`${base(tenant)}/snapshots?product=${product}`);

export const createSnapshot = (tenant: string, label?: string, product = "ZIA"): Promise<ConfigSnapshot> =>
  apiFetch<ConfigSnapshot>(`${base(tenant)}/snapshots`, {
    method: "POST",
    body: JSON.stringify({ label: label || null, product }),
  });

export const deleteSnapshot = (tenant: string, snapshotId: number): Promise<void> =>
  apiFetch<void>(`${base(tenant)}/snapshots/${snapshotId}`, { method: "DELETE" });
