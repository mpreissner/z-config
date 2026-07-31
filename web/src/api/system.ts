import { apiFetch } from "./client";

export interface SystemInfo {
  version: string;
  container_mode: boolean;
  db_path: string;
  plugin_dir: string | null;
  idle_timeout_minutes: number;
}

export interface HealthStatus {
  status: string;
  version: string;
}

export interface SystemSettings {
  access_token_ttl: number;
  refresh_token_ttl: number;
  idle_timeout_minutes: number;
  max_login_attempts: number;
  audit_log_retention_days: number;
  idp_enabled: boolean;
  idp_provider: string;
  idp_auto_provision: boolean;
  idp_default_role: string;
  idp_group_claim: string;
  idp_issuer_url: string;
  idp_client_id: string;
  /** Read-only marker — the secret itself is never returned. */
  idp_client_secret_set: boolean;
  idp_scopes: string;
  saml_idp_metadata_xml: string;
  saml_idp_metadata_url: string;
  saml_sp_entity_id: string;
  saml_sp_cert: string;
  /** Read-only marker — the key itself is never returned. */
  saml_sp_key_set: boolean;
  sso_base_url: string;
  /**
   * Write-only. Absent from GET responses; send "" to leave the stored value
   * alone or "__CLEAR__" to wipe it.
   */
  idp_client_secret?: string;
  saml_sp_key?: string;
  ssl_mode: string;
  ssl_domain: string;
  encryption_algorithm: string;
  fips_mode: boolean;
  key_rotation_interval_days: number;
  key_last_rotated_at: string | null;
  update_notify_enabled: boolean;
  update_notify_email: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  smtp_from_address: string;
  smtp_tls: boolean;
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

export function sendTestUpdateEmail(): Promise<{ sent: boolean }> {
  return apiFetch<{ sent: boolean }>("/api/v1/system/update-notify/test", { method: "POST" });
}
