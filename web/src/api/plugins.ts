/**
 * Plugin manager client.
 *
 * Every path here is served only by a deployment that switched the manager on
 * (see api/routers/plugins.py). Everywhere else these addresses hit the SPA
 * catch-all and come back as index.html, so nothing in the UI may assume the
 * endpoints exist — probePluginManager() decides that once, and the nav and
 * route hang off its answer.
 */

import { apiFetch } from "./client";

export interface InstalledPlugin {
  name: string | null;
  package: string | null;
  version: string | null;
  entry_point: string | null;
  has_menu: boolean;
  error: string | null;
}

export interface AvailablePlugin {
  name: string;
  package: string;
  description: string;
  version: string;
  installed: boolean;
  installed_version: string | null;
  /** The URL this host would use — channel and branch override applied. */
  install_url: string;
}

export interface PluginStatus {
  github: { authenticated: boolean; username: string | null; error: string | null };
  channel: string;
  branch_overrides: Record<string, string>;
  pending_install: { package?: string; url?: string } | null;
}

export interface DeviceFlowStart {
  job_id: string;
  already_running: boolean;
  /** Absent when a login was already polling — that one still holds the code. */
  user_code?: string;
  verification_uri?: string;
  expires_in?: number;
}

export interface JobStart {
  job_id: string;
  already_running: boolean;
}

export interface PluginDataSummary {
  package: string;
  tables: string[];
  rows: number;
  candidates?: number;
  error?: string | null;
}

export interface PluginEntitlement {
  id: number;
  package: string;
  user_id: number | null;
  username: string | null;
  group_id: number | null;
  group_name: string | null;
  granted_at: string | null;
  granted_by: string | null;
}

export interface GrantResult {
  granted: PluginEntitlement[];
  skipped_user_ids: number[];
  skipped_group_ids: number[];
}

/**
 * Whether this deployment runs the plugin manager.
 *
 * Resolves false for any failure at all: a 404 from the router being absent, a
 * 404 from a non-admin session, and the HTML body the SPA fallback returns when
 * the path was never routed (which makes apiFetch's res.json() throw).
 */
export async function probePluginManager(): Promise<boolean> {
  try {
    const status = await apiFetch<PluginStatus>("/api/v1/plugins/status?verify=false");
    return typeof status?.channel === "string";
  } catch {
    return false;
  }
}

export const fetchPluginStatus = (verify = true): Promise<PluginStatus> =>
  apiFetch(`/api/v1/plugins/status?verify=${verify}`);

export const fetchInstalledPlugins = (): Promise<{ plugins: InstalledPlugin[] }> =>
  apiFetch("/api/v1/plugins");

export const fetchAvailablePlugins = (): Promise<{ plugins: AvailablePlugin[]; ref: string }> =>
  apiFetch("/api/v1/plugins/available");

export const startGithubLogin = (): Promise<DeviceFlowStart> =>
  apiFetch("/api/v1/plugins/auth/device", { method: "POST" });

export const githubLogout = (): Promise<{ authenticated: boolean }> =>
  apiFetch("/api/v1/plugins/auth", { method: "DELETE" });

export const setPluginChannel = (channel: "stable" | "dev"): Promise<{ channel: string; previous: string }> =>
  apiFetch("/api/v1/plugins/channel", {
    method: "PUT",
    body: JSON.stringify({ channel }),
  });

export const installPlugin = (packageName: string): Promise<JobStart> =>
  apiFetch("/api/v1/plugins/install", {
    method: "POST",
    body: JSON.stringify({ package: packageName }),
  });

export const fetchPluginData = (packageName: string): Promise<PluginDataSummary> =>
  apiFetch(`/api/v1/plugins/${packageName}/data`);

export const uninstallPlugin = (packageName: string, purgeData: boolean): Promise<JobStart> =>
  apiFetch(`/api/v1/plugins/${packageName}?purge_data=${purgeData}`, { method: "DELETE" });

export const clearPendingInstall = (): Promise<{ cleared: boolean }> =>
  apiFetch("/api/v1/plugins/pending-install", { method: "DELETE" });

export const fetchPluginEntitlements = (
  packageName?: string,
): Promise<{ entitlements: PluginEntitlement[] }> =>
  apiFetch(
    packageName
      ? `/api/v1/plugins/entitlements?package=${encodeURIComponent(packageName)}`
      : "/api/v1/plugins/entitlements",
  );

export const grantPluginAccess = (
  packageName: string,
  userIds: number[],
  groupIds: number[],
): Promise<GrantResult> =>
  apiFetch("/api/v1/plugins/entitlements", {
    method: "POST",
    body: JSON.stringify({ package: packageName, user_ids: userIds, group_ids: groupIds }),
  });

export const revokePluginAccess = (id: number): Promise<void> =>
  apiFetch(`/api/v1/plugins/entitlements/${id}`, { method: "DELETE" });
