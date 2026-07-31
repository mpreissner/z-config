import { apiFetch } from "./client";

export interface SSLStatus {
  active: boolean;
  mode: string;
  domain: string;
  subject: string | null;
  sans: string[] | null;
  not_before: string | null;
  not_after: string | null;
  days_until_expiry: number | null;
}

export interface SSLUploadResult {
  status: "restarting";
  domain: string;
}

export interface SSLRemoveResult {
  status: "restarting";
}

export function fetchSSLStatus(): Promise<SSLStatus> {
  return apiFetch<SSLStatus>("/api/v1/system/ssl/status");
}

export function uploadSSLPfx(
  file: File,
  password: string,
  domain: string
): Promise<SSLUploadResult> {
  const fd = new FormData();
  fd.append("method", "pfx");
  fd.append("domain", domain);
  fd.append("file", file);
  fd.append("pfx_password", password);
  return apiFetch<SSLUploadResult>("/api/v1/system/ssl/upload", { method: "POST", body: fd });
}

export function uploadSSLPemFile(certFile: File, domain: string): Promise<SSLUploadResult> {
  const fd = new FormData();
  fd.append("method", "pem_file");
  fd.append("domain", domain);
  fd.append("file", certFile);
  return apiFetch<SSLUploadResult>("/api/v1/system/ssl/upload", { method: "POST", body: fd });
}

export function uploadSSLPemPaste(pemText: string, domain: string): Promise<SSLUploadResult> {
  const fd = new FormData();
  fd.append("method", "pem_paste");
  fd.append("domain", domain);
  fd.append("pem_text", pemText);
  return apiFetch<SSLUploadResult>("/api/v1/system/ssl/upload", { method: "POST", body: fd });
}

export function removeSSL(): Promise<SSLRemoveResult> {
  return apiFetch<SSLRemoveResult>("/api/v1/system/ssl", { method: "DELETE" });
}

// ── Let's Encrypt ─────────────────────────────────────────────────────────────

export interface LetsEncryptConfig {
  domain: string;
  email: string;
  staging: boolean;
  auto_renew: boolean;
  token_set: boolean;
  last_issued: string | null;
  last_error: string | null;
}

/** What the form posts. A blank token keeps the one already on file. */
export interface LetsEncryptRequest {
  domain: string;
  email: string;
  staging: boolean;
  auto_renew: boolean;
  cf_api_token: string;
}

export function fetchLetsEncryptConfig(): Promise<LetsEncryptConfig> {
  return apiFetch<LetsEncryptConfig>("/api/v1/system/ssl/letsencrypt");
}

/** Pre-flights the Cloudflare token and zone without spending an issuance attempt. */
export function verifyLetsEncrypt(body: LetsEncryptRequest): Promise<{ ok: boolean; zone: string }> {
  return apiFetch("/api/v1/system/ssl/letsencrypt/verify", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function issueLetsEncrypt(
  body: LetsEncryptRequest
): Promise<{ job_id: string; already_running: boolean }> {
  return apiFetch("/api/v1/system/ssl/letsencrypt/issue", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function pollSSLHealthy(
  timeoutMs = 30_000,
  intervalMs = 1_000
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      // Poll wherever the browser actually reached us. Hardcoding :8443 works
      // only for direct access; behind ZPA Browser Access or a reverse proxy
      // that port is not published and every probe hangs until TCP timeout.
      const url = `${window.location.origin}/health`;
      const res = await fetch(url, { mode: "no-cors" });
      if (res.ok || res.type === "opaque") return true;
    } catch {
      /* not yet up */
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}
