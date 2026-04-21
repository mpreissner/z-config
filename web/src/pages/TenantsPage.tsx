import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchTenants,
  createTenant,
  updateTenant,
  deleteTenant,
  importZIA,
  importZPA,
  Tenant,
  TenantCreate,
  TenantUpdate,
  ImportResult,
} from "../api/tenants";
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

// ── Create Modal ─────────────────────────────────────────────────────────────

function CreateModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<TenantCreate>({
    name: "",
    zidentity_base_url: "",
    client_id: "",
    client_secret: "",
    oneapi_base_url: "https://api.zsapi.net",
    govcloud: false,
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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    mut.mutate({
      ...form,
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
        <Field label="ZIdentity Base URL" value={form.zidentity_base_url} onChange={(v) => set("zidentity_base_url", v)} required placeholder="https://..." />
        <Field label="Client ID" value={form.client_id} onChange={(v) => set("client_id", v)} required />
        <Field label="Client Secret" value={form.client_secret} onChange={(v) => set("client_secret", v)} type="password" required />
        <Field label="OneAPI Base URL" value={form.oneapi_base_url ?? ""} onChange={(v) => set("oneapi_base_url", v)} placeholder="https://api.zsapi.net" />
        <CheckboxField label="GovCloud" checked={form.govcloud ?? false} onChange={(v) => set("govcloud", v)} />
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
    zidentity_base_url: tenant.zidentity_base_url,
    client_id: tenant.client_id,
    client_secret: "",
    oneapi_base_url: tenant.oneapi_base_url,
    govcloud: tenant.govcloud,
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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const body: TenantUpdate = {
      zidentity_base_url: form.zidentity_base_url,
      client_id: form.client_id,
      oneapi_base_url: form.oneapi_base_url,
      govcloud: form.govcloud,
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
        <Field label="ZIdentity Base URL" value={form.zidentity_base_url ?? ""} onChange={(v) => set("zidentity_base_url", v)} placeholder="https://..." />
        <Field label="Client ID" value={form.client_id ?? ""} onChange={(v) => set("client_id", v)} />
        <Field label="Client Secret (leave blank to keep existing)" value={form.client_secret} onChange={(v) => set("client_secret", v)} type="password" placeholder="(unchanged)" />
        <Field label="OneAPI Base URL" value={form.oneapi_base_url ?? ""} onChange={(v) => set("oneapi_base_url", v)} />
        <CheckboxField label="GovCloud" checked={form.govcloud ?? false} onChange={(v) => set("govcloud", v)} />
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

function ImportModal({ tenant, onClose }: { tenant: Tenant; onClose: () => void }) {
  const qc = useQueryClient();
  const [ziaResult, setZiaResult] = useState<ImportResult | null>(null);
  const [zpaResult, setZpaResult] = useState<ImportResult | null>(null);
  const [ziaError, setZiaError] = useState<string | null>(null);
  const [zpaError, setZpaError] = useState<string | null>(null);

  const ziaMut = useMutation({
    mutationFn: () => importZIA(tenant.id),
    onSuccess: (data) => { setZiaResult(data); qc.invalidateQueries({ queryKey: ["tenants"] }); },
    onError: (e: Error) => setZiaError(e.message),
  });

  const zpaMut = useMutation({
    mutationFn: () => importZPA(tenant.id),
    onSuccess: (data) => { setZpaResult(data); qc.invalidateQueries({ queryKey: ["tenants"] }); },
    onError: (e: Error) => setZpaError(e.message),
  });

  function ResultBadge({ result, error }: { result: ImportResult | null; error: string | null }) {
    if (error) return <p className="text-xs text-red-600 mt-1">{error}</p>;
    if (!result) return null;
    const ok = result.status === "SUCCESS" || result.status === "PARTIAL";
    return (
      <p className={`text-xs mt-1 ${ok ? "text-green-700" : "text-red-600"}`}>
        {result.status} — {result.resources_synced} synced, {result.resources_updated} updated
        {result.error_message && ` (${result.error_message})`}
      </p>
    );
  }

  return (
    <Modal title={`Import: ${tenant.name}`} onClose={onClose}>
      <p className="text-sm text-gray-600 mb-4">
        Run initial data import for this tenant. This pulls configuration from Zscaler into the local database.
      </p>
      <div className="space-y-4">
        <div className="p-3 border border-gray-200 rounded-lg">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-900">ZIA Import</p>
              <p className="text-xs text-gray-500">Pulls URL categories, firewall rules, and other ZIA config</p>
            </div>
            <button
              onClick={() => ziaMut.mutate()}
              disabled={ziaMut.isPending || !!ziaResult}
              className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
            >
              {ziaMut.isPending ? "Importing..." : ziaResult ? "Done" : "Import ZIA"}
            </button>
          </div>
          <ResultBadge result={ziaResult} error={ziaError} />
        </div>

        {tenant.zpa_customer_id && (
          <div className="p-3 border border-gray-200 rounded-lg">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-900">ZPA Import</p>
                <p className="text-xs text-gray-500">Pulls applications, segment groups, and other ZPA config</p>
              </div>
              <button
                onClick={() => zpaMut.mutate()}
                disabled={zpaMut.isPending || !!zpaResult}
                className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
              >
                {zpaMut.isPending ? "Importing..." : zpaResult ? "Done" : "Import ZPA"}
              </button>
            </div>
            <ResultBadge result={zpaResult} error={zpaError} />
          </div>
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

// ── Main page ────────────────────────────────────────────────────────────────

type ModalState =
  | { type: "none" }
  | { type: "create" }
  | { type: "edit"; tenant: Tenant }
  | { type: "delete"; tenant: Tenant }
  | { type: "import"; tenant: Tenant };

export default function TenantsPage() {
  const { data: tenants, isLoading, error } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
  });
  const { isAdmin } = useAuth();

  const [modal, setModal] = useState<ModalState>({ type: "none" });
  const closeModal = () => setModal({ type: "none" });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Tenants</h1>
        {isAdmin && (
          <button
            onClick={() => setModal({ type: "create" })}
            className="bg-zs-500 hover:bg-zs-600 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
          >
            Add Tenant
          </button>
        )}
      </div>

      {isLoading && <LoadingSpinner />}
      {error && (
        <ErrorMessage
          message={error instanceof Error ? error.message : "Failed to load tenants"}
        />
      )}
      {tenants && (
        <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
          <table className="min-w-full divide-y divide-gray-300">
            <thead className="bg-gray-50">
              <tr>
                <th className="py-3 pl-4 pr-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Name</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">ZIA Cloud</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Gov Cloud</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Created</th>
                {isAdmin && (
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {tenants.length === 0 && (
                <tr>
                  <td colSpan={isAdmin ? 6 : 5} className="py-8 text-center text-sm text-gray-500">
                    No tenants configured.
                  </td>
                </tr>
              )}
              {tenants.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap py-3 pl-4 pr-3 text-sm font-medium text-gray-900">
                    {t.name}
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
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">{t.govcloud ? "Yes" : "No"}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {t.created_at ? new Date(t.created_at).toLocaleDateString() : "-"}
                  </td>
                  {isAdmin && (
                    <td className="whitespace-nowrap px-3 py-3 text-sm">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => setModal({ type: "import", tenant: t })}
                          className="text-indigo-600 hover:text-indigo-700 font-medium text-xs"
                        >
                          Import
                        </button>
                        <button
                          onClick={() => setModal({ type: "edit", tenant: t })}
                          className="text-zs-500 hover:text-zs-600 font-medium text-xs"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => setModal({ type: "delete", tenant: t })}
                          className="text-red-600 hover:text-red-700 font-medium text-xs"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  )}
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
