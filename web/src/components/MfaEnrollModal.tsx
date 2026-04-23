import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { startRegistration } from "@simplewebauthn/browser";
import { useAuth } from "../context/AuthContext";
import { beginRegistration, completeRegistration } from "../api/webauthn";
import zLogo from "../assets/z-logo.jpg";

export default function MfaEnrollModal() {
  const { logout, user } = useAuth();
  const navigate = useNavigate();
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [done, setDone] = useState(false);

  async function handleEnroll() {
    setEnrolling(true);
    setError(null);
    try {
      const options = await beginRegistration(label.trim());
      const credential = await startRegistration(options as Parameters<typeof startRegistration>[0]);
      await completeRegistration(label.trim(), credential);
      setDone(true);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "NotAllowedError") {
        setError("Registration cancelled.");
      } else {
        setError(err instanceof Error ? err.message : "Registration failed.");
      }
    } finally {
      setEnrolling(false);
    }
  }

  async function handleSignOut() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-sm mx-4">
        <div className="bg-zs-500 rounded-t-xl px-8 py-6 flex items-center gap-3">
          <img src={zLogo} alt="Z" className="h-9 w-9 rounded-lg object-cover" />
          <div>
            <div className="text-white font-bold text-lg leading-none">zs-config</div>
            <div className="text-blue-200 text-xs">Security Key Required</div>
          </div>
        </div>

        <div className="bg-white rounded-b-xl shadow-xl px-8 py-6 space-y-4">
          {done ? (
            <>
              <div className="flex items-center gap-2 text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2 text-sm">
                <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Security key registered successfully.
              </div>
              <p className="text-sm text-gray-600">
                Sign in again with your security key to access the app.
              </p>
              <button
                onClick={handleSignOut}
                className="w-full bg-zs-500 hover:bg-zs-600 text-white font-medium py-2 rounded-md text-sm transition-colors"
              >
                Continue to sign in
              </button>
            </>
          ) : (
            <>
              <div>
                <h2 className="text-gray-800 font-semibold">Register a Security Key</h2>
                <p className="text-xs text-gray-500 mt-1">
                  Hi <span className="font-medium">{user?.username}</span>. Your account requires
                  multi-factor authentication. Register a security key or passkey before continuing.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Key label <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g. YubiKey, Touch ID"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 focus:border-transparent"
                />
              </div>

              {error && <p className="text-red-600 text-xs">{error}</p>}

              <button
                onClick={handleEnroll}
                disabled={enrolling}
                className="w-full bg-zs-500 hover:bg-zs-600 disabled:opacity-60 text-white font-medium py-2 rounded-md text-sm transition-colors flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
                {enrolling ? "Touch your key…" : "Register Security Key"}
              </button>

              <button
                onClick={handleSignOut}
                disabled={enrolling}
                className="w-full text-gray-500 hover:text-gray-700 disabled:opacity-40 text-sm py-1 transition-colors"
              >
                Cancel — sign out
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
