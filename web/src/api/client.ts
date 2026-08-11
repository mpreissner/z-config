/**
 * Base fetch helper.
 * Sets base URL to "/" (same-origin) so the app works when served by FastAPI.
 * Throws on non-2xx responses.
 */

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

let _getToken: (() => string | null) | null = null;
let _onUnauthorized: (() => void) | null = null;

export function setTokenGetter(fn: () => string | null) {
  _getToken = fn;
}

export function setOnUnauthorized(fn: () => void) {
  _onUnauthorized = fn;
}

export function getAuthHeaders(): Record<string, string> {
  const token = _getToken?.();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Endpoints where a 401 does not mean "your session died".
 *
 * These are the ones reached before a session exists, or that establish one.
 * Everything else under /auth/ — the admin-only SSO helpers especially — is an
 * ordinary authenticated call, and blanket-matching "/auth/" made an expired
 * token there surface as a bare "HTTP 401" beside the button the admin pressed,
 * with the app still pretending to be logged in.
 */
const NO_LOGOUT_ON_401 = [
  "/api/v1/auth/login",
  "/api/v1/auth/logout",
  "/api/v1/auth/refresh",
  "/api/v1/auth/sso/status",
  "/api/v1/auth/sso/exchange",
  "/api/v1/auth/webauthn/authenticate/",
];

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = _getToken?.();
  const isFormData = init?.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(path, { ...init, headers, credentials: "include" });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.detail ?? message;
    } catch { /* ignore */ }
    // Only trigger logout if we actually sent a token and the server rejected it.
    // Avoids false positives from unauthenticated requests fired before the token
    // getter updates (e.g., queries that fire immediately after login).
    if (res.status === 401 && token && !NO_LOGOUT_ON_401.some((p) => path.startsWith(p))) {
      _onUnauthorized?.();
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
