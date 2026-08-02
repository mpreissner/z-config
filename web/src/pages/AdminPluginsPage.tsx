/**
 * Plugin manager.
 *
 * Reachable only where the API registered the plugin router and only for
 * admins — App.tsx keeps the route and Layout.tsx the nav item behind
 * usePluginManagerAvailable(), so on a deployment without it this page is not
 * merely hidden, it has no address.
 *
 * Two things the UI has to be honest about: pip changes need a process restart
 * before the plugin is live, and installing a plugin gives nobody access to it
 * until it is granted here.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AvailablePlugin,
  DeviceFlowStart,
  InstalledPlugin,
  PluginDataSummary,
  PluginEntitlement,
  clearPendingInstall,
  fetchAvailablePlugins,
  fetchInstalledPlugins,
  fetchPluginData,
  fetchPluginEntitlements,
  fetchPluginStatus,
  githubLogout,
  grantPluginAccess,
  installPlugin,
  revokePluginAccess,
  setPluginChannel,
  startGithubLogin,
  uninstallPlugin,
} from "../api/plugins";
import { fetchAdminUsers } from "../api/admin";
import { fetchScimGroups } from "../api/scim";
import { useJobStream } from "../hooks/useJobStream";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

const CARD = "bg-white rounded-lg shadow ring-1 ring-black ring-opacity-5 p-5";

function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

// ── pip job progress ─────────────────────────────────────────────────────────

interface PipResult {
  message?: string;
  restart_required?: boolean;
  revoked_entitlements?: number;
}

/** Progress for the one pip job that may be running: install or uninstall. */
function PipJob({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const { progressEvents, jobStatus, result, streamError } = useJobStream<PipResult>(jobId);
  const lines = progressEvents.map((e) => e.message).filter(Boolean);

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-2">
      {lines.map((line, i) => (
        <p key={i} className="text-xs text-gray-600 font-mono">{line}</p>
      ))}
      {jobStatus === "running" && <LoadingSpinner />}
      {jobStatus === "error" && (
        <ErrorMessage message={streamError ?? "The operation failed"} />
      )}
      {jobStatus === "done" && (
        <div className="space-y-2">
          <p className="text-sm text-green-700">{result?.message ?? "Done."}</p>
          {result?.revoked_entitlements ? (
            <p className="text-xs text-gray-600">
              {result.revoked_entitlements} access grant
              {result.revoked_entitlements === 1 ? "" : "s"} removed with the purged data.
            </p>
          ) : null}
          {result?.restart_required && (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
              Plugins are loaded when the process starts. Restart zs-config before this
              change takes effect.
            </p>
          )}
        </div>
      )}
      {(jobStatus === "done" || jobStatus === "error") && (
        <button
          onClick={onDone}
          className="px-3 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-100"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

// ── GitHub session ───────────────────────────────────────────────────────────

function GithubPanel() {
  const qc = useQueryClient();
  const [flow, setFlow] = useState<DeviceFlowStart | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: status, isLoading } = useQuery({
    queryKey: ["plugin-status"],
    queryFn: () => fetchPluginStatus(true),
  });

  // Polls until the user finishes in their browser; the server side of the
  // exchange is a background job, so the page just watches its outcome.
  const { jobStatus, streamError } = useJobStream(flow?.job_id ?? null);
  useEffect(() => {
    if (jobStatus !== "done") return;
    setFlow(null);
    qc.invalidateQueries({ queryKey: ["plugin-status"] });
    qc.invalidateQueries({ queryKey: ["plugins-available"] });
  }, [jobStatus, qc]);

  const login = useMutation({
    mutationFn: startGithubLogin,
    onSuccess: (res) => { setError(null); setFlow(res); },
    onError: (e) => setError(errText(e, "Could not start GitHub login")),
  });

  const logout = useMutation({
    mutationFn: githubLogout,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plugin-status"] }),
    onError: (e) => setError(errText(e, "Could not sign out")),
  });

  if (isLoading) return <div className={CARD}><LoadingSpinner /></div>;

  const gh = status?.github;

  return (
    <div className={`${CARD} space-y-3`}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-900">GitHub</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Plugins install from a private repository. Your GitHub account has to be a
            collaborator on it.
          </p>
        </div>
        {gh?.authenticated ? (
          <button
            onClick={() => logout.mutate()}
            className="px-3 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
          >
            Sign out
          </button>
        ) : (
          <button
            onClick={() => login.mutate()}
            disabled={login.isPending || !!flow}
            className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
          >
            {flow ? "Waiting..." : "Sign in"}
          </button>
        )}
      </div>

      {gh?.authenticated && (
        <p className="text-sm text-gray-700">
          Signed in{gh.username ? ` as ${gh.username}` : ""}.
        </p>
      )}
      {gh?.error && <ErrorMessage message={gh.error} />}

      {flow?.user_code && (
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 space-y-2">
          <p className="text-sm text-blue-900">
            Open{" "}
            <a
              href={flow.verification_uri}
              target="_blank"
              rel="noreferrer"
              className="underline font-medium"
            >
              {flow.verification_uri}
            </a>{" "}
            and enter this code:
          </p>
          <p className="font-mono text-2xl tracking-widest text-blue-900">{flow.user_code}</p>
          <p className="text-xs text-blue-800">
            This page picks up the result on its own. The code expires in about{" "}
            {Math.round((flow.expires_in ?? 900) / 60)} minutes.
          </p>
        </div>
      )}
      {flow && jobStatus === "error" && (
        <ErrorMessage message={streamError ?? "GitHub login failed"} />
      )}
      {error && <ErrorMessage message={error} />}
    </div>
  );
}

// ── Channel + deferred install ───────────────────────────────────────────────

function ChannelPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { data: status } = useQuery({
    queryKey: ["plugin-status"],
    queryFn: () => fetchPluginStatus(true),
  });

  const change = useMutation({
    mutationFn: (channel: "stable" | "dev") => setPluginChannel(channel),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["plugin-status"] });
      qc.invalidateQueries({ queryKey: ["plugins-available"] });
    },
    onError: (e) => setError(errText(e, "Could not switch channel")),
  });

  const clear = useMutation({
    mutationFn: clearPendingInstall,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plugin-status"] }),
    onError: (e) => setError(errText(e, "Could not clear the pending install")),
  });

  const channel = status?.channel ?? "stable";
  const overrides = Object.entries(status?.branch_overrides ?? {});

  return (
    <div className={`${CARD} space-y-3`}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-900">Channel</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Which branch new installs come from. Nothing already installed changes.
          </p>
        </div>
        <select
          value={channel}
          onChange={(e) => change.mutate(e.target.value as "stable" | "dev")}
          disabled={change.isPending}
          className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        >
          <option value="stable">stable</option>
          <option value="dev">dev</option>
        </select>
      </div>

      {overrides.length > 0 && (
        <p className="text-xs text-gray-600">
          Branch pins:{" "}
          {overrides.map(([pkg, branch]) => `${pkg} → ${branch}`).join(", ")}
        </p>
      )}

      {status?.pending_install && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 flex items-start justify-between gap-3">
          <p className="text-xs text-amber-900">
            An install of <strong>{status.pending_install.package}</strong> was recorded but
            never finished. It is retried on the next start; clear it if it can no longer
            succeed.
          </p>
          <button
            onClick={() => clear.mutate()}
            className="px-2.5 py-1 text-xs rounded-md border border-amber-300 hover:bg-amber-100 whitespace-nowrap"
          >
            Clear
          </button>
        </div>
      )}
      {error && <ErrorMessage message={error} />}
    </div>
  );
}

