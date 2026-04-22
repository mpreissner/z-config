import { apiFetch } from "./client";

export interface SystemInfo {
  version: string;
  container_mode: boolean;
  db_path: string;
  plugin_dir: string | null;
}

export interface HealthStatus {
  status: string;
  version: string;
}

export interface SystemSettings {
  access_token_ttl: number;
  refresh_token_ttl: number;
  max_login_attempts: number;
  audit_log_retention_days: number;
  idp_enabled: boolean;
  idp_provider: string;
  idp_issuer_url: string;
  idp_client_id: string;
  ssl_mode: string;
  ssl_domain: string;
}

export function fetchSystemInfo(): Promise<SystemInfo> {
  return apiFetch<SystemInfo>("/api/v1/system/info");
}

export function fetchHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/health");
}

export function fetchSettings(): Promise<SystemSettings> {
  return apiFetch<SystemSettings>("/api/v1/system/settings");
}

export function patchSettings(patch: Partial<SystemSettings>): Promise<SystemSettings> {
  return apiFetch<SystemSettings>("/api/v1/system/settings", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
