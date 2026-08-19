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
  owner_user_id: number | null;
  /** Denormalized, so a template keeps its byline after the account is deleted. */
  owner_username: string | null;
  visibility: "private" | "shared" | "org";
  /** "scoped" templates hold only what their author picked — never wipe with one. */
  scope: "full" | "scoped";
  is_owner: boolean;
  /** Owner or admin: may rename, re-share, and delete. */
  can_manage: boolean;
  share_count: number;
}

export interface TemplateSelectionMeta {
  selected: Record<string, string[]>;
  auto_included: {
    resource_type: string;
    id: string;
    name: string;
    predefined: boolean;
    required_by: string;
  }[];
  warnings: string[];
}

export interface ZIATemplateDetail extends ZIATemplate {
  included_types: { resource_type: string; count: number }[];
  selection_meta: TemplateSelectionMeta | null;
}

export interface TemplateShare {
  id: number;
  template_id: number;
  user_id: number | null;
  username: string | null;
  group_id: number | null;
  group_name: string | null;
  shared_at: string | null;
  shared_by: string | null;
}

export interface TemplateEntry {
  id: string;
  name: string;
  /** Already exists in every tenant — matched on push, never created. */
  predefined: boolean;
  summary: string;
  order: number | null;
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

export interface TemplatePreviewDetailResult extends TemplatePreviewResult {
  entries: Record<string, TemplateEntry[]>;
}

export interface TemplateCreateRequest {
  source_tenant_id: number;
  snapshot_id: number;
  name: string;
  description?: string;
  /** Omit for a full template over everything portable in the snapshot. */
  selection?: Record<string, string[]>;
  visibility?: "private" | "shared" | "org";
}

export interface TemplateUpdateRequest {
  name?: string;
  description?: string;
  visibility?: "private" | "shared" | "org";
  /** Admin-only: adopt a template that predates ownership. */
  owner_user_id?: number;
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

export const previewTemplateDetail = (
  req: TemplatePreviewRequest,
): Promise<TemplatePreviewDetailResult> =>
  apiFetch<TemplatePreviewDetailResult>("/api/v1/templates/preview/detail", {
    method: "POST",
    body: JSON.stringify(req),
  });

export const updateTemplate = (
  id: number,
  req: TemplateUpdateRequest,
): Promise<ZIATemplate> =>
  apiFetch<ZIATemplate>(`/api/v1/templates/${id}`, {
    method: "PATCH",
    body: JSON.stringify(req),
  });

export const deleteTemplate = (id: number): Promise<void> =>
  apiFetch<void>(`/api/v1/templates/${id}`, { method: "DELETE" });

export interface ShareTargets {
  users: { id: number; username: string }[];
  groups: { id: number; display_name: string }[];
}

/** Open to any authenticated account — sharing is not an admin action. */
export const fetchShareTargets = (): Promise<ShareTargets> =>
  apiFetch<ShareTargets>("/api/v1/templates/share-targets");

export const fetchTemplateShares = (id: number): Promise<TemplateShare[]> =>
  apiFetch<TemplateShare[]>(`/api/v1/templates/${id}/shares`);

/** Idempotent — re-granting an existing share is a no-op, not a conflict. */
export const addTemplateShares = (
  id: number,
  req: { user_ids?: number[]; group_ids?: number[] },
): Promise<TemplateShare[]> =>
  apiFetch<TemplateShare[]>(`/api/v1/templates/${id}/shares`, {
    method: "POST",
    body: JSON.stringify({ user_ids: req.user_ids ?? [], group_ids: req.group_ids ?? [] }),
  });

export const removeTemplateShare = (id: number, shareId: number): Promise<void> =>
  apiFetch<void>(`/api/v1/templates/${id}/shares/${shareId}`, { method: "DELETE" });

export const applyTemplate = (
  targetTenantId: number,
  templateId: number,
  wipeMode = false,
): Promise<{ job_id: string }> =>
  apiFetch<{ job_id: string }>(`/api/v1/tenants/${targetTenantId}/templates/apply`, {
    method: "POST",
    body: JSON.stringify({ template_id: templateId, wipe_mode: wipeMode }),
  });
