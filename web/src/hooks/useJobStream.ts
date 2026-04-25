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
}

export type JobStreamStatus = "idle" | "running" | "done" | "error" | "cancelled";

export function useJobStream<T = unknown>(jobId: string | null) {
  const { token } = useAuth();
  const [progressEvents, setProgressEvents] = useState<JobProgressEvent[]>([]);
  const [latestByPhase, setLatestByPhase] = useState<Record<string, JobProgressEvent>>({});
  const [jobStatus, setJobStatus] = useState<JobStreamStatus>("idle");
  const [result, setResult] = useState<T | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) {
      setProgressEvents([]);
      setLatestByPhase({});
      setJobStatus("idle");
      setResult(null);
      setStreamError(null);
      return;
    }
    setJobStatus("running");
    setProgressEvents([]);
    setLatestByPhase({});
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

  return { progressEvents, latestByPhase, jobStatus, result, streamError };
}
