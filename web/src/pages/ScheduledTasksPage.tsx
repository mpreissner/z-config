import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchTenants } from "../api/tenants";
import {
  fetchScheduledTasks,
  createScheduledTask,
  updateScheduledTask,
  deleteScheduledTask,
  enableScheduledTask,
  disableScheduledTask,
  triggerScheduledTask,
  fetchTaskRuns,
  fetchTaskRunDetail,
  ScheduledTask,
  CreateScheduledTaskRequest,
} from "../api/scheduledTasks";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RESOURCE_GROUPS: Array<{ key: string; label: string; note?: string }> = [
  { key: "firewall", label: "Firewall Rules" },
  { key: "ips", label: "IPS Rules" },
  { key: "dns_filter", label: "DNS Filter Rules" },
  { key: "ssl_inspection", label: "SSL Inspection Rules" },
  { key: "url_categories", label: "URL Categories", note: "Custom categories only — global cloud app settings are excluded" },
  { key: "url_filtering", label: "URL Filtering Rules" },
  { key: "cloud_app_control", label: "Cloud App Control" },
  { key: "dlp", label: "DLP (Engines, Dictionaries, Rules)" },
  { key: "network_objects", label: "Network Objects" },
  { key: "forwarding", label: "Forwarding Rules" },
  { key: "bandwidth", label: "Bandwidth Control" },
  { key: "nat", label: "NAT Control Rules" },
  { key: "sandbox", label: "Sandbox Rules" },
  { key: "tenancy", label: "Tenancy Restriction Profiles" },
];

const LABEL_SUPPORTED_RESOURCE_TYPES: Array<{ key: string; label: string }> = [
  { key: "firewall_rule",          label: "Firewall Rules" },
  { key: "url_filtering_rule",     label: "URL Filtering Rules" },
  { key: "ssl_inspection_rule",    label: "SSL Inspection Rules" },
  { key: "forwarding_rule",        label: "Forwarding Rules" },
  { key: "bandwidth_control_rule", label: "Bandwidth Control Rules" },
  { key: "nat_control_rule",       label: "NAT Control Rules" },
  { key: "dlp_web_rule",           label: "DLP Web Rules" },
  { key: "firewall_dns_rule",      label: "Firewall DNS Rules" },
  { key: "firewall_ips_rule",      label: "Firewall IPS Rules" },
  { key: "sandbox_rule",           label: "Sandbox Rules" },
  { key: "traffic_capture_rule",   label: "Traffic Capture Rules" },
  { key: "cloud_app_control_rule", label: "Cloud App Control Rules" },
];

const INTERVAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "1h", label: "Every 1 hour" },
  { value: "4h", label: "Every 4 hours" },
  { value: "12h", label: "Every 12 hours" },
  { value: "24h", label: "Every 24 hours" },
];

function groupLabel(key: string): string {
  return RESOURCE_GROUPS.find((g) => g.key === key)?.label ?? key;
}

export function labelTypeLabel(key: string): string {
  return LABEL_SUPPORTED_RESOURCE_TYPES.find((t) => t.key === key)?.label ?? key;
}

