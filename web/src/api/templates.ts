import { apiFetch } from "./client";

export interface ZIATemplate {
  id: number;
  name: string;
  description: string | null;
  source_tenant_id: number | null;
  source_tenant_name: string | null;
  source_snapshot_id: number | null;
  created_at: string | null;
  updated_at: string | null;
  resource_count: number;
  stripped_types: string[];
}

export interface ZIATemplateDetail extends ZIATemplate {
  included_types: { resource_type: string; count: number }[];
}

export interface TemplatePreviewResult {
  included: { resource_type: string; count: number }[];
  stripped: { resource_type: string; count: number; reason: string }[];
  stripped_rule_entries: { resource_type: string; count: number; reason: string }[];
}

export interface TemplatePreviewRequest {
  source_tenant_id: number;
  snapshot_id: number;
}

export interface TemplateCreateRequest {
  source_tenant_id: number;
  snapshot_id: number;
  name: string;
  description?: string;
}

export interface TemplateApplyRequest {
  template_id: number;
  wipe_mode?: boolean;
}

export interface TemplateApplyResult {
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
}

export const fetchTemplates = (): Promise<ZIATemplate[]> =>
  apiFetch<ZIATemplate[]>("/api/v1/templates");

export const fetchTemplate = (id: number): Promise<ZIATemplateDetail> =>
  apiFetch<ZIATemplateDetail>(`/api/v1/templates/${id}`);

export const previewTemplate = (req: TemplatePreviewRequest): Promise<TemplatePreviewResult> =>
  apiFetch<TemplatePreviewResult>("/api/v1/templates/preview", {
    method: "POST",
    body: JSON.stringify(req),
  });

export const createTemplate = (req: TemplateCreateRequest): Promise<ZIATemplate> =>
  apiFetch<ZIATemplate>("/api/v1/templates", {
    method: "POST",
    body: JSON.stringify(req),
  });

export const deleteTemplate = (id: number): Promise<void> =>
  apiFetch<void>(`/api/v1/templates/${id}`, { method: "DELETE" });

export const applyTemplate = (
  targetTenantId: number,
  templateId: number,
  wipeMode = false,
): Promise<{ job_id: string }> =>
  apiFetch<{ job_id: string }>(`/api/v1/tenants/${targetTenantId}/templates/apply`, {
    method: "POST",
    body: JSON.stringify({ template_id: templateId, wipe_mode: wipeMode }),
  });
