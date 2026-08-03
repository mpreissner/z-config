/**
 * Groups: membership, role mapping, and the tenants a group grants.
 *
 * `source` says who owns the record — "scim" for anything the identity
 * provider pushed, "local" for a group an admin created here. The API refuses
 * to rename or delete a SCIM group and to remove a SCIM-owned membership, so
 * the UI disables those controls rather than letting the request fail.
 */

import { apiFetch } from "./client";

export interface Group {
  id: number;
  display_name: string;
  description: string | null;
  external_id: string | null;
  mapped_role: string | null;
  source: "scim" | "local";
  member_count: number;
  tenant_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface GroupMember {
  user_id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  /** Whether the IdP put this person in the group, or an admin did. */
  source: "scim" | "local";
  added_at: string | null;
  added_by: string | null;
}

export interface GroupTenantGrant {
  id: number;
  group_id: number;
  tenant_id: number;
  tenant_name: string;
  granted_at: string | null;
  granted_by: string | null;
}

export const fetchGroups = (): Promise<Group[]> => apiFetch("/api/v1/admin/groups");

export const createGroup = (
  displayName: string,
  description?: string | null,
  mappedRole?: string | null,
): Promise<Group> =>
  apiFetch("/api/v1/admin/groups", {
    method: "POST",
    body: JSON.stringify({
      display_name: displayName,
      description: description || null,
      mapped_role: mappedRole || null,
    }),
  });

/**
 * Patch a group. Only the keys present are touched, which is what lets
 * `mapped_role: null` mean "clear the mapping" rather than "leave it alone".
 */
export const updateGroup = (
  id: number,
  patch: { display_name?: string; description?: string | null; mapped_role?: string | null },
): Promise<Group> =>
  apiFetch(`/api/v1/admin/groups/${id}`, { method: "PATCH", body: JSON.stringify(patch) });

export const setGroupRole = (id: number, mappedRole: string | null): Promise<Group> =>
  updateGroup(id, { mapped_role: mappedRole });

export const deleteGroup = (id: number): Promise<void> =>
  apiFetch(`/api/v1/admin/groups/${id}`, { method: "DELETE" });

export const fetchGroupMembers = (id: number): Promise<GroupMember[]> =>
  apiFetch(`/api/v1/admin/groups/${id}/members`);

export const addGroupMembers = (
  id: number,
  userIds: number[],
): Promise<{ added: number[]; skipped: number[]; group_name: string }> =>
  apiFetch(`/api/v1/admin/groups/${id}/members`, {
    method: "POST",
    body: JSON.stringify({ user_ids: userIds }),
  });

export const removeGroupMember = (id: number, userId: number): Promise<void> =>
  apiFetch(`/api/v1/admin/groups/${id}/members/${userId}`, { method: "DELETE" });

export const fetchGroupTenants = (id: number): Promise<GroupTenantGrant[]> =>
  apiFetch(`/api/v1/admin/groups/${id}/tenants`);

export const grantGroupTenants = (
  id: number,
  tenantIds: number[],
): Promise<{ granted: number[]; skipped: number[]; group_name: string }> =>
  apiFetch(`/api/v1/admin/groups/${id}/tenants`, {
    method: "POST",
    body: JSON.stringify({ tenant_ids: tenantIds }),
  });

export const revokeGroupTenant = (id: number, tenantId: number): Promise<void> =>
  apiFetch(`/api/v1/admin/groups/${id}/tenants/${tenantId}`, { method: "DELETE" });
