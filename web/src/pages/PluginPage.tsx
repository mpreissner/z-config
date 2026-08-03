/**
 * The page behind every plugin nav item.
 *
 * There is one of these for all plugins, not one per plugin: a plugin declares
 * its actions and their parameters (see lib/plugin_web.py) and this renders the
 * form, runs the action as a job and shows what came back. Plugins ship no
 * JavaScript, so nothing installed from GitHub can execute in the browser, and
 * a plugin that describes itself badly loses its own nav item and nothing else.
 *
 * A plugin whose actions are steps of one job says so, and the page grows a
 * context bar and a step strip around the same machinery: the values in the bar
 * are chosen once and folded into every action that named them, which the
 * server does — not this — so they are checked exactly like any other parameter.
 */

import { useState, useEffect, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  fetchPluginUi,
  runPluginAction,
  fetchPluginActionOptions,
  fetchPluginContextOptions,
  fetchPluginState,
  downloadPluginArtifact,
  PluginAction,
  PluginParam,
  PluginActionResult,
  PluginStepStatus,
  PluginUi,
} from "../api/plugins";
import { fetchTenants } from "../api/tenants";
import { cancelJob } from "../api/jobs";
import { useJobStream } from "../hooks/useJobStream";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import SelectionGrid from "../components/plugin/SelectionGrid";
import ResultSections from "../components/plugin/ResultSections";

type Values = Record<string, unknown>;
type Files = Record<string, File>;

const inputClass =
  "w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-zs-500 focus:border-zs-500";

/** Starting values for one action's form, honouring any declared defaults. */
function initialValues(action: PluginAction): Values {
  const out: Values = {};
  for (const p of action.params) {
    if (p.default !== undefined) out[p.name] = p.default;
    else if (p.type === "boolean") out[p.name] = false;
    // A grid is left undefined until its rows load, so the ticks the plugin
    // arrives with can seed it without overwriting a choice already made.
    else if (p.type === "selection") out[p.name] = undefined;
    else out[p.name] = "";
  }
  return out;
}

