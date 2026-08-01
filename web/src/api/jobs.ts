import { apiFetch } from "./client";

export const cancelJob = (jobId: string): Promise<void> =>
  apiFetch(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" });

export interface ActiveJob {
  /** null when nothing is running for the requested tenant/product. */
  job_id: string | null;
  status?: "running" | "cancel_requested";
  /** Unix seconds. */
  started_at?: number;
  /** Number of progress events emitted so far. */
  events?: number;
}

/** Look up the in-flight import job for a tenant/product, if any. Lets the
 *  import modal reattach to a job that is still running after it was closed
 *  (or started in another tab). */
export const fetchActiveImportJob = (
  tenantId: number,
  product: "ZIA" | "ZPA" | "ZCC",
): Promise<ActiveJob> =>
  apiFetch<ActiveJob>(
    `/api/v1/jobs/active/import?tenant_id=${tenantId}&product=${product}`,
  );
