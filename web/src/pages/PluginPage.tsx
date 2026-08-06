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
 *
 * A step is a screen. Everything a step lists is drawn on it, one card under
 * the next, and the strip moves between steps rather than between actions — so
 * a job of four steps is four screens however many actions it takes to do them.
 * Two things follow. Until the context exists only the actions needing none can
 * run, so those are all the page opens with; and an action that stops on a
 * decision asks for it in its own result, which is answered where it was asked
 * and replaced by what came next.
 *
 * The context bar sits at the top from the first paint and never moves. What it
 * holds is what the whole page is about, so it reads as a heading — and a
 * control that arrives late, or somewhere else than last time, is one the user
 * has to find twice.
 */

import { useState, useEffect, useMemo, useRef } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPluginUi,
  runPluginAction,
  answerPluginPrompt,
  fetchPluginActionOptions,
  fetchPluginContextOptions,
  fetchPluginState,
  downloadPluginArtifact,
  PluginAction,
  PluginParam,
  PluginActionResult,
  PluginPrompt,
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

/** Starting values for one form, honoring any declared defaults. */
function initialValues(params: PluginParam[]): Values {
  const out: Values = {};
  for (const p of params) {
    if (p.default !== undefined) out[p.name] = p.default;
    else if (p.type === "boolean") out[p.name] = false;
    // A grid whose rows are still to load is left undefined, so the ticks that
    // arrive with them can seed it without overwriting a choice already made.
    // A prompt's grid came with its rows, so its ticks are honored here.
    else if (p.type === "selection") {
      out[p.name] = p.dynamic
        ? undefined
        : (p.options ?? []).filter((o) => o.selected).map((o) => o.value);
    } else out[p.name] = "";
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

/**
 * The question an action stopped on, drawn under the result that explains it.
 *
 * Its fields were built while the action ran, so nothing here is fetched and
 * nothing is dynamic — the options came with the question. Answering starts
 * another job and the card swaps its own job for it, so the reply lands where
 * the question was instead of somewhere further down the page.
 */
function PromptForm({ pkg, prompt, jobId, context, disabled, onJob }: {
  pkg: string;
  prompt: PluginPrompt;
  /** The job whose result carried the question — how the server finds it again. */
  jobId: string;
  /** The whole page context; the server keeps whatever the action named. */
  context: Values;
  disabled: boolean;
  onJob: (jobId: string) => void;
}) {
  const [values, setValues] = useState<Values>(() => initialValues(prompt.params));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    setSending(true);
    try {
      const payload: Values = {};
      for (const p of prompt.params) {
        payload[p.name] = p.type === "selection" ? (values[p.name] ?? []) : values[p.name];
      }
      const r = await answerPluginPrompt(pkg, jobId, payload, context);
      onJob(r.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send that answer");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mt-4 rounded-md border border-gray-200 bg-white p-4">
      {prompt.title && <h3 className="text-sm font-medium text-gray-900">{prompt.title}</h3>}
      {prompt.help && <p className="mt-1 text-sm text-gray-500">{prompt.help}</p>}

      {prompt.params.length > 0 && (
        <div className="mt-3 space-y-4">
          {prompt.params.map((p) => (
            <ParamField
              key={p.name}
              param={p}
              value={values[p.name]}
              siblings={values}
              pkg={pkg}
              actionKey={null}
              onChange={(v) => setValues((prev) => ({ ...prev, [p.name]: v }))}
              onFile={() => {}}
            />
          ))}
        </div>
      )}

      <button
        onClick={submit}
        disabled={sending || disabled}
        className="mt-4 rounded-md bg-zs-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zs-600 disabled:opacity-60"
      >
        {sending ? "Sending…" : prompt.submit}
      </button>
      {error && <div className="mt-3"><ErrorMessage message={error} /></div>}
    </div>
  );
}

function ResultView({ result, jobId, pkg, context, running, onAction, canAction, onJob }: {
  result: PluginActionResult;
  jobId: string;
  pkg: string;
  context: Values;
  /** A follow-up is already on its way; don't let it be sent twice. */
  running: boolean;
  onAction?: (key: string) => void;
  canAction?: (key: string) => boolean;
  onJob: (jobId: string) => void;
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
          <ResultSections sections={sections} onAction={onAction} canAction={canAction} />
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

      {result.prompt && (
        <PromptForm
          pkg={pkg}
          prompt={result.prompt}
          jobId={jobId}
          context={context}
          disabled={running}
          onJob={onJob}
        />
      )}
    </div>
  );
}

function ActionCard({
  pkg, action, context, contextParams, onFinished, onContext, onAction, canAction,
}: {
  pkg: string;
  action: PluginAction;
  /** Page-level values this action named. Submitted alongside its own. */
  context: Values;
  contextParams: PluginParam[];
  /** Fires when a run completes, so the step strip can catch up. */
  onFinished?: () => void;
  /** The context the run handed back, for the page to adopt. */
  onContext: (values: Record<string, string>) => void;
  onAction?: (key: string) => void;
  canAction?: (key: string) => boolean;
}) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Values>(() => initialValues(action.params));
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

  // A form filled in for one migration has nothing to say about the next, so a
  // change to the context clears this card — unless the change came from this
  // card's own result, which is the thing the user is reading.
  const contextKey = JSON.stringify(context);
  const lastContext = useRef(contextKey);
  const adopting = useRef(false);
  useEffect(() => {
    if (contextKey === lastContext.current) return;
    lastContext.current = contextKey;
    if (adopting.current) {
      adopting.current = false;
      return;
    }
    setValues(initialValues(action.params));
    setFiles({});
    setJobId(null);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextKey]);

  const handled = useRef<string | null>(null);
  useEffect(() => {
    if (jobStatus !== "done" || !jobId || !result || handled.current === jobId) return;
    handled.current = jobId;
    // Whatever it did, it may have changed what every list on this page would
    // say: an import belongs in the picker without waiting for a page reload.
    queryClient.invalidateQueries({ queryKey: ["plugin-options", pkg] });
    const adopted = result.context ?? {};
    if (Object.keys(adopted).length > 0) {
      adopting.current = true;
      onContext(adopted);
    }
    onFinished?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobStatus, jobId, result]);

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
        <ResultView
          result={result}
          jobId={jobId}
          pkg={pkg}
          context={context}
          running={running}
          onAction={onAction}
          canAction={canAction}
          // Answering replaces this result with the next one, in place: a
          // pipeline that stops three times is still one card on one screen.
          onJob={setJobId}
        />
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

  // Where the user is: a step for a workflow, an action for a plugin without
  // one. Null until they choose, so the page can follow the work instead.
  const [stepKey, setStepKey] = useState<string | null>(null);
  const [actionKey, setActionKey] = useState<string | null>(null);

  const actions = useMemo(() => ui?.actions ?? [], [ui]);
  const contextParams = useMemo(() => ui?.context ?? [], [ui]);
  const workflow = ui?.workflow ?? null;
  const steps = useMemo(() => workflow?.steps ?? [], [workflow]);
  const byKey = useMemo(() => new Map(actions.map((a) => [a.key, a])), [actions]);

  // Context lives in the query string, so a reload or a shared link comes back
  // to the same migration rather than an empty bar.
  const context = useMemo(() => {
    const out: Values = {};
    for (const p of contextParams) out[p.name] = search.get(p.name) ?? "";
    return out;
  }, [contextParams, search]);

  const needsContext = contextParams.some((p) => p.required !== false);
  // Vacuously ready for a plugin that asks for nothing.
  const contextReady = contextParams.every((p) => p.required === false || context[p.name]);

  const { data: state, refetch: refetchState } = useQuery({
    queryKey: ["plugin-state", pkg, context],
    queryFn: () => fetchPluginState(pkg, context),
    enabled: !!workflow?.stateful && contextReady,
    retry: false,
  });
  const stepState = state?.state;
  const statusOf = (key: string): PluginStepStatus => stepState?.[key]?.status ?? "pending";

  // The step the user picked while it still exists, otherwise the one the
  // plugin calls current — so a reload lands on the work, not back at step one.
  const currentStep = useMemo(() => {
    if (!steps.length) return null;
    const picked = steps.find((s) => s.key === stepKey);
    if (picked) return picked;
    return (
      steps.find((s) => (stepState?.[s.key]?.status ?? "pending") === "current") ??
      steps.find((s) => (stepState?.[s.key]?.status ?? "pending") !== "complete") ??
      steps[0]
    );
  }, [steps, stepKey, stepState]);

  // Nothing can be folded in before the context exists, so the first screen
  // offers only what runs without any — and nothing above it to explain.
  const firstScreen = needsContext && !contextReady;
  const starters = useMemo(
    () => actions.filter((a) => (a.context ?? []).length === 0),
    [actions],
  );
  const flatActive = actions.find((a) => a.key === actionKey) ?? actions[0] ?? null;

  // A step is a screen: every action it lists is drawn on it, one card under
  // the next. Without a workflow there are no steps, so it is one at a time.
  const shown = useMemo<PluginAction[]>(() => {
    if (firstScreen) return starters;
    if (!workflow) return flatActive ? [flatActive] : [];
    if (currentStep && (stepState?.[currentStep.key]?.status ?? "pending") === "blocked") {
      return [];
    }
    return (currentStep?.actions ?? [])
      .map((k) => byKey.get(k))
      .filter((a): a is PluginAction => !!a);
  }, [firstScreen, starters, workflow, currentStep, byKey, flatActive, stepState]);

  // Finishing a step moves the user on. It stays a move — the strip is still
  // clickable, and a step they picked themselves is never taken away.
  const advance = useRef(false);
  useEffect(() => {
    if (!advance.current || !stepState || !currentStep) return;
    advance.current = false;
    if ((stepState[currentStep.key]?.status ?? "pending") !== "complete") return;
    const next = steps.find((s) => (stepState[s.key]?.status ?? "pending") !== "complete");
    if (next && next.key !== currentStep.key) setStepKey(next.key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepState]);

  // The nav switched plugins under us; start the new one where it starts.
  useEffect(() => {
    setStepKey(null);
    setActionKey(null);
  }, [pkg]);

  function setContext(name: string, value: unknown) {
    const next = new URLSearchParams(search);
    if (value === "" || value === null || value === undefined) next.delete(name);
    else next.set(name, String(value));
    setSearch(next, { replace: true });
  }

  /** Context an action made: adopted, so the user never goes looking for it. */
  function adoptContext(values: Record<string, string>) {
    const next = new URLSearchParams(search);
    for (const [name, value] of Object.entries(values)) {
      if (value === "") next.delete(name);
      else next.set(name, value);
    }
    setSearch(next, { replace: true });
  }

  const canReach = (key: string) =>
    workflow ? steps.some((s) => s.actions.includes(key)) : byKey.has(key);

  function goToAction(key: string) {
    advance.current = false;
    if (!workflow) {
      if (byKey.has(key)) setActionKey(key);
      return;
    }
    const step = steps.find((s) => s.actions.includes(key));
    if (step) setStepKey(step.key);
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

  const contextBar = (
    <ContextBar
      pkg={ui.package}
      params={contextParams}
      values={context}
      onChange={setContext}
    />
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{ui.name || ui.package}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {ui.description || ui.package}
          {ui.version && <span className="ml-2 text-gray-400">v{ui.version}</span>}
        </p>
      </div>

      {contextParams.length > 0 && contextBar}

      {!firstScreen &&
        (workflow ? (
          <StepStrip
            steps={steps}
            state={stepState}
            current={currentStep?.key ?? null}
            onPick={(key) => {
              advance.current = false;
              setStepKey(key);
            }}
          />
        ) : (
          actions.length > 1 && (
            <TabRail
              actions={actions}
              current={flatActive?.key ?? null}
              onPick={setActionKey}
            />
          )
        ))}

      {shown.map((a) => (
        <ActionCard
          key={`${ui.package}:${a.key}`}
          pkg={ui.package}
          action={a}
          context={context}
          contextParams={contextParams}
          onFinished={() => {
            if (workflow?.stateful && contextReady) {
              advance.current = true;
              refetchState();
            }
          }}
          onContext={adoptContext}
          onAction={goToAction}
          canAction={canReach}
        />
      ))}

      {shown.length === 0 && !firstScreen && currentStep &&
        statusOf(currentStep.key) === "blocked" && (
          <p className="rounded-lg border border-dashed border-gray-300 px-4 py-6 text-center text-sm text-gray-500">
            {stepState?.[currentStep.key]?.detail ?? "Not ready for this step yet."}
          </p>
        )}

      {shown.length === 0 && !firstScreen && !currentStep && (
        <p className="text-sm italic text-gray-400">This plugin offers no actions.</p>
      )}
    </div>
  );
}

/**
 * How far along the job is, and the way between its steps.
 *
 * These are not controls that do something — they are where you are and where
 * else you could be. A step nobody can start yet says so and stays put.
 */
function StepStrip({ steps, state, current, onPick }: {
  steps: NonNullable<PluginUi["workflow"]>["steps"];
  state?: Record<string, { status: PluginStepStatus; detail: string | null }>;
  current: string | null;
  onPick: (stepKey: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-stretch gap-2">
      {steps.map((s) => {
        const st = state?.[s.key];
        const on = s.key === current;
        const blocked = st?.status === "blocked";
        return (
          <button
            key={s.key}
            onClick={() => onPick(s.key)}
            disabled={blocked}
            className={`flex-1 rounded-md border px-3 py-2 text-left transition-colors ${
              on
                ? "border-zs-500 bg-zs-500/5"
                : blocked
                  ? "cursor-default border-gray-200 bg-gray-50"
                  : "border-gray-200 bg-white hover:border-gray-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${STEP_DOT[st?.status ?? "pending"]}`}
              />
              <span
                className={`truncate text-sm font-medium ${
                  on ? "text-zs-600" : blocked ? "text-gray-400" : "text-gray-700"
                }`}
              >
                {s.label}
              </span>
            </div>
            <p className="mt-0.5 truncate text-xs text-gray-500">
              {st?.detail ?? s.description ?? " "}
            </p>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The way between the actions of a plugin that has no workflow.
 *
 * Text on a rail, like every other set of tabs in this app: filled and rounded
 * is a thing that happens, and choosing where to look is not one.
 */
function TabRail({ actions, current, onPick }: {
  actions: PluginAction[];
  current: string | null;
  onPick: (key: string) => void;
}) {
  return (
    <div className="border-b border-gray-200">
      <nav className="-mb-px flex gap-6">
        {actions.map((a) => (
          <button
            key={a.key}
            onClick={() => onPick(a.key)}
            className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
              current === a.key
                ? "border-zs-500 text-zs-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {a.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
