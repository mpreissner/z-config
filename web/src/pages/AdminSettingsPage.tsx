import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, patchSettings, SystemSettings, fetchSystemInfo, sendTestUpdateEmail } from "../api/system";
import { importDatabase, ImportDbResult, clearData, ClearDataResult, rotateKey, RotateKeyResult } from "../api/admin";
import { fetchTenants, Tenant } from "../api/tenants";
import {
  fetchSSLStatus, SSLStatus,
  uploadSSLPfx, uploadSSLPemFile, uploadSSLPemPaste,
  removeSSL,
} from "../api/ssl";
import { testSso, ssoMetadataUrl } from "../api/sso";
import {
  fetchScimTokens, createScimToken, revokeScimToken,
  fetchScimGroups, mapScimGroup,
} from "../api/scim";
import { ApiError } from "../api/client";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

// ── Shared field components ───────────────────────────────────────────────────

function SectionCard({ title, badge, children, defaultOpen = false }: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-6 py-4 border-b border-gray-100 bg-gray-50 text-left hover:bg-gray-100 transition-colors"
      >
        <svg
          className={`h-4 w-4 text-gray-400 transition-transform duration-200 flex-shrink-0 ${isOpen ? "rotate-90" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <h2 className="font-semibold text-gray-800 text-sm">{title}</h2>
        {badge}
      </button>
      <div className={`overflow-hidden transition-all duration-300 ease-in-out ${isOpen ? "max-h-[2000px]" : "max-h-0"}`}>
        <div className="px-6 py-5 space-y-4">{children}</div>
      </div>
    </div>
  );
}

function FieldRow({ label, hint, children }: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-4">
      <div className="sm:w-56 flex-shrink-0">
        <p className="text-sm font-medium text-gray-700">{label}</p>
        {hint && <p className="text-xs text-gray-400 mt-0.5">{hint}</p>}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function NumberInput({ value, onChange, min, max, disabled }: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  disabled?: boolean;
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      disabled={disabled}
      onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
      className="w-36 border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:bg-gray-50 disabled:text-gray-400"
    />
  );
}

function TextInput({ value, onChange, placeholder, disabled }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:bg-gray-50 disabled:text-gray-400"
    />
  );
}

function TextArea({ value, onChange, placeholder, rows = 5 }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      value={value}
      rows={rows}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
    />
  );
}

/**
 * Write-only secret field. The API never returns the stored value, so the box
 * starts blank and an empty submission means "leave what is on file alone".
 */
function SecretInput({ value, onChange, isSet, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  isSet: boolean;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1">
      <input
        type="password"
        value={value}
        placeholder={placeholder ?? (isSet ? "•••••••• (unchanged)" : "")}
        autoComplete="new-password"
        onChange={(e) => onChange(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
      />
      {isSet && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-green-600">A value is stored.</span>
          <button
            type="button"
            onClick={() => onChange("__CLEAR__")}
            className="text-xs text-red-600 hover:underline"
          >
            Clear it
          </button>
          {value === "__CLEAR__" && (
            <span className="text-xs text-red-600 font-medium">— will be cleared on save</span>
          )}
        </div>
      )}
    </div>
  );
}

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <code className="flex-1 truncate rounded bg-gray-50 border border-gray-200 px-2 py-1.5 text-xs text-gray-700">
        {value}
      </code>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="text-xs px-2 py-1.5 rounded border border-gray-300 hover:bg-gray-50 text-gray-600"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function SelectInput({ value, onChange, options, disabled }: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:bg-gray-50 disabled:text-gray-400"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
      ))}
    </select>
  );
}

function Toggle({ checked, onChange, disabled }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-zs-500 focus:ring-offset-2 ${
        checked ? "bg-zs-500" : "bg-gray-200"
      } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
        checked ? "translate-x-6" : "translate-x-1"
      }`} />
    </button>
  );
}

// ── Algorithm labels ──────────────────────────────────────────────────────────

