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

// Groups moved to ./groups — they are no longer SCIM-only, and the endpoints
// went with them.
