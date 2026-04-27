import { apiFetch, getAuthHeaders } from "./client";

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
  predefined?: boolean;
  nwServices?: Array<{id: number; name: string}>;
  srcIpGroups?: Array<{id: number; name: string}>;
  destIpGroups?: Array<{id: number; name: string}>;
  locations?: Array<{id: number; name: string}>;
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
  predefined?: boolean;
  urlCategories?: string[];
  departments?: Array<{id: number; name: string}>;
  groups?: Array<{id: number; name: string}>;
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
  predefined?: boolean;
}

export const fetchForwardingRules = (tenant: string): Promise<ForwardingRule[]> =>
  apiFetch<ForwardingRule[]>(`${base(tenant)}/forwarding-rules`);

export const patchForwardingRuleState = (tenant: string, ruleId: number, state: string): Promise<ForwardingRule> =>
  apiFetch<ForwardingRule>(`${base(tenant)}/forwarding-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

// ── Firewall DNS Filter Rules ─────────────────────────────────────────────────

export interface FirewallDnsRule {
  id: number;
  name: string;
  order: number;
  action?: string | { type: string };
  state: string;
  description?: string;
  predefined?: boolean;
}

export const fetchFirewallDnsRules = (tenant: string): Promise<FirewallDnsRule[]> =>
  apiFetch<FirewallDnsRule[]>(`${base(tenant)}/firewall-dns-rules`);

export const patchFirewallDnsRuleState = (tenant: string, ruleId: number, state: string): Promise<FirewallDnsRule> =>
  apiFetch<FirewallDnsRule>(`${base(tenant)}/firewall-dns-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

// ── Firewall IPS Rules ────────────────────────────────────────────────────────

export interface FirewallIpsRule {
  id: number;
  name: string;
  order: number;
  action?: string | { type: string };
  state: string;
  description?: string;
  predefined?: boolean;
}

export const fetchFirewallIpsRules = (tenant: string): Promise<FirewallIpsRule[]> =>
  apiFetch<FirewallIpsRule[]>(`${base(tenant)}/firewall-ips-rules`);

export const patchFirewallIpsRuleState = (tenant: string, ruleId: number, state: string): Promise<FirewallIpsRule> =>
  apiFetch<FirewallIpsRule>(`${base(tenant)}/firewall-ips-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

// ── DLP ───────────────────────────────────────────────────────────────────────

export interface DlpEngine {
  id: number;
  name: string;
  description?: string;
  predefinedEngine?: boolean;
  engine_expression?: string;
  custom_dlp_engine?: boolean;
}

export interface DlpDictionary {
  id: number;
  name: string;
  type?: string;
  description?: string;
  confidence_threshold?: string;
  confidenceThreshold?: string;
  threshold_allowed?: boolean;
  thresholdAllowed?: boolean;
  predefined_phrases?: string[];
}

export interface DlpWebRule {
  id: number;
  name: string;
  order: number;
  action: string;
  state: string;
  description?: string;
  protocols?: string[];
  dlpEngines?: Array<{id: number; name: string}>;
  predefined?: boolean;
}

export const fetchDlpEngines = (tenant: string): Promise<DlpEngine[]> =>
  apiFetch<DlpEngine[]>(`${base(tenant)}/dlp-engines`);

export const fetchDlpDictionaries = (tenant: string): Promise<DlpDictionary[]> =>
  apiFetch<DlpDictionary[]>(`${base(tenant)}/dlp-dictionaries`);

export const fetchDlpWebRules = (tenant: string): Promise<DlpWebRule[]> =>
  apiFetch<DlpWebRule[]>(`${base(tenant)}/dlp-web-rules`);

export const patchDlpDictionaryConfidence = (
  tenant: string,
  dictId: number,
  confidenceThreshold: string
): Promise<DlpDictionary> =>
  apiFetch<DlpDictionary>(`${base(tenant)}/dlp-dictionaries/${dictId}/confidence`, {
    method: "PATCH",
    body: JSON.stringify({ confidenceThreshold }),
  });

export const patchDlpWebRuleState = (tenant: string, ruleId: number, state: string): Promise<DlpWebRule> =>
  apiFetch<DlpWebRule>(`${base(tenant)}/dlp-web-rules/${ruleId}/state`, {
    method: "PATCH",
    body: JSON.stringify({ state }),
  });

// ── URL Category CRUD ─────────────────────────────────────────────────────────

export const deleteUrlCategory = (
  tenant: string,
  categoryId: string
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/url-categories/${encodeURIComponent(categoryId)}`, {
    method: "DELETE",
  });

// ── URL Filtering Rule CRUD (delete already exists; here for completeness) ───

// ── Firewall Rule CRUD ────────────────────────────────────────────────────────

export const getFirewallRule = (tenant: string, ruleId: number): Promise<FirewallRule> =>
  apiFetch<FirewallRule>(`${base(tenant)}/firewall-rules/${ruleId}`);

export const createFirewallRule = (tenant: string, body: unknown): Promise<FirewallRule> =>
  apiFetch<FirewallRule>(`${base(tenant)}/firewall-rules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateFirewallRule = (
  tenant: string,
  ruleId: number,
  body: unknown
): Promise<FirewallRule> =>
  apiFetch<FirewallRule>(`${base(tenant)}/firewall-rules/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteFirewallRule = (
  tenant: string,
  ruleId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/firewall-rules/${ruleId}`, {
    method: "DELETE",
  });

// ── SSL Inspection Rule CRUD ──────────────────────────────────────────────────

export const getSslInspectionRule = (tenant: string, ruleId: number): Promise<SslInspectionRule> =>
  apiFetch<SslInspectionRule>(`${base(tenant)}/ssl-inspection-rules/${ruleId}`);

export const createSslInspectionRule = (tenant: string, body: unknown): Promise<SslInspectionRule> =>
  apiFetch<SslInspectionRule>(`${base(tenant)}/ssl-inspection-rules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateSslInspectionRule = (
  tenant: string,
  ruleId: number,
  body: unknown
): Promise<SslInspectionRule> =>
  apiFetch<SslInspectionRule>(`${base(tenant)}/ssl-inspection-rules/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteSslInspectionRule = (
  tenant: string,
  ruleId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/ssl-inspection-rules/${ruleId}`, {
    method: "DELETE",
  });

// ── Forwarding Rule CRUD ──────────────────────────────────────────────────────

export const getForwardingRule = (tenant: string, ruleId: number): Promise<ForwardingRule> =>
  apiFetch<ForwardingRule>(`${base(tenant)}/forwarding-rules/${ruleId}`);

export const createForwardingRule = (tenant: string, body: unknown): Promise<ForwardingRule> =>
  apiFetch<ForwardingRule>(`${base(tenant)}/forwarding-rules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateForwardingRule = (
  tenant: string,
  ruleId: number,
  body: unknown
): Promise<ForwardingRule> =>
  apiFetch<ForwardingRule>(`${base(tenant)}/forwarding-rules/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteForwardingRule = (
  tenant: string,
  ruleId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/forwarding-rules/${ruleId}`, {
    method: "DELETE",
  });

// ── DLP Web Rule CRUD ─────────────────────────────────────────────────────────

export const getDlpWebRule = (tenant: string, ruleId: number): Promise<DlpWebRule> =>
  apiFetch<DlpWebRule>(`${base(tenant)}/dlp-web-rules/${ruleId}`);

export const createDlpWebRule = (tenant: string, body: unknown): Promise<DlpWebRule> =>
  apiFetch<DlpWebRule>(`${base(tenant)}/dlp-web-rules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateDlpWebRule = (
  tenant: string,
  ruleId: number,
  body: unknown
): Promise<DlpWebRule> =>
  apiFetch<DlpWebRule>(`${base(tenant)}/dlp-web-rules/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteDlpWebRule = (
  tenant: string,
  ruleId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/dlp-web-rules/${ruleId}`, {
    method: "DELETE",
  });

// ── DLP Engine CRUD ───────────────────────────────────────────────────────────

export const getDlpEngine = (tenant: string, engineId: number): Promise<DlpEngine> =>
  apiFetch<DlpEngine>(`${base(tenant)}/dlp-engines/${engineId}`);

export const createDlpEngine = (tenant: string, body: unknown): Promise<DlpEngine> =>
  apiFetch<DlpEngine>(`${base(tenant)}/dlp-engines`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateDlpEngine = (
  tenant: string,
  engineId: number,
  body: unknown
): Promise<DlpEngine> =>
  apiFetch<DlpEngine>(`${base(tenant)}/dlp-engines/${engineId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteDlpEngine = (
  tenant: string,
  engineId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/dlp-engines/${engineId}`, {
    method: "DELETE",
  });

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

export interface CloudAppPolicy {
  app?: string;
  app_name?: string;
  app_class?: string;
  policy?: string;
  [key: string]: unknown;
}

export interface CloudAppControlRule {
  id?: number;
  name?: string;
  type?: string;
  order?: number;
  state?: string;
  action?: string;
  description?: string;
  [key: string]: unknown;
}

export interface TenancyRestrictionProfile {
  id?: number;
  name?: string;
  description?: string;
  app_type?: string;
  item_type_primary?: string;
  item_data_primary?: string;
  item_type_secondary?: string;
  item_data_secondary?: string;
  item_value?: string;
  restrict_personal_o365_domains?: boolean;
  allow_google_consumers?: boolean;
  ms_login_services_trv2?: boolean;
  allow_google_visitors?: boolean;
  allow_gcp_cloud_storage_read?: boolean;
  [key: string]: unknown;
}

export interface CloudAppInstance {
  instance_id?: number;
  instance_name?: string;
  instance_type?: string;
  modified_at?: string;
  instance_identifiers?: Array<{
    instance_id?: number;
    instance_identifier?: string;
    instance_identifier_name?: string;
    identifier_type?: string;
  }>;
  [key: string]: unknown;
}

export const fetchCloudAppPolicies = (tenant: string): Promise<CloudAppPolicy[]> =>
  apiFetch<CloudAppPolicy[]>(`${base(tenant)}/cloud-app-policies`);

export const fetchCloudAppInstances = (tenant: string): Promise<CloudAppInstance[]> =>
  apiFetch<CloudAppInstance[]>(`${base(tenant)}/cloud-app-instances`);

export const fetchCloudAppControlRules = (tenant: string): Promise<CloudAppControlRule[]> =>
  apiFetch<CloudAppControlRule[]>(`${base(tenant)}/cloud-app-control-rules`);

export const fetchTenancyRestrictionProfiles = (tenant: string): Promise<TenancyRestrictionProfile[]> =>
  apiFetch<TenancyRestrictionProfile[]>(`${base(tenant)}/tenancy-restriction-profiles`);

export const patchCloudAppRuleState = (
  tenant: string,
  ruleType: string,
  ruleId: number,
  state: string,
): Promise<CloudAppControlRule> =>
  apiFetch<CloudAppControlRule>(
    `${base(tenant)}/cloud-app-control-rules/${encodeURIComponent(ruleType)}/${ruleId}/state`,
    { method: "PATCH", body: JSON.stringify({ state }) },
  );

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

// ── Firewall CSV Export / Sync ────────────────────────────────────────────────

export async function exportFirewallRulesToCsv(tenant: string, tenantName: string): Promise<void> {
  const res = await fetch(`/api/v1/zia/${encodeURIComponent(tenant)}/firewall-rules/export-csv`, {
    headers: getAuthHeaders(),
    credentials: "include",
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `firewall_rules_${tenantName}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function syncFirewallRulesFromCsv(
  tenant: string,
  file: File
): Promise<{ created: number; updated: number; deleted: number; skipped: number; errors: string[] }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api/v1/zia/${encodeURIComponent(tenant)}/firewall-rules/sync-csv`, {
    method: "POST",
    headers: getAuthHeaders(),
    credentials: "include",
    body: fd,
  });
  if (!res.ok) throw new Error("Sync failed");
  return res.json();
}
