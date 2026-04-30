import { apiFetch } from "./client";

export interface AdminUser {
  id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  force_password_change: boolean;
  mfa_required: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface UserCreate {
  username: string;
  password: string;
  email?: string;
  role: "admin" | "user";
  force_password_change: boolean;
}

export interface UserUpdate {
  email?: string;
  role?: "admin" | "user";
  is_active?: boolean;
  force_password_change?: boolean;
  mfa_required?: boolean;
  password?: string;
}

export interface Entitlement {
  id: number;
  user_id: number;
  username: string;
  tenant_id: number;
  tenant_name: string;
  granted_at: string;
}

export function fetchAdminUsers(): Promise<AdminUser[]> {
  return apiFetch("/api/v1/admin/users");
}

export function createAdminUser(body: UserCreate): Promise<AdminUser> {
  return apiFetch("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateAdminUser(id: number, body: UserUpdate): Promise<AdminUser> {
  return apiFetch(`/api/v1/admin/users/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteAdminUser(id: number): Promise<void> {
  return apiFetch(`/api/v1/admin/users/${id}`, { method: "DELETE" });
}

export function fetchEntitlements(): Promise<Entitlement[]> {
  return apiFetch("/api/v1/admin/entitlements");
}

export function createEntitlement(user_id: number, tenant_id: number): Promise<Entitlement> {
  return apiFetch("/api/v1/admin/entitlements", {
    method: "POST",
    body: JSON.stringify({ user_id, tenant_id }),
  });
}

export function deleteEntitlement(id: number): Promise<void> {
  return apiFetch(`/api/v1/admin/entitlements/${id}`, { method: "DELETE" });
}

export interface ImportDbResult {
  ok: boolean;
  message: string;
  seeded_admin: boolean;
  temp_password: string | null;
}

export function importDatabase(dbFile: File, keyFile?: File): Promise<ImportDbResult> {
  const form = new FormData();
  form.append("db_file", dbFile);
  if (keyFile) form.append("key_file", keyFile);
  return apiFetch("/api/v1/admin/import-db", { method: "POST", body: form });
}

export interface ClearDataResult {
  zia: number;
  zpa: number;
  zcc: number;
  snapshots: number;
  sync_logs: number;
  audit_entries: number;
}

export function clearData(tenantId?: number): Promise<ClearDataResult> {
  return apiFetch("/api/v1/admin/clear-data", {
    method: "POST",
    body: JSON.stringify({ tenant_id: tenantId ?? null }),
  });
}