const ALGO_LABELS: Record<string, string> = {
  fernet: "Fernet (AES-128-CBC)",
  aes256gcm: "AES-256-GCM",
  chacha20poly1305: "ChaCha20-Poly1305 (non-FIPS)",
};

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminSettingsPage() {
  const qc = useQueryClient();
  const { data: settings, isLoading, error } = useQuery({
    queryKey: ["system-settings"],
    queryFn: fetchSettings,
  });
  const { data: sysInfo } = useQuery({
    queryKey: ["system-info"],
    queryFn: fetchSystemInfo,
  });

  const [draft, setDraft] = useState<SystemSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings && !draft) setDraft(settings);
  }, [settings, draft]);

  const mut = useMutation({
    mutationFn: patchSettings,
    onSuccess: (updated) => {
      qc.setQueryData(["system-settings"], updated);
      setDraft(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  function set<K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) {
    setDraft((d) => d ? { ...d, [key]: value } : d);
  }

  function handleSave() {
    if (!draft || !settings) return;
    const patch: Partial<SystemSettings> = {};
    for (const k of Object.keys(draft) as (keyof SystemSettings)[]) {
      if (draft[k] !== settings[k]) (patch as Record<string, unknown>)[k] = draft[k];
    }
    if (Object.keys(patch).length > 0) mut.mutate(patch);
  }

  const isDirty = draft && settings && JSON.stringify(draft) !== JSON.stringify(settings);

  if (isLoading) return <LoadingSpinner />;
  if (error || !draft) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load settings"} />;

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">System Settings</h1>
        <div className="flex items-center gap-3">
          {saved && (
            <span className="text-sm text-green-600 font-medium">Saved</span>
          )}
          <button
            onClick={handleSave}
            disabled={!isDirty || mut.isPending}
            className="px-4 py-2 text-sm font-medium rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50 transition-colors"
          >
            {mut.isPending ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      {mut.isError && (
        <ErrorMessage message={mut.error instanceof Error ? mut.error.message : "Save failed"} />
      )}

      {/* ── Session ───────────────────────────────────────────────────────── */}
      <SectionCard title="Session">
        <FieldRow
          label="Session timeout"
          hint="Maximum session duration from login, regardless of activity."
        >
          <div className="flex items-center gap-2">
            <NumberInput
              value={Math.round(draft.refresh_token_ttl / 60)}
              onChange={(v) => set("refresh_token_ttl", v * 60)}
              min={5}
              max={1440}
            />
            <span className="text-sm text-gray-500">minutes</span>
          </div>
        </FieldRow>
        <FieldRow
          label="Idle timeout"
          hint="Log out users after this many minutes of inactivity. A warning appears 2 minutes before."
        >
          <div className="flex items-center gap-2">
            <NumberInput
              value={draft.idle_timeout_minutes}
              onChange={(v) => set("idle_timeout_minutes", v)}
              min={3}
              max={120}
            />
            <span className="text-sm text-gray-500">minutes</span>
          </div>
        </FieldRow>
        <FieldRow
          label="Max login attempts"
          hint="Locks the account after this many consecutive failures. 0 = disabled."
        >
          <div className="flex items-center gap-2">
            <NumberInput
              value={draft.max_login_attempts}
              onChange={(v) => set("max_login_attempts", v)}
              min={0}
              max={100}
            />
            <span className="text-sm text-gray-500">attempts</span>
          </div>
        </FieldRow>
      </SectionCard>

      {/* ── Identity Provider ─────────────────────────────────────────────── */}
      <IdentityProviderSection draft={draft} set={set} />

      {/* ── SCIM Provisioning ─────────────────────────────────────────────── */}
      <ScimSection baseUrl={draft.sso_base_url} />

      {/* ── SSL / TLS ─────────────────────────────────────────────────────── */}
      {sysInfo?.container_mode && <SSLTlsSection />}

      {/* ── Audit & Retention ─────────────────────────────────────────────── */}
      <SectionCard title="Audit &amp; Retention">
        <FieldRow
          label="Audit log retention"
          hint="Entries older than this are pruned automatically. 0 = keep forever."
        >
          <div className="flex items-center gap-2">
            <NumberInput
              value={draft.audit_log_retention_days}
              onChange={(v) => set("audit_log_retention_days", v)}
              min={0}
              max={3650}
            />
            <span className="text-sm text-gray-500">days</span>
          </div>
        </FieldRow>
      </SectionCard>

      {/* ── Updates ───────────────────────────────────────────────────────── */}
      <UpdatesSection draft={draft} set={set} />

      {/* ── Database Maintenance ──────────────────────────────────────────── */}
      <DatabaseMaintenanceCard draft={draft} set={set} />
    </div>
  );
}

// ── SSL / TLS section ─────────────────────────────────────────────────────────

const SSL_ERROR_MESSAGES: Record<string, string> = {
  no_private_key:     "No private key found in the uploaded file.",
  no_certificates:    "No certificates found in the uploaded file.",
  key_cert_mismatch:  "The private key does not match the certificate.",
  domain_mismatch:    "The domain does not match any Subject CN or SAN in the certificate.",
  chain_order:        "Could not determine certificate chain order. Verify the bundle contains a leaf certificate.",
  pfx_decrypt_failed: "Failed to decrypt the PFX file. Check the password.",
};

type SSLPhase =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "success" }
  | { kind: "error"; code: string; message: string }
  | { kind: "removing" };

function ExpiryBadge({ days }: { days: number }) {
  const color = days > 30 ? "text-green-700 bg-green-50" : days >= 8 ? "text-amber-700 bg-amber-50" : "text-red-700 bg-red-50";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {days > 0 ? `${days} days` : "Expired"}
    </span>
  );
}

