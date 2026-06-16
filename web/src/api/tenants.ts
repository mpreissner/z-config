import { apiFetch, getAuthHeaders } from "./client";

export interface Tenant {
  id: number;
  name: string;
  vanity_domain: string;
  zidentity_base_url: string;
  oneapi_base_url: string;
  client_id: string;
  has_credentials: boolean;
  govcloud: boolean;
  zpa_customer_id: string | null;
  zia_tenant_id: string | null;
  zia_cloud: string | null;
  last_validation_error: string | null;
  notes: string | null;
  created_at: string | null;
  zia_subscriptions: unknown | null;
}

export interface TenantCreate {
  name: string;
  vanity_domain: string;
  client_id: string;
  client_secret: string;
  govcloud?: boolean;
  govcloud_oneapi_url?: string;
  zpa_customer_id?: string;
  notes?: string;
}

export interface TenantUpdate {
  vanity_domain?: string;
  client_id?: string;
  client_secret?: string;
  govcloud?: boolean;
  govcloud_oneapi_url?: string;
  zpa_customer_id?: string;
  notes?: string;
}

export interface ImportResult {
  status: string;
  resources_synced: number;
  resources_updated: number;
  error_message: string | null;
}

export interface JobRef {
  job_id: string;
}

export const fetchTenants = (): Promise<Tenant[]> =>
  apiFetch<Tenant[]>("/api/v1/tenants");

export const fetchTenant = (id: number): Promise<Tenant> =>
  apiFetch<Tenant>(`/api/v1/tenants/${id}`);

export const createTenant = (body: TenantCreate): Promise<Tenant> =>
  apiFetch<Tenant>("/api/v1/tenants", { method: "POST", body: JSON.stringify(body) });

export const updateTenant = (id: number, body: TenantUpdate): Promise<Tenant> =>
  apiFetch<Tenant>(`/api/v1/tenants/${id}`, { method: "PUT", body: JSON.stringify(body) });

export const deleteTenant = (id: number): Promise<void> =>
  apiFetch<void>(`/api/v1/tenants/${id}`, { method: "DELETE" });

export const importZIA = (id: number): Promise<JobRef> =>
  apiFetch<JobRef>(`/api/v1/tenants/${id}/import/zia`, { method: "POST" });

export const importZPA = (id: number): Promise<JobRef> =>
  apiFetch<JobRef>(`/api/v1/tenants/${id}/import/zpa`, { method: "POST" });

export const importZCC = (id: number): Promise<JobRef> =>
  apiFetch<JobRef>(`/api/v1/tenants/${id}/import/zcc`, { method: "POST" });

export const clearZCCDisabledResources = (id: number): Promise<{ cleared: string[] }> =>
  apiFetch<{ cleared: string[] }>(`/api/v1/tenants/${id}/import/zcc/disabled-resources`, { method: "DELETE" });

export interface PolicyCheck {
  engine: string;
  matched: boolean;
  rule_name: string | null;
  action: string | null;
  reason: string;
  category: string | null;
  caveats: string[];
}

export interface SimulationResult {
  destination: string;
  port: number;
  protocol: string;
  zpa: PolicyCheck;
  zia_firewall: PolicyCheck;
  zia_dns: PolicyCheck;
  zia_url: PolicyCheck;
  verdict: "ZPA" | "ZIA_ALLOW" | "ZIA_BLOCK_FIREWALL" | "ZIA_BLOCK_DNS" | "ZIA_BLOCK_URL" | "INTERNET";
  verdict_label: string;
}

export interface SimulateParams {
  destination: string;
  port: number;
  protocol: string;
  nwApplication?: string;
  appServiceGroup?: string;
  srcIp?: string;
  userName?: string;
  deptName?: string;
  groupName?: string;
  locationName?: string;
}

