import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { formatDate } from "../utils/time";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import {
  fetchTenants,
  createTenant,
  updateTenant,
  deleteTenant,
  importZIA,
  importZPA,
  importZCC,
  Tenant,
  TenantCreate,
  TenantUpdate,
  ImportResult,
  GovCloudTier,
  DEFAULT_GOV_TIER,
} from "../api/tenants";
import { useJobStream } from "../hooks/useJobStream";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import { useAuth } from "../context/AuthContext";

// ── Field helpers ────────────────────────────────────────────────────────────

interface FieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  placeholder?: string;
  readOnly?: boolean;
}

function Field({ label, value, onChange, type = "text", required, placeholder, readOnly }: FieldProps) {
  const [show, setShow] = useState(false);
  const isPassword = type === "password";
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <div className="relative">
        <input
          type={isPassword && !show ? "password" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          placeholder={placeholder}
          readOnly={readOnly}
          className={`w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 ${readOnly ? "bg-gray-100 text-gray-500" : ""} ${isPassword ? "pr-16" : ""}`}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
          >
            {show ? "Hide" : "Show"}
          </button>
        )}
      </div>
    </div>
  );
}

interface CheckboxFieldProps {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}

function CheckboxField({ label, checked, onChange }: CheckboxFieldProps) {
  return (
    <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-zs-500"
      />
      {label}
    </label>
  );
}

// ── Modal wrapper ────────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4">{children}</div>
      </div>
    </div>
  );
}

// ── GovCloud tier ────────────────────────────────────────────────────────────

const GOV_TIERS: { value: GovCloudTier; label: string; hint: string }[] = [
  { value: "govus", label: "FedRAMP Moderate", hint: "zidentitygov.us / api.zscalergov.us" },
  { value: "gov", label: "FedRAMP High", hint: "zidentitygov.net / api.zscalergov.net" },
];

/** Tier picker. The SDK derives both the ZIdentity host and the OneAPI gateway
 *  from this value, so there is no URL for the user to enter. */