function SSLTlsSection() {
  const qc = useQueryClient();
  const { data: sslStatus, isLoading: statusLoading } = useQuery<SSLStatus>({
    queryKey: ["ssl-status"],
    queryFn: fetchSSLStatus,
  });

  const [phase, setPhase] = useState<SSLPhase>({ kind: "idle" });
  const [selectedTab, setSelectedTab] = useState<"pfx" | "pem_file" | "pem_paste">("pfx");
  const [domain, setDomain] = useState("");
  const [pfxFile, setPfxFile] = useState<File | null>(null);
  const [pfxPassword, setPfxPassword] = useState("");
  const [pemFile, setPemFile] = useState<File | null>(null);
  const [leafCertText, setLeafCertText] = useState("");
  const [chainCertText, setChainCertText] = useState("");
  const [privateKeyText, setPrivateKeyText] = useState("");
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [showFido2Confirm, setShowFido2Confirm] = useState(false);
  const pfxRef = useRef<HTMLInputElement>(null);
  const pemFileRef = useRef<HTMLInputElement>(null);

  function handleError(e: unknown) {
    const code = e instanceof ApiError ? e.message : "unknown";
    const msg = SSL_ERROR_MESSAGES[code] ?? `Validation failed: ${code}`;
    setPhase({ kind: "error", code, message: msg });
  }

  async function handleUpload() {
    if (!domain.trim()) return;
    setPhase({ kind: "uploading" });
    try {
      if (selectedTab === "pfx" && pfxFile) {
        await uploadSSLPfx(pfxFile, pfxPassword, domain);
      } else if (selectedTab === "pem_file" && pemFile) {
        await uploadSSLPemFile(pemFile, domain);
      } else if (selectedTab === "pem_paste") {
        const combined = [leafCertText, chainCertText, privateKeyText]
          .map((t) => t.trim())
          .filter(Boolean)
          .join("\n");
        if (!combined) { setPhase({ kind: "idle" }); return; }
        await uploadSSLPemPaste(combined, domain);
      } else {
        setPhase({ kind: "idle" });
        return;
      }
    } catch (e) {
      handleError(e);
      return;
    }
    // Container is restarting in the background; show the HTTPS link immediately.
    setPhase({ kind: "success" });
    qc.invalidateQueries({ queryKey: ["ssl-status"] });
  }

  async function handleRemove() {
    setShowRemoveConfirm(false);
    setPhase({ kind: "removing" });
    try {
      await removeSSL();
    } catch (e) {
      handleError(e);
      return;
    }
    const deadline = Date.now() + 30_000;
    let recovered = false;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`http://${window.location.hostname}:8000/health`);
        if (res.ok) { recovered = true; break; }
      } catch { /* not yet up */ }
      await new Promise((r) => setTimeout(r, 1_000));
    }
    if (recovered) {
      window.location.reload();
    } else {
      setPhase({
        kind: "error",
        code: "restart_timeout",
        message: "Container did not return on port 8000 within 30 seconds. Check container logs.",
      });
    }
  }

  const busy = phase.kind === "uploading" || phase.kind === "removing";
  const hasActiveCert = sslStatus?.active && sslStatus?.mode === "upload";

  return (
    <SectionCard title="SSL / TLS" defaultOpen={hasActiveCert}>
      {/* Security warning: hardware key FIDO2 caveat */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
        <strong>Hardware security keys (YubiKey, etc.)</strong> require this certificate to be trusted
        by the browser. Use a CA-signed certificate, or import a self-signed certificate into your
        system/browser trust store before enrolling hardware keys.
      </div>

      {/* Current certificate info */}
      {statusLoading && <p className="text-xs text-gray-400">Loading certificate status…</p>}
      {hasActiveCert && sslStatus && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-1.5 text-xs text-gray-700">
          <p className="text-sm font-semibold text-gray-800 mb-2">Current certificate</p>
          {sslStatus.subject && (
            <div className="flex gap-2"><span className="w-20 text-gray-500">Subject</span><span className="font-mono">{sslStatus.subject}</span></div>
          )}
          {sslStatus.sans && sslStatus.sans.length > 0 && (
            <div className="flex gap-2"><span className="w-20 text-gray-500">SANs</span><span className="font-mono">{sslStatus.sans.join(", ")}</span></div>
          )}
          {sslStatus.not_after && sslStatus.days_until_expiry !== null && (
            <div className="flex gap-2 items-center">
              <span className="w-20 text-gray-500">Expires</span>
              <span>{new Date(sslStatus.not_after).toLocaleDateString()}</span>
              <ExpiryBadge days={sslStatus.days_until_expiry} />
            </div>
          )}
          <div className="pt-2">
            {!showRemoveConfirm ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => setShowRemoveConfirm(true)}
                className="px-3 py-1.5 text-sm font-medium rounded-md border border-red-400 text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
              >
                Remove SSL
              </button>
            ) : (
              <div className="rounded-lg border border-red-300 bg-red-50 p-3 space-y-2">
                <p className="text-xs text-red-800">Remove SSL and revert to HTTP? The container will restart.</p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setShowRemoveConfirm(false)}
                    className="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 transition-colors">
                    Cancel
                  </button>
                  <button type="button" onClick={handleRemove}
                    className="px-3 py-1.5 text-xs font-medium rounded-md bg-red-600 hover:bg-red-700 text-white transition-colors">
                    Confirm Remove
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Phase: uploading / removing */}
      {phase.kind === "uploading" && (
        <div className="flex items-center gap-3 text-sm text-gray-600">
          <LoadingSpinner />
          <span>Validating and saving certificate…</span>
        </div>
      )}
      {phase.kind === "removing" && (
        <div className="flex items-center gap-3 text-sm text-gray-600">
          <LoadingSpinner />
          <span>Removing SSL certificate and restarting…</span>
        </div>
      )}

      {/* Phase: success */}
      {phase.kind === "success" && (
        <div className="rounded-lg border border-green-300 bg-green-50 p-4 space-y-3">
          <p className="text-sm font-semibold text-green-800">Certificate saved. Container is restarting with HTTPS — navigate to the new URL when ready:</p>
          <p className="font-mono text-sm text-green-900">
            https://{domain}:8443
          </p>
          {!/^(localhost|127\.0\.0\.1|::1)$/.test(domain.trim()) && (
            <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <strong>Check network binding:</strong> If this container is bound to localhost only
              (the default), port 8443 will not be reachable via <code className="font-mono">{domain}</code>.
              Set <code className="font-mono">BIND_ADDR=0.0.0.0</code> in your <code className="font-mono">.env</code> file
              and restart the container if needed.
            </div>
          )}
          <div className="flex gap-2">
            <a
              href={`https://${domain}:8443`}
              target="_blank"
              rel="noreferrer"
              className="px-3 py-1.5 text-sm font-medium rounded-md bg-green-600 hover:bg-green-700 text-white transition-colors"
            >
              Open in new tab
            </a>
            <button
              type="button"
              onClick={() => { setPhase({ kind: "idle" }); qc.invalidateQueries({ queryKey: ["ssl-status"] }); }}
              className="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Phase: error */}
      {phase.kind === "error" && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-4 space-y-3">
          <p className="text-sm text-red-800">{phase.message}</p>
          <button
            type="button"
            onClick={() => setPhase({ kind: "idle" })}
            className="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 transition-colors"
          >
            Back to upload form
          </button>
        </div>
      )}

      {/* Upload form (shown in idle state) */}
      {phase.kind === "idle" && (
        <div className="space-y-4">
          {/* Tab bar */}
          <div className="flex gap-1 border-b border-gray-200">
            {(["pfx", "pem_file", "pem_paste"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setSelectedTab(tab)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  selectedTab === tab
                    ? "border-zs-500 text-zs-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {tab === "pfx" ? "PFX File" : tab === "pem_file" ? "PEM File" : "Paste PEM"}
              </button>
            ))}
          </div>

          {/* Shared domain field */}
          <FieldRow label="Domain" hint="Hostname in the certificate (no scheme or port).">
            <TextInput
              value={domain}
              onChange={setDomain}
              placeholder="zs-config.example.com"
            />
          </FieldRow>

          {/* PFX tab */}
          {selectedTab === "pfx" && (
            <>
              <FieldRow label="PFX file">
                <input
                  ref={pfxRef}
                  type="file"
                  accept=".pfx,.p12"
                  onChange={(e) => setPfxFile(e.target.files?.[0] ?? null)}
                  className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-600 hover:file:bg-gray-200"
                />
              </FieldRow>
              <FieldRow label="PFX password">
                <input
                  type="password"
                  value={pfxPassword}
                  onChange={(e) => setPfxPassword(e.target.value)}
                  placeholder="Leave blank if no password"
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                />
              </FieldRow>
            </>
          )}

          {/* PEM file tab */}
          {selectedTab === "pem_file" && (
            <FieldRow label="PEM / CRT file" hint="Must contain full chain + unencrypted private key in a single file.">
              <input
                ref={pemFileRef}
                type="file"
                accept=".pem,.crt,.cer"
                onChange={(e) => setPemFile(e.target.files?.[0] ?? null)}
                className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-600 hover:file:bg-gray-200"
              />
            </FieldRow>
          )}

          {/* Paste PEM tab */}
          {selectedTab === "pem_paste" && (
            <div className="space-y-3">
              <FieldRow label="Server certificate" hint="Leaf / end-entity certificate only.">
                <textarea
                  rows={5}
                  value={leafCertText}
                  onChange={(e) => setLeafCertText(e.target.value)}
                  placeholder={"-----BEGIN CERTIFICATE-----\n(server / leaf certificate)\n-----END CERTIFICATE-----"}
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-zs-500 resize-y"
                />
              </FieldRow>
              <FieldRow label="CA chain" hint="Intermediate and root CA certificates. Leave blank for self-signed.">
                <textarea
                  rows={5}
                  value={chainCertText}
                  onChange={(e) => setChainCertText(e.target.value)}
                  placeholder={"-----BEGIN CERTIFICATE-----\n(intermediate CA)\n-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----\n(root CA, optional)\n-----END CERTIFICATE-----"}
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-zs-500 resize-y"
                />
              </FieldRow>
              <FieldRow label="Private key" hint="Unencrypted PEM private key.">
                <textarea
                  rows={5}
                  value={privateKeyText}
                  onChange={(e) => setPrivateKeyText(e.target.value)}
                  placeholder={"-----BEGIN PRIVATE KEY-----\n(unencrypted private key)\n-----END PRIVATE KEY-----"}
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-zs-500 resize-y"
                />
              </FieldRow>
            </div>
          )}

          {showFido2Confirm ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 space-y-3">
              <p className="text-sm font-semibold text-amber-800">Security key re-registration required</p>
              <p className="text-xs text-amber-700">
                Enabling HTTPS changes the WebAuthn origin from <code className="font-mono">http://…:8000</code> to{" "}
                <code className="font-mono">https://…:8443</code>. All existing passkeys and hardware security key
                registrations will be <strong>permanently invalidated</strong>. Every user must re-register their
                security keys at next login.
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setShowFido2Confirm(false)}
                  className="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => { setShowFido2Confirm(false); handleUpload(); }}
                  className="px-3 py-1.5 text-xs font-medium rounded-md bg-amber-600 hover:bg-amber-700 text-white transition-colors"
                >
                  I understand, continue
                </button>
              </div>
            </div>
          ) : (
            <div>
              <button
                type="button"
                onClick={() => {
                  const originChanging = !sslStatus?.active || sslStatus.domain !== domain.trim();
                  if (originChanging) setShowFido2Confirm(true);
                  else handleUpload();
                }}
                disabled={
                  !domain.trim() ||
                  (selectedTab === "pfx" && !pfxFile) ||
                  (selectedTab === "pem_file" && !pemFile) ||
                  (selectedTab === "pem_paste" && (!leafCertText.trim() || !privateKeyText.trim()))
                }
                className="px-4 py-2 text-sm font-medium rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50 transition-colors"
              >
                Upload &amp; Enable HTTPS
              </button>
            </div>
          )}
        </div>
      )}
    </SectionCard>
  );
}