export const simulateTraffic = (tenantId: number, p: SimulateParams): Promise<SimulationResult> =>
  apiFetch<SimulationResult>(`/api/v1/tenants/${tenantId}/simulate`, {
    method: "POST",
    body: JSON.stringify({
      destination: p.destination,
      port: p.port,
      protocol: p.protocol,
      nw_application: p.nwApplication || null,
      app_service_group: p.appServiceGroup || null,
      src_ip: p.srcIp || null,
      user_name: p.userName || null,
      dept_name: p.deptName || null,
      group_name: p.groupName || null,
      location_name: p.locationName || null,
    }),
    headers: { "Content-Type": "application/json" },
  });

export const fetchSimApplications = (tenantId: number): Promise<string[]> =>
  apiFetch<string[]>(`/api/v1/tenants/${tenantId}/simulate/applications`);

export const fetchSimAppServiceGroups = (tenantId: number): Promise<string[]> =>
  apiFetch<string[]>(`/api/v1/tenants/${tenantId}/simulate/app-service-groups`);

export const fetchSimUsers = (tenantId: number): Promise<string[]> =>
  apiFetch<string[]>(`/api/v1/tenants/${tenantId}/simulate/users`);

export const fetchSimDepartments = (tenantId: number): Promise<string[]> =>
  apiFetch<string[]>(`/api/v1/tenants/${tenantId}/simulate/departments`);

export const fetchSimGroups = (tenantId: number): Promise<string[]> =>
  apiFetch<string[]>(`/api/v1/tenants/${tenantId}/simulate/groups`);

export const fetchSimLocations = (tenantId: number): Promise<string[]> =>
  apiFetch<string[]>(`/api/v1/tenants/${tenantId}/simulate/locations`);

export async function downloadTerraform(tenantId: number, product: "zia" | "zpa", tenantName: string): Promise<void> {
  const res = await fetch(`/api/v1/tenants/${tenantId}/terraform/${product}`, {
    headers: getAuthHeaders(),
    credentials: "include",
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${tenantName.replace(/\s+/g, "_")}_${product}.tf`;
  a.click();
  URL.revokeObjectURL(url);
}

export interface SnapshotDiffItem {
  action: "create" | "update" | "delete";
  resource_type: string;
  name: string;
}

export interface SnapshotPreview {
  snapshot_name: string;
  snapshot_comment: string | null;
  snapshot_created: string;
  snapshot_resource_count: number;
  creates: number;
  updates: number;
  skips: number;
  deletes: number;
  items: SnapshotDiffItem[];
}

export interface ApplySnapshotFailedItem {
  resource_type: string;
  name: string;
  reason: string;
}

export interface ApplySnapshotWarning {
  resource_type: string;
  name: string;
  warnings: string[];
}

export interface ApplySnapshotResult {
  status: string;
  snapshot_name: string;
  mode: "wipe" | "delta" | "full_clone" | "full_clone_wipe";
  wiped: number;
  created: number;
  updated: number;
  deleted: number;
  failed: number;
  failed_items: ApplySnapshotFailedItem[];
  warnings: ApplySnapshotWarning[];
  cancelled?: boolean;
  rolled_back?: number;
  rollback_failed?: number;
}

export const previewApplySnapshot = (
  targetTenantId: number,
  sourceTenantId: number,
  snapshotId: number,
  fullClone = false,
): Promise<JobRef> =>
  apiFetch<JobRef>(`/api/v1/tenants/${targetTenantId}/snapshots/preview`, {
    method: "POST",
    body: JSON.stringify({
      source_tenant_id: sourceTenantId,
      snapshot_id: snapshotId,
      full_clone: fullClone,
    }),
  });

export const applySnapshot = (
  targetTenantId: number,
  sourceTenantId: number,
  snapshotId: number,
  wipeMode = false,
  fullClone = false,
): Promise<JobRef> =>
  apiFetch<JobRef>(`/api/v1/tenants/${targetTenantId}/snapshots/apply`, {
    method: "POST",
    body: JSON.stringify({
      source_tenant_id: sourceTenantId,
      snapshot_id: snapshotId,
      wipe_mode: wipeMode,
      full_clone: fullClone,
    }),
  });
