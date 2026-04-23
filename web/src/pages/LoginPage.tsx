import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { startAuthentication } from "@simplewebauthn/browser";
import { useAuth } from "../context/AuthContext";
import { login } from "../api/auth";
import { beginAuthentication, completeAuthentication } from "../api/webauthn";
import zLogo from "../assets/z-logo.jpg";

export default function LoginPage() {
  const { login: setToken } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [keyLoading, setKeyLoading] = useState(false);

  function postLogin(accessToken: string, forcePasswordChange: boolean, mfaEnrollRequired?: boolean) {
    setToken(accessToken);
    if (!mfaEnrollRequired) {
      navigate(forcePasswordChange ? "/change-password" : "/");
    }
    // mfaEnrollRequired: token is stored, MfaEnrollModal renders automatically via App
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await login(username, password);
      postLogin(res.access_token, res.force_password_change, res.mfa_enrollment_required);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      setError(
        msg === "mfa_required"
          ? "This account requires a security key. Use 'Sign in with Security Key' below."
          : msg,
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleSecurityKey() {
    if (!username.trim()) {
      setError("Enter your username first, then click Sign in with Security Key.");
      return;
    }
    setError(null);
    setKeyLoading(true);
    try {
      const options = await beginAuthentication(username.trim());
      const credential = await startAuthentication(options as Parameters<typeof startAuthentication>[0]);
      const res = await completeAuthentication(username.trim(), credential);
      postLogin(res.access_token, res.force_password_change);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "NotAllowedError") {
        setError("Authentication cancelled.");
      } else {
        setError(err instanceof Error ? err.message : "Security key authentication failed.");
      }
    } finally {
      setKeyLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="bg-zs-500 rounded-t-xl px-8 py-6 flex items-center gap-3">
          <img src={zLogo} alt="Z" className="h-9 w-9 rounded-lg object-cover" />
          <div>
            <div className="text-white font-bold text-lg leading-none">zs-config</div>
            <div className="text-blue-200 text-xs">Zscaler Management</div>
          </div>
        </div>
        <div className="bg-white rounded-b-xl shadow-lg px-8 py-6">
          <h2 className="text-gray-700 font-semibold mb-4">Sign in</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 focus:border-transparent"
              />
            </div>
            {error && <p className="text-red-600 text-xs">{error}</p>}
            <button
              type="submit"
              disabled={loading || keyLoading}
              className="w-full bg-zs-500 hover:bg-zs-600 disabled:opacity-60 text-white font-medium py-2 rounded-md text-sm transition-colors"
            >
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>

          <div className="mt-3 flex items-center gap-2">
            <div className="flex-1 h-px bg-gray-200" />
            <span className="text-xs text-gray-400">or</span>
            <div className="flex-1 h-px bg-gray-200" />
          </div>

          <button
            type="button"
            onClick={handleSecurityKey}
            disabled={loading || keyLoading}
            className="mt-3 w-full border border-gray-300 hover:border-gray-400 disabled:opacity-60 text-gray-700 font-medium py-2 rounded-md text-sm transition-colors flex items-center justify-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
            {keyLoading ? "Touch your key…" : "Sign in with Security Key"}
          </button>
        </div>
      </div>
    </div>
  );
}