// ── Updates section ───────────────────────────────────────────────────────────

function UpdatesSection({
  draft,
  set,
}: {
  draft: SystemSettings;
  set: <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => void;
}) {
  const [testState, setTestState] = useState<"idle" | "sending" | "ok" | "error">("idle");
  const [testError, setTestError] = useState<string | null>(null);

  async function handleTest() {
    setTestState("sending");
    setTestError(null);
    try {
      await sendTestUpdateEmail();
      setTestState("ok");
      setTimeout(() => setTestState("idle"), 3000);
    } catch (e: unknown) {
      setTestError(e instanceof Error ? e.message : "Failed to send test email");
      setTestState("error");
    }
  }

  const smtpComplete = !!draft.update_notify_email && !!draft.smtp_host;

  return (
    <SectionCard title="Updates">
      <FieldRow
        label="Daily update check"
        hint="Check PyPI once per day and send an email when a new version is available."
      >
        <Toggle
          checked={draft.update_notify_enabled}
          onChange={(v) => set("update_notify_enabled", v)}
        />
      </FieldRow>

      {draft.update_notify_enabled && (
        <>
          <FieldRow label="Notify email" hint="Address that receives update alerts.">
            <TextInput
              value={draft.update_notify_email}
              onChange={(v) => set("update_notify_email", v)}
              placeholder="admin@example.com"
            />
          </FieldRow>

          <FieldRow label="SMTP host">
            <TextInput
              value={draft.smtp_host}
              onChange={(v) => set("smtp_host", v)}
              placeholder="smtp.example.com"
            />
          </FieldRow>

          <FieldRow label="SMTP port">
            <NumberInput
              value={draft.smtp_port}
              onChange={(v) => set("smtp_port", v)}
              min={1}
              max={65535}
            />
          </FieldRow>

          <FieldRow label="Username" hint="Leave blank if the server requires no authentication.">
            <TextInput
              value={draft.smtp_username}
              onChange={(v) => set("smtp_username", v)}
              placeholder="user@example.com"
            />
          </FieldRow>

          <FieldRow label="Password">
            <input
              type="password"
              value={draft.smtp_password}
              onChange={(e) => set("smtp_password", e.target.value)}
              placeholder="••••••••"
              className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
            />
          </FieldRow>

          <FieldRow label="From address" hint="Defaults to the username if left blank.">
            <TextInput
              value={draft.smtp_from_address}
              onChange={(v) => set("smtp_from_address", v)}
              placeholder="zs-config@example.com"
            />
          </FieldRow>

          <FieldRow label="Use TLS" hint="STARTTLS on port 587; implicit TLS on port 465.">
            <Toggle
              checked={draft.smtp_tls}
              onChange={(v) => set("smtp_tls", v)}
            />
          </FieldRow>

          <FieldRow label="Test">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleTest}
                disabled={!smtpComplete || testState === "sending"}
                className="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-50 transition-colors"
              >
                {testState === "sending" ? "Sending…" : "Send Test Email"}
              </button>
              {testState === "ok" && <span className="text-sm text-green-600 font-medium">Sent</span>}
              {testState === "error" && <span className="text-sm text-red-600">{testError}</span>}
            </div>
            {!smtpComplete && (
              <p className="text-xs text-gray-400 mt-1">Save your settings first, then send a test.</p>
            )}
          </FieldRow>
        </>
      )}
    </SectionCard>
  );
}

