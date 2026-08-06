/**
 * Plugin manager client.
 *
 * Every path here is served only by a deployment that switched the manager on
 * (see api/routers/plugins.py). Everywhere else these addresses hit the SPA
 * catch-all and come back as index.html, so nothing in the UI may assume the
 * endpoints exist — probePluginManager() decides that once, and the nav and
 * route hang off its answer.
 */

import { apiFetch, getAuthHeaders } from "./client";

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

/** One row of a `selection` grid. Plain selects use only value and label. */
export interface PluginOption {
  value: string;
  label: string;
  /** A grid row's columns, in the order the parameter declared them. */
  cells?: string[];
  /** Whether the plugin considers this row already picked. */
  selected?: boolean;
  disabled?: boolean;
  /** Heading this row sorts under in the grid. */
  group?: string | null;
  /** Aside shown beside the row — why it was grouped, why it is off by default. */
  note?: string | null;
}

export interface PluginParamFilter {
  name: string;
  label: string;
  options: { value: string; label: string }[];
}

export interface PluginParam {
  name: string;
  label: string;
  type:
    | "text"
    | "textarea"
    | "password"
    | "number"
    | "boolean"
    | "select"
    | "selection"
    | "tenant"
    | "file";
  required: boolean;
  help: string | null;
  placeholder: string | null;
  options?: PluginOption[];
  default?: unknown;
  /**
   * A select whose options the plugin computes rather than declares. `options`
   * arrives empty and the real list comes from fetchPluginActionOptions() once
   * everything in `depends_on` has a value. Always true for a selection grid.
   */
  dynamic?: boolean;
  /** Parameters this one reads. Changing any of them invalidates the list. */
  depends_on?: string[];
  /** selection only: the grid's column headings. */
  columns?: string[];
  /** selection only: dropdowns that narrow the visible rows, matched on cells. */
  filters?: PluginParamFilter[];
}

export interface PluginAction {
  key: string;
  label: string;
  description: string | null;
  /** Shown as a confirmation prompt before the action runs. */
  confirm: string | null;
  destructive: boolean;
  /** Names of the page-level context values this action consumes. */
  context?: string[];
  params: PluginParam[];
}

export interface PluginWorkflowStep {
  key: string;
  label: string;
  description: string | null;
  /** Actions drawn under this step, in the order the plugin listed them. */
  actions: string[];
}

export interface PluginWorkflow {
  steps: PluginWorkflowStep[];
  /** Whether asking fetchPluginState() for per-step progress is worth a request. */
  stateful: boolean;
}

/** Everything the page needs to draw itself. The plugin ships no markup. */
export interface PluginUi {
  name: string | null;
  package: string;
  version: string | null;
  description: string | null;
  /** Values chosen once at the top of the page and kept across actions. */
  context: PluginParam[];
  workflow: PluginWorkflow | null;
  actions: PluginAction[];
}

export type PluginTone = "neutral" | "good" | "warn" | "bad";

export type PluginSection =
  | {
      kind: "stats";
      title: string | null;
      subtitle: string | null;
      items: { label: string; value: unknown; tone: PluginTone; detail: string | null }[];
    }
  | {
      kind: "table";
      title: string | null;
      subtitle: string | null;
      columns: string[];
      rows: string[][];
      /** Index of the column holding a tone name, used to colour the row. */
      tone_column: number | null;
    }
  | {
      kind: "groups";
      title: string | null;
      subtitle: string | null;
      groups: {
        key: string;
        title: string;
        subtitle: string | null;
        badge: string | null;
        tone: PluginTone;
        columns: string[];
        rows: string[][];
      }[];
    }
  | {
      kind: "notes";
      title: string | null;
      subtitle: string | null;
      notes: {
        tone: PluginTone;
        text: string;
        /** The action that resolves this note. Prefills the form; grants nothing. */
        action: { key: string; label: string } | null;
      }[];
    };

/**
 * A question the action stopped on, drawn as a form under its own result.
 *
 * The fields were built by the plugin while it ran, so they are values rather
 * than spec — their options come with them and nothing here is fetched. The
 * answer goes back with the job id, and the server checks it against its own
 * copy of this: what arrives here is for drawing, not for deciding.
 */