// ── Access (entitlements) ────────────────────────────────────────────────────

function AccessModal({ pkg, onClose }: { pkg: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [userIds, setUserIds] = useState<Set<number>>(new Set());
  const [groupIds, setGroupIds] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const { data: grants } = useQuery({
    queryKey: ["plugin-entitlements", pkg],
    queryFn: () => fetchPluginEntitlements(pkg),
  });
  const { data: users } = useQuery({ queryKey: ["admin-users"], queryFn: fetchAdminUsers });
  const { data: groups } = useQuery({ queryKey: ["scim-groups"], queryFn: fetchScimGroups });

  const rows: PluginEntitlement[] = grants?.entitlements ?? [];
  const grantedUsers = new Set(rows.map((r) => r.user_id).filter(Boolean) as number[]);
  const grantedGroups = new Set(rows.map((r) => r.group_id).filter(Boolean) as number[]);

  // Admins bypass the grant list entirely, so offering them here would be a lie.
  const candidates = (users ?? []).filter(
    (u) => u.role !== "admin" && u.is_active && !grantedUsers.has(u.id),
  );
  const groupCandidates = (groups ?? []).filter((g) => !grantedGroups.has(g.id));

  const grant = useMutation({
    mutationFn: () =>
      grantPluginAccess(pkg, Array.from(userIds), Array.from(groupIds)),
    onSuccess: () => {
      setUserIds(new Set());
      setGroupIds(new Set());
      setError(null);
      qc.invalidateQueries({ queryKey: ["plugin-entitlements"] });
    },
    onError: (e) => setError(errText(e, "Could not grant access")),
  });

  const revoke = useMutation({
    mutationFn: revokePluginAccess,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plugin-entitlements"] }),
    onError: (e) => setError(errText(e, "Could not revoke access")),
  });

  function toggle(set: Set<number>, apply: (s: Set<number>) => void, id: number) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    apply(next);
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">Access — {pkg}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">
            &times;
          </button>
        </div>

        <div className="px-6 py-4 space-y-5 overflow-y-auto flex-1">
          <p className="text-xs text-gray-500">
            Installing a plugin does not expose it. Admins can always use it; everyone else
            needs a grant, directly or through a group.
          </p>

          <div>
            <h4 className="text-xs font-medium text-gray-600 mb-2">Current access</h4>
            {rows.length === 0 ? (
              <p className="text-xs text-gray-400">
                Nobody but admins can use this plugin yet.
              </p>
            ) : (
              <ul className="border border-gray-200 rounded-md divide-y divide-gray-100">
                {rows.map((r) => (
                  <li key={r.id} className="flex items-center gap-3 px-3 py-2">
                    <span className="text-sm text-gray-800">
                      {r.username ?? r.group_name ?? "(deleted)"}
                    </span>
                    <span className="text-xs text-gray-400">
                      {r.group_id ? "group" : "user"}
                    </span>
                    <button
                      onClick={() => revoke.mutate(r.id)}
                      disabled={revoke.isPending}
                      className="ml-auto text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-60"
                    >
                      Revoke
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h4 className="text-xs font-medium text-gray-600 mb-2">Grant to users</h4>
            {candidates.length === 0 ? (
              <p className="text-xs text-gray-400">No further users to grant.</p>
            ) : (
              <div className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-40 overflow-y-auto">
                {candidates.map((u) => (
                  <label key={u.id} className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50">
                    <input
                      type="checkbox"
                      checked={userIds.has(u.id)}
                      onChange={() => toggle(userIds, setUserIds, u.id)}
                      className="accent-zs-500"
                    />
                    <span className="text-sm text-gray-800">{u.username}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div>
            <h4 className="text-xs font-medium text-gray-600 mb-2">Grant to groups</h4>
            {groupCandidates.length === 0 ? (
              <p className="text-xs text-gray-400">
                No provisioned groups available. Groups arrive over SCIM.
              </p>
            ) : (
              <div className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-40 overflow-y-auto">
                {groupCandidates.map((g) => (
                  <label key={g.id} className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50">
                    <input
                      type="checkbox"
                      checked={groupIds.has(g.id)}
                      onChange={() => toggle(groupIds, setGroupIds, g.id)}
                      className="accent-zs-500"
                    />
                    <span className="text-sm text-gray-800">{g.display_name}</span>
                    <span className="ml-auto text-xs text-gray-400">
                      {g.member_count} member{g.member_count === 1 ? "" : "s"}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {error && <ErrorMessage message={error} />}
        </div>

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
          >
            Close
          </button>
          <button
            onClick={() => grant.mutate()}
            disabled={grant.isPending || (userIds.size === 0 && groupIds.size === 0)}
            className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
          >
            {grant.isPending ? "Granting..." : "Grant access"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Uninstall ────────────────────────────────────────────────────────────────

function UninstallModal({
  pkg,
  onClose,
  onJob,
}: {
  pkg: string;
  onClose: () => void;
  onJob: (jobId: string) => void;
}) {
  const [purge, setPurge] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: summary, isLoading } = useQuery<PluginDataSummary>({
    queryKey: ["plugin-data", pkg],
    queryFn: () => fetchPluginData(pkg),
  });

  const run = useMutation({
    mutationFn: () => uninstallPlugin(pkg, purge),
    onSuccess: (res) => { onJob(res.job_id); onClose(); },
    onError: (e) => setError(errText(e, "Could not start the uninstall")),
  });

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">Uninstall {pkg}</h3>
        </div>
        <div className="px-6 py-4 space-y-4">
          {isLoading && <LoadingSpinner />}
          {summary?.error && <ErrorMessage message={summary.error} />}
          {summary && !summary.error && (
            <p className="text-sm text-gray-700">
              This plugin owns {summary.tables?.length ?? 0} table
              {(summary.tables?.length ?? 0) === 1 ? "" : "s"} holding {summary.rows ?? 0} row
              {(summary.rows ?? 0) === 1 ? "" : "s"}.
            </p>
          )}
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={purge}
              onChange={(e) => setPurge(e.target.checked)}
              className="mt-0.5 accent-red-600"
            />
            <span className="text-sm text-gray-700">
              Also delete its data and access grants.
              <span className="block text-xs text-gray-500">
                Config already pushed to a tenant stays — this only removes what the plugin
                stored locally.
              </span>
            </span>
          </label>
          {error && <ErrorMessage message={error} />}
        </div>
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-200">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={() => run.mutate()}
            disabled={run.isPending}
            className="px-4 py-2 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white disabled:opacity-60"
          >
            {run.isPending ? "Starting..." : "Uninstall"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AdminPluginsPage() {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [accessPkg, setAccessPkg] = useState<string | null>(null);
  const [uninstallPkg, setUninstallPkg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: installed, isLoading: loadingInstalled } = useQuery({
    queryKey: ["plugins-installed"],
    queryFn: fetchInstalledPlugins,
  });

  const { data: available, error: availableError, isLoading: loadingAvailable } = useQuery({
    queryKey: ["plugins-available"],
    queryFn: fetchAvailablePlugins,
    retry: false,
  });

  const { data: allGrants } = useQuery({
    queryKey: ["plugin-entitlements"],
    queryFn: () => fetchPluginEntitlements(),
  });

  const install = useMutation({
    mutationFn: installPlugin,
    onSuccess: (res) => { setError(null); setJobId(res.job_id); },
    onError: (e) => setError(errText(e, "Could not start the install")),
  });

  const grantCount = (pkg: string | null) =>
    (allGrants?.entitlements ?? []).filter((g) => g.package === pkg).length;

  const installedRows: InstalledPlugin[] = installed?.plugins ?? [];
  const availableRows: AvailablePlugin[] = available?.plugins ?? [];
  const notInstalled = availableRows.filter((p) => !p.installed);

  function jobFinished() {
    setJobId(null);
    qc.invalidateQueries({ queryKey: ["plugins-installed"] });
    qc.invalidateQueries({ queryKey: ["plugins-available"] });
    qc.invalidateQueries({ queryKey: ["plugin-entitlements"] });
    qc.invalidateQueries({ queryKey: ["plugin-status"] });
  }

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold text-gray-900">Plugins</h1>

      <GithubPanel />
      <ChannelPanel />

      {jobId && (
        <div className={CARD}>
          <PipJob jobId={jobId} onDone={jobFinished} />
        </div>
      )}
      {error && <ErrorMessage message={error} />}

      {/* Installed */}
      <div className={CARD}>
        <h2 className="font-semibold text-gray-900 mb-1">Installed</h2>
        <p className="text-xs text-gray-500 mb-3">
          Grant access before anyone but an admin can use a plugin.
        </p>
        {loadingInstalled && <LoadingSpinner />}
        {!loadingInstalled && installedRows.length === 0 && (
          <p className="text-sm text-gray-500">No plugins installed.</p>
        )}
        {installedRows.length > 0 && (
          <ul className="divide-y divide-gray-100 border border-gray-200 rounded-md">
            {installedRows.map((p) => (
              <li key={p.package} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900">{p.name ?? p.package}</p>
                  <p className="text-xs text-gray-500">
                    {p.package}
                    {p.version ? ` · ${p.version}` : ""}
                  </p>
                  {p.error && <p className="text-xs text-red-600 mt-0.5">{p.error}</p>}
                </div>
                <span className="ml-auto text-xs text-gray-500 whitespace-nowrap">
                  {grantCount(p.package)} grant{grantCount(p.package) === 1 ? "" : "s"}
                </span>
                <button
                  onClick={() => setAccessPkg(p.package!)}
                  className="px-3 py-1.5 text-xs rounded-md border border-gray-300 hover:bg-gray-50 whitespace-nowrap"
                >
                  Access
                </button>
                <button
                  onClick={() => setUninstallPkg(p.package!)}
                  disabled={!!jobId}
                  className="px-3 py-1.5 text-xs rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-60 whitespace-nowrap"
                >
                  Uninstall
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Available */}
      <div className={CARD}>
        <h2 className="font-semibold text-gray-900 mb-1">Available</h2>
        <p className="text-xs text-gray-500 mb-3">
          From the plugin repository{available?.ref ? ` (${available.ref})` : ""}.
        </p>
        {loadingAvailable && <LoadingSpinner />}
        {availableError && (
          <ErrorMessage message={errText(availableError, "Could not read the plugin manifest")} />
        )}
        {available && notInstalled.length === 0 && (
          <p className="text-sm text-gray-500">Everything on offer is already installed.</p>
        )}
        {notInstalled.length > 0 && (
          <ul className="divide-y divide-gray-100 border border-gray-200 rounded-md">
            {notInstalled.map((p) => (
              <li key={p.package} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900">{p.name}</p>
                  <p className="text-xs text-gray-500">
                    {p.package}
                    {p.version ? ` · ${p.version}` : ""}
                  </p>
                  {p.description && (
                    <p className="text-xs text-gray-600 mt-0.5">{p.description}</p>
                  )}
                </div>
                <button
                  onClick={() => install.mutate(p.package)}
                  disabled={!!jobId || install.isPending}
                  className="ml-auto px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60 whitespace-nowrap"
                >
                  Install
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {accessPkg && <AccessModal pkg={accessPkg} onClose={() => setAccessPkg(null)} />}
      {uninstallPkg && (
        <UninstallModal
          pkg={uninstallPkg}
          onClose={() => setUninstallPkg(null)}
          onJob={setJobId}
        />
      )}
    </div>
  );
}
