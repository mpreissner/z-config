import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { exchangeSsoCode } from "../api/sso";
import zLogo from "../assets/z-logo.jpg";

/**
 * Landing page for the IdP redirect.
 *
 * The backend puts a short-lived one-time code in the URL rather than the JWTs
 * themselves, so nothing sensitive ends up in browser history or a Referer
 * header. This page trades it in and then replaces the history entry.
 */
export default function SsoCompletePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { login: setToken } = useAuth();
  const [error, setError] = useState<string | null>(null);
  // React 18 StrictMode mounts effects twice in dev; the code is single-use, so
  // the second call would always fail.
  const exchanged = useRef(false);

  useEffect(() => {
    if (exchanged.current) return;
    exchanged.current = true;

    const code = params.get("code");
    if (!code) {
      setError("No login code was returned by the identity provider.");
      return;
    }

    exchangeSsoCode(code)
      .then((res) => {
        setToken(res.access_token);
        navigate(res.force_password_change ? "/change-password" : "/", { replace: true });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Single sign-on failed.");
      });
  }, [params, navigate, setToken]);

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
        <div className="bg-white rounded-b-xl shadow-lg px-8 py-8 text-center">
          {error ? (
            <>
              <p className="text-sm text-red-600 mb-4">{error}</p>
              <button
                type="button"
                onClick={() => navigate("/login", { replace: true })}
                className="w-full bg-zs-500 hover:bg-zs-600 text-white font-medium py-2 rounded-md text-sm transition-colors"
              >
                Back to sign in
              </button>
            </>
          ) : (
            <p className="text-sm text-gray-600">Completing sign-in…</p>
          )}
        </div>
      </div>
    </div>
  );
}