function GovTierField({ value, onChange }: { value: GovCloudTier; onChange: (v: GovCloudTier) => void }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">FedRAMP Tier</label>
      <div className="space-y-1">
        {GOV_TIERS.map((t) => (
          <label key={t.value} className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="radio"
              name="gov_cloud_tier"
              checked={value === t.value}
              onChange={() => onChange(t.value)}
              className="text-zs-500 focus:ring-zs-500"
            />
            <span>{t.label}</span>
            <span className="text-xs text-gray-400 font-mono">{t.hint}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function zidentityHint(vanity: string, govcloud: boolean | undefined, tier: GovCloudTier): string {
  const host = govcloud ? (tier === "gov" ? "zidentitygov.net" : "zidentitygov.us") : "zslogin.net";
  return `→ https://${vanity || "acme"}.${host}`;
}

// ── Create Modal ─────────────────────────────────────────────────────────────

function CreateModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<TenantCreate>({
    name: "",
    vanity_domain: "",
    client_id: "",
    client_secret: "",
    govcloud: false,
    gov_cloud_tier: DEFAULT_GOV_TIER,
    zpa_customer_id: "",
    notes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Tenant | null>(null);

  const mut = useMutation({
    mutationFn: createTenant,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      setResult(data);
    },
    onError: (e: Error) => setError(e.message),
  });

  function set(key: keyof TenantCreate, value: string | boolean) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  const vanityHint = zidentityHint(
    form.vanity_domain,
    form.govcloud,
    form.gov_cloud_tier ?? DEFAULT_GOV_TIER,
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    mut.mutate({
      ...form,
      gov_cloud_tier: form.govcloud ? (form.gov_cloud_tier ?? DEFAULT_GOV_TIER) : undefined,
      zpa_customer_id: form.zpa_customer_id || undefined,
      notes: form.notes || undefined,
    });
  }

  if (result) {
    return (
      <Modal title="Tenant Added" onClose={onClose}>
        <div className="space-y-3">
          {result.last_validation_error ? (
            <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-md text-sm text-yellow-800">
              <p className="font-medium mb-1">Tenant saved, but credential validation failed:</p>
              <p>{result.last_validation_error}</p>
            </div>
          ) : (
            <div className="p-3 bg-green-50 border border-green-200 rounded-md text-sm text-green-800">
              <p className="font-medium">Tenant added and credentials validated successfully.</p>
              {result.zia_tenant_id && <p className="mt-1">ZIA Tenant ID: <span className="font-mono">{result.zia_tenant_id}</span></p>}
              {result.zia_cloud && <p>Cloud: <span className="font-mono">{result.zia_cloud}</span></p>}
            </div>
          )}
          <div className="flex justify-end">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white">Done</button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Add Tenant" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Name" value={form.name} onChange={(v) => set("name", v)} required />
        <CheckboxField label="GovCloud" checked={form.govcloud ?? false} onChange={(v) => set("govcloud", v)} />
        {form.govcloud && (
          <GovTierField
            value={form.gov_cloud_tier ?? DEFAULT_GOV_TIER}
            onChange={(v) => set("gov_cloud_tier", v)}
          />
        )}
        <div>
          <Field
            label="Vanity Domain"
            value={form.vanity_domain}
            onChange={(v) => set("vanity_domain", v)}
            required
            placeholder="acme"
          />
          <p className="text-xs text-gray-400 mt-1 font-mono">{vanityHint}</p>
        </div>
        <Field label="Client ID" value={form.client_id} onChange={(v) => set("client_id", v)} required />
        <Field label="Client Secret" value={form.client_secret} onChange={(v) => set("client_secret", v)} type="password" required />
        <Field label="ZPA Customer ID" value={form.zpa_customer_id ?? ""} onChange={(v) => set("zpa_customer_id", v)} />
        <Field label="Notes" value={form.notes ?? ""} onChange={(v) => set("notes", v)} />
        {error && <p className="text-red-600 text-xs">{error}</p>}
        {mut.isPending && (
          <p className="text-xs text-gray-500">Saving and validating credentials...</p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">Cancel</button>
          <button type="submit" disabled={mut.isPending} className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60">
            {mut.isPending ? "Creating..." : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Edit Modal ───────────────────────────────────────────────────────────────

function EditModal({ tenant, onClose }: { tenant: Tenant; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<TenantUpdate & { client_secret: string }>({
    vanity_domain: tenant.vanity_domain,
    client_id: tenant.client_id,
    client_secret: "",
    govcloud: tenant.govcloud,
    gov_cloud_tier: tenant.gov_cloud_tier ?? DEFAULT_GOV_TIER,
    zpa_customer_id: tenant.zpa_customer_id ?? "",
    notes: tenant.notes ?? "",
  });
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: (body: TenantUpdate) => updateTenant(tenant.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function set(key: keyof typeof form, value: string | boolean) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  const vanityHint = zidentityHint(
    form.vanity_domain ?? "",
    form.govcloud,
    form.gov_cloud_tier ?? DEFAULT_GOV_TIER,
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const body: TenantUpdate = {
      vanity_domain: form.vanity_domain,
      client_id: form.client_id,
      govcloud: form.govcloud,
      gov_cloud_tier: form.govcloud ? (form.gov_cloud_tier ?? DEFAULT_GOV_TIER) : undefined,
      zpa_customer_id: form.zpa_customer_id || undefined,
      notes: form.notes || undefined,
    };
    if (form.client_secret) body.client_secret = form.client_secret;
    mut.mutate(body);
  }

  return (
    <Modal title={`Edit: ${tenant.name}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Name" value={tenant.name} onChange={() => {}} readOnly />
        <CheckboxField label="GovCloud" checked={form.govcloud ?? false} onChange={(v) => set("govcloud", v)} />
        {form.govcloud && (
          <GovTierField
            value={form.gov_cloud_tier ?? DEFAULT_GOV_TIER}
            onChange={(v) => set("gov_cloud_tier", v)}
          />
        )}
        <div>
          <Field label="Vanity Domain" value={form.vanity_domain ?? ""} onChange={(v) => set("vanity_domain", v)} placeholder="acme" />
          <p className="text-xs text-gray-400 mt-1 font-mono">{vanityHint}</p>
        </div>
        <Field label="Client ID" value={form.client_id ?? ""} onChange={(v) => set("client_id", v)} />
        <Field label="Client Secret (leave blank to keep existing)" value={form.client_secret} onChange={(v) => set("client_secret", v)} type="password" placeholder="(unchanged)" />
        <Field label="ZPA Customer ID" value={form.zpa_customer_id ?? ""} onChange={(v) => set("zpa_customer_id", v)} />
        <Field label="Notes" value={form.notes ?? ""} onChange={(v) => set("notes", v)} />
        {error && <p className="text-red-600 text-xs">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">Cancel</button>
          <button type="submit" disabled={mut.isPending} className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60">
            {mut.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Delete Modal ─────────────────────────────────────────────────────────────

function DeleteModal({ tenant, onClose }: { tenant: Tenant; onClose: () => void }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () => deleteTenant(tenant.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Modal title="Delete Tenant" onClose={onClose}>
      <p className="text-gray-700 text-sm mb-4">
        Are you sure you want to delete <strong>{tenant.name}</strong>? This action cannot be undone.
      </p>
      {error && <p className="text-red-600 text-xs mb-2">{error}</p>}
      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">Cancel</button>
        <button
          onClick={() => mut.mutate()}
          disabled={mut.isPending}
          className="px-4 py-2 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white disabled:opacity-60"
        >
          {mut.isPending ? "Deleting..." : "Delete"}
        </button>
      </div>
    </Modal>
  );
}

// ── Import Modal ─────────────────────────────────────────────────────────────

function ImportProductRow({
  label,
  description,
  tenantId,
  importFn,
  onDone,
}: {
  label: string;
  description: string;
  tenantId: number;
  importFn: (id: number) => Promise<{ job_id: string }>;
  onDone: () => void;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [mutErr, setMutErr] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () => importFn(tenantId),
    onSuccess: (data) => setJobId(data.job_id),
    onError: (e: Error) => setMutErr(e.message),
  });

  const { latestByPhase, jobStatus, result, streamError } = useJobStream<ImportResult>(jobId);
  const importEv = latestByPhase["import"];
  const isRunning = mut.isPending || jobStatus === "running";
  const isDone = jobStatus === "done";

  useEffect(() => { if (isDone) onDone(); }, [isDone, onDone]);

  const err = mutErr ?? streamError;

  return (
    <div className="p-3 border border-gray-200 rounded-lg space-y-1.5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-gray-900">{label}</p>
          <p className="text-xs text-gray-500">{description}</p>
        </div>
        <button
          onClick={() => mut.mutate()}
          disabled={isRunning || isDone}
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
        >
          {isRunning ? "Importing..." : isDone ? "Done" : `Import ${label.split(" ")[0]}`}
        </button>
      </div>

      {isRunning && (
        <>
          {importEv?.total ? (
            <div className="space-y-0.5">
              <p className="text-xs text-gray-500">
                {importEv.resource_type}… {importEv.done}/{importEv.total}
              </p>
              <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-zs-500 rounded-full transition-all duration-300"
                  style={{ width: `${Math.min(100, Math.round((importEv.done / importEv.total) * 100))}%` }}
                />
              </div>
            </div>
          ) : (
            <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
              <div className="h-full w-2/5 bg-zs-500 rounded-full animate-indeterminate" />
            </div>
          )}
          <p className="text-xs text-gray-400 italic">This may take several minutes.</p>
        </>
      )}

      {err && <p className="text-xs text-red-600">{err}</p>}
      {isDone && result && (
        <p className={`text-xs ${result.status === "SUCCESS" || result.status === "PARTIAL" ? "text-green-700" : "text-red-600"}`}>
          {result.status} — {result.resources_synced} synced, {result.resources_updated} updated
          {result.error_message && ` (${result.error_message})`}
        </p>
      )}
    </div>
  );
}

function ImportModal({ tenant, onClose }: { tenant: Tenant; onClose: () => void }) {
  const qc = useQueryClient();
  function invalidate() { qc.invalidateQueries({ queryKey: ["tenants"] }); }

  return (
    <Modal title={`Import: ${tenant.name}`} onClose={onClose}>
      <p className="text-sm text-gray-600 mb-4">
        Run initial data import for this tenant. This pulls configuration from Zscaler into the local database.
      </p>
      <div className="space-y-4">
        <ImportProductRow
          label="ZIA Import"
          description="Pulls URL categories, firewall rules, and other ZIA config"
          tenantId={tenant.id}
          importFn={importZIA}
          onDone={invalidate}
        />
        {/* ZPA on GovCloud is handled natively by the SDK (config.zpagov.net/.us). */}
        {tenant.zpa_customer_id && (
          <ImportProductRow
            label="ZPA Import"
            description="Pulls applications, segment groups, and other ZPA config"
            tenantId={tenant.id}
            importFn={importZPA}
            onDone={invalidate}
          />
        )}
        {/* The GovCloud OneAPI gateways do not route the /zcc service — every
            ZCC endpoint answers 500 with an empty body, so there is nothing
            to import. ZIA and ZPA are unaffected. */}
        {tenant.govcloud ? (
          <div className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
            <p className="text-sm font-medium text-gray-500">ZCC Import</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Not available on GovCloud — the FedRAMP OneAPI gateway does not serve the ZCC API.
            </p>
          </div>
        ) : (
          <ImportProductRow
            label="ZCC Import"
            description="Pulls app profiles, forwarding profiles, trusted networks, and other ZCC config"
            tenantId={tenant.id}
            importFn={importZCC}
            onDone={invalidate}
          />
        )}
      </div>
      <div className="flex justify-end mt-4">
        <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">Close</button>
      </div>
    </Modal>
  );
}

// ── Validation badge ─────────────────────────────────────────────────────────

function ValidationBadge({ tenant }: { tenant: Tenant }) {
  if (tenant.last_validation_error) {
    return (
      <span
        title={tenant.last_validation_error}
        className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 cursor-help"
      >
        Invalid
      </span>
    );
  }
  if (tenant.zia_tenant_id) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
        Valid
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
      Unverified
    </span>
  );
}

// ── Kebab menu ───────────────────────────────────────────────────────────────

type ModalState =
  | { type: "none" }
  | { type: "create" }
  | { type: "edit"; tenant: Tenant }
  | { type: "delete"; tenant: Tenant }
  | { type: "import"; tenant: Tenant };

function KebabMenu({
  tenant,
  onAction,
  isAdmin,
}: {
  tenant: Tenant;
  isAdmin: boolean;
  onAction: (action: "import" | "edit" | "delete", t: Tenant) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, right: 0 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function handleToggle(e: React.MouseEvent) {
    e.stopPropagation();
    if (!open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
    }
    setOpen((v) => !v);
  }

  return (
    <>
      <button
        ref={buttonRef}
        onClick={handleToggle}
        className="p-1 rounded hover:bg-gray-200 text-gray-500 hover:text-gray-700"
        title="Actions"
      >
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
          <path d="M10 3a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm0 5.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm0 5.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3z" />
        </svg>
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          style={{ position: "fixed", top: pos.top, right: pos.right, zIndex: 9999 }}
          className="w-36 bg-white border border-gray-200 rounded-md shadow-lg"
        >
          <button
            onClick={(e) => { e.stopPropagation(); setOpen(false); onAction("import", tenant); }}
            className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Import
          </button>
          {isAdmin && (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); setOpen(false); onAction("edit", tenant); }}
                className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                Edit
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setOpen(false); onAction("delete", tenant); }}
                className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
              >
                Delete
              </button>
            </>
          )}
        </div>,
        document.body
      )}
    </>
  );
}

// ── Card view ────────────────────────────────────────────────────────────────

function TenantCard({
  tenant,
  isAdmin,
  onAction,
}: {
  tenant: Tenant;
  isAdmin: boolean;
  onAction: (action: "import" | "edit" | "delete", t: Tenant) => void;
}) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/tenant/${tenant.id}/zia`)}
      className="relative bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md hover:border-zs-500 transition-all cursor-pointer"
    >
      <div className="absolute top-3 right-3" onClick={(e) => e.stopPropagation()}>
        <KebabMenu tenant={tenant} isAdmin={isAdmin} onAction={onAction} />
      </div>
      <div className="pr-6 space-y-2">
        <p className="font-semibold text-gray-900 text-sm">{tenant.name}</p>
        <div className="flex items-center gap-2 flex-wrap">
          <ValidationBadge tenant={tenant} />
          {tenant.zia_cloud && (
            <span className="font-mono text-xs text-gray-500">{tenant.zia_cloud}</span>
          )}
          {tenant.govcloud && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
              GovCloud
            </span>
          )}
        </div>
        {tenant.notes && (
          <p className="text-xs text-gray-400 line-clamp-2">
            {tenant.notes.length > 80 ? tenant.notes.slice(0, 80) + "…" : tenant.notes}
          </p>
        )}
      </div>
    </div>
  );
}

// ── View toggle icons ────────────────────────────────────────────────────────

function GridIcon({ active }: { active: boolean }) {
  return (
    <svg className={`h-4 w-4 ${active ? "text-zs-600" : "text-gray-400"}`} fill="currentColor" viewBox="0 0 20 20">
      <path d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
    </svg>
  );
}

function ListIcon({ active }: { active: boolean }) {
  return (
    <svg className={`h-4 w-4 ${active ? "text-zs-600" : "text-gray-400"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
    </svg>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function TenantsPage() {
  const { data: tenants, isLoading, error } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
  });
  const { isAdmin } = useAuth();

  const [modal, setModal] = useState<ModalState>({ type: "none" });
  const closeModal = () => setModal({ type: "none" });

  const [view, setView] = useState<"grid" | "list">(() => {
    const stored = localStorage.getItem("tenants_view");
    return stored === "list" ? "list" : "grid";
  });
  const [search, setSearch] = useState("");

  function changeView(v: "grid" | "list") {
    setView(v);
    localStorage.setItem("tenants_view", v);
  }

  function handleAction(action: "import" | "edit" | "delete", t: Tenant) {
    setModal({ type: action, tenant: t });
  }

  const filtered = (tenants ?? []).filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">Tenants</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => changeView("grid")}
            className={`p-1.5 rounded ${view === "grid" ? "bg-gray-100" : "hover:bg-gray-100"}`}
            title="Grid view"
          >
            <GridIcon active={view === "grid"} />
          </button>
          <button
            onClick={() => changeView("list")}
            className={`p-1.5 rounded ${view === "list" ? "bg-gray-100" : "hover:bg-gray-100"}`}
            title="List view"
          >
            <ListIcon active={view === "list"} />
          </button>
          {isAdmin && (
            <button
              onClick={() => setModal({ type: "create" })}
              className="ml-2 bg-zs-500 hover:bg-zs-600 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
            >
              Add Tenant
            </button>
          )}
        </div>
      </div>

      {/* Search bar */}
      <div className="mb-4">
        <input
          type="text"
          placeholder="Search tenants..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full sm:w-72 border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
      </div>

      {isLoading && <LoadingSpinner />}
      {error && (
        <ErrorMessage
          message={error instanceof Error ? error.message : "Failed to load tenants"}
        />
      )}

      {tenants && view === "grid" && (
        <>
          {filtered.length === 0 ? (
            <p className="text-sm text-gray-500 py-8 text-center">No tenants found.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {filtered.map((t) => (
                <TenantCard key={t.id} tenant={t} isAdmin={isAdmin} onAction={handleAction} />
              ))}
            </div>
          )}
        </>
      )}

      {tenants && view === "list" && (
        <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
          <table className="min-w-full divide-y divide-gray-300">
            <thead className="bg-gray-50">
              <tr>
                <th className="py-3 pl-4 pr-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Name</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">ZIA Cloud</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Gov Cloud</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Created</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-sm text-gray-500">
                    No tenants found.
                  </td>
                </tr>
              )}
              {filtered.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap py-3 pl-4 pr-3 text-sm font-medium text-gray-900">
                    <Link
                      to={`/tenant/${t.id}/zia`}
                      className="text-zs-600 hover:text-zs-700 hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {t.name}
                    </Link>
                    {t.notes && <p className="text-xs text-gray-400 font-normal">{t.notes}</p>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {t.zia_cloud ? (
                      <span className="font-mono text-xs">{t.zia_cloud}</span>
                    ) : "-"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    <ValidationBadge tenant={t} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">{t.govcloud ? (t.gov_cloud_tier ?? "yes") : "No"}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {formatDate(t.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    <KebabMenu tenant={t} isAdmin={isAdmin} onAction={handleAction} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal.type === "create" && <CreateModal onClose={closeModal} />}
      {modal.type === "edit" && <EditModal tenant={modal.tenant} onClose={closeModal} />}
      {modal.type === "delete" && <DeleteModal tenant={modal.tenant} onClose={closeModal} />}
      {modal.type === "import" && <ImportModal tenant={modal.tenant} onClose={closeModal} />}
    </div>
  );
}
