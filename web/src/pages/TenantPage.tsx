import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchTenant, Tenant } from "../api/tenants";
import {
  fetchActivationStatus,
  activateTenant,
  fetchUrlCategories,
  lookupUrls,
  fetchUrlFilteringRules,
  fetchUsers,
  fetchLocations,
  fetchDepartments,
  fetchGroups,
  fetchAllowlist,
  fetchDenylist,
  UrlCategory,
  UrlFilteringRule,
  ZiaUser,
  ZiaLocation,
  ZiaDepartment,
  ZiaGroup,
} from "../api/zia";
import {
  fetchCertificates,
  fetchApplications,
  fetchPraPortals,
  ZpaCertificate,
  ZpaApplication,
  ZpaPraPortal,
} from "../api/zpa";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import Accordion from "../components/Accordion";
import { useAuth } from "../context/AuthContext";

// ── Shared helpers ────────────────────────────────────────────────────────────

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

// ── ZIA sections ──────────────────────────────────────────────────────────────

function ActivationSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const { isAdmin } = useAuth();

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-activation", tenantName],
    queryFn: () => fetchActivationStatus(tenantName),
    enabled: isOpen,
  });

  const activateMut = useMutation({
    mutationFn: () => activateTenant(tenantName),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] }),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const isActive = data.status === "ACTIVE";

  return (
    <div className="flex items-center gap-4">
      <span
        className={`inline-flex items-center px-2.5 py-1 rounded text-xs font-semibold ${
          isActive ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"
        }`}
      >
        {data.status}
      </span>
      {isAdmin && (
        <button
          onClick={() => activateMut.mutate()}
          disabled={activateMut.isPending}
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
        >
          {activateMut.isPending ? "Activating..." : "Activate Now"}
        </button>
      )}
      {activateMut.isError && (
        <span className="text-xs text-red-600">
          {activateMut.error instanceof Error ? activateMut.error.message : "Activation failed"}
        </span>
      )}
    </div>
  );
}

function UrlCategoriesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [filter, setFilter] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-url-categories", tenantName],
    queryFn: () => fetchUrlCategories(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((c: UrlCategory) =>
    c.name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="space-y-3">
      <input
        type="text"
        placeholder="Filter by name..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
      />
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((c: UrlCategory) => (
              <tr key={c.id}>
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{c.id}</td>
                <td className="px-3 py-2 text-gray-900">{c.name}</td>
                <td className="px-3 py-2 text-gray-500">{c.type}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No results</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UrlLookupSection({ tenantName }: { tenantName: string }) {
  const [input, setInput] = useState("");

  const mut = useMutation({
    mutationFn: () => {
      const urls = input.split("\n").map((u) => u.trim()).filter(Boolean);
      return lookupUrls(tenantName, urls);
    },
  });

  return (
    <div className="space-y-3">
      <textarea
        rows={4}
        placeholder="Paste URLs, one per line..."
        value={input}
        onChange={(e) => setInput(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
      />
      <button
        onClick={() => mut.mutate()}
        disabled={mut.isPending || !input.trim()}
        className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
      >
        {mut.isPending ? "Looking up..." : "Lookup"}
      </button>
      {mut.isPending && <LoadingSpinner />}
      {mut.isError && (
        <ErrorMessage message={mut.error instanceof Error ? mut.error.message : "Lookup failed"} />
      )}
      {mut.data && (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">URL</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Classifications</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Security Alerts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {mut.data.map((r, i) => (
                <tr key={i}>
                  <td className="px-3 py-2 font-mono text-xs text-gray-700">{r.url}</td>
                  <td className="px-3 py-2 text-gray-600">{r.urlClassifications?.join(", ") || "-"}</td>
                  <td className="px-3 py-2 text-gray-600">{r.urlClassificationsWithSecurityAlert?.join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function UrlFilteringRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-url-filtering-rules", tenantName],
    queryFn: () => fetchUrlFilteringRules(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Order</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">State</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {data.map((r: UrlFilteringRule) => (
            <tr key={r.id}>
              <td className="px-3 py-2 text-gray-500">{r.order}</td>
              <td className="px-3 py-2 text-gray-900">{r.name}</td>
              <td className="px-3 py-2 text-gray-600">{r.action}</td>
              <td className="px-3 py-2 text-gray-600">{r.state}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No rules</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function UsersSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [filter, setFilter] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-users", tenantName],
    queryFn: () => fetchUsers(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const q = filter.toLowerCase();
  const filtered = data.filter((u: ZiaUser) =>
    u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
  );

  return (
    <div className="space-y-3">
      <input
        type="text"
        placeholder="Filter by name or email..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
      />
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Department</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((u: ZiaUser) => (
              <tr key={u.id}>
                <td className="px-3 py-2 text-gray-900">{u.name}</td>
                <td className="px-3 py-2 text-gray-600 font-mono text-xs">{u.email}</td>
                <td className="px-3 py-2 text-gray-500">{u.department?.name ?? "-"}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No results</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LocationsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-locations", tenantName],
    queryFn: () => fetchLocations(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Country</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">IP Addresses</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {data.map((loc: ZiaLocation) => {
            const ips = loc.ipAddresses ?? [];
            const shown = ips.slice(0, 3).join(", ");
            const extra = ips.length > 3 ? ` +${ips.length - 3} more` : "";
            return (
              <tr key={loc.id}>
                <td className="px-3 py-2 text-gray-900">{loc.name}</td>
                <td className="px-3 py-2 text-gray-500">{loc.country ?? "-"}</td>
                <td className="px-3 py-2 text-gray-500 font-mono text-xs">{ips.length ? shown + extra : "-"}</td>
              </tr>
            );
          })}
          {data.length === 0 && (
            <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No locations</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function DepartmentsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-departments", tenantName],
    queryFn: () => fetchDepartments(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {data.map((d: ZiaDepartment) => (
            <tr key={d.id}>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{d.id}</td>
              <td className="px-3 py-2 text-gray-900">{d.name}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No departments</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function GroupsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-groups", tenantName],
    queryFn: () => fetchGroups(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {data.map((g: ZiaGroup) => (
            <tr key={g.id}>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{g.id}</td>
              <td className="px-3 py-2 text-gray-900">{g.name}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No groups</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function AllowDenySection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const allowQuery = useQuery({
    queryKey: ["zia-allowlist", tenantName],
    queryFn: () => fetchAllowlist(tenantName),
    enabled: isOpen,
  });
  const denyQuery = useQuery({
    queryKey: ["zia-denylist", tenantName],
    queryFn: () => fetchDenylist(tenantName),
    enabled: isOpen,
  });

  if (allowQuery.isLoading || denyQuery.isLoading) return <LoadingSpinner />;

  return (
    <div className="flex flex-col sm:flex-row gap-6">
      <div className="flex-1">
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Allowlist</h4>
        {allowQuery.error ? (
          <ErrorMessage message={allowQuery.error instanceof Error ? allowQuery.error.message : "Failed to load"} />
        ) : (
          <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-md p-2">
            {(allowQuery.data?.whitelistUrls ?? []).length === 0 ? (
              <p className="text-xs text-gray-400 p-1">No entries</p>
            ) : (
              (allowQuery.data?.whitelistUrls ?? []).map((url, i) => (
                <p key={i} className="text-xs font-mono text-gray-700 py-0.5">{url}</p>
              ))
            )}
          </div>
        )}
      </div>
      <div className="flex-1">
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Denylist</h4>
        {denyQuery.error ? (
          <ErrorMessage message={denyQuery.error instanceof Error ? denyQuery.error.message : "Failed to load"} />
        ) : (
          <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-md p-2">
            {(denyQuery.data?.blacklistUrls ?? []).length === 0 ? (
              <p className="text-xs text-gray-400 p-1">No entries</p>
            ) : (
              (denyQuery.data?.blacklistUrls ?? []).map((url, i) => (
                <p key={i} className="text-xs font-mono text-gray-700 py-0.5">{url}</p>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── ZPA sections ──────────────────────────────────────────────────────────────

function CertificatesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-certificates", tenantName],
    queryFn: () => fetchCertificates(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const now = Math.floor(Date.now() / 1000);

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Issued To</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Expires</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.map((c: ZpaCertificate) => {
              const expEpoch = c.expireTime ? parseInt(c.expireTime, 10) : null;
              const expired = expEpoch !== null && expEpoch < now;
              return (
                <tr key={c.id}>
                  <td className="px-3 py-2 text-gray-900">{c.name}</td>
                  <td className="px-3 py-2 text-gray-600">{c.issuedTo ?? "-"}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs">
                    {expEpoch ? new Date(expEpoch * 1000).toLocaleDateString() : "-"}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${expired ? "bg-red-100 text-red-800" : "bg-green-100 text-green-800"}`}>
                      {expired ? "Expired" : "Valid"}
                    </span>
                  </td>
                </tr>
              );
            })}
            {data.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No certificates</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-400">
        Certificate rotation is only available via the CLI (<span className="font-mono">zs-config</span>).
      </p>
    </div>
  );
}

function ApplicationsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [filter, setFilter] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-applications", tenantName],
    queryFn: () => fetchApplications(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((a: ZpaApplication) =>
    a.name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="space-y-3">
      <input
        type="text"
        placeholder="Filter by name..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
      />
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Domains</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((a: ZpaApplication) => {
              const domains = a.domainNames ?? [];
              const shown = domains.slice(0, 3).join(", ");
              const extra = domains.length > 3 ? ` +${domains.length - 3} more` : "";
              return (
                <tr key={a.id}>
                  <td className="px-3 py-2 text-gray-900">{a.name}</td>
                  <td className="px-3 py-2 text-gray-500">{a.applicationType ?? "-"}</td>
                  <td className="px-3 py-2 text-gray-500 font-mono text-xs">{domains.length ? shown + extra : "-"}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${a.enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-500"}`}>
                      {a.enabled ? "Yes" : "No"}
                    </span>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No results</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PraPortalsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-pra-portals", tenantName],
    queryFn: () => fetchPraPortals(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Certificate</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {data.map((p: ZpaPraPortal) => (
            <tr key={p.id}>
              <td className="px-3 py-2 text-gray-900">{p.name}</td>
              <td className="px-3 py-2 text-gray-500 font-mono text-xs">{p.domain ?? "-"}</td>
              <td className="px-3 py-2 text-gray-500">{p.certificateName ?? "-"}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No PRA portals</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Tab panels ────────────────────────────────────────────────────────────────

function ZiaTab({ tenant }: { tenant: Tenant }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ activation: true });

  function toggle(key: string) {
    setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="space-y-3">
      <Accordion title="Activation" isOpen={!!open.activation} onToggle={() => toggle("activation")}>
        <ActivationSection tenantName={tenant.name} isOpen={!!open.activation} />
      </Accordion>
      <Accordion title="URL Categories" isOpen={!!open.urlCategories} onToggle={() => toggle("urlCategories")}>
        <UrlCategoriesSection tenantName={tenant.name} isOpen={!!open.urlCategories} />
      </Accordion>
      <Accordion title="URL Lookup" isOpen={!!open.urlLookup} onToggle={() => toggle("urlLookup")}>
        <UrlLookupSection tenantName={tenant.name} />
      </Accordion>
      <Accordion title="URL Filtering Rules" isOpen={!!open.urlFilteringRules} onToggle={() => toggle("urlFilteringRules")}>
        <UrlFilteringRulesSection tenantName={tenant.name} isOpen={!!open.urlFilteringRules} />
      </Accordion>
      <Accordion title="Users" isOpen={!!open.users} onToggle={() => toggle("users")}>
        <UsersSection tenantName={tenant.name} isOpen={!!open.users} />
      </Accordion>
      <Accordion title="Locations" isOpen={!!open.locations} onToggle={() => toggle("locations")}>
        <LocationsSection tenantName={tenant.name} isOpen={!!open.locations} />
      </Accordion>
      <Accordion title="Departments" isOpen={!!open.departments} onToggle={() => toggle("departments")}>
        <DepartmentsSection tenantName={tenant.name} isOpen={!!open.departments} />
      </Accordion>
      <Accordion title="Groups" isOpen={!!open.groups} onToggle={() => toggle("groups")}>
        <GroupsSection tenantName={tenant.name} isOpen={!!open.groups} />
      </Accordion>
      <Accordion title="Allow / Deny Lists" isOpen={!!open.allowdeny} onToggle={() => toggle("allowdeny")}>
        <AllowDenySection tenantName={tenant.name} isOpen={!!open.allowdeny} />
      </Accordion>
    </div>
  );
}

function ZpaTab({ tenant }: { tenant: Tenant }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  function toggle(key: string) {
    setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="space-y-3">
      <Accordion title="Certificates" isOpen={!!open.certificates} onToggle={() => toggle("certificates")}>
        <CertificatesSection tenantName={tenant.name} isOpen={!!open.certificates} />
      </Accordion>
      <Accordion title="Applications (Browser Access)" isOpen={!!open.applications} onToggle={() => toggle("applications")}>
        <ApplicationsSection tenantName={tenant.name} isOpen={!!open.applications} />
      </Accordion>
      <Accordion title="PRA Portals" isOpen={!!open.praPortals} onToggle={() => toggle("praPortals")}>
        <PraPortalsSection tenantName={tenant.name} isOpen={!!open.praPortals} />
      </Accordion>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TenantPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<"zia" | "zpa">("zia");

  const { data: tenant, isLoading, error } = useQuery({
    queryKey: ["tenant", Number(id)],
    queryFn: () => fetchTenant(Number(id)),
    enabled: !!id,
    retry: (failureCount, err: unknown) => {
      if (err instanceof Error && "status" in err && (err as { status: number }).status === 404) return false;
      return failureCount < 2;
    },
  });

  if (isLoading) return <LoadingSpinner />;

  if (error) {
    const is404 = error instanceof Error && "status" in error && (error as { status: number }).status === 404;
    if (is404) {
      return (
        <div className="py-16 text-center space-y-3">
          <p className="text-gray-500">Tenant not found.</p>
          <Link to="/tenants" className="text-zs-500 hover:text-zs-600 text-sm">
            Back to Tenants
          </Link>
        </div>
      );
    }
    return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load tenant"} />;
  }

  if (!tenant) return null;

  const hasZpa = !!tenant.zpa_customer_id;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link
          to="/tenants"
          className="flex items-center gap-1 text-gray-400 hover:text-gray-600 text-sm"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Tenants
        </Link>
        <span className="text-gray-300">/</span>
        <h1 className="text-xl font-semibold text-gray-900">{tenant.name}</h1>
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

      {/* Tab bar */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          <button
            onClick={() => setActiveTab("zia")}
            className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "zia"
                ? "border-zs-500 text-zs-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            ZIA
          </button>
          {hasZpa && (
            <button
              onClick={() => setActiveTab("zpa")}
              className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "zpa"
                  ? "border-zs-500 text-zs-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              ZPA
            </button>
          )}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === "zia" && <ZiaTab tenant={tenant} />}
      {activeTab === "zpa" && hasZpa && <ZpaTab tenant={tenant} />}
    </div>
  );
}
