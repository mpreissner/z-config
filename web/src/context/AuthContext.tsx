import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from "react";
import { apiFetch, setTokenGetter, setOnUnauthorized } from "../api/client";
import { fetchSystemInfo } from "../api/system";
import { useIdleLogout } from "../hooks/useIdleLogout";

interface TokenPayload {
  sub: number;
  username: string;
  role: string;
  fpc: boolean;
  mfa_enroll?: boolean;
  exp: number;
}

interface AuthState {
  token: string | null;
  user: TokenPayload | null;
}

interface AuthContextValue extends AuthState {
  login: (token: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
  mfaEnrollRequired: boolean;
  logoutReason: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function parseToken(token: string): TokenPayload | null {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload)) as TokenPayload;
  } catch {
    return null;
  }
}

function fmt(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}:${String(sec).padStart(2, "0")}` : `${s}s`;
}

function IdleWarningModal({ secondsLeft, idleMinutes, onStay, onLogout }: {
  secondsLeft: number;
  idleMinutes: number;
  onStay: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-sm w-full mx-4">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Session Expiring</h2>
        <p className="text-sm text-gray-600 mb-5">
          You've been inactive for {idleMinutes - 2} minutes. You'll be logged out in{" "}
          <span className="font-mono font-semibold text-red-600">{fmt(secondsLeft)}</span>.
        </p>
        <div className="flex gap-3">
          <button
            onClick={onStay}
            className="flex-1 px-4 py-2 text-sm font-medium rounded-md bg-zs-500 hover:bg-zs-600 text-white transition-colors"
          >
            Stay logged in
          </button>
          <button
            onClick={onLogout}
            className="flex-1 px-4 py-2 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50 text-gray-700 transition-colors"
          >
            Log out now
          </button>
        </div>
      </div>
    </div>
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>({ token: null, user: null });
  const [ready, setReady] = useState(false);
  const [idleMinutes, setIdleMinutes] = useState(15);
  const [logoutReason, setLogoutReason] = useState<string | null>(null);

  // An expired token 401s every in-flight query at once and each one calls
  // back here. Without this latch that becomes one logout POST per query —
  // six round trips on the dashboard, which is slow enough to notice over a
  // proxied WAN path. Cleared on the next successful login.
  const loggingOut = useRef(false);

  const login = useCallback((token: string) => {
    const user = parseToken(token);
    loggingOut.current = false;
    setTokenGetter(() => token);
    setAuth({ token, user });
    setLogoutReason(null);
  }, []);

  const logout = useCallback(async () => {
    if (loggingOut.current) return;
    loggingOut.current = true;
    setTokenGetter(() => null);
    try { await apiFetch("/api/v1/auth/logout", { method: "POST" }); } catch { /* ignore */ }
    setAuth({ token: null, user: null });
  }, []);

  const logoutWithReason = useCallback(async (reason: string) => {
    setLogoutReason(reason);
    await logout();
  }, [logout]);

  useEffect(() => {
    setOnUnauthorized(() => logoutWithReason("unauthorized"));
  }, [logoutWithReason]);

  // Proactively refresh the JWT 60 s before it expires. If the refresh cookie
  // is also gone, the refresh fails and we log the user out.
  useEffect(() => {
    if (!auth.user) return;
    const ms = auth.user.exp * 1000 - Date.now();
    if (ms <= 0) { logout(); return; }
    const timer = setTimeout(async () => {
      try {
        const r = await apiFetch<{ access_token: string }>("/api/v1/auth/refresh", { method: "POST" });
        login(r.access_token);
      } catch {
        logoutWithReason("expired");
      }
    }, Math.max(0, ms - 60_000));
    return () => clearTimeout(timer);
  }, [auth.user, login, logout, logoutWithReason]);

  useEffect(() => {
    Promise.all([
      apiFetch<{ access_token: string }>("/api/v1/auth/refresh", { method: "POST" })
        .then((r) => login(r.access_token))
        .catch(() => {}),
      fetchSystemInfo()
        .then((info) => setIdleMinutes(info.idle_timeout_minutes ?? 15))
        .catch(() => {}),
    ]).finally(() => setReady(true));
  }, [login]);

  const { showWarning, secondsLeft, extend } = useIdleLogout(!!auth.token, logout, idleMinutes);

  if (!ready) return null;

  return (
    <AuthContext.Provider value={{
      ...auth,
      login,
      logout,
      isAuthenticated: !!auth.token,
      isAdmin: auth.user?.role === "admin",
      mfaEnrollRequired: !!auth.user?.mfa_enroll,
      logoutReason,
    }}>
      {children}
      {showWarning && (
        <IdleWarningModal secondsLeft={secondsLeft} idleMinutes={idleMinutes} onStay={extend} onLogout={logout} />
      )}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
