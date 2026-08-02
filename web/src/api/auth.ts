import { apiFetch } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  force_password_change: boolean;
  mfa_enrollment_required?: boolean;
  active_role?: string;
  available_roles?: string[];
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function changePassword(current_password: string, new_password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
}

export interface AssumeRoleResponse {
  access_token: string;
  token_type: string;
  active_role: string;
  available_roles: string[];
}

/** Swap the session onto another of the account's roles. The server re-derives
 *  what is available, so a role revoked since login comes back 403. */
export function assumeRole(role: string): Promise<AssumeRoleResponse> {
  return apiFetch<AssumeRoleResponse>("/api/v1/auth/assume-role", {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}
