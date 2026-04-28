import { apiFetch } from "./client";

export interface ScheduledTask {
  id: number;
  name: string;
  source_tenant_id: number;
  source_tenant_name: string;
  target_tenant_id: number;
  target_tenant_name: string;
  resource_groups: string[];
  cron_expression: string;
  sync_deletes: boolean;
  enabled: boolean;
  owner_email: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  next_run_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  sync_mode: "resource_type" | "label";
  label_name: string | null;
  label_resource_types: string[] | null;
}

export interface TaskRunHistory {
  id: number;
  task_id: number;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  status: string;
  resources_synced: number;
  error_count: number;
}

export interface TaskRunHistoryDetail extends TaskRunHistory {
  errors: Array<{
    resource_type: string;
    resource_name: string;
    operation: string;
    error: string;
  }>;
}

export interface CreateScheduledTaskRequest {
  name: string;
  source_tenant_id: number;
  target_tenant_id: number;
  resource_groups: string[];
  schedule: string;
  sync_deletes?: boolean;
  enabled?: boolean;
  owner_email?: string | null;
  sync_mode?: "resource_type" | "label";
  label_name?: string | null;
  label_resource_types?: string[] | null;
}

export const fetchScheduledTasks = (): Promise<ScheduledTask[]> =>
  apiFetch<ScheduledTask[]>("/api/v1/scheduled-tasks");

export const createScheduledTask = (data: CreateScheduledTaskRequest): Promise<ScheduledTask> =>
  apiFetch<ScheduledTask>("/api/v1/scheduled-tasks", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateScheduledTask = (
  id: number,
  data: Partial<CreateScheduledTaskRequest>
): Promise<ScheduledTask> =>
  apiFetch<ScheduledTask>(`/api/v1/scheduled-tasks/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const deleteScheduledTask = (id: number): Promise<void> =>
  apiFetch<void>(`/api/v1/scheduled-tasks/${id}`, { method: "DELETE" });

export const enableScheduledTask = (id: number): Promise<ScheduledTask> =>
  apiFetch<ScheduledTask>(`/api/v1/scheduled-tasks/${id}/enable`, { method: "POST" });

export const disableScheduledTask = (id: number): Promise<ScheduledTask> =>
  apiFetch<ScheduledTask>(`/api/v1/scheduled-tasks/${id}/disable`, { method: "POST" });

export const triggerScheduledTask = (id: number): Promise<{ job_id: string; message: string }> =>
  apiFetch<{ job_id: string; message: string }>(
    `/api/v1/scheduled-tasks/${id}/trigger`,
    { method: "POST" }
  );

export const fetchTaskRuns = (
  id: number,
  limit = 50,
  offset = 0
): Promise<TaskRunHistory[]> =>
  apiFetch<TaskRunHistory[]>(
    `/api/v1/scheduled-tasks/${id}/runs?limit=${limit}&offset=${offset}`
  );

export const fetchTaskRunDetail = (
  taskId: number,
  runId: number
): Promise<TaskRunHistoryDetail> =>
  apiFetch<TaskRunHistoryDetail>(`/api/v1/scheduled-tasks/${taskId}/runs/${runId}`);