export interface PluginPrompt {
  /** The action the answer runs. Chosen by the plugin, not by this page. */
  action: string;
  title: string | null;
  help: string | null;
  submit: string;
  params: PluginParam[];
}

export interface PluginActionResult {
  message: string;
  table: { columns: string[]; rows: unknown[][] } | null;
  /** Richer blocks the plugin asked for, drawn in order above the detail pairs. */
  sections?: PluginSection[];
  details: Record<string, unknown>;
  /** Set when the action produced a file; fetch it with downloadPluginArtifact(). */
  download: { filename: string; content_type: string; size: number } | null;
  /** Page context the action created — adopted by the page when it finishes. */
  context?: Record<string, string>;
  /** Set when the action paused on a decision. */
  prompt?: PluginPrompt | null;
}

export type PluginStepStatus = "pending" | "current" | "complete" | "blocked";

export interface PluginStepState {
  status: PluginStepStatus;
  detail: string | null;
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

/**
 * Answer the question a finished action stopped on. Starts another job.
 *
 * The action that runs comes from the prompt the server recorded against this
 * job, so there is no action key to send: a gate answer generally is not an
 * action the page could navigate to at all.
 */
export const answerPluginPrompt = (
  packageName: string,
  jobId: string,
  params: Record<string, unknown>,
  context: Record<string, unknown>,
): Promise<JobStart> =>
  apiFetch(`/api/v1/plugins/${packageName}/prompts/${encodeURIComponent(jobId)}`, {
    method: "POST",
    body: JSON.stringify({ params, context }),
  });

/**
 * The current options for one dynamically-populated select.
 *
 * POST because the answer depends on the rest of the form, which can hold a
 * tenant id — not something to leave in a URL and an access log. The server
 * checks that tenant before the plugin sees it, and checks the chosen value
 * again when the action runs: this list is a convenience, not the gate.
 */
export const fetchPluginActionOptions = (
  packageName: string,
  actionKey: string,
  param: string,
  params: Record<string, unknown>,
): Promise<{ options: PluginOption[] }> =>
  apiFetch(
    `/api/v1/plugins/${packageName}/actions/${encodeURIComponent(actionKey)}` +
      `/options/${encodeURIComponent(param)}`,
    { method: "POST", body: JSON.stringify({ params }) },
  );

/**
 * The options for one page-level context value.
 *
 * Its own endpoint because the context bar is drawn before any action has been
 * picked, so there is no action key to ask through. Same checks either way.
 */
export const fetchPluginContextOptions = (
  packageName: string,
  param: string,
  params: Record<string, unknown>,
): Promise<{ options: PluginOption[] }> =>
  apiFetch(
    `/api/v1/plugins/${packageName}/context/options/${encodeURIComponent(param)}`,
    { method: "POST", body: JSON.stringify({ params }) },
  );

/**
 * How far along each workflow step is for the given context.
 *
 * Cosmetic: it decides what the step strip looks like. A step reported blocked
 * is still authorised on its own terms if something posts to it directly.
 */
export const fetchPluginState = (
  packageName: string,
  params: Record<string, unknown>,
): Promise<{ state: Record<string, PluginStepState> }> =>
  apiFetch(`/api/v1/plugins/${packageName}/state`, {
    method: "POST",
    body: JSON.stringify({ params }),
  });

/**
 * Save the file a finished action produced.
 *
 * Not apiFetch: the body is bytes, not JSON. The server owns the copy until the
 * job ages out, so this can be clicked more than once, and it answers only to
 * the account whose run made the file.
 */
export async function downloadPluginArtifact(jobId: string, filename: string): Promise<void> {
  const res = await fetch(`/api/v1/plugins/downloads/${encodeURIComponent(jobId)}`, {
    headers: getAuthHeaders(),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(
      res.status === 404
        ? "That download is no longer available — run the action again."
        : `Download failed (HTTP ${res.status})`,
    );
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
