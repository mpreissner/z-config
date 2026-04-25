import { apiFetch } from "./client";

export const cancelJob = (jobId: string): Promise<void> =>
  apiFetch(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" });