function ParamField({ param, value, siblings, pkg, actionKey, onChange, onFile }: {
  param: PluginParam;
  value: unknown;
  /** The rest of the form — what a dynamic select's options are computed from. */
  siblings: Values;
  pkg: string;
  /** Null for a page-level context value, which has no action to ask through. */
  actionKey: string | null;
  onChange: (v: unknown) => void;
  onFile: (f: File | null) => void;
}) {
  const { data: tenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
    // Only a tenant parameter needs the list, and it is the same list the nav
    // already holds, so this almost always answers from cache.
    enabled: param.type === "tenant",
    staleTime: 60_000,
  });

  // What a dynamic select reads, and whether it has been given enough to ask.
  const deps = useMemo(() => {
    const out: Values = {};
    for (const name of param.depends_on ?? []) out[name] = siblings[name];
    return out;
  }, [param.depends_on, siblings]);
  const ready = (param.depends_on ?? []).every(
    (n) => deps[n] !== "" && deps[n] !== null && deps[n] !== undefined,
  );

  const {
    data: loaded,
    isFetching: loadingOptions,
    error: optionsError,
  } = useQuery({
    queryKey: ["plugin-options", pkg, actionKey ?? "__context__", param.name, deps],
    queryFn: () =>
      actionKey
        ? fetchPluginActionOptions(pkg, actionKey, param.name, deps)
        : fetchPluginContextOptions(pkg, param.name, deps),
    enabled: !!param.dynamic && ready,
    retry: false,
  });

  const options = param.dynamic ? loaded?.options ?? [] : param.options ?? [];

  // A choice made before a dependency changed is not a choice in the new list.
  // Left alone it would sit there looking selected and be refused on submit.
  useEffect(() => {
    if (!param.dynamic) return;
    if (param.type === "selection") {
      if (!loaded) return;
      const offered = new Set(loaded.options.map((o) => o.value));
      if (value === undefined) {
        onChange(loaded.options.filter((o) => o.selected).map((o) => o.value));
        return;
      }
      const kept = (value as string[]).filter((v) => offered.has(v));
      if (kept.length !== (value as string[]).length) onChange(kept);
      return;
    }
    if (!value) return;
    if (!loaded) {
      if (!ready) onChange("");
      return;
    }
    if (!loaded.options.some((o) => o.value === String(value))) onChange("");
    // onChange is a fresh closure each render; depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, ready, param.dynamic]);

  const label = (
    <label className="block text-sm font-medium text-gray-700 mb-1">
      {param.label}
      {!param.required && <span className="ml-1 text-xs text-gray-400">(optional)</span>}
    </label>
  );
  const help = param.help && <p className="mt-1 text-xs text-gray-500">{param.help}</p>;

  if (param.type === "boolean") {
    return (
      <div>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-zs-500 focus:ring-zs-500"
          />
          {param.label}
        </label>
        {help}
      </div>
    );
  }

  return (
    <div>
      {label}
      {param.type === "textarea" && (
        <textarea
          rows={5}
          value={String(value ?? "")}
          placeholder={param.placeholder ?? undefined}
          onChange={(e) => onChange(e.target.value)}
          className={`${inputClass} font-mono`}
        />
      )}
      {param.type === "select" && (
        <>
          <select
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value)}
            disabled={!!param.dynamic && (!ready || loadingOptions)}
            className={`${inputClass} disabled:bg-gray-50 disabled:text-gray-400`}
          >
            <option value="">
              {!param.dynamic
                ? "Select…"
                : !ready
                  ? `Choose ${(param.depends_on ?? []).join(" and ")} first…`
                  : loadingOptions
                    ? "Loading…"
                    : "Select…"}
            </option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {param.dynamic && optionsError && (
            <p className="mt-1 text-xs text-red-600">
              {optionsError instanceof Error
                ? optionsError.message
                : "Could not load the options"}
            </p>
          )}
          {param.dynamic && ready && !loadingOptions && !optionsError &&
            options.length === 0 && (
              <p className="mt-1 text-xs text-gray-500">Nothing to choose from here yet.</p>
            )}
        </>
      )}
      {param.type === "selection" && (
        <>
          {!ready ? (
            <p className="rounded-md border border-dashed border-gray-300 px-3 py-4 text-sm italic text-gray-400">
              Choose {(param.depends_on ?? []).join(" and ")} first.
            </p>
          ) : (
            <SelectionGrid
              param={param}
              options={options}
              value={(value as string[]) ?? []}
              onChange={onChange}
              loading={loadingOptions}
            />
          )}
          {optionsError && (
            <p className="mt-1 text-xs text-red-600">
              {optionsError instanceof Error
                ? optionsError.message
                : "Could not load the rows"}
            </p>
          )}
        </>
      )}
      {param.type === "tenant" && (
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={inputClass}
        >
          <option value="">Select a tenant…</option>
          {(tenants ?? []).map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      )}
      {param.type === "file" && (
        <input
          type="file"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-zs-500 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-zs-600"
        />
      )}
      {["text", "password", "number"].includes(param.type) && (
        <input
          type={param.type === "number" ? "number" : param.type}
          value={String(value ?? "")}
          placeholder={param.placeholder ?? undefined}
          onChange={(e) => onChange(e.target.value)}
          className={inputClass}
          autoComplete={param.type === "password" ? "new-password" : "off"}
        />
      )}
      {help}
    </div>
  );
}

/** Bytes as something a person reads, for the size beside a download button. */
function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}

