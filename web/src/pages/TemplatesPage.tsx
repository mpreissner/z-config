import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchTemplates,
  fetchTemplate,
  previewTemplateDetail,
  createTemplate,
  deleteTemplate,
  applyTemplate,
  ZIATemplate,
  ZIATemplateDetail,
} from "../api/templates";
import { fetchTenants } from "../api/tenants";
import { fetchSnapshots } from "../api/zia";
import { useJobStream, describeProgress } from "../hooks/useJobStream";
import { cancelJob } from "../api/jobs";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import TemplateResourcePicker from "../components/TemplateResourcePicker";
import TemplateShareDialog from "../components/TemplateShareDialog";
import { formatDateTime } from "../utils/time";

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function ProgressBar({ active, message }: { active: boolean; message?: string }) {
  if (!active) return null;
  return (
    <div className="mt-2 space-y-1.5">
      <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
        <div className="h-full w-2/5 bg-zs-500 rounded-full animate-indeterminate" />
      </div>
      <p className="text-xs text-gray-400 italic">
        {message ?? "This may take several minutes depending on the number of resources."}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create Template Dialog
// ---------------------------------------------------------------------------

/**
 * Four steps: pick a snapshot, pick what goes in, name it, confirm.
 *
 * Step 2 is the one that earns its place. A full template mirrors everything
 * portable in the snapshot — fine for cloning a tenant, far too much for
 * describing a single integration. A scoped template holds only the ticked
 * entries plus whatever they reference, which the server closes over at create
 * time; that closure is reported back on the finished template rather than
 * previewed here, so the boxes stay a record of what was actually chosen.
 */
function CreateTemplateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [sourceTenantId, setSourceTenantId] = useState<number | "">("");
  const [snapshotId, setSnapshotId] = useState<number | "">("");
  const [scopeMode, setScopeMode] = useState<"full" | "scoped">("scoped");
  const [selection, setSelection] = useState<Record<string, string[]>>({});
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"private" | "shared" | "org">("private");
  const [err, setErr] = useState<string | null>(null);

  const { data: allTenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
    staleTime: 60_000,
  });

  const { data: snapshots } = useQuery({
    queryKey: ["zia-snapshots-for-template", sourceTenantId],
    queryFn: () => {
      const src = allTenants?.find((t) => t.id === sourceTenantId);
      return src ? fetchSnapshots(src.name, "ZIA") : Promise.resolve([]);
    },
    enabled: !!sourceTenantId && !!allTenants,
  });

  const selectedSnapshot = snapshots?.find((s) => s.id === snapshotId) ?? null;

  const previewMut = useMutation({
    mutationFn: () =>
      previewTemplateDetail({
        source_tenant_id: sourceTenantId as number,
        snapshot_id: snapshotId as number,
      }),
    onSuccess: () => { setStep(2); setErr(null); },
    onError: (e: Error) => setErr(e.message),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createTemplate({
        source_tenant_id: sourceTenantId as number,
        snapshot_id: snapshotId as number,
        name: name.trim(),
        description: description.trim() || undefined,
        // Omitting `selection` is what makes a template full — an empty object
        // would read as "a scoped template containing nothing".
        selection: scopeMode === "scoped" ? selection : undefined,
        visibility,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
    },
    onError: (e: Error) => setErr(e.message),
  });

  const preview = previewMut.data ?? null;
  const selectedCount = Object.values(selection).reduce((n, ids) => n + ids.length, 0);
  const selectedTypes = Object.keys(selection).filter((t) => selection[t].length > 0);
  const sortedTenants = allTenants
    ? [...allTenants].sort((a, b) => a.name.localeCompare(b.name))
    : [];

  const STEP_LABELS = ["Select Snapshot", "Choose Resources", "Template Details", "Confirm"];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">Create Template from Snapshot</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 px-5 py-3 border-b border-gray-100 text-xs text-gray-500">
          {STEP_LABELS.map((label, i) => (
            <span key={label} className="flex items-center gap-2">
              {i > 0 && <span>&rarr;</span>}
              <span className={step === i + 1 ? "font-semibold text-zs-600" : ""}>
                {i + 1}. {label}
              </span>
            </span>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {err && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{err}</p>}

          {/* Step 1 */}
          {step === 1 && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Source Tenant</label>
                <select
                  value={sourceTenantId}
                  onChange={(e) => {
                    setSourceTenantId(e.target.value ? Number(e.target.value) : "");
                    setSnapshotId("");
                    setSelection({});
                    setErr(null);
                  }}
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                >
                  <option value="">Select tenant…</option>
                  {sortedTenants.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">ZIA Snapshot</label>
                <select
                  value={snapshotId}
                  onChange={(e) => {
                    setSnapshotId(e.target.value ? Number(e.target.value) : "");
                    setSelection({});
                    setErr(null);
                  }}
                  disabled={!sourceTenantId || !snapshots}
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:bg-gray-100"
                >
                  <option value="">Select snapshot…</option>
                  {(snapshots ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {formatDateTime(s.created_at)}{s.label ? ` — ${s.label}` : ""}
                    </option>
                  ))}
                  {snapshots?.length === 0 && <option disabled>No snapshots found</option>}
                </select>
              </div>
              {selectedSnapshot && (
                <div className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-md px-3 py-2 space-y-0.5">
                  <p><span className="font-medium">Created:</span> {formatDateTime(selectedSnapshot.created_at)}</p>
                  <p><span className="font-medium">Resources:</span> {selectedSnapshot.resource_count ?? "—"}</p>
                  {selectedSnapshot.label && <p><span className="font-medium">Label:</span> {selectedSnapshot.label}</p>}
                </div>
              )}
              {previewMut.isPending && (
                <ProgressBar active message="Analyzing snapshot resources…" />
              )}
            </div>
          )}

          {/* Step 2 — scope */}
          {step === 2 && preview && (
            <div className="space-y-4">
              <div className="border border-gray-200 rounded-md px-3 py-2">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scopeMode === "full"}
                    onChange={(e) => { setScopeMode(e.target.checked ? "full" : "scoped"); setErr(null); }}
                    className="mt-0.5"
                  />
                  <div>
                    <span className="text-sm font-medium text-gray-800">Include everything portable in this snapshot</span>
                    <p className="text-xs text-gray-500">
                      A full template across all {preview.included.length} resource type
                      {preview.included.length !== 1 ? "s" : ""} ({preview.included.reduce((n, r) => n + r.count, 0)} resources).
                      Only a full template can be applied in wipe mode. Leave this unticked to pick
                      individual resources below.
                    </p>
                  </div>
                </label>
              </div>

              <TemplateResourcePicker
                entries={preview.entries}
                selection={selection}
                onChange={(next) => { setSelection(next); setErr(null); }}
                disabled={scopeMode === "full"}
              />

              {preview.stripped.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-amber-700 mb-2">Stripped types (tenant-specific, {preview.stripped.length}):</p>
                  <div className="max-h-32 overflow-y-auto border border-amber-200 rounded-md">
                    <table className="min-w-full text-xs divide-y divide-amber-100">
                      <thead className="bg-amber-50 sticky top-0">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-medium text-amber-600 uppercase">Type</th>
                          <th className="px-3 py-1.5 text-right font-medium text-amber-600 uppercase">Count</th>
                          <th className="px-3 py-1.5 text-left font-medium text-amber-600 uppercase">Reason</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-amber-100 bg-white">
                        {preview.stripped.map((r) => (
                          <tr key={r.resource_type}>
                            <td className="px-3 py-1.5 font-mono text-gray-700">{r.resource_type}</td>
                            <td className="px-3 py-1.5 text-right text-gray-700">{r.count}</td>
                            <td className="px-3 py-1.5 text-amber-700">{r.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {preview.stripped_rule_entries?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-orange-700 mb-2">Stripped rules (location/ZPA-scoped, {preview.stripped_rule_entries.reduce((s, r) => s + r.count, 0)} rules across {preview.stripped_rule_entries.length} type{preview.stripped_rule_entries.length !== 1 ? "s" : ""}):</p>
                  <div className="max-h-24 overflow-y-auto border border-orange-200 rounded-md">
                    <table className="min-w-full text-xs divide-y divide-orange-100">
                      <thead className="bg-orange-50 sticky top-0">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-medium text-orange-600 uppercase">Type</th>
                          <th className="px-3 py-1.5 text-right font-medium text-orange-600 uppercase">Stripped</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-orange-100 bg-white">
                        {preview.stripped_rule_entries.map((r) => (
                          <tr key={r.resource_type}>
                            <td className="px-3 py-1.5 font-mono text-gray-700">{r.resource_type}</td>
                            <td className="px-3 py-1.5 text-right text-gray-700">{r.count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 3 — details */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Template Name <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => { setName(e.target.value); setErr(null); }}
                  placeholder="e.g. Corp-ZIA-Baseline-2026"
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Description (optional)</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe what this template is for…"
                  rows={2}
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 resize-none"
                />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-600 mb-1.5">Who can see it</p>
                <div className="space-y-1.5">
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input type="radio" name="newvis" checked={visibility === "private"} onChange={() => setVisibility("private")} className="mt-0.5" />
                    <div>
                      <span className="text-sm font-medium text-gray-800">Private</span>
                      <p className="text-xs text-gray-500">Only you and administrators. You can share it with named people afterwards.</p>
                    </div>
                  </label>
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input type="radio" name="newvis" checked={visibility === "org"} onChange={() => setVisibility("org")} className="mt-0.5" />
                    <div>
                      <span className="text-sm font-medium text-gray-800">Org-wide</span>
                      <p className="text-xs text-gray-500">Every account in this deployment can see and apply it.</p>
                    </div>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Step 4 — confirm */}
          {step === 4 && (
            <div className="space-y-3">
              <div className="bg-gray-50 border border-gray-200 rounded-md px-4 py-3 text-sm space-y-1.5">
                <p><span className="font-medium text-gray-600">Name:</span> {name}</p>
                {description && <p><span className="font-medium text-gray-600">Description:</span> {description}</p>}
                <p><span className="font-medium text-gray-600">Visibility:</span> {visibility === "org" ? "Org-wide" : "Private"}</p>
                {scopeMode === "scoped" ? (
                  <p>
                    <span className="font-medium text-gray-600">Scope:</span> {selectedCount} resource
                    {selectedCount !== 1 ? "s" : ""} across {selectedTypes.length} type{selectedTypes.length !== 1 ? "s" : ""}
                  </p>
                ) : (
                  <>
                    <p><span className="font-medium text-gray-600">Scope:</span> full snapshot</p>
                    <p><span className="font-medium text-gray-600">Included types:</span> {preview?.included.length ?? 0}</p>
                  </>
                )}
                <p><span className="font-medium text-gray-600">Stripped types:</span> {preview?.stripped.length ?? 0}</p>
              </div>

              {scopeMode === "scoped" && (
                <div className="text-xs text-gray-600 bg-blue-50 border border-blue-200 rounded-md px-3 py-2 space-y-1">
                  <p>
                    Anything the selected resources reference — network services, IP groups, labels,
                    URL categories — is pulled in automatically. The finished template lists exactly
                    what was added and flags any reference it could not resolve.
                  </p>
                  <p>
                    Rules are renumbered to close the gaps left by rules you did not select, so their
                    order relative to each other is kept but their numbers will differ from the source.
                  </p>
                  <p>
                    A scoped template can only be applied in merge mode — wipe mode would delete
                    everything the template does not contain.
                  </p>
                </div>
              )}

              {createMut.isPending && <ProgressBar active message="Creating template…" />}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
          >
            Cancel
          </button>
          <div className="flex gap-2">
            {step > 1 && (
              <button
                onClick={() => { setStep((s) => (s - 1) as 1 | 2 | 3 | 4); setErr(null); }}
                className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
              >
                Back
              </button>
            )}
            {step === 1 && (
              <button
                onClick={() => previewMut.mutate()}
                disabled={!sourceTenantId || !snapshotId || previewMut.isPending}
                className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
              >
                Next
              </button>
            )}
            {step === 2 && (
              <button
                onClick={() => {
                  if (scopeMode === "full" && (!preview || preview.included.length === 0)) {
                    setErr("No portable resources — cannot create a template with zero included types.");
                    return;
                  }
                  if (scopeMode === "scoped" && selectedCount === 0) {
                    setErr("Select at least one resource, or switch to a full template.");
                    return;
                  }
                  setErr(null);
                  setStep(3);
                }}
                className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
              >
                Next
              </button>
            )}
            {step === 3 && (
              <button
                onClick={() => {
                  if (!name.trim()) { setErr("Template name is required."); return; }
                  setErr(null);
                  setStep(4);
                }}
                className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
              >
                Next
              </button>
            )}
            {step === 4 && (
              <button
                onClick={() => createMut.mutate()}
                disabled={createMut.isPending}
                className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
              >
                Create Template
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Apply Template Dialog
// ---------------------------------------------------------------------------

interface ApplyTemplateResult {
  status: string;
  template_name: string;
  mode: string;
  wiped: number;
  created: number;
  updated: number;
  failed: number;
  failed_items: { resource_type: string; name: string; reason: string }[];
  warnings: { resource_type: string; name: string; warnings: string[] }[];
  cancelled?: boolean;
  rolled_back?: number;
  rollback_failed?: number;
}

function ApplyTemplateDialog({ template, onClose }: { template: ZIATemplate; onClose: () => void }) {
  const [targetTenantId, setTargetTenantId] = useState<number | "">("");
  const [wipeMode, setWipeMode] = useState(false);
  //: A scoped template covers part of a tenant, so wiping the rest is never
  //  what was meant. The API 422s it too — this only keeps the toggle honest.
  const isScoped = template.scope === "scoped";
  const [applyJobId, setApplyJobId] = useState<string | null>(null);
  const [mutErr, setMutErr] = useState<string | null>(null);

  const { data: allTenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
    staleTime: 60_000,
  });

  const applyMut = useMutation({
    mutationFn: () =>
      applyTemplate(targetTenantId as number, template.id, wipeMode),
    onSuccess: (data) => { setApplyJobId(data.job_id); setMutErr(null); },
    onError: (e: Error) => setMutErr(e.message),
  });

  const {
    latestEvent: applyLatest,
    jobStatus: applyJobStatus,
    result: applyResult,
    streamError: applyStreamError,
  } = useJobStream<ApplyTemplateResult>(applyJobId);

  const isApplyRunning = applyMut.isPending || applyJobStatus === "running";
  const applyDone = applyJobStatus === "done";
  const applyCancelled = applyJobStatus === "cancelled" || (applyJobStatus === "done" && !!applyResult?.cancelled);

  const sortedTenants = allTenants
    ? [...allTenants].sort((a, b) => a.name.localeCompare(b.name))
    : [];

  const err = mutErr ?? applyStreamError ?? null;

  const applyPhaseLabel = () => describeProgress(applyLatest, "Applying template…");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">Apply Template to Tenant</h2>
          <button onClick={onClose} disabled={isApplyRunning} className="text-gray-400 hover:text-gray-600 disabled:opacity-40">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <div className="text-sm text-gray-700">
            Applying template <span className="font-medium">{template.name}</span>
            {template.description && <span className="text-gray-500"> — {template.description}</span>}
          </div>

          {err && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{err}</p>}

          {/* Cancelled view */}
          {applyCancelled && (
            <div className="p-3 rounded-md text-sm bg-amber-50 text-amber-800">
              <p className="font-medium">Push cancelled.</p>
              {applyResult?.rolled_back !== undefined ? (
                <p className="text-xs mt-1">
                  Rolled back {applyResult.rolled_back} change{applyResult.rolled_back !== 1 ? "s" : ""}.
                  {!!applyResult.rollback_failed && ` ${applyResult.rollback_failed} rollback${applyResult.rollback_failed !== 1 ? "s" : ""} failed — check ZIA manually.`}
                </p>
              ) : (
                <p className="text-xs mt-1">Any changes already pushed to ZIA remain in effect.</p>
              )}
            </div>
          )}

          {/* Apply result */}
          {applyDone && applyResult && !applyCancelled && (() => {
            const ok = applyResult.status === "SUCCESS" || applyResult.status === "PARTIAL";
            return (
              <div className="space-y-3">
                <div className={`p-3 rounded-md text-sm ${ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
                  <p className="font-medium">
                    {applyResult.status} — Template &ldquo;{applyResult.template_name}&rdquo; applied
                    <span className="ml-2 font-normal text-xs opacity-70">({applyResult.mode === "wipe" ? "Wipe & Push" : "Delta Push"})</span>
                  </p>
                  <p className="text-xs mt-1">
                    {applyResult.mode === "wipe" && applyResult.wiped > 0 && `${applyResult.wiped} wiped · `}
                    {applyResult.created} created · {applyResult.updated} updated
                    {applyResult.failed > 0 && ` · ${applyResult.failed} failed`}
                  </p>
                </div>

                {applyResult.failed_items?.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-red-700 mb-1">Failed resources ({applyResult.failed_items.length}):</p>
                    <div className="max-h-40 overflow-y-auto border border-red-200 rounded-md">
                      <table className="min-w-full text-xs divide-y divide-red-100">
                        <thead className="bg-red-50 sticky top-0">
                          <tr>
                            <th className="px-3 py-1.5 text-left font-medium text-red-600 uppercase">Type</th>
                            <th className="px-3 py-1.5 text-left font-medium text-red-600 uppercase">Name</th>
                            <th className="px-3 py-1.5 text-left font-medium text-red-600 uppercase">Reason</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-red-100 bg-white">
                          {applyResult.failed_items.map((item, i) => (
                            <tr key={i}>
                              <td className="px-3 py-1 font-mono text-gray-500">{item.resource_type}</td>
                              <td className="px-3 py-1 text-gray-800">{item.name}</td>
                              <td className="px-3 py-1 text-red-700 font-mono text-xs break-all">{item.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {applyResult.warnings?.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-amber-700 mb-1">Warnings ({applyResult.warnings.length} resources):</p>
                    <div className="max-h-48 overflow-y-auto border border-amber-200 rounded-md divide-y divide-amber-100">
                      {applyResult.warnings.map((w, i) => (
                        <div key={i} className="px-3 py-2 bg-amber-50">
                          <p className="text-xs font-medium text-gray-700 font-mono">{w.resource_type}: {w.name}</p>
                          <ul className="mt-0.5 space-y-0.5">
                            {w.warnings.map((msg, j) => (
                              <li key={j} className="text-xs text-amber-800">{msg}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Form (pre-apply) */}
          {!applyDone && !applyCancelled && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Target Tenant</label>
                <select
                  value={targetTenantId}
                  onChange={(e) => { setTargetTenantId(e.target.value ? Number(e.target.value) : ""); setMutErr(null); }}
                  disabled={isApplyRunning}
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:bg-gray-100"
                >
                  <option value="">Select tenant…</option>
                  {sortedTenants.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <p className="text-xs font-medium text-gray-600 mb-1.5">Apply mode:</p>
                <div className="space-y-1.5">
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="mode"
                      checked={!wipeMode}
                      onChange={() => setWipeMode(false)}
                      disabled={isApplyRunning}
                      className="mt-0.5"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-800">Delta Push</span>
                      <p className="text-xs text-gray-500">Applies creates and updates only. Resources not in the template are left untouched.</p>
                    </div>
                  </label>
                  <label className={`flex items-start gap-2 ${isScoped ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                    <input
                      type="radio"
                      name="mode"
                      checked={wipeMode}
                      onChange={() => setWipeMode(true)}
                      disabled={isApplyRunning || isScoped}
                      className="mt-0.5"
                    />
                    <div>
                      <span className="text-sm font-medium text-red-700">Wipe &amp; Push</span>
                      <p className="text-xs text-gray-500">Deletes all user-created resources first, then pushes the full template. More thorough but destructive.</p>
                      {isScoped && (
                        <p className="text-xs text-amber-700 mt-0.5">
                          Unavailable for a scoped template: it holds only part of a tenant, so a wipe
                          would delete everything it leaves out. The API rejects this combination.
                        </p>
                      )}
                    </div>
                  </label>
                </div>
              </div>

              {/* Apply progress */}
              {isApplyRunning && (
                <div className="space-y-1.5">
                  <p className="text-xs text-gray-500">{applyPhaseLabel()}</p>
                  <ProgressBar active message="Applying template — this may take several minutes." />
                  <button
                    onClick={() => applyJobId && cancelJob(applyJobId)}
                    className="px-3 py-1 text-xs rounded-md border border-gray-300 hover:bg-gray-50 text-gray-600"
                  >
                    Stop
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-200">
          {(applyDone || applyCancelled) ? (
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
            >
              Close
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                disabled={isApplyRunning}
                className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => applyMut.mutate()}
                disabled={!targetTenantId || isApplyRunning}
                className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
              >
                Apply Template
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chips
// ---------------------------------------------------------------------------

/** Reach at a glance. "Shared" carries the count because 0 recipients means the
 *  template reaches nobody but its owner, which the word alone hides. */
function VisibilityChip({ template }: { template: ZIATemplate }) {
  const styles: Record<string, string> = {
    private: "bg-gray-100 text-gray-600",
    shared: "bg-blue-50 text-blue-700",
    org: "bg-green-50 text-green-700",
  };
  const label =
    template.visibility === "org"
      ? "Org-wide"
      : template.visibility === "shared"
        ? `Shared with ${template.share_count}`
        : "Private";
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs ${styles[template.visibility] ?? styles.private}`}>
      {label}
    </span>
  );
}

function ScopeChip({ scope }: { scope: string }) {
  if (scope !== "scoped") return null;
  return (
    <span className="px-2 py-0.5 rounded-full text-xs bg-purple-50 text-purple-700">Scoped</span>
  );
}

// ---------------------------------------------------------------------------
// Template detail panel
// ---------------------------------------------------------------------------

function TemplateDetail({ templateId, onApply, onDelete, onShare }: {
  templateId: number;
  onApply: (t: ZIATemplate) => void;
  onDelete: (t: ZIATemplate) => void;
  onShare: (t: ZIATemplate) => void;
}) {
  const { data: tmpl, isLoading, error } = useQuery<ZIATemplateDetail>({
    queryKey: ["template", templateId],
    queryFn: () => fetchTemplate(templateId),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error || !tmpl) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load template"} />;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-start justify-between mb-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900">{tmpl.name}</h2>
          {tmpl.description && <p className="text-sm text-gray-500 mt-0.5">{tmpl.description}</p>}
          <div className="flex items-center gap-2 mt-1.5">
            <VisibilityChip template={tmpl} />
            <ScopeChip scope={tmpl.scope} />
            <span className="text-xs text-gray-500">
              {tmpl.owner_username
                ? `Owned by ${tmpl.is_owner ? "you" : tmpl.owner_username}`
                : "No owner — predates ownership"}
            </span>
          </div>
        </div>
        <div className="flex gap-2 flex-shrink-0 ml-4">
          <button
            onClick={() => onApply(tmpl)}
            className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
          >
            Apply to Tenant
          </button>
          {tmpl.can_manage && (
            <button
              onClick={() => onShare(tmpl)}
              className="px-3 py-1.5 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
            >
              Share
            </button>
          )}
          <button
            onClick={() => onDelete(tmpl)}
            disabled={!tmpl.can_manage}
            title={
              tmpl.can_manage
                ? undefined
                : tmpl.owner_username
                  ? `Only ${tmpl.owner_username} or an administrator can delete this template`
                  : "This template predates ownership — only an administrator can delete it"
            }
            className="px-3 py-1.5 text-sm rounded-md border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-40 disabled:hover:bg-transparent disabled:cursor-not-allowed"
          >
            Delete
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm mb-4">
        <div className="bg-gray-50 rounded-md px-3 py-2">
          <p className="text-xs text-gray-500 mb-0.5">Source Tenant</p>
          <p className="font-medium text-gray-800">{tmpl.source_tenant_name ?? <span className="text-gray-400 italic">tenant deleted</span>}</p>
        </div>
        <div className="bg-gray-50 rounded-md px-3 py-2">
          <p className="text-xs text-gray-500 mb-0.5">Resource Count</p>
          <p className="font-medium text-gray-800">{tmpl.resource_count}</p>
        </div>
        <div className="bg-gray-50 rounded-md px-3 py-2">
          <p className="text-xs text-gray-500 mb-0.5">Created</p>
          <p className="font-medium text-gray-800">{tmpl.created_at ? formatDateTime(tmpl.created_at) : "—"}</p>
        </div>
        <div className="bg-gray-50 rounded-md px-3 py-2">
          <p className="text-xs text-gray-500 mb-0.5">Updated</p>
          <p className="font-medium text-gray-800">{tmpl.updated_at ? formatDateTime(tmpl.updated_at) : "—"}</p>
        </div>
      </div>

      {tmpl.stripped_types.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-amber-700 mb-1.5">Stripped types (excluded from template):</p>
          <div className="flex flex-wrap gap-1.5">
            {tmpl.stripped_types.map((t) => (
              <span key={t} className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-800 font-mono">{t}</span>
            ))}
          </div>
        </div>
      )}

      {tmpl.selection_meta && (
        <div className="mb-4 space-y-3">
          {tmpl.selection_meta.warnings.length > 0 && (
            <div className="border border-amber-200 bg-amber-50 rounded-md px-3 py-2">
              <p className="text-xs font-medium text-amber-800 mb-1">
                Unresolved references ({tmpl.selection_meta.warnings.length}):
              </p>
              <ul className="space-y-0.5">
                {tmpl.selection_meta.warnings.map((w, i) => (
                  <li key={i} className="text-xs text-amber-800">{w}</li>
                ))}
              </ul>
            </div>
          )}
          {tmpl.selection_meta.auto_included.length > 0 && (
            <div>
              {/* Named separately from the picked resources so it stays clear
                  what the author chose and what the closure dragged in. */}
              <p className="text-xs font-medium text-gray-700 mb-1.5">
                Pulled in automatically ({tmpl.selection_meta.auto_included.length}):
              </p>
              <div className="overflow-y-auto border border-gray-200 rounded-md" style={{ maxHeight: "160px" }}>
                <table className="min-w-full text-xs divide-y divide-gray-100">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Type</th>
                      <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Name</th>
                      <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Required by</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {tmpl.selection_meta.auto_included.map((a, i) => (
                      <tr key={i}>
                        <td className="px-3 py-1 font-mono text-gray-500">{a.resource_type}</td>
                        <td className="px-3 py-1 text-gray-800">
                          {a.name}
                          {a.predefined && (
                            <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-400">predefined</span>
                          )}
                        </td>
                        <td className="px-3 py-1 text-gray-500">{a.required_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {tmpl.included_types && tmpl.included_types.length > 0 && (
        <div className="flex-1 min-h-0">
          <p className="text-xs font-medium text-gray-700 mb-1.5">Included resource types:</p>
          <div className="overflow-y-auto border border-gray-200 rounded-md" style={{ maxHeight: "280px" }}>
            <table className="min-w-full text-xs divide-y divide-gray-100">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Resource Type</th>
                  <th className="px-3 py-1.5 text-right font-medium text-gray-500 uppercase">Count</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {tmpl.included_types.map((r) => (
                  <tr key={r.resource_type}>
                    <td className="px-3 py-1.5 font-mono text-gray-700">{r.resource_type}</td>
                    <td className="px-3 py-1.5 text-right text-gray-700">{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delete confirmation
// ---------------------------------------------------------------------------

function DeleteConfirmDialog({ template, onClose, onDeleted }: {
  template: ZIATemplate;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const deleteMut = useMutation({
    mutationFn: () => deleteTemplate(template.id),
    onSuccess: () => { onDeleted(); onClose(); },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-5 space-y-4">
        <h2 className="text-base font-semibold text-gray-900">Delete Template</h2>
        <p className="text-sm text-gray-600">
          Are you sure you want to delete <span className="font-medium">{template.name}</span>? This cannot be undone.
        </p>
        {deleteMut.isError && (
          <ErrorMessage message={deleteMut.error instanceof Error ? deleteMut.error.message : "Delete failed"} />
        )}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={() => deleteMut.mutate()}
            disabled={deleteMut.isPending}
            className="px-4 py-1.5 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TemplatesPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [applyTarget, setApplyTarget] = useState<ZIATemplate | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ZIATemplate | null>(null);
  const [shareTarget, setShareTarget] = useState<ZIATemplate | null>(null);

  const { data: templates, isLoading, error, refetch, isFetching } = useQuery<ZIATemplate[]>({
    queryKey: ["templates"],
    queryFn: fetchTemplates,
  });

  function handleCreated() {
    queryClient.invalidateQueries({ queryKey: ["templates"] });
  }

  function handleDeleted() {
    queryClient.invalidateQueries({ queryKey: ["templates"] });
    if (deleteTarget && selectedId === deleteTarget.id) {
      setSelectedId(null);
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">ZIA Templates</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { refetch(); }}
            disabled={isFetching}
            title="Refresh"
            className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-40 transition-colors"
          >
            <svg
              className={`h-5 w-5 ${isFetching ? "animate-spin" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
          >
            Create Template from Snapshot
          </button>
        </div>
      </div>

      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load templates"} />}

      {!isLoading && !error && templates && (
        <div className="flex gap-4 flex-1 min-h-0">
          {/* Left panel — list */}
          <div className="w-72 flex-shrink-0 flex flex-col border border-gray-200 rounded-lg overflow-hidden">
            <div className="px-3 py-2 bg-gray-50 border-b border-gray-200">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Templates ({templates.length})
              </p>
            </div>
            {templates.length === 0 ? (
              <div className="flex-1 flex items-center justify-center p-6">
                <p className="text-sm text-gray-400 text-center">
                  No templates yet. Save a snapshot from a ZIA tenant and create a template from it.
                </p>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedId(t.id)}
                    className={`w-full text-left px-3 py-3 hover:bg-gray-50 transition-colors ${
                      selectedId === t.id ? "bg-zs-50 border-l-2 border-zs-500" : ""
                    }`}
                  >
                    <p className="text-sm font-medium text-gray-800 truncate">{t.name}</p>
                    {t.description && (
                      <p className="text-xs text-gray-500 truncate mt-0.5">{t.description}</p>
                    )}
                    <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                      <VisibilityChip template={t} />
                      <ScopeChip scope={t.scope} />
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-xs text-gray-400 truncate">
                        {t.resource_count} resources
                        {t.owner_username && ` · ${t.is_owner ? "you" : t.owner_username}`}
                      </span>
                      <span className="text-xs text-gray-400 flex-shrink-0 ml-2">
                        {t.created_at ? formatDateTime(t.created_at) : ""}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Right panel — detail */}
          <div className="flex-1 min-h-0 border border-gray-200 rounded-lg p-4 overflow-y-auto">
            {selectedId ? (
              <TemplateDetail
                templateId={selectedId}
                onApply={(t) => setApplyTarget(t)}
                onDelete={(t) => setDeleteTarget(t)}
                onShare={(t) => setShareTarget(t)}
              />
            ) : (
              <div className="h-full flex items-center justify-center">
                <p className="text-sm text-gray-400">
                  {templates.length === 0
                    ? "Create your first template using the button above."
                    : "Select a template from the list to view its details."}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Dialogs */}
      {showCreate && (
        <CreateTemplateDialog
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
      {applyTarget && (
        <ApplyTemplateDialog
          template={applyTarget}
          onClose={() => setApplyTarget(null)}
        />
      )}
      {shareTarget && (
        <TemplateShareDialog
          template={shareTarget}
          onClose={() => setShareTarget(null)}
          onChanged={() => {
            queryClient.invalidateQueries({ queryKey: ["templates"] });
            queryClient.invalidateQueries({ queryKey: ["template", shareTarget.id] });
          }}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmDialog
          template={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={handleDeleted}
        />
      )}
    </div>
  );
}