// ── Database Maintenance card (Import + Clear Data + Encryption) ──────────────

function DatabaseMaintenanceCard({
  draft,
  set,
}: {
  draft: SystemSettings;
  set: <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => void;
}) {
  return (
    <SectionCard title="Database Maintenance">
      <p className="text-sm font-semibold text-gray-700 mb-1">Import Database</p>
      <ImportDatabaseSection />
      <hr className="border-gray-100" />
      <p className="text-sm font-semibold text-gray-700 mb-1">Clear Data</p>
      <ClearDataSection />
      <hr className="border-gray-100" />
      <p className="text-sm font-semibold text-gray-700 mb-1">Encryption</p>
      <EncryptionSection draft={draft} set={set} />
    </SectionCard>
  );
}

// ── Import Database section ───────────────────────────────────────────────────

function ImportDatabaseSection() {
  const [dbFile, setDbFile] = useState<File | null>(null);
  const [keyFile, setKeyFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportDbResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const dbRef = useRef<HTMLInputElement>(null);
  const keyRef = useRef<HTMLInputElement>(null);

  async function handleImport() {
    if (!dbFile) return;
    setLoading(true);
    setResult(null);
    setErr(null);
    try {
      const res = await importDatabase(dbFile, keyFile ?? undefined);
      setResult(res);
      setDbFile(null);
      setKeyFile(null);
      if (dbRef.current) dbRef.current.value = "";
      if (keyRef.current) keyRef.current.value = "";
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Import failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        Replace the running database with one exported from a local TUI-based zs-config install.
        Use the <code className="bg-gray-100 px-1 rounded text-xs font-mono">scripts/export_tui_db.sh</code> script
        to export the database and encryption key from a local install.
      </p>
      <FieldRow
        label="Database file"
        hint="SQLite .db file exported from a local install."
      >
        <input
          ref={dbRef}
          type="file"
          accept=".db,.sqlite,.sqlite3"
          onChange={(e) => setDbFile(e.target.files?.[0] ?? null)}
          className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-600 hover:file:bg-gray-200"
        />
        {dbFile && <p className="text-xs text-gray-400 mt-1">{dbFile.name} ({(dbFile.size / 1024).toFixed(1)} KB)</p>}
      </FieldRow>
      <FieldRow
        label="Encryption key"
        hint="secret.key file — required if the exported database contains encrypted tenant credentials."
      >
        <input
          ref={keyRef}
          type="file"
          accept=".key,.txt"
          onChange={(e) => setKeyFile(e.target.files?.[0] ?? null)}
          className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-600 hover:file:bg-gray-200"
        />
        {keyFile && <p className="text-xs text-gray-400 mt-1">{keyFile.name}</p>}
      </FieldRow>
      {err && <p className="text-xs text-red-600">{err}</p>}
      {result && (
        <div className="space-y-3">
          <p className="text-xs text-green-700 font-medium">{result.message}</p>
          {result.seeded_admin && result.temp_password && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 space-y-2">
              <p className="text-sm font-semibold text-amber-800">Admin account created</p>
              <p className="text-xs text-amber-700">
                No admin users were found in the imported database. A temporary admin account
                has been created. Sign in and change the password immediately.
              </p>
              <div className="flex items-center gap-3 mt-1">
                <div>
                  <p className="text-xs text-amber-600 font-medium">Username</p>
                  <code className="text-sm font-mono font-bold text-amber-900">admin</code>
                </div>
                <div>
                  <p className="text-xs text-amber-600 font-medium">Temporary password</p>
                  <code className="text-sm font-mono font-bold text-amber-900">{result.temp_password}</code>
                </div>
              </div>
              <p className="text-xs text-amber-600">
                This password is shown once and will not be displayed again. Sign out and log in with these credentials now.
              </p>
            </div>
          )}
        </div>
      )}
      <div>
        <button
          onClick={handleImport}
          disabled={!dbFile || loading}
          className="px-4 py-2 text-sm font-medium rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50 transition-colors"
        >
          {loading ? "Importing…" : "Import Database"}
        </button>
      </div>
    </div>
  );
}

// ── Clear Data section ────────────────────────────────────────────────────────

function ClearDataSection() {
  const { data: tenants } = useQuery<Tenant[]>({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
  });

  const [scope, setScope] = useState<"all" | "one">("all");
  const [tenantId, setTenantId] = useState<string>("");
  const [confirm, setConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ClearDataResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const sortedTenants = tenants
    ? [...tenants].sort((a, b) => a.name.localeCompare(b.name))
    : [];

  async function handleClear() {
    setLoading(true);
    setResult(null);
    setErr(null);
    try {
      const tid = scope === "one" && tenantId ? parseInt(tenantId, 10) : undefined;
      const res = await clearData(tid);
      setResult(res);
      setConfirm(false);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Clear failed");
    } finally {
      setLoading(false);
    }
  }

  const canSubmit = !loading && confirm && (scope === "all" || !!tenantId);

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        Permanently deletes imported resources, config snapshots, sync logs, and audit log entries.
        Tenant configuration (credentials, connection details) is preserved.
      </p>

      <FieldRow label="Scope">
        <SelectInput
          value={scope}
          onChange={(v) => { setScope(v as "all" | "one"); setTenantId(""); setConfirm(false); setResult(null); }}
          options={[
            { value: "all", label: "All tenants" },
            { value: "one", label: "Specific tenant" },
          ]}
        />
      </FieldRow>

      {scope === "one" && (
        <FieldRow label="Tenant">
          <select
            value={tenantId}
            onChange={(e) => { setTenantId(e.target.value); setConfirm(false); setResult(null); }}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          >
            <option value="">— select tenant —</option>
            {sortedTenants.map((t) => (
              <option key={t.id} value={String(t.id)}>{t.name}</option>
            ))}
          </select>
        </FieldRow>
      )}

      <FieldRow label="Confirm">
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
            className="rounded border-gray-300 text-zs-500 focus:ring-zs-500"
          />
          I understand this cannot be undone
        </label>
      </FieldRow>

      {err && <p className="text-xs text-red-600">{err}</p>}

      {result && (
        <p className="text-xs text-green-700 font-medium">
          Cleared: {result.zia} ZIA, {result.zpa} ZPA, {result.zcc} ZCC resources,{" "}
          {result.snapshots} snapshots, {result.sync_logs} sync logs,{" "}
          {result.audit_entries} audit entries.
        </p>
      )}

      <div>
        <button
          onClick={handleClear}
          disabled={!canSubmit}
          className="px-4 py-2 text-sm font-medium rounded-md bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 transition-colors"
        >
          {loading ? "Clearing…" : "Clear Data"}
        </button>
      </div>
    </div>
  );
}

// ── Encryption section ────────────────────────────────────────────────────────

function EncryptionSection({
  draft,
  set,
}: {
  draft: SystemSettings;
  set: <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => void;
}) {
  const qc = useQueryClient();
  const [showConfirm, setShowConfirm] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotateResult, setRotateResult] = useState<RotateKeyResult | null>(null);
  const [rotateError, setRotateError] = useState<string | null>(null);

  async function handleRotate() {
    setRotating(true);
    setRotateResult(null);
    setRotateError(null);
    try {
      const res = await rotateKey(draft.encryption_algorithm);
      setRotateResult(res);
      setShowConfirm(false);
      qc.invalidateQueries({ queryKey: ["system-settings"] });
    } catch (e: unknown) {
      setRotateError(e instanceof Error ? e.message : "Rotation failed");
    } finally {
      setRotating(false);
    }
  }

  function handleFipsModeChange(v: boolean) {
    set("fips_mode", v);
    if (v && draft.encryption_algorithm === "chacha20poly1305") {
      set("encryption_algorithm", "fernet");
    }
  }

  return (
    <div className="space-y-4">
      <FieldRow label="Current algorithm">
        <span className="text-sm text-gray-700">{ALGO_LABELS[draft.encryption_algorithm] ?? draft.encryption_algorithm}</span>
      </FieldRow>

      <FieldRow label="Last rotated">
        <span className="text-sm text-gray-700">
          {draft.key_last_rotated_at
            ? new Date(draft.key_last_rotated_at + "Z").toLocaleString()
            : "Never"}
        </span>
      </FieldRow>

      <FieldRow
        label="Algorithm"
        hint="Select the encryption algorithm for tenant secrets."
      >
        <SelectInput
          value={draft.encryption_algorithm}
          onChange={(v) => set("encryption_algorithm", v)}
          options={[
            { value: "fernet", label: "Fernet (AES-128-CBC)" },
            { value: "aes256gcm", label: "AES-256-GCM" },
            { value: "chacha20poly1305", label: "ChaCha20-Poly1305 (non-FIPS)", disabled: draft.fips_mode },
          ]}
        />
        {draft.fips_mode && draft.encryption_algorithm === "chacha20poly1305" && (
          <p className="text-xs text-amber-600 mt-1">ChaCha20-Poly1305 is not FIPS-compliant. Algorithm reset to Fernet.</p>
        )}
      </FieldRow>

      <FieldRow
        label="FIPS mode"
        hint="Restrict algorithm selection to FIPS 140-2 validated ciphers. Actual FIPS compliance requires a FIPS-validated OpenSSL build."
      >
        <Toggle checked={draft.fips_mode} onChange={handleFipsModeChange} />
      </FieldRow>

      <FieldRow
        label="Auto-rotation interval"
        hint="Automatically rotate the key after this interval at startup. 0 = disabled."
      >
        <SelectInput
          value={String(draft.key_rotation_interval_days)}
          onChange={(v) => set("key_rotation_interval_days", parseInt(v, 10))}
          options={[
            { value: "0", label: "Off" },
            { value: "30", label: "30 days" },
            { value: "60", label: "60 days" },
            { value: "90", label: "90 days" },
            { value: "180", label: "180 days" },
            { value: "365", label: "365 days" },
          ]}
        />
      </FieldRow>

      <hr className="border-gray-100" />

      <FieldRow label="Manual rotation">
        {!showConfirm ? (
          <button
            type="button"
            onClick={() => { setShowConfirm(true); setRotateResult(null); setRotateError(null); }}
            className="px-4 py-2 text-sm font-medium rounded-md border border-red-400 text-red-600 hover:bg-red-50 transition-colors"
          >
            Rotate Key Now
          </button>
        ) : (
          <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4">
            <p className="text-sm text-amber-800">
              This will re-encrypt all tenant secrets with a new key. The old key will be
              overwritten. Ensure you have a database backup.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                disabled={rotating}
                className="px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100 disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRotate}
                disabled={rotating}
                className="px-3 py-1.5 text-sm font-medium rounded-md bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 transition-colors"
              >
                {rotating ? "Rotating…" : "Confirm Rotation"}
              </button>
            </div>
          </div>
        )}
      </FieldRow>

      {rotateResult && (
        <p className="text-xs text-green-700 font-medium">
          Rotated {rotateResult.rotated} tenant secrets using {ALGO_LABELS[rotateResult.algorithm] ?? rotateResult.algorithm}.
          Completed at {new Date(rotateResult.rotated_at + "Z").toLocaleString()}.
        </p>
      )}
      {rotateError && <p className="text-xs text-red-600">{rotateError}</p>}
    </div>
  );
}

