import { apiFetch } from "./client";

export interface ScimTokenRow {
  id: number;
  label: string | null;
  token_prefix: string;
  created_at: string | null;
  created_by: string | null;
  last_used_at: string | null;
  is_active: boolean;
}

/** The plaintext token is present only on the create response. */
export interface ScimTokenCreated extends ScimTokenRow {
  token: string;
}

export interface ScimGroupRow {
  id: number;
  display_name: string;
  external_id: string | null;
  mapped_role: string | null;
  member_count: number;
  updated_at: string | null;
}

export function fetchScimTokens(): Promise<ScimTokenRow[]> {
  return apiFetch<ScimTokenRow[]>("/api/v1/admin/scim/tokens");
}

export function createScimToken(label?: string): Promise<ScimTokenCreated> {
  return apiFetch<ScimTokenCreated>("/api/v1/admin/scim/tokens", {
    method: "POST",
    body: JSON.stringify({ label: label || null }),
  });
}

export function revokeScimToken(id: number): Promise<void> {
  return apiFetch<void>(`/api/v1/admin/scim/tokens/${id}`, { method: "DELETE" });
}

export function fetchScimGroups(): Promise<ScimGroupRow[]> {
  return apiFetch<ScimGroupRow[]>("/api/v1/admin/scim/groups");
}

export function mapScimGroup(id: number, mappedRole: string | null): Promise<ScimGroupRow> {
  return apiFetch<ScimGroupRow>(`/api/v1/admin/scim/groups/${id}`, {
    method: "PUT",
    body: JSON.stringify({ mapped_role: mappedRole }),
  });
}