function ResultView({ result, jobId, onAction }: {
  result: PluginActionResult;
  jobId: string;
  onAction?: (key: string) => void;
}) {
  const details = Object.entries(result.details ?? {});
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const download = result.download;
  const sections = result.sections ?? [];

  return (
    <div className="mt-4 rounded-md border border-green-200 bg-green-50 p-4">
      <p className="text-sm font-medium text-green-900">{result.message}</p>

      {download && (
        <div className="mt-3">
          <button
            onClick={() =>
              downloadPluginArtifact(jobId, download.filename)
                .then(() => setDownloadError(null))
                .catch((e) =>
                  setDownloadError(e instanceof Error ? e.message : "Download failed"),
                )
            }
            className="inline-flex items-center gap-2 rounded-md bg-zs-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-zs-600"
          >
            Download {download.filename}
            <span className="text-xs text-white/70">{humanSize(download.size)}</span>
          </button>
          {downloadError && <p className="mt-1 text-xs text-red-600">{downloadError}</p>}
        </div>
      )}

      {sections.length > 0 && (
        <div className="mt-3">
          <ResultSections sections={sections} onAction={onAction} />
        </div>
      )}

      {details.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
          {details.map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs uppercase tracking-wide text-green-700">{k}</dt>
              <dd className="font-mono text-gray-800">
                {typeof v === "object" ? JSON.stringify(v) : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {result.table && result.table.columns.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-md border border-green-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                {result.table.columns.map((c) => (
                  <th key={c} className="px-3 py-2 text-left font-medium text-gray-600">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {result.table.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-1.5 text-gray-800">
                      {cell === null || cell === undefined ? "" : String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {result.table.rows.length === 0 && (
            <p className="px-3 py-2 text-sm italic text-gray-400">No rows</p>
          )}
        </div>
      )}
    </div>
  );
}

function ActionCard({ pkg, action, context, contextParams, onFinished, onAction }: {
  pkg: string;
  action: PluginAction;
  /** Page-level values this action named. Submitted alongside its own. */
  context: Values;
  contextParams: PluginParam[];
  /** Fires when a run completes, so the step strip can catch up. */
  onFinished?: () => void;
  onAction?: (key: string) => void;
}) {
  const [values, setValues] = useState<Values>(() => initialValues(action));
  const [files, setFiles] = useState<Files>({});
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { progressEvents, jobStatus, result, streamError } =
    useJobStream<PluginActionResult>(jobId);
  const running = starting || jobStatus === "running";

  // Context is part of the form as far as a dependent parameter is concerned:
  // a grid that reads the chosen session has to see it to know it may load.
  const wanted = action.context ?? [];
  const siblings = useMemo(() => {
    const out: Values = { ...values };
    for (const name of wanted) out[name] = context[name];
    return out;
  }, [values, context, wanted]);

  const missingContext = wanted.filter((name) => {
    const spec = contextParams.find((c) => c.name === name);
    const v = context[name];
    return spec?.required !== false && (v === undefined || v === null || v === "");
  });

  useEffect(() => {
    if (jobStatus === "done") onFinished?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobStatus]);

  async function start() {
    if (action.confirm && !window.confirm(action.confirm)) return;
    setError(null);
    setJobId(null);
    setStarting(true);
    try {
      // File values live outside `values`; everything else goes as declared,
      // with the context values the action named added to it.
      const payload: Values = {};
      for (const name of wanted) payload[name] = context[name];
      for (const p of action.params) {
        if (p.type === "file") continue;
        payload[p.name] = p.type === "selection" ? (values[p.name] ?? []) : values[p.name];
      }
      const r = await runPluginAction(pkg, action.key, payload, files);
      setJobId(r.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the action");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-medium text-gray-900">{action.label}</h2>
      {action.description && (
        <p className="mt-1 text-sm text-gray-500">{action.description}</p>
      )}

      {action.params.length > 0 && (
        <div className="mt-4 space-y-4">
          {action.params.map((p) => (
            <ParamField
              key={p.name}
              param={p}
              value={values[p.name]}
              siblings={siblings}
              pkg={pkg}
              actionKey={action.key}
              onChange={(v) => setValues((prev) => ({ ...prev, [p.name]: v }))}
              onFile={(f) =>
                setFiles((prev) => {
                  const next = { ...prev };
                  if (f) next[p.name] = f;
                  else delete next[p.name];
                  return next;
                })
              }
            />
          ))}
        </div>
      )}

      <div className="mt-5 flex items-center gap-3">
        <button
          onClick={start}
          disabled={running || missingContext.length > 0}
          className={`rounded-md px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-60 ${
            action.destructive ? "bg-red-600 hover:bg-red-700" : "bg-zs-500 hover:bg-zs-600"
          }`}
        >
          {running ? "Running…" : action.label}
        </button>
        {running && jobId && (
          <button
            onClick={() => cancelJob(jobId).catch(() => {})}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
        )}
        {missingContext.length > 0 && (
          <span className="text-sm text-gray-500">
            Choose {missingContext
              .map((n) => contextParams.find((c) => c.name === n)?.label ?? n)
              .join(" and ")} above first.
          </span>
        )}
      </div>

      {error && <div className="mt-4"><ErrorMessage message={error} /></div>}

      {jobId && progressEvents.length > 0 && (
        <div className="mt-4 max-h-48 overflow-y-auto rounded-md bg-gray-900 p-3 font-mono text-xs text-gray-100">
          {progressEvents.map((e, i) => (
            <div key={i}>{e.message ?? e.phase}</div>
          ))}
        </div>
      )}

      {jobStatus === "cancelled" && (
        <p className="mt-3 text-sm text-gray-500">Cancelled.</p>
      )}
      {jobStatus === "error" && streamError && (
        <div className="mt-4"><ErrorMessage message={streamError} /></div>
      )}
      {jobStatus === "done" && result && jobId && (
        <ResultView result={result} jobId={jobId} onAction={onAction} />
      )}
    </div>
  );
}

const STEP_DOT: Record<PluginStepStatus, string> = {
  complete: "bg-green-500",
  current: "bg-zs-500",
  blocked: "bg-amber-500",
  pending: "bg-gray-300",
};

/** The context bar: values chosen once and kept while the user moves around. */
function ContextBar({ pkg, params, values, onChange }: {
  pkg: string;
  params: PluginParam[];
  values: Values;
  onChange: (name: string, value: unknown) => void;
}) {
  return (
    <div className="sticky top-0 z-10 rounded-lg border border-gray-200 bg-gray-50 p-4 shadow-sm">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {params.map((p) => (
          <ParamField
            key={p.name}
            param={p}
            value={values[p.name]}
            siblings={values}
            pkg={pkg}
            actionKey={null}
            onChange={(v) => onChange(p.name, v)}
            onFile={() => {}}
          />
        ))}
      </div>
    </div>
  );
}

export default function PluginPage() {
  const { pkg = "" } = useParams<{ pkg: string }>();
  const [search, setSearch] = useSearchParams();
  const { data: ui, isLoading, error } = useQuery({
    queryKey: ["plugin-ui", pkg],
    queryFn: () => fetchPluginUi(pkg),
    enabled: !!pkg,
    retry: false,
  });

  const [activeKey, setActiveKey] = useState<string | null>(null);
  const actions = useMemo(() => ui?.actions ?? [], [ui]);
  const contextParams = useMemo(() => ui?.context ?? [], [ui]);
  const workflow = ui?.workflow ?? null;

  // Context lives in the query string, so a reload or a shared link comes back
  // to the same migration rather than an empty bar.
  const context = useMemo(() => {
    const out: Values = {};
    for (const p of contextParams) out[p.name] = search.get(p.name) ?? "";
    return out;
  }, [contextParams, search]);

  const contextReady =
    contextParams.length > 0 &&
    contextParams.every((p) => p.required === false || context[p.name]);

  const { data: state, refetch: refetchState } = useQuery({
    queryKey: ["plugin-state", pkg, context],
    queryFn: () => fetchPluginState(pkg, context),
    enabled: !!workflow?.stateful && contextReady,
    retry: false,
  });

  const active = actions.find((a) => a.key === activeKey) ?? actions[0] ?? null;
  const activeStep = useMemo(() => {
    if (!workflow || !active) return null;
    return workflow.steps.find((s) => s.actions.includes(active.key)) ?? null;
  }, [workflow, active]);

  // The nav switched plugins under us; fall back to the new plugin's first action.
  useEffect(() => setActiveKey(null), [pkg]);

  function setContext(name: string, value: unknown) {
    const next = new URLSearchParams(search);
    if (value === "" || value === null || value === undefined) next.delete(name);
    else next.set(name, String(value));
    setSearch(next, { replace: true });
  }

  if (isLoading) return <LoadingSpinner />;
  if (error) {
    return (
      <ErrorMessage
        message={error instanceof Error ? error.message : "Could not load this plugin"}
      />
    );
  }
  if (!ui) return null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{ui.name || ui.package}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {ui.description || ui.package}
          {ui.version && <span className="ml-2 text-gray-400">v{ui.version}</span>}
        </p>
      </div>

      {contextParams.length > 0 && (
        <ContextBar
          pkg={ui.package}
          params={contextParams}
          values={context}
          onChange={setContext}
        />
      )}

      {workflow ? (
        <StepStrip
          ui={ui}
          workflow={workflow}
          state={state?.state}
          activeStep={activeStep?.key ?? null}
          activeAction={active?.key ?? null}
          onPick={setActiveKey}
        />
      ) : (
        actions.length > 1 && (
          <div className="flex flex-wrap gap-2 border-b border-gray-200 pb-3">
            {actions.map((a) => (
              <button
                key={a.key}
                onClick={() => setActiveKey(a.key)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  active?.key === a.key
                    ? "bg-zs-500 text-white"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                {a.label}
              </button>
            ))}
          </div>
        )
      )}

      {active ? (
        <ActionCard
          // Remounted per action and per context: a form filled in for one
          // migration has nothing to say about the next one.
          key={`${ui.package}:${active.key}:${JSON.stringify(context)}`}
          pkg={ui.package}
          action={active}
          context={context}
          contextParams={contextParams}
          onFinished={() => { if (workflow?.stateful && contextReady) refetchState(); }}
          onAction={(key) => {
            if (actions.some((a) => a.key === key)) setActiveKey(key);
          }}
        />
      ) : (
        <p className="text-sm italic text-gray-400">This plugin offers no actions.</p>
      )}
    </div>
  );
}

function StepStrip({ ui, workflow, state, activeStep, activeAction, onPick }: {
  ui: PluginUi;
  workflow: NonNullable<PluginUi["workflow"]>;
  state?: Record<string, { status: PluginStepStatus; detail: string | null }>;
  activeStep: string | null;
  activeAction: string | null;
  onPick: (actionKey: string) => void;
}) {
  const byKey = useMemo(
    () => Object.fromEntries(ui.actions.map((a) => [a.key, a])),
    [ui.actions],
  );
  const step = workflow.steps.find((s) => s.key === activeStep) ?? workflow.steps[0];
  const siblings = (step?.actions ?? []).map((k) => byKey[k]).filter(Boolean);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-stretch gap-2">
        {workflow.steps.map((s) => {
          const st = state?.[s.key];
          const on = s.key === activeStep;
          return (
            <button
              key={s.key}
              onClick={() => onPick(s.actions[0])}
              className={`flex-1 rounded-md border px-3 py-2 text-left transition-colors ${
                on
                  ? "border-zs-500 bg-zs-500/5"
                  : "border-gray-200 bg-white hover:border-gray-300"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${STEP_DOT[st?.status ?? "pending"]}`}
                />
                <span
                  className={`truncate text-sm font-medium ${
                    on ? "text-zs-600" : "text-gray-700"
                  }`}
                >
                  {s.label}
                </span>
              </div>
              <p className="mt-0.5 truncate text-xs text-gray-500">
                {st?.detail ?? s.description ?? " "}
              </p>
            </button>
          );
        })}
      </div>

      {siblings.length > 1 && (
        <div className="flex flex-wrap gap-2 border-b border-gray-200 pb-3">
          {siblings.map((a) => (
            <button
              key={a.key}
              onClick={() => onPick(a.key)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                activeAction === a.key
                  ? "bg-zs-500 text-white"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