// ── Identity Provider (SSO) ───────────────────────────────────────────────────

type SetFn = <K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) => void;

function IdentityProviderSection({ draft, set }: { draft: SystemSettings; set: SetFn }) {
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const test = useMutation({
    mutationFn: testSso,
    onSuccess: (res) => {
      setTestError(null);
      const { ok: _ok, provider, ...rest } = res;
      setTestResult(
        [`provider: ${provider}`, ...Object.entries(rest).map(([k, v]) => `${k}: ${v}`)].join("\n"),
      );
    },
    onError: (err: unknown) => {
      setTestResult(null);
      setTestError(err instanceof Error ? err.message : "Connection test failed");
    },
  });

  const provider = draft.idp_provider || "oidc";
  const base = draft.sso_base_url || window.location.origin;

  return (
    <SectionCard title="Identity Provider (SSO)">
      <FieldRow label="Enable SSO" hint="Adds a 'Sign in with SSO' button to the login page.">
        <Toggle checked={draft.idp_enabled} onChange={(v) => set("idp_enabled", v)} />
      </FieldRow>
      <FieldRow label="Protocol">
        <SelectInput
          value={provider}
          onChange={(v) => set("idp_provider", v)}
          options={[
            { value: "oidc", label: "OIDC" },
            { value: "saml", label: "SAML 2.0" },
          ]}
        />
      </FieldRow>
      <FieldRow
        label="Public base URL"
        hint="How browsers and the IdP reach this install. Used to build redirect, ACS and metadata URLs."
      >
        <TextInput
          value={draft.sso_base_url}
          onChange={(v) => set("sso_base_url", v)}
          placeholder="https://zs-config.example.com"
        />
      </FieldRow>

      {provider === "oidc" ? (
        <>
          <FieldRow label="Issuer URL" hint="Discovery is read from {issuer}/.well-known/openid-configuration.">
            <TextInput
              value={draft.idp_issuer_url}
              onChange={(v) => set("idp_issuer_url", v)}
              placeholder="https://login.example.com/oauth2/default"
            />
          </FieldRow>
          <FieldRow label="Client ID">
            <TextInput
              value={draft.idp_client_id}
              onChange={(v) => set("idp_client_id", v)}
              placeholder="0oa1b2c3d4e5f6g7h8i9"
            />
          </FieldRow>
          <FieldRow label="Client secret">
            <SecretInput
              value={draft.idp_client_secret ?? ""}
              onChange={(v) => set("idp_client_secret", v)}
              isSet={draft.idp_client_secret_set}
            />
          </FieldRow>
          <FieldRow label="Scopes">
            <TextInput
              value={draft.idp_scopes}
              onChange={(v) => set("idp_scopes", v)}
              placeholder="openid profile email groups"
            />
          </FieldRow>
          <FieldRow label="Redirect URI" hint="Register this exact value with your IdP.">
            <CopyField value={`${base}/api/v1/auth/sso/callback`} />
          </FieldRow>
        </>
      ) : (
        <>
          <FieldRow
            label="IdP metadata URL"
            hint="Preferred — the metadata is re-read on each request. Leave blank to paste XML instead."
          >
            <TextInput
              value={draft.saml_idp_metadata_url}
              onChange={(v) => set("saml_idp_metadata_url", v)}
              placeholder="https://login.example.com/app/exk1234/sso/saml/metadata"
            />
          </FieldRow>
          <FieldRow label="IdP metadata XML" hint="Used when no metadata URL is set.">
            <TextArea
              value={draft.saml_idp_metadata_xml}
              onChange={(v) => set("saml_idp_metadata_xml", v)}
              placeholder="<EntityDescriptor …>"
              rows={6}
            />
          </FieldRow>
          <FieldRow label="SP entity ID" hint="Defaults to the metadata URL below if left blank.">
            <TextInput
              value={draft.saml_sp_entity_id}
              onChange={(v) => set("saml_sp_entity_id", v)}
              placeholder={`${base}/api/v1/auth/sso/metadata`}
            />
          </FieldRow>
          <FieldRow
            label="SP certificate"
            hint="Optional. Only needed if your IdP requires signed AuthnRequests."
          >
            <TextArea
              value={draft.saml_sp_cert}
              onChange={(v) => set("saml_sp_cert", v)}
              placeholder="-----BEGIN CERTIFICATE-----"
              rows={4}
            />
          </FieldRow>
          <FieldRow label="SP private key">
            <SecretInput
              value={draft.saml_sp_key ?? ""}
              onChange={(v) => set("saml_sp_key", v)}
              isSet={draft.saml_sp_key_set}
            />
          </FieldRow>
          <FieldRow label="ACS URL" hint="Register this exact value with your IdP.">
            <CopyField value={`${base}/api/v1/auth/sso/acs`} />
          </FieldRow>
          <FieldRow label="SP metadata">
            <a
              href={ssoMetadataUrl()}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-zs-600 hover:underline"
            >
              Download SP metadata XML
            </a>
          </FieldRow>
        </>
      )}

      <FieldRow
        label="Auto-provision users"
        hint="Create a local account the first time an unknown user signs in through the IdP."
      >
        <Toggle
          checked={draft.idp_auto_provision}
          onChange={(v) => set("idp_auto_provision", v)}
        />
      </FieldRow>
      <FieldRow label="Default role" hint="Applied when no SCIM group mapping matches.">
        <SelectInput
          value={draft.idp_default_role || "user"}
          onChange={(v) => set("idp_default_role", v)}
          options={[
            { value: "user", label: "User" },
            { value: "admin", label: "Admin" },
          ]}
        />
      </FieldRow>
      <FieldRow
        label="Group claim"
        hint="Claim or SAML attribute carrying group names, matched against SCIM group mappings."
      >
        <TextInput
          value={draft.idp_group_claim}
          onChange={(v) => set("idp_group_claim", v)}
          placeholder="groups"
        />
      </FieldRow>

      <div className="pt-2 border-t border-gray-100 space-y-2">
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending}
          className="px-3 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50 disabled:opacity-50 text-gray-700"
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </button>
        <p className="text-xs text-gray-400">
          Tests the configuration that is already saved — save your changes first.
        </p>
        {testError && <ErrorMessage message={testError} />}
        {testResult && (
          <pre className="rounded bg-green-50 border border-green-200 px-3 py-2 text-xs text-green-800 whitespace-pre-wrap">
            {testResult}
          </pre>
        )}
      </div>
    </SectionCard>
  );
}

