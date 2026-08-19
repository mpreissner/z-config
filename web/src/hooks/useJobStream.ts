import { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";

export interface JobProgressEvent {
  type: "progress";
  phase: string;
  resource_type: string;
  name?: string;
  status?: string;
  done: number;
  total?: number;
  /** Jobs whose progress is a narrative rather than a resource count use this. */
  message?: string;
}

export type JobStreamStatus = "idle" | "running" | "done" | "error" | "cancelled";

/** Render one progress event as a status line.
 *
 * Callers pass the *latest* event rather than picking a phase, because a job
 * moves back through phases it has already been in — a push is followed by a
 * re-import — and a phase-priority chain pins the label to the highest-ranked
 * phase seen so far.  That made the final re-import look like a hang on the
 * last resource pushed.
 */
export function describeProgress(
  ev: JobProgressEvent | null,
  fallback: string,
): string {
  if (!ev) return fallback;
  if (ev.message) return ev.message;
  const count = `${ev.done}${ev.total ? `/${ev.total}` : ""}`;
  switch (ev.phase) {
    case "rollback":  return `Rolling back ${ev.resource_type}: ${ev.name ?? ""}`;
    case "push":      return `Pushing ${ev.resource_type}: ${ev.name ?? ""}`;
    case "remediate": return `Remediating ${ev.resource_type}: ${ev.name ?? ""}`;
    case "wipe":      return `Wiping ${ev.resource_type}: ${ev.name ?? ""}`;
    case "delete":    return `Deleting ${ev.resource_type}: ${ev.name ?? ""}`;
    case "verify":    return `Verifying ${ev.resource_type}… ${count}`;
    case "import":    return `Importing ${ev.resource_type}… ${count}`;
    default:          return fallback;
  }
}

export function useJobStream<T = unknown>(jobId: string | null) {
  const { token } = useAuth();
  const [progressEvents, setProgressEvents] = useState<JobProgressEvent[]>([]);
  const [latestByPhase, setLatestByPhase] = useState<Record<string, JobProgressEvent>>({});
  const [latestEvent, setLatestEvent] = useState<JobProgressEvent | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStreamStatus>("idle");
  const [result, setResult] = useState<T | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) {
      setProgressEvents([]);
      setLatestByPhase({});
      setLatestEvent(null);
      setJobStatus("idle");
      setResult(null);
      setStreamError(null);
      return;
    }
    setJobStatus("running");
    setProgressEvents([]);
    setLatestByPhase({});
    setLatestEvent(null);
    setResult(null);
    setStreamError(null);

    const url = `/api/v1/jobs/${jobId}/events${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    const es = new EventSource(url, { withCredentials: true });

    es.onmessage = (e: MessageEvent) => {
      const data = JSON.parse(e.data as string);
      if (data.type === "progress") {
        const ev = data as JobProgressEvent;
        setProgressEvents((prev) => [...prev, ev]);
        setLatestByPhase((prev) => ({ ...prev, [ev.phase]: ev }));
        setLatestEvent(ev);
      } else if (data.type === "done") {
        setResult(data.result as T);
        setJobStatus("done");
        es.close();
      } else if (data.type === "error") {
        setStreamError(data.message as string);
        setJobStatus("error");
        es.close();
      } else if (data.type === "cancelled") {
        setJobStatus("cancelled");
        es.close();
      }
    };

    es.onerror = () => {
      setStreamError("Connection to job stream lost");
      setJobStatus("error");
      es.close();
    };

    return () => es.close();
  }, [jobId, token]);

  return { progressEvents, latestByPhase, latestEvent, jobStatus, result, streamError };
}