function humanCron(cron: string): string {
  const presetMap: Record<string, string> = {
    "0 * * * *": "Every 1 hour",
    "0 */4 * * *": "Every 4 hours",
    "0 */12 * * *": "Every 12 hours",
    "0 0 * * *": "Every 24 hours",
  };
  return presetMap[cron] ?? cron;
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return "-";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Status badges
// ---------------------------------------------------------------------------

function EnabledBadge({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        enabled
          ? "bg-green-100 text-green-800"
          : "bg-gray-100 text-gray-600"
      }`}
    >
      {enabled ? "Enabled" : "Disabled"}
    </span>
  );
}

function RunStatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-gray-400 text-xs">-</span>;
  const map: Record<string, string> = {
    success: "bg-green-100 text-green-800",
    partial: "bg-yellow-100 text-yellow-800",
    failed: "bg-red-100 text-red-800",
    running: "bg-blue-100 text-blue-800",
  };
  const cls = map[status] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// TaskFormModal
// ---------------------------------------------------------------------------

interface TaskFormModalProps {
  mode: "create" | "edit";
  initial?: ScheduledTask | null;
  onClose: () => void;
  onSaved: () => void;
}

function TaskFormModal({ mode, initial, onClose, onSaved }: TaskFormModalProps) {
  const { data: tenants } = useQuery({ queryKey: ["tenants"], queryFn: fetchTenants });

  const [name, setName] = useState(initial?.name ?? "");
  const [sourceTenantId, setSourceTenantId] = useState<number | "">(
    initial?.source_tenant_id ?? ""
  );
  const [targetTenantId, setTargetTenantId] = useState<number | "">(
    initial?.target_tenant_id ?? ""
  );
  const [selectedGroups, setSelectedGroups] = useState<string[]>(
    initial?.resource_groups ?? []
  );
  const [scheduleType, setScheduleType] = useState<"interval" | "cron">("interval");
  const [intervalValue, setIntervalValue] = useState("4h");
  const [cronValue, setCronValue] = useState(initial?.cron_expression ?? "0 */4 * * *");
  const [syncDeletes, setSyncDeletes] = useState(initial?.sync_deletes ?? false);
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [ownerEmail, setOwnerEmail] = useState(initial?.owner_email ?? "");
  const [syncMode, setSyncMode] = useState<"resource_type" | "label">(
    initial?.sync_mode ?? "resource_type"
  );
  const [labelName, setLabelName] = useState(initial?.label_name ?? "");
  const [selectedLabelTypes, setSelectedLabelTypes] = useState<string[]>(
    initial?.label_resource_types ?? LABEL_SUPPORTED_RESOURCE_TYPES.map((t) => t.key)
  );
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const createMut = useMutation({
    mutationFn: createScheduledTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      onSaved();
    },
    onError: (e: Error) => setError(e.message),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<CreateScheduledTaskRequest> }) =>
      updateScheduledTask(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      onSaved();
    },
    onError: (e: Error) => setError(e.message),
  });

  const isPending = createMut.isPending || updateMut.isPending;

  function toggleGroup(key: string) {
    setSelectedGroups((prev) =>
      prev.includes(key) ? prev.filter((g) => g !== key) : [...prev, key]
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim()) { setError("Name is required."); return; }
    if (sourceTenantId === "") { setError("Source tenant is required."); return; }
    if (targetTenantId === "") { setError("Target tenant is required."); return; }
    if (sourceTenantId === targetTenantId) {
      setError("Source and target tenants must be different.");
      return;
    }
    if (syncMode === "resource_type" && selectedGroups.length === 0) {
      setError("Select at least one resource group.");
      return;
    }
    if (syncMode === "label" && !labelName.trim()) {
      setError("Label name is required.");
      return;
    }
    if (syncMode === "label" && selectedLabelTypes.length === 0) {
      setError("Select at least one resource type for label sync.");
      return;
    }

    const schedule = scheduleType === "interval" ? intervalValue : cronValue.trim();
    if (!schedule) { setError("Schedule is required."); return; }

    const data: CreateScheduledTaskRequest = {
      name: name.trim(),
      source_tenant_id: sourceTenantId as number,
      target_tenant_id: targetTenantId as number,
      resource_groups: syncMode === "resource_type" ? selectedGroups : [],
      schedule,
      sync_deletes: syncDeletes,
      enabled,
      owner_email: ownerEmail.trim() || null,
      sync_mode: syncMode,
      label_name: syncMode === "label" ? labelName.trim() : null,
      label_resource_types:
        syncMode === "label"
          ? (selectedLabelTypes.length === LABEL_SUPPORTED_RESOURCE_TYPES.length
              ? null
              : selectedLabelTypes)
          : null,
    };

    if (mode === "create") {
      createMut.mutate(data);
    } else if (initial) {
      updateMut.mutate({ id: initial.id, data });
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black bg-opacity-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">
            {mode === "create" ? "New Scheduled Task" : "Edit Scheduled Task"}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-400 hover:text-gray-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4 overflow-y-auto max-h-[70vh]">
          {error && <ErrorMessage message={error} />}

          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              placeholder="Primary to DR Sync"
            />
          </div>

          {/* Source / Target Tenant */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Source Tenant</label>
              <select
                value={sourceTenantId}
                onChange={(e) => setSourceTenantId(e.target.value ? Number(e.target.value) : "")}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              >
                <option value="">Select tenant...</option>
                {(tenants ?? []).map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Target Tenant</label>
              <select
                value={targetTenantId}
                onChange={(e) => setTargetTenantId(e.target.value ? Number(e.target.value) : "")}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              >
                <option value="">Select tenant...</option>
                {(tenants ?? []).map((t) => (
                  <option key={t.id} value={t.id} disabled={t.id === sourceTenantId}>
                    {t.name}{t.id === sourceTenantId ? " (same as source)" : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Sync Mode */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Sync Mode</label>
            <div className="flex gap-6">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="syncMode"
                  value="resource_type"
                  checked={syncMode === "resource_type"}
                  onChange={() => { setSyncMode("resource_type"); }}
                  className="text-zs-500"
                />
                <span>By Resource Type</span>
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="syncMode"
                  value="label"
                  checked={syncMode === "label"}
                  onChange={() => { setSyncMode("label"); setSelectedGroups([]); }}
                  className="text-zs-500"
                />
                <span>By Label</span>
              </label>
            </div>
          </div>

          {/* Resource Groups — resource_type mode only */}
          {syncMode === "resource_type" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Resource Groups</label>
              <div className="grid grid-cols-2 gap-2 border border-gray-200 rounded-md p-3 bg-gray-50">
                {RESOURCE_GROUPS.map((g) => (
                  <label key={g.key} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedGroups.includes(g.key)}
                      onChange={() => toggleGroup(g.key)}
                      className="rounded border-gray-300 text-zs-500 focus:ring-zs-500"
                    />
                    <span className="text-gray-700">{g.label}</span>
                    {g.note && (
                      <span
                        className="relative group/tooltip"
                        onClick={(e) => e.preventDefault()}
                      >
                        <span className="text-gray-400 text-xs cursor-help select-none">ⓘ</span>
                        <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-56 rounded bg-gray-800 px-2 py-1.5 text-xs text-white opacity-0 group-hover/tooltip:opacity-100 transition-opacity z-50 whitespace-normal text-center shadow-lg">
                          {g.note}
                        </span>
                      </span>
                    )}
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Label mode panel */}
          {syncMode === "label" && (
            <div className="space-y-4">
              {/* Label name input */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Label Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={labelName}
                  onChange={(e) => setLabelName(e.target.value)}
                  placeholder="e.g. test123"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Case-sensitive. Only resources with this label will be synced.
                </p>
              </div>

              {/* Label resource type multi-select */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium text-gray-700">
                    Resource Types to Sync
                  </label>
                  <div className="flex gap-3 text-xs">
                    <button
                      type="button"
                      onClick={() => setSelectedLabelTypes(LABEL_SUPPORTED_RESOURCE_TYPES.map((t) => t.key))}
                      className="text-zs-600 hover:underline"
                    >
                      Select all
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedLabelTypes([])}
                      className="text-gray-500 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 border border-gray-200 rounded-md p-3 bg-gray-50">
                  {LABEL_SUPPORTED_RESOURCE_TYPES.map((t) => (
                    <label key={t.key} className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedLabelTypes.includes(t.key)}
                        onChange={() =>
                          setSelectedLabelTypes((prev) =>
                            prev.includes(t.key)
                              ? prev.filter((k) => k !== t.key)
                              : [...prev, t.key]
                          )
                        }
                        className="rounded border-gray-300 text-zs-500 focus:ring-zs-500"
                      />
                      <span className="text-gray-700">{t.label}</span>
                    </label>
                  ))}
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  Uncheck to exclude specific rule types from this sync. All are synced by default.
                </p>
              </div>
            </div>
          )}

          {/* Schedule */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Schedule</label>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  checked={scheduleType === "interval"}
                  onChange={() => setScheduleType("interval")}
                  className="text-zs-500"
                />
                <span>Interval</span>
              </label>
              {scheduleType === "interval" && (
                <select
                  value={intervalValue}
                  onChange={(e) => setIntervalValue(e.target.value)}
                  className="ml-6 border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                >
                  {INTERVAL_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              )}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  checked={scheduleType === "cron"}
                  onChange={() => setScheduleType("cron")}
                  className="text-zs-500"
                />
                <span>Custom cron expression</span>
              </label>
              {scheduleType === "cron" && (
                <input
                  type="text"
                  value={cronValue}
                  onChange={(e) => setCronValue(e.target.value)}
                  placeholder="0 */4 * * *"
                  className="ml-6 w-64 border border-gray-300 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                />
              )}
            </div>
          </div>

          {/* Sync Deletes */}
          <div>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncDeletes}
                onChange={(e) => setSyncDeletes(e.target.checked)}
                className="mt-0.5 rounded border-gray-300 text-zs-500 focus:ring-zs-500"
              />
              <div>
                <span className="text-sm font-medium text-gray-700">Sync Deletes</span>
                <p className="text-xs text-amber-600 mt-0.5">
                  Warning: removes resources from target that are absent from source. This is
                  irreversible once the target is activated.
                </p>
              </div>
            </label>
          </div>

          {/* Enabled */}
          <div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="rounded border-gray-300 text-zs-500 focus:ring-zs-500"
              />
              <span className="font-medium text-gray-700">Enable task immediately</span>
            </label>
          </div>

          {/* Owner Email */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Owner Email <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              type="email"
              value={ownerEmail}
              onChange={(e) => setOwnerEmail(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              placeholder="ops@example.com"
            />
          </div>
        </form>

        <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit as unknown as React.MouseEventHandler}
            disabled={isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-zs-500 rounded-md hover:bg-zs-600 disabled:opacity-50"
          >
            {isPending ? "Saving..." : mode === "create" ? "Create Task" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Run Error Detail Panel
// ---------------------------------------------------------------------------

interface RunDetailPanelProps {
  taskId: number;
  runId: number;
  onClose: () => void;
}

function RunDetailPanel({ taskId, runId, onClose }: RunDetailPanelProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["scheduled-task-run-detail", taskId, runId],
    queryFn: () => fetchTaskRunDetail(taskId, runId),
  });

  return (
    <div className="fixed inset-0 z-50 bg-black bg-opacity-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
          <h2 className="text-lg font-semibold text-gray-900">Run Detail — #{runId}</h2>
          <button onClick={onClose} className="p-1 rounded text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {isLoading && <LoadingSpinner />}
          {error && <ErrorMessage message="Failed to load run detail." />}
          {data && (
            <>
              <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
                <div>
                  <p className="text-gray-500">Started</p>
                  <p className="font-medium">{formatTimestamp(data.started_at)}</p>
                </div>
                <div>
                  <p className="text-gray-500">Duration</p>
                  <p className="font-medium">{formatDuration(data.duration_seconds)}</p>
                </div>
                <div>
                  <p className="text-gray-500">Status</p>
                  <RunStatusBadge status={data.status} />
                </div>
                <div>
                  <p className="text-gray-500">Resources Synced</p>
                  <p className="font-medium">{data.resources_synced}</p>
                </div>
                <div>
                  <p className="text-gray-500">Errors</p>
                  <p className="font-medium text-red-600">{data.error_count}</p>
                </div>
              </div>

              {data.errors && data.errors.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">Error Details</h3>
                  <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
                    <table className="min-w-full divide-y divide-gray-300 text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          {["Resource Type", "Resource Name", "Operation", "Error"].map((h) => (
                            <th
                              key={h}
                              className="py-2 px-3 text-left font-medium text-gray-500 uppercase tracking-wide"
                            >
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200 bg-white">
                        {data.errors.map((e, i) => (
                          <tr key={i}>
                            <td className="py-2 px-3 font-mono text-gray-700">{e.resource_type}</td>
                            <td className="py-2 px-3 text-gray-700">{e.resource_name}</td>
                            <td className="py-2 px-3 text-gray-600">{e.operation}</td>
                            <td className="py-2 px-3 text-red-600 break-words">{e.error}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 1: Task List
// ---------------------------------------------------------------------------

interface TaskListTabProps {
  onOpenMonitoring: (task: ScheduledTask) => void;
}

function TaskListTab({ onOpenMonitoring }: TaskListTabProps) {
  const queryClient = useQueryClient();
  const [formModal, setFormModal] = useState<{ mode: "create" | "edit"; task?: ScheduledTask } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const { data: tasks, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["scheduled-tasks"],
    queryFn: fetchScheduledTasks,
  });

  const enableMut = useMutation({
    mutationFn: enableScheduledTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] }),
  });

  const disableMut = useMutation({
    mutationFn: disableScheduledTask,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] }),
  });

  const deleteMut = useMutation({
    mutationFn: deleteScheduledTask,
    onSuccess: () => {
      setDeleteConfirm(null);
      queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
    },
  });

  const triggerMut = useMutation({
    mutationFn: triggerScheduledTask,
    onSuccess: (data) => {
      setTriggerMsg(`Task triggered. Job ID: ${data.job_id}`);
      setTimeout(() => setTriggerMsg(null), 5000);
    },
  });

  return (
    <div>
      {triggerMsg && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md text-sm text-blue-700">
          {triggerMsg}
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-medium text-gray-900">Scheduled Tasks</h2>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            title="Refresh"
            className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-40 transition-colors"
          >
            <svg
              className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
        <button
          onClick={() => setFormModal({ mode: "create" })}
          className="px-4 py-2 text-sm font-medium text-white bg-zs-500 rounded-md hover:bg-zs-600"
        >
          New Task
        </button>
      </div>

      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message="Failed to load scheduled tasks." />}

      {tasks && (
        <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
          <table className="min-w-full divide-y divide-gray-300 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {["Name", "Source", "Target", "Scope", "Schedule", "Status", "Last Run", "Next Run", "Actions"].map((h) => (
                  <th
                    key={h}
                    className="py-3 px-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {tasks.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-gray-500">
                    No scheduled tasks. Click New Task to create one.
                  </td>
                </tr>
              )}
              {tasks.map((task) => (
                <tr key={task.id} className="hover:bg-gray-50">
                  <td className="py-3 px-3 font-medium text-gray-900">{task.name}</td>
                  <td className="py-3 px-3 text-gray-600">{task.source_tenant_name}</td>
                  <td className="py-3 px-3 text-gray-600">{task.target_tenant_name}</td>
                  <td className="py-3 px-3 text-gray-600 max-w-xs">
                    <span className="text-xs">
                      {task.sync_mode === "label" ? (
                        <>
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-xs font-medium mr-1">
                            Label
                          </span>
                          {task.label_name}
                          {task.label_resource_types && (
                            <span className="text-gray-400 ml-1">
                              ({task.label_resource_types.length} types)
                            </span>
                          )}
                        </>
                      ) : (
                        task.resource_groups.map((g) => groupLabel(g)).join(", ")
                      )}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-gray-600 whitespace-nowrap">
                    {humanCron(task.cron_expression)}
                  </td>
                  <td className="py-3 px-3">
                    <EnabledBadge enabled={task.enabled} />
                  </td>
                  <td className="py-3 px-3">
                    <div className="text-xs text-gray-600">{formatTimestamp(task.last_run_at)}</div>
                    <RunStatusBadge status={task.last_run_status} />
                  </td>
                  <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap">
                    {task.enabled ? formatTimestamp(task.next_run_at) : "-"}
                  </td>
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-1">
                      {/* Edit */}
                      <button
                        onClick={() => setFormModal({ mode: "edit", task })}
                        title="Edit"
                        className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                      {/* Enable/Disable toggle */}
                      <button
                        onClick={() =>
                          task.enabled ? disableMut.mutate(task.id) : enableMut.mutate(task.id)
                        }
                        title={task.enabled ? "Disable" : "Enable"}
                        className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                      >
                        {task.enabled ? (
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        ) : (
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        )}
                      </button>
                      {/* Manual trigger */}
                      <button
                        onClick={() => triggerMut.mutate(task.id)}
                        title="Run now"
                        className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        </svg>
                      </button>
                      {/* Monitoring */}
                      <button
                        onClick={() => onOpenMonitoring(task)}
                        title="View run history"
                        className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                      </button>
                      {/* Delete */}
                      <button
                        onClick={() => setDeleteConfirm(task.id)}
                        title="Delete"
                        className="p-2 rounded-md text-gray-500 hover:text-red-600 hover:bg-red-50"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 z-50 bg-black bg-opacity-40 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete Task</h3>
            <p className="text-sm text-gray-600 mb-4">
              Are you sure? This will permanently delete the task and all its run history.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMut.mutate(deleteConfirm)}
                disabled={deleteMut.isPending}
                className="px-4 py-2 text-sm text-white bg-red-600 rounded-md hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMut.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Task form modal */}
      {formModal && (
        <TaskFormModal
          mode={formModal.mode}
          initial={formModal.task}
          onClose={() => setFormModal(null)}
          onSaved={() => setFormModal(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 2: Task Monitoring
// ---------------------------------------------------------------------------

interface MonitoringTabProps {
  initialTaskId?: number | null;
}

function MonitoringTab({ initialTaskId }: MonitoringTabProps) {
  const { data: tasks } = useQuery({ queryKey: ["scheduled-tasks"], queryFn: fetchScheduledTasks });
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(initialTaskId ?? null);
  const [detailRun, setDetailRun] = useState<{ taskId: number; runId: number } | null>(null);

  const { data: runs, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["scheduled-task-runs", selectedTaskId],
    queryFn: () => (selectedTaskId ? fetchTaskRuns(selectedTaskId) : Promise.resolve([])),
    enabled: selectedTaskId !== null,
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-medium text-gray-900">Task Monitoring</h2>
        <button
          onClick={() => refetch()}
          disabled={isFetching || !selectedTaskId}
          title="Refresh"
          className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-40 transition-colors"
        >
          <svg
            className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">Select Task</label>
        <select
          value={selectedTaskId ?? ""}
          onChange={(e) => setSelectedTaskId(e.target.value ? Number(e.target.value) : null)}
          className="w-full max-w-md border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        >
          <option value="">Choose a task...</option>
          {(tasks ?? []).map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </div>

      {!selectedTaskId && (
        <p className="text-gray-500 text-sm">Select a task above to view its run history.</p>
      )}

      {selectedTaskId && isLoading && <LoadingSpinner />}

      {selectedTaskId && runs && (
        <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
          <table className="min-w-full divide-y divide-gray-300 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {["Started", "Duration", "Status", "Resources Synced", "Errors"].map((h) => (
                  <th
                    key={h}
                    className="py-3 px-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {runs.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-gray-500">
                    No run history for this task.
                  </td>
                </tr>
              )}
              {runs.map((run) => (
                <tr key={run.id} className="hover:bg-gray-50">
                  <td className="py-3 px-3 text-gray-700">{formatTimestamp(run.started_at)}</td>
                  <td className="py-3 px-3 text-gray-600">{formatDuration(run.duration_seconds)}</td>
                  <td className="py-3 px-3">
                    <RunStatusBadge status={run.status} />
                  </td>
                  <td className="py-3 px-3 text-gray-700">{run.resources_synced}</td>
                  <td className="py-3 px-3">
                    {run.error_count > 0 ? (
                      <button
                        onClick={() =>
                          setDetailRun({ taskId: selectedTaskId, runId: run.id })
                        }
                        className="text-red-600 hover:text-red-800 hover:underline text-sm font-medium"
                      >
                        {run.error_count} {run.error_count === 1 ? "error" : "errors"}
                      </button>
                    ) : (
                      <span className="text-gray-400 text-sm">None</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detailRun && (
        <RunDetailPanel
          taskId={detailRun.taskId}
          runId={detailRun.runId}
          onClose={() => setDetailRun(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

type TabId = "tasks" | "monitoring";

export default function ScheduledTasksPage() {
  const [activeTab, setActiveTab] = useState<TabId>("tasks");
  const [monitoringTask, setMonitoringTask] = useState<number | null>(null);

  const tabs: Array<{ id: TabId; label: string }> = [
    { id: "tasks", label: "Scheduled Tasks" },
    { id: "monitoring", label: "Task Monitoring" },
  ];

  function handleOpenMonitoring(task: ScheduledTask) {
    setMonitoringTask(task.id);
    setActiveTab("monitoring");
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Scheduled Tasks</h1>
        <p className="mt-1 text-sm text-gray-500">
          Automate periodic ZIA configuration sync between tenants.
        </p>
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-zs-500 text-zs-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === "tasks" && (
        <TaskListTab onOpenMonitoring={handleOpenMonitoring} />
      )}
      {activeTab === "monitoring" && (
        <MonitoringTab initialTaskId={monitoringTask} />
      )}
    </div>
  );
}