// ── SCIM provisioning ─────────────────────────────────────────────────────────

function ScimSection({ baseUrl }: { baseUrl: string }) {
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  // Shown once, right after creation — the plaintext is never stored server-side.
  const [newToken, setNewToken] = useState<string | null>(null);

  const { data: tokens } = useQuery({ queryKey: ["scim-tokens"], queryFn: fetchScimTokens });
  const { data: groups } = useQuery({ queryKey: ["scim-groups"], queryFn: fetchScimGroups });

  const create = useMutation({
    mutationFn: () => createScimToken(label.trim() || undefined),
    onSuccess: (res) => {
      setNewToken(res.token);
      setLabel("");
      qc.invalidateQueries({ queryKey: ["scim-tokens"] });
    },
  });

  const revoke = useMutation({
    mutationFn: revokeScimToken,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scim-tokens"] }),
  });

  const map = useMutation({
    mutationFn: ({ id, role }: { id: number; role: string | null }) => mapScimGroup(id, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scim-groups"] });
      // A remapped group can change roles, so the user list is stale too.
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const base = baseUrl || window.location.origin;

  return (
    <SectionCard title="SCIM Provisioning">
      <p className="text-xs text-gray-500">
        Point your identity provider at these values to provision and deprovision zs-config
        web users automatically. This manages application accounts only — it does not touch
        Zscaler tenants.
      </p>

      <FieldRow label="SCIM base URL">
        <CopyField value={`${base}/scim/v2`} />
      </FieldRow>

      <div className="pt-3 border-t border-gray-100 space-y-3">
        <p className="text-sm font-medium text-gray-700">Bearer tokens</p>

        {newToken && (
          <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 space-y-2">
            <p className="text-xs text-amber-800 font-medium">
              Copy this token now — it is not shown again.
            </p>
            <CopyField value={newToken} />
            <button
              type="button"
              onClick={() => setNewToken(null)}
              className="text-xs text-amber-700 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={label}
            placeholder="Label (e.g. Okta production)"
            onChange={(e) => setLabel(e.target.value)}
            className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
          <button
            type="button"
            onClick={() => create.mutate()}
            disabled={create.isPending}
            className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
          >
            {create.isPending ? "Generating…" : "Generate token"}
          </button>
        </div>
        {create.isError && (
          <ErrorMessage message={create.error instanceof Error ? create.error.message : "Failed to generate token"} />
        )}

        {tokens && tokens.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200">
                <th className="py-1.5 font-medium">Label</th>
                <th className="py-1.5 font-medium">Prefix</th>
                <th className="py-1.5 font-medium">Last used</th>
                <th className="py-1.5" />
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr key={t.id} className="border-b border-gray-100">
                  <td className="py-1.5 text-gray-700">{t.label || <span className="text-gray-400">—</span>}</td>
                  <td className="py-1.5 font-mono text-gray-500">{t.token_prefix}…</td>
                  <td className="py-1.5 text-gray-500">
                    {t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "never"}
                  </td>
                  <td className="py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => revoke.mutate(t.id)}
                      className="text-red-600 hover:underline"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-gray-400">No tokens issued yet.</p>
        )}
      </div>

      <div className="pt-3 border-t border-gray-100 space-y-3">
        <p className="text-sm font-medium text-gray-700">Group role mapping</p>
        <p className="text-xs text-gray-500">
          Groups appear here once your IdP pushes them. Mapping one to a role applies it to
          its members immediately. Unmapped groups leave members on the default role.
        </p>
        {groups && groups.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200">
                <th className="py-1.5 font-medium">Group</th>
                <th className="py-1.5 font-medium">Members</th>
                <th className="py-1.5 font-medium">Role</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.id} className="border-b border-gray-100">
                  <td className="py-1.5 text-gray-700">{g.display_name}</td>
                  <td className="py-1.5 text-gray-500">{g.member_count}</td>
                  <td className="py-1.5">
                    <select
                      value={g.mapped_role ?? ""}
                      onChange={(e) => map.mutate({ id: g.id, role: e.target.value || null })}
                      className="border border-gray-300 rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-zs-500"
                    >
                      <option value="">Not mapped</option>
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-gray-400">No groups have been provisioned yet.</p>
        )}
        {map.isError && (
          <ErrorMessage message={map.error instanceof Error ? map.error.message : "Failed to update mapping"} />
        )}
      </div>
    </SectionCard>
  );
}
