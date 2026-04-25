import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, patchSettings, SystemSettings } from "../api/system";
import { importDatabase, ImportDbResult } from "../api/admin";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

// ── Shared field components ───────────────────────────────────────────────────

function SectionCard({ title, badge, children }: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
      <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-100 bg-gray-50">
        <h2 className="font-semibold text-gray-800 text-sm">{title}</h2>
        {badge}
      </div>
      <div className="px-6 py-5 space-y-4">{children}</div>
    </div>
  );
}

function ComingSoon() {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">
      Coming Soon
    </span>
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

function SelectInput({ value, onChange, options, disabled }: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
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
        <option key={o.value} value={o.value}>{o.label}</option>
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminSettingsPage() {
  const qc = useQueryClient();
  const { data: settings, isLoading, error } = useQuery({
    queryKey: ["system-settings"],
    queryFn: fetchSettings,
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
      <SectionCard title="Identity Provider (SSO)" badge={<ComingSoon />}>
        <p className="text-xs text-gray-500">
          OIDC and SAML integration is planned for a future release. These fields are saved
          and will be activated when support is enabled.
        </p>
        <FieldRow label="Enable SSO">
          <Toggle
            checked={draft.idp_enabled}
            onChange={(v) => set("idp_enabled", v)}
            disabled
          />
        </FieldRow>
        <FieldRow label="Provider" hint="oidc or saml">
          <SelectInput
            value={draft.idp_provider || "oidc"}
            onChange={(v) => set("idp_provider", v)}
            options={[
              { value: "oidc", label: "OIDC" },
              { value: "saml", label: "SAML" },
            ]}
            disabled
          />
        </FieldRow>
        <FieldRow label="Issuer URL">
          <TextInput
            value={draft.idp_issuer_url}
            onChange={(v) => set("idp_issuer_url", v)}
            placeholder="https://accounts.example.com"
            disabled
          />
        </FieldRow>
        <FieldRow label="Client ID">
          <TextInput
            value={draft.idp_client_id}
            onChange={(v) => set("idp_client_id", v)}
            placeholder="your-client-id"
            disabled
          />
        </FieldRow>
      </SectionCard>

      {/* ── SSL / TLS ─────────────────────────────────────────────────────── */}
      <SectionCard title="SSL / TLS" badge={<ComingSoon />}>
        <p className="text-xs text-gray-500">
          HTTPS termination configuration is planned for a future release. Currently, SSL
          should be handled by a reverse proxy (nginx, Caddy, etc.) in front of zs-config.
        </p>
        <FieldRow label="SSL mode">
          <SelectInput
            value={draft.ssl_mode}
            onChange={(v) => set("ssl_mode", v)}
            options={[
              { value: "none", label: "None (HTTP only)" },
              { value: "upload", label: "Upload certificate & key" },
              { value: "letsencrypt", label: "Let's Encrypt (ACME)" },
            ]}
            disabled
          />
        </FieldRow>
        <FieldRow label="Domain" hint="Required for Let's Encrypt.">
          <TextInput
            value={draft.ssl_domain}
            onChange={(v) => set("ssl_domain", v)}
            placeholder="zs-config.example.com"
            disabled
          />
        </FieldRow>
        {draft.ssl_mode === "upload" && (
          <FieldRow label="Certificate files">
            <div className="space-y-2">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Certificate (.crt / .pem)</label>
                <input type="file" accept=".crt,.pem,.cer" disabled
                  className="text-sm text-gray-400 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-500" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Private key (.key)</label>
                <input type="file" accept=".key,.pem" disabled
                  className="text-sm text-gray-400 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-gray-100 file:text-gray-500" />
              </div>
            </div>
          </FieldRow>
        )}
      </SectionCard>

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

      {/* ── Import Database ───────────────────────────────────────────────── */}
      <ImportDatabaseCard />
    </div>
  );
}

// ── Import Database card ──────────────────────────────────────────────────────

function ImportDatabaseCard() {
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
    <SectionCard title="Import Database">
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
    </SectionCard>
  );
}
