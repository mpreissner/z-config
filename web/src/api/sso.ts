import { apiFetch } from "./client";

/** Public — the login page reads this before the user has a token. */
export interface SsoStatus {
  enabled: boolean;
  provider: string;
}

export interface SsoTestResult {
  ok: boolean;
  provider: string;
  [key: string]: unknown;
}

/** Same shape as POST /auth/login, so the auth context handles both alike. */
export interface SsoExchangeResult {
  access_token: string;
  token_type: string;
  force_password_change: boolean;
}

export function fetchSsoStatus(): Promise<SsoStatus> {
  return apiFetch<SsoStatus>("/api/v1/auth/sso/status");
}

/** Full page navigation — the IdP redirect cannot happen inside fetch(). */
export function ssoLoginUrl(): string {
  return "/api/v1/auth/sso/login";
}

export function ssoMetadataUrl(): string {
  return "/api/v1/auth/sso/metadata";
}

export function testSso(): Promise<SsoTestResult> {
  return apiFetch<SsoTestResult>("/api/v1/auth/sso/test", { method: "POST" });
}

/** Trades the one-time code from the IdP redirect for real tokens. */
export function exchangeSsoCode(code: string): Promise<SsoExchangeResult> {
  return apiFetch<SsoExchangeResult>("/api/v1/auth/sso/exchange", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}
