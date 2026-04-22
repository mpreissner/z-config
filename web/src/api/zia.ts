import { apiFetch } from "./client";

export interface ActivationStatus {
  status: string;
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
