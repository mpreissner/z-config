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
  /** The URL this host would use — channel and any per-plugin pin applied. */
  install_url: string;
  /** This plugin's own pin, or null when it just follows the channel. */
  pinned_ref: string | null;
  /** What the pin resolves to once the channel fills in for a null pin. */
  effective_ref: string;
  /** Whether the manifest publishes a dev URL for this plugin at all. */
  has_dev: boolean;
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

export const fetchAvailablePlugins = (): Promise<{
  plugins: AvailablePlugin[];
  ref: string;
  channel: string;
}> => apiFetch("/api/v1/plugins/available");

export const fetchPluginBranches = (
  packageName: string,
): Promise<{ package: string; branches: string[] }> =>
  apiFetch(`/api/v1/plugins/${packageName}/branches`);

/**
 * Pin one plugin to a ref, or clear its pin with `ref = null`.
 *
 * `reinstall` is the caller's business: an installed plugin has to be rebuilt
 * from the new ref (a job), while pinning one that is not installed yet is just
 * a recorded preference the next install reads.
 */
export const setPluginRef = (
  packageName: string,
  ref: string | null,
  reinstall: boolean,
): Promise<JobStart | { package: string; branch: string | null; reinstalled: false }> =>
  apiFetch(`/api/v1/plugins/${packageName}/branch`, {
    method: "PUT",
    body: JSON.stringify({ branch: ref, reinstall }),
  });

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

// ---------------------------------------------------------------------------
// Using a plugin (as opposed to managing one)
// ---------------------------------------------------------------------------

/** A plugin the current account may open — one left-nav item. */
export interface EntitledPlugin {
  package: string;
  name: string | null;
  version: string | null;
}

export interface PluginParam {
  name: string;
  label: string;
  type: "text" | "textarea" | "password" | "number" | "boolean" | "select" | "tenant" | "file";
  required: boolean;
  help: string | null;
  placeholder: string | null;
  options?: { value: string; label: string }[];
  default?: unknown;
}

export interface PluginAction {
  key: string;
  label: string;
  description: string | null;
  /** Shown as a confirmation prompt before the action runs. */
  confirm: string | null;
  destructive: boolean;
  params: PluginParam[];
}

/** Everything the page needs to draw itself. The plugin ships no markup. */
export interface PluginUi {
  name: string | null;
  package: string;
  version: string | null;
  description: string | null;
  actions: PluginAction[];
}

export interface PluginActionResult {
  message: string;
  table: { columns: string[]; rows: unknown[][] } | null;
  details: Record<string, unknown>;
}

/**
 * Plugins granted to this account that are installed and have a web interface.
 *
 * Resolves to an empty list rather than throwing whenever the manager is off —
 * the nav asks this on every page load and a deployment without plugins is the
 * ordinary case, not an error worth surfacing.
 */
export async function fetchEntitledPlugins(): Promise<EntitledPlugin[]> {
  try {
    const r = await apiFetch<{ plugins?: EntitledPlugin[] }>("/api/v1/plugins/entitled");
    return Array.isArray(r?.plugins) ? r.plugins : [];
  } catch {
    return [];
  }
}

export const fetchPluginUi = (packageName: string): Promise<PluginUi> =>
  apiFetch(`/api/v1/plugins/${packageName}/ui`);

/**
 * Start one of a plugin's actions. Always a job — the work is arbitrary.
 *
 * Files cannot ride in a JSON body, so an action that declares any goes out as
 * multipart with the rest of the values as a JSON string under `params`. The
 * server reads both shapes; this picks whichever the values require.
 */
export function runPluginAction(
  packageName: string,
  actionKey: string,
  params: Record<string, unknown>,
  files: Record<string, File>,
): Promise<JobStart> {
  const path = `/api/v1/plugins/${packageName}/actions/${encodeURIComponent(actionKey)}`;
  const names = Object.keys(files);
  if (names.length === 0) {
    return apiFetch(path, { method: "POST", body: JSON.stringify(params) });
  }
  const form = new FormData();
  form.append("params", JSON.stringify(params));
  for (const name of names) form.append(name, files[name]);
  // No Content-Type header: the browser has to set the multipart boundary.
  return apiFetch(path, { method: "POST", body: form });
}
