import { apiFetch } from "./client";

export interface ZpaCertificate {
  id: string;
  name: string;
  description?: string;
  issuedTo?: string;
  issuedBy?: string;
  expireTime?: string;
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
