import { useState, useEffect, ReactNode } from "react";
import { formatDateTime, formatDate } from "../utils/time";
import { Link, useParams, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchTenant,
  fetchTenants,
  importZIA,
  importZPA,
  previewApplySnapshot,
  applySnapshot,
  Tenant,
  ImportResult,
  SnapshotPreview,
  ApplySnapshotResult,
} from "../api/tenants";
import { useJobStream } from "../hooks/useJobStream";
import {
  fetchActivationStatus,
  activateTenant,
  fetchUrlCategories,
  fetchUrlCategoryDetail,
  addUrlsToCategory,
  removeUrlsFromCategory,
  lookupUrls,
  fetchUrlFilteringRules,
  patchUrlFilteringRuleState,
  fetchUsers,
  fetchLocations,
  fetchDepartments,
  fetchGroups,
  fetchAllowlist,
  fetchDenylist,
  updateAllowlist,
  updateDenylist,
  fetchFirewallRules,
  patchFirewallRuleState,
  exportFirewallRulesToCsv,
  syncFirewallRulesFromCsv,
  fetchSslInspectionRules,
  patchSslRuleState,
  fetchForwardingRules,
  patchForwardingRuleState,
  fetchFirewallDnsRules,
  patchFirewallDnsRuleState,
  fetchFirewallIpsRules,
  patchFirewallIpsRuleState,
  fetchDlpEngines,
  updateDlpEngine,
  deleteDlpEngine,
  fetchDlpDictionaries,
  patchDlpDictionaryConfidence,
  fetchDlpWebRules,
  patchDlpWebRuleState,
  fetchCloudAppSettings,
  fetchCloudAppInstances,
  fetchCloudAppControlRules,
  patchCloudAppRuleState,
  fetchTenancyRestrictionProfiles,
  fetchSnapshots,
  createSnapshot,
  deleteSnapshot,
  UrlCategory,
  UrlCategoryDetail,
  UrlFilteringRule,
  ZiaUser,
  ZiaLocation,
  ZiaDepartment,
  ZiaGroup,
  FirewallRule,
  SslInspectionRule,
  ForwardingRule,
  FirewallDnsRule,
  FirewallIpsRule,
  DlpEngine,
  DlpDictionary,
  DlpWebRule,
  CloudAppInstance,
  CloudAppControlRule,
  TenancyRestrictionProfile,
  ConfigSnapshot,
} from "../api/zia";
import {
  fetchCertificates,
  fetchApplications,
  fetchPraPortals,
  listAppConnectors,
  listServiceEdges,
  listSegmentGroups,
  ZpaCertificate,
  ZpaApplication,
  ZpaPraPortal,
  ZpaAppConnector,
  ZpaServiceEdge,
  ZpaSegmentGroup,
} from "../api/zpa";
import {
  listDevices as listZccDevices,
  listTrustedNetworks,
  listForwardingProfiles,
  listWebPolicies,
  listWebAppServices,
  getDeviceOtp,
  ZccDevice,
  ZccTrustedNetwork,
  ZccForwardingProfile,
  ZccWebPolicy,
  ZccWebAppService,
} from "../api/zcc";
import {
  searchDevices as searchZdxDevices,
  lookupUsers as lookupZdxUsers,
  ZdxDevice,
  ZdxUser,
} from "../api/zdx";
import {
  listUsers as listZidUsers,
  listGroups as listZidGroups,
  getGroupMembers,
  listApiClients,
  getApiClientSecrets,
  resetUserPassword,
  ZidUser,
  ZidGroup,
  ZidApiClient,
  ZidApiClientSecret,
} from "../api/zid";
import { cancelJob } from "../api/jobs";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import Accordion from "../components/Accordion";
import CopyButton from "../components/CopyButton";
import ConfirmDialog from "../components/ConfirmDialog";
import { useActiveTenant } from "../context/ActiveTenantContext";

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

function ActivationSection({ tenantName }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-activation", tenantName],
    queryFn: () => fetchActivationStatus(tenantName),
    staleTime: 60_000,
    refetchInterval: 60_000,
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
      <button
        onClick={() => activateMut.mutate()}
        disabled={activateMut.isPending}
        className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
      >
        {activateMut.isPending ? "Activating..." : "Activate Now"}
      </button>
      {activateMut.isError && (
        <span className="text-xs text-red-600">
          {activateMut.error instanceof Error ? activateMut.error.message : "Activation failed"}
        </span>
      )}
    </div>
  );
}

function UrlCategoryRow({
  tenantName,
  category,
}: {
  tenantName: string;
  category: UrlCategory;
}) {
  const [expanded, setExpanded] = useState(false);
  const [addInput, setAddInput] = useState("");
  const qc = useQueryClient();
  const isCustom = category.type === "URL_CATEGORY" && !!category.configuredName;

  const detailQuery = useQuery({
    queryKey: ["zia-url-category-detail", tenantName, category.id],
    queryFn: () => fetchUrlCategoryDetail(tenantName, category.id),
    enabled: expanded && isCustom,
    staleTime: 60 * 1000,
  });

  const addMut = useMutation({
    mutationFn: (urls: string[]) => addUrlsToCategory(tenantName, category.id, urls),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-url-category-detail", tenantName, category.id] });
      setAddInput("");
    },
  });

  const removeMut = useMutation({
    mutationFn: (urls: string[]) => removeUrlsFromCategory(tenantName, category.id, urls),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-url-category-detail", tenantName, category.id] });
    },
  });

  function handleAdd() {
    const urls = addInput.split("\n").map((u) => u.trim()).filter(Boolean);
    if (urls.length) addMut.mutate(urls);
  }

  const detail: UrlCategoryDetail | undefined = detailQuery.data;
  const currentUrls: string[] = detail?.urls ?? [];

  return (
    <>
      <tr
        className={`${isCustom ? "cursor-pointer hover:bg-gray-50" : ""}`}
        onClick={() => isCustom && setExpanded((x) => !x)}
      >
        <td className="px-3 py-2 font-mono text-xs text-gray-500">{category.id}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          {isCustom && (
            <svg
              className={`w-3 h-3 text-gray-400 flex-shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          )}
          {category.name || category.configuredName || category.id}
        </td>
        <td className="px-3 py-2 text-gray-500">{isCustom ? "Custom" : category.type}</td>
      </tr>
      {expanded && isCustom && (
        <tr>
          <td colSpan={3} className="bg-gray-50 px-4 py-3">
            {detailQuery.isLoading && <LoadingSpinner />}
            {detailQuery.error && (
              <ErrorMessage message={detailQuery.error instanceof Error ? detailQuery.error.message : "Failed to load"} />
            )}
            {detail && (
              <div className="space-y-3">
                <div className="text-xs text-gray-500 font-medium uppercase tracking-wide">
                  URLs ({currentUrls.length})
                </div>
                {currentUrls.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {currentUrls.map((url) => (
                      <span
                        key={url}
                        className="inline-flex items-center gap-1 bg-white border border-gray-200 rounded px-2 py-0.5 text-xs font-mono text-gray-700"
                      >
                        {url}
                        <button
                          onClick={() => removeMut.mutate([url])}
                          disabled={removeMut.isPending}
                          className="text-gray-400 hover:text-red-500 disabled:opacity-40 ml-0.5"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-gray-400">No URLs in this category.</p>
                )}
                <div className="flex gap-2 pt-1">
                  <textarea
                    rows={2}
                    placeholder="Add URLs, one per line..."
                    value={addInput}
                    onChange={(e) => setAddInput(e.target.value)}
                    className="flex-1 border border-gray-300 rounded-md px-2 py-1 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                  />
                  <button
                    onClick={handleAdd}
                    disabled={addMut.isPending || !addInput.trim()}
                    className="self-end px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
                  >
                    {addMut.isPending ? "Adding…" : "Add"}
                  </button>
                </div>
                {(addMut.isError || removeMut.isError) && (
                  <ErrorMessage
                    message={
                      (addMut.error instanceof Error ? addMut.error.message : null) ??
                      (removeMut.error instanceof Error ? removeMut.error.message : "Operation failed")
                    }
                  />
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function UrlCategoriesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [filter, setFilter] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-url-categories", tenantName],
    queryFn: () => fetchUrlCategories(tenantName),
    enabled: isOpen,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const q = filter.toLowerCase();
  const filtered = data.filter((c: UrlCategory) => {
    const displayName = (c.name || c.configuredName || c.id).toLowerCase();
    return displayName.includes(q);
  });

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
              <UrlCategoryRow
                key={c.id}
                tenantName={tenantName}
                category={c}
              />
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

function StateToggle({
  ruleId,
  state,
  onToggle,
  pending,
}: {
  ruleId: number | string;
  state: string;
  onToggle: (id: number | string, next: string) => void;
  pending: boolean;
}) {
  const enabled = state === "ENABLED";
  return (
    <button
      onClick={() => onToggle(ruleId, enabled ? "DISABLED" : "ENABLED")}
      disabled={pending}
      title={enabled ? "Disable" : "Enable"}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        enabled ? "bg-green-500" : "bg-gray-300"
      } disabled:opacity-60`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
          enabled ? "translate-x-4" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function UrlFilteringRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: UrlFilteringRule;
  onToggle: (id: number | string, next: string) => void;
  togglePending: boolean;
}) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-3 py-2 text-gray-500">{rule.order}</td>
      <td className="px-3 py-2 text-gray-900">{rule.name}</td>
      <td className="px-3 py-2 text-gray-600">{rule.action}</td>
      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
        <StateToggle
          ruleId={rule.id}
          state={rule.state}
          onToggle={onToggle}
          pending={togglePending}
        />
      </td>
    </tr>
  );
}

function UrlFilteringRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-url-filtering-rules", tenantName],
    queryFn: () => fetchUrlFilteringRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchUrlFilteringRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-url-filtering-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
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
            <UrlFilteringRuleRow
              key={r.id}
              rule={r}
              onToggle={(id, next) => toggleMut.mutate({ id: id as number, state: next })}
              togglePending={toggleMut.isPending}
            />
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

function EditableUrlList({
  title,
  urls,
  onSave,
  saving,
}: {
  title: string;
  urls: string[];
  onSave: (urls: string[]) => void;
  saving: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  function startEdit() {
    setDraft(urls.join("\n"));
    setEditing(true);
  }
  function handleSave() {
    const parsed = draft.split("\n").map((u) => u.trim()).filter(Boolean);
    onSave(parsed);
    setEditing(false);
  }

  return (
    <div className="flex-1">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-gray-700">{title} ({urls.length})</h4>
        {!editing && (
          <button onClick={startEdit} className="text-xs text-zs-500 hover:underline">Edit</button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            rows={8}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
            placeholder="One URL per line"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
            >
              {saving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 text-xs rounded-md border border-gray-300 text-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-md p-2">
          {urls.length === 0 ? (
            <p className="text-xs text-gray-400 p-1">No entries</p>
          ) : (
            urls.map((url, i) => (
              <p key={i} className="text-xs font-mono text-gray-700 py-0.5">{url}</p>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function AllowDenySection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();

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

  const allowMut = useMutation({
    mutationFn: (urls: string[]) => updateAllowlist(tenantName, urls),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zia-allowlist", tenantName] }),
  });
  const denyMut = useMutation({
    mutationFn: (urls: string[]) => updateDenylist(tenantName, urls),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zia-denylist", tenantName] }),
  });

  if (allowQuery.isLoading || denyQuery.isLoading) return <LoadingSpinner />;

  return (
    <div className="flex flex-col sm:flex-row gap-6">
      {allowQuery.error ? (
        <ErrorMessage message={allowQuery.error instanceof Error ? allowQuery.error.message : "Failed to load"} />
      ) : (
        <EditableUrlList
          title="Allowlist"
          urls={allowQuery.data?.whitelistUrls ?? []}
          onSave={(urls) => allowMut.mutate(urls)}
          saving={allowMut.isPending}
        />
      )}
      {denyQuery.error ? (
        <ErrorMessage message={denyQuery.error instanceof Error ? denyQuery.error.message : "Failed to load"} />
      ) : (
        <EditableUrlList
          title="Denylist"
          urls={denyQuery.data?.blacklistUrls ?? []}
          onSave={(urls) => denyMut.mutate(urls)}
          saving={denyMut.isPending}
        />
      )}
    </div>
  );
}

// ── Firewall / SSL / Forwarding / DLP / Cloud App / Snapshots ────────────────

// Shared helper: render a detail grid from a rule's extra fields
const CHEVRON = (
  <svg className="w-3 h-3 text-gray-400 flex-shrink-0 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
  </svg>
);

function RuleDetailGrid({ rule, skipKeys }: { rule: Record<string, unknown>; skipKeys: Set<string> }) {
  const fields = Object.entries(rule).filter(([k, v]) => {
    if (skipKeys.has(k)) return false;
    if (v === null || v === undefined) return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  });
  if (fields.length === 0) return <p className="text-xs text-gray-400">No additional details.</p>;
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
      <div className="font-medium text-gray-500 uppercase tracking-wide col-span-2 mb-1">Rule Details</div>
      {fields.map(([key, value]) => (
        <div key={key} className="contents">
          <div className="text-gray-500 capitalize">{key.replace(/([A-Z])/g, " $1").replace(/_/g, " ").trim()}</div>
          <div className="text-gray-800 break-all">
            {Array.isArray(value)
              ? (value as unknown[]).map((v, i) => (
                  <span key={i} className="inline-block bg-gray-100 rounded px-1 py-0.5 mr-1 mb-0.5 font-mono">
                    {typeof v === "object" ? (String((v as Record<string, unknown>).name ?? "") || JSON.stringify(v)) : String(v)}
                  </span>
                ))
              : typeof value === "object"
              ? JSON.stringify(value)
              : String(value)}
          </div>
        </div>
      ))}
    </div>
  );
}

const DLP_ENGINE_SKIP = new Set(["id", "name", "predefinedEngine"]);
const DLP_WEB_RULE_SKIP = new Set(["id", "name", "order", "action", "state"]);
const SSL_SKIP = new Set(["id", "name", "order", "action", "state"]);
const FORWARDING_SKIP = new Set(["id", "name", "order", "type", "state"]);
const FIREWALL_SKIP = new Set(["id", "name", "order", "action", "state"]);
const DNS_RULE_SKIP = new Set(["id", "name", "order", "action", "state"]);
const IPS_RULE_SKIP = new Set(["id", "name", "order", "action", "state"]);

function resolveEngineExpression(expr: string, dictMap: Map<number, string>): string {
  return expr.replace(/D(\d+)/g, (_match, id) => {
    const name = dictMap.get(parseInt(id));
    return name ? `"${name}"` : `D${id}`;
  });
}

function DlpEngineRow({
  tenantName,
  engine,
  dictMap,
  onDeleted,
}: {
  tenantName: string;
  engine: DlpEngine;
  dictMap: Map<number, string>;
  onDeleted?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(engine.name);
  const [editExpr, setEditExpr] = useState(engine.engine_expression ?? "");
  const [editDesc, setEditDesc] = useState(engine.description ?? "");
  const [editCustom, setEditCustom] = useState(engine.custom_dlp_engine ?? false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const qc = useQueryClient();
  const isPredefined = engine.predefinedEngine === true;

  const resolvedEngine = { ...engine } as Record<string, unknown>;
  if (engine.engine_expression && dictMap.size > 0) {
    resolvedEngine.engine_expression = resolveEngineExpression(engine.engine_expression, dictMap);
  }

  const updateMut = useMutation({
    mutationFn: () => updateDlpEngine(tenantName, engine.id, {
      id: engine.id,
      name: editName,
      engine_expression: editExpr || undefined,
      description: editDesc || undefined,
      custom_dlp_engine: editCustom,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-dlp-engines", tenantName] });
      setEditing(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteDlpEngine(tenantName, engine.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-dlp-engines", tenantName] });
      onDeleted?.();
    },
  });

  return (
    <>
      {confirmDelete && (
        <ConfirmDialog
          title="Delete DLP Engine"
          message={`Delete DLP engine "${engine.name}"? This cannot be undone.`}
          onConfirm={() => { setConfirmDelete(false); deleteMut.mutate(); }}
          onCancel={() => setConfirmDelete(false)}
          destructive
        />
      )}
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 font-mono text-xs text-gray-500">{engine.id}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {engine.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-500">{engine.predefinedEngine ?? engine.custom_dlp_engine !== undefined ? (engine.custom_dlp_engine ? "Custom" : "Built-in") : "-"}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={3} className="bg-gray-50 px-4 py-3">
            {!editing ? (
              <div className="space-y-3">
                <RuleDetailGrid rule={resolvedEngine} skipKeys={DLP_ENGINE_SKIP} />
                {!isPredefined && (
                  <div className="flex gap-3 pt-1">
                    <button onClick={() => { setEditName(engine.name); setEditExpr(engine.engine_expression ?? ""); setEditDesc(engine.description ?? ""); setEditCustom(engine.custom_dlp_engine ?? false); setEditing(true); }}
                      className="text-xs text-zs-500 hover:underline">Edit</button>
                    <button onClick={() => setConfirmDelete(true)} className="text-xs text-red-500 hover:underline">Delete</button>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3 border border-gray-200 rounded-md p-3 bg-white">
                <h4 className="text-sm font-semibold text-gray-700">Edit DLP Engine</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
                    <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)}
                      className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
                    <input type="text" value={editDesc} onChange={(e) => setEditDesc(e.target.value)}
                      className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500" />
                  </div>
                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Engine Expression</label>
                    <input type="text" value={editExpr} onChange={(e) => setEditExpr(e.target.value)}
                      className="w-full border border-gray-300 rounded px-2 py-1 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                      placeholder="e.g. (D1 AND D2)" />
                  </div>
                  <div className="flex items-center gap-2">
                    <input type="checkbox" id="editCustom" checked={editCustom} onChange={(e) => setEditCustom(e.target.checked)}
                      className="rounded border-gray-300" />
                    <label htmlFor="editCustom" className="text-xs text-gray-600">Custom Engine</label>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => updateMut.mutate()} disabled={updateMut.isPending || !editName.trim()}
                    className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60">
                    {updateMut.isPending ? "Saving..." : "Save"}
                  </button>
                  <button onClick={() => setEditing(false)}
                    className="px-3 py-1.5 text-xs rounded-md border border-gray-300 text-gray-600">Cancel</button>
                </div>
                {updateMut.isError && <ErrorMessage message={updateMut.error instanceof Error ? updateMut.error.message : "Save failed"} />}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function DlpWebRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: DlpWebRule;
  onToggle: (id: number, next: string) => void;
  togglePending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPredefined = rule.predefined === true;

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{rule.order}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {rule.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-600">{rule.action}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <StateToggle ruleId={rule.id} state={rule.state} onToggle={(id, next) => onToggle(id as number, next)} pending={togglePending} />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid rule={rule as unknown as Record<string, unknown>} skipKeys={DLP_WEB_RULE_SKIP} />
          </td>
        </tr>
      )}
    </>
  );
}

function FirewallRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: FirewallRule;
  onToggle: (id: number, next: string) => void;
  togglePending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPredefined = rule.predefined === true;
  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{rule.order}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {rule.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-600">{rule.action}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <StateToggle ruleId={rule.id} state={rule.state} onToggle={(id, next) => onToggle(id as number, next)} pending={togglePending} />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid rule={rule as unknown as Record<string, unknown>} skipKeys={FIREWALL_SKIP} />
          </td>
        </tr>
      )}
    </>
  );
}

function SslRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: SslInspectionRule;
  onToggle: (id: number, next: string) => void;
  togglePending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPredefined = rule.predefined === true;

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{rule.order}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {rule.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-600">{rule.action ?? "-"}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <StateToggle ruleId={rule.id} state={rule.state} onToggle={(id, next) => onToggle(id as number, next)} pending={togglePending} />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid rule={rule as unknown as Record<string, unknown>} skipKeys={SSL_SKIP} />
          </td>
        </tr>
      )}
    </>
  );
}

function ForwardingRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: ForwardingRule;
  onToggle: (id: number, next: string) => void;
  togglePending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPredefined = rule.predefined === true;

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{rule.order}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {rule.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-500">{rule.type ?? "-"}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <StateToggle ruleId={rule.id} state={rule.state} onToggle={(id, next) => onToggle(id as number, next)} pending={togglePending} />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid rule={rule as unknown as Record<string, unknown>} skipKeys={FORWARDING_SKIP} />
          </td>
        </tr>
      )}
    </>
  );
}

function FirewallDnsRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: FirewallDnsRule;
  onToggle: (id: number, next: string) => void;
  togglePending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPredefined = rule.predefined === true;
  const actionLabel = typeof rule.action === "object" && rule.action !== null
    ? (rule.action as { type: string }).type
    : (rule.action ?? "-");

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{rule.order}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {rule.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-600">{actionLabel}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <StateToggle ruleId={rule.id} state={rule.state} onToggle={(id, next) => onToggle(id as number, next)} pending={togglePending} />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid rule={rule as unknown as Record<string, unknown>} skipKeys={DNS_RULE_SKIP} />
          </td>
        </tr>
      )}
    </>
  );
}

function FirewallIpsRuleRow({
  rule,
  onToggle,
  togglePending,
}: {
  rule: FirewallIpsRule;
  onToggle: (id: number, next: string) => void;
  togglePending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPredefined = rule.predefined === true;
  const actionLabel = typeof rule.action === "object" && rule.action !== null
    ? (rule.action as { type: string }).type
    : (rule.action ?? "-");

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{rule.order}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {rule.name}
          {isPredefined && <span className="ml-1 text-xs text-gray-400 italic">predefined</span>}
        </td>
        <td className="px-3 py-2 text-gray-600">{actionLabel}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <StateToggle ruleId={rule.id} state={rule.state} onToggle={(id, next) => onToggle(id as number, next)} pending={togglePending} />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid rule={rule as unknown as Record<string, unknown>} skipKeys={IPS_RULE_SKIP} />
          </td>
        </tr>
      )}
    </>
  );
}

function FirewallDnsRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-firewall-dns-rules", tenantName],
    queryFn: () => fetchFirewallDnsRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchFirewallDnsRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-firewall-dns-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {toggleErr && (
        <div className="px-3 py-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>Dismiss</button>
        </div>
      )}
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
            {data.map((r: FirewallDnsRule) => (
              <FirewallDnsRuleRow
                key={r.id}
                rule={r}
                onToggle={(id, next) => { setToggleErr(null); toggleMut.mutate({ id, state: next }); }}
                togglePending={toggleMut.isPending}
              />
            ))}
            {data.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No DNS filter rules</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FirewallIpsRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-firewall-ips-rules", tenantName],
    queryFn: () => fetchFirewallIpsRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchFirewallIpsRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-firewall-ips-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {toggleErr && (
        <div className="px-3 py-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>Dismiss</button>
        </div>
      )}
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
            {data.map((r: FirewallIpsRule) => (
              <FirewallIpsRuleRow
                key={r.id}
                rule={r}
                onToggle={(id, next) => { setToggleErr(null); toggleMut.mutate({ id, state: next }); }}
                togglePending={toggleMut.isPending}
              />
            ))}
            {data.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No IPS rules</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FirewallRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);
  const [exportErr, setExportErr] = useState<string | null>(null);
  const [exportPending, setExportPending] = useState(false);
  const [syncResult, setSyncResult] = useState<{ created: number; updated: number; deleted: number; skipped: number; errors: string[] } | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-firewall-rules", tenantName],
    queryFn: () => fetchFirewallRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchFirewallRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-firewall-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  const syncMut = useMutation({
    mutationFn: (file: File) => syncFirewallRulesFromCsv(tenantName, file),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["zia-firewall-rules", tenantName] });
      setSyncResult(result);
    },
  });

  async function handleExport() {
    setExportErr(null);
    setExportPending(true);
    try {
      await exportFirewallRulesToCsv(tenantName, tenantName);
    } catch (e) {
      setExportErr(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExportPending(false);
    }
  }

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {toggleErr && (
        <div className="px-3 py-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>Dismiss</button>
        </div>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={handleExport}
          disabled={exportPending}
          className="px-3 py-1.5 text-xs rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60"
        >
          {exportPending ? "Exporting..." : "Export to CSV"}
        </button>
        <label className="px-3 py-1.5 text-xs rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 cursor-pointer">
          Sync from CSV
          <input
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setSyncResult(null);
              if (f) syncMut.mutate(f);
              e.target.value = "";
            }}
          />
        </label>
        {syncMut.isPending && <span className="text-xs text-gray-500">Syncing...</span>}
        {exportErr && <span className="text-xs text-red-600">{exportErr}</span>}
        {syncMut.isError && (
          <span className="text-xs text-red-600">
            {syncMut.error instanceof Error ? syncMut.error.message : "Sync failed"}
          </span>
        )}
        {syncResult && syncResult.errors.length === 0 && (
          <span className="text-xs text-green-700">
            {syncResult.created} created, {syncResult.updated} updated, {syncResult.deleted} deleted, {syncResult.skipped} skipped
          </span>
        )}
      </div>
      {syncResult && syncResult.errors.length > 0 && (
        <div className="px-3 py-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded space-y-1">
          <div className="font-medium">{syncResult.created} created, {syncResult.updated} updated, {syncResult.deleted} deleted, {syncResult.skipped} skipped — {syncResult.errors.length} error(s):</div>
          {syncResult.errors.map((e, i) => <div key={i} className="font-mono break-all">{e}</div>)}
        </div>
      )}
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
            {data.map((r: FirewallRule) => (
              <FirewallRuleRow
                key={r.id}
                rule={r}
                onToggle={(id, next) => { setToggleErr(null); toggleMut.mutate({ id, state: next }); }}
                togglePending={toggleMut.isPending}
              />
            ))}
            {data.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No firewall rules</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SslInspectionSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-ssl-rules", tenantName],
    queryFn: () => fetchSslInspectionRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchSslRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-ssl-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {toggleErr && (
        <div className="px-3 py-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>Dismiss</button>
        </div>
      )}
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
            {data.map((r: SslInspectionRule) => (
              <SslRuleRow
                key={r.id}
                rule={r}
                onToggle={(id, next) => { setToggleErr(null); toggleMut.mutate({ id, state: next }); }}
                togglePending={toggleMut.isPending}
              />
            ))}
            {data.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No SSL inspection rules</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ForwardingRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-forwarding-rules", tenantName],
    queryFn: () => fetchForwardingRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchForwardingRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-forwarding-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {toggleErr && (
        <div className="px-3 py-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>Dismiss</button>
        </div>
      )}
      <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Order</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">State</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {data.map((r: ForwardingRule) => (
            <ForwardingRuleRow
              key={r.id}
              rule={r}
              onToggle={(id, next) => { setToggleErr(null); toggleMut.mutate({ id, state: next }); }}
              togglePending={toggleMut.isPending}
            />
          ))}
          {data.length === 0 && (
            <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No forwarding rules</td></tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function DlpEnginesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-dlp-engines", tenantName],
    queryFn: () => fetchDlpEngines(tenantName),
    enabled: isOpen,
  });

  // Fetch dictionaries to resolve D{id} references in engine expressions.
  const { data: dicts } = useQuery({
    queryKey: ["zia-dlp-dicts", tenantName],
    queryFn: () => fetchDlpDictionaries(tenantName),
    enabled: isOpen,
    staleTime: 5 * 60 * 1000,
  });

  const dictMap = new Map<number, string>(
    (dicts ?? []).map((d: DlpDictionary) => [
      d.id,
      d.predefined_phrases?.[0] ?? d.name,
    ])
  );

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
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
          {data.map((e: DlpEngine) => (
            <DlpEngineRow key={e.id} tenantName={tenantName} engine={e} dictMap={dictMap}
              onDeleted={() => qc.invalidateQueries({ queryKey: ["zia-dlp-engines", tenantName] })} />
          ))}
          {data.length === 0 && (
            <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No DLP engines</td></tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

const CONFIDENCE_LABELS: Record<string, string> = {
  CONFIDENCE_LEVEL_LOW: "Low",
  CONFIDENCE_LEVEL_MEDIUM: "Medium",
  CONFIDENCE_LEVEL_HIGH: "High",
};

function DlpDictionariesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [confErr, setConfErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-dlp-dicts", tenantName],
    queryFn: () => fetchDlpDictionaries(tenantName),
    enabled: isOpen,
  });

  const confMut = useMutation({
    mutationFn: ({ id, threshold }: { id: number; threshold: string }) =>
      patchDlpDictionaryConfidence(tenantName, id, threshold),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zia-dlp-dicts", tenantName] }),
    onError: (e: Error) => setConfErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((d: DlpDictionary) =>
    d.name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="space-y-3">
      {confErr && (
        <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          Update failed: {confErr}
          <button className="ml-2 underline" onClick={() => setConfErr(null)}>dismiss</button>
        </div>
      )}
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
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Confidence Threshold</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((d: DlpDictionary) => {
              const rawThreshold = d.confidence_threshold ?? d.confidenceThreshold;
              const canEdit = d.threshold_allowed === true || d.thresholdAllowed === true;
              return (
                <tr key={d.id}>
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">{d.id}</td>
                  <td className="px-3 py-2 text-gray-900">{d.name}</td>
                  <td className="px-3 py-2 text-gray-500">{d.type ?? "-"}</td>
                  <td className="px-3 py-2">
                    {canEdit ? (
                      <select
                        value={rawThreshold ?? ""}
                        disabled={confMut.isPending}
                        onChange={(e) => { setConfErr(null); confMut.mutate({ id: d.id, threshold: e.target.value }); }}
                        className="border border-gray-300 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-zs-500 disabled:opacity-60"
                      >
                        <option value="CONFIDENCE_LEVEL_LOW">Low</option>
                        <option value="CONFIDENCE_LEVEL_MEDIUM">Medium</option>
                        <option value="CONFIDENCE_LEVEL_HIGH">High</option>
                      </select>
                    ) : (
                      <span className="text-gray-500 text-xs">{rawThreshold ? (CONFIDENCE_LABELS[rawThreshold] ?? rawThreshold) : "-"}</span>
                    )}
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

function DlpWebRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-dlp-web-rules", tenantName],
    queryFn: () => fetchDlpWebRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, state }: { id: number; state: string }) =>
      patchDlpWebRuleState(tenantName, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-dlp-web-rules", tenantName] });
      qc.invalidateQueries({ queryKey: ["zia-activation", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {toggleErr && (
        <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>dismiss</button>
        </div>
      )}
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
            {data.map((r: DlpWebRule) => (
              <DlpWebRuleRow
                key={r.id}
                rule={r}
                onToggle={(id, next) => { setToggleErr(null); toggleMut.mutate({ id, state: next }); }}
                togglePending={toggleMut.isPending}
              />
            ))}
            {data.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No DLP web rules</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const CLOUD_APP_INSTANCE_SKIP = new Set(["instance_id", "instance_name", "instance_type"]);

function CloudAppInstancesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-cloud-app-instances", tenantName],
    queryFn: () => fetchCloudAppInstances(tenantName),
    enabled: isOpen,
  });
  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {(data ?? []).map((inst: CloudAppInstance, i: number) => {
            const key = inst.instance_id ?? i;
            const expanded = expandedId === key;
            return (
              <>
                <tr key={key} className="cursor-pointer hover:bg-gray-50" onClick={() => setExpandedId(expanded ? null : (key as number))}>
                  <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
                    <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
                    {inst.instance_name ?? "-"}
                  </td>
                  <td className="px-3 py-2 text-gray-500 text-xs">{inst.instance_type ?? "-"}</td>
                </tr>
                {expanded && (
                  <tr key={`${key}-detail`}>
                    <td colSpan={2} className="bg-gray-50 px-4 py-3">
                      <RuleDetailGrid
                        rule={inst as unknown as Record<string, unknown>}
                        skipKeys={CLOUD_APP_INSTANCE_SKIP}
                      />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
          {(data ?? []).length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No cloud app instances</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

const TENANCY_APP_TYPE_LABELS: Record<string, string> = {
  YOUTUBE:                 "YouTube",
  GOOGLE:                  "Google",
  MSLOGINSERVICES:         "Microsoft Login Services",
  SLACK:                   "Slack",
  BOX:                     "Box",
  FACEBOOK:                "Facebook",
  AWS:                     "AWS",
  DROPBOX:                 "Dropbox",
  WEBEX_LOGIN_SERVICES:    "Webex Login Services",
  AMAZON_S3:               "Amazon S3",
  ZOHO_LOGIN_SERVICES:     "Zoho Login Services",
  GOOGLE_CLOUD_PLATFORM:   "Google Cloud Platform",
  ZOOM:                    "Zoom",
  IBMSMARTCLOUD:           "IBM Smart Cloud",
  GITHUB:                  "GitHub",
  CHATGPT_AI:              "ChatGPT / AI",
};

const TENANCY_SKIP = new Set(["id", "name", "app_type", "description"]);

function TenancyRestrictionRow({ profile }: { profile: TenancyRestrictionProfile }) {
  const [expanded, setExpanded] = useState(false);
  const appLabel = profile.app_type
    ? (TENANCY_APP_TYPE_LABELS[profile.app_type] ?? profile.app_type)
    : "-";
  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {profile.name ?? "-"}
        </td>
        <td className="px-3 py-2 text-gray-600">{appLabel}</td>
        <td className="px-3 py-2 text-gray-500 text-xs">{profile.description ?? "-"}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={3} className="bg-gray-50 px-4 py-3">
            <RuleDetailGrid
              rule={profile as unknown as Record<string, unknown>}
              skipKeys={TENANCY_SKIP}
            />
          </td>
        </tr>
      )}
    </>
  );
}

function TenancyRestrictionsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-tenancy-restriction-profiles", tenantName],
    queryFn: () => fetchTenancyRestrictionProfiles(tenantName),
    enabled: isOpen,
  });
  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Cloud Application</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {(data ?? []).map((p: TenancyRestrictionProfile, i: number) => (
            <TenancyRestrictionRow key={p.id ?? i} profile={p} />
          ))}
          {(data ?? []).length === 0 && (
            <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No tenancy restriction profiles</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

const CLOUD_APP_RULE_TYPE_LABELS: Record<string, string> = {
  AI_ML:                    "AI & ML Applications",
  DNS_OVER_HTTPS:           "DNS over HTTPS Services",
  ENTERPRISE_COLLABORATION: "Collaboration & Online Meetings",
  BUSINESS_PRODUCTIVITY:    "Productivity & CRM Tools",
  FILE_SHARE:               "File Sharing",
  HOSTING_PROVIDER:         "Hosting Providers",
  INSTANT_MESSAGING:        "Instant Messaging",
  IT_SERVICES:              "IT Services",
  SOCIAL_NETWORKING:        "Social Networking",
  STREAMING_MEDIA:          "Streaming Media",
  WEBMAIL:                  "Webmail",
  CONSUMER:                 "Consumer",
  FINANCE:                  "Finance",
  HEALTH_CARE:              "Health Care",
  HUMAN_RESOURCES:          "Human Resources",
  LEGAL:                    "Legal",
  SALES_AND_MARKETING:      "Sales & Marketing",
  SYSTEM_AND_DEVELOPMENT:   "System & Development",
};

function CloudAppRulesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [toggleErr, setToggleErr] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-cloud-app-control-rules", tenantName],
    queryFn: () => fetchCloudAppControlRules(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ ruleType, id, state }: { ruleType: string; id: number; state: string }) =>
      patchCloudAppRuleState(tenantName, ruleType, id, state),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-cloud-app-control-rules", tenantName] });
    },
    onError: (e: Error) => setToggleErr(e.message),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;

  const rules = data ?? [];

  // Group by type, preserving the canonical order from CLOUD_APP_RULE_TYPE_LABELS
  const grouped = new Map<string, CloudAppControlRule[]>();
  for (const r of rules) {
    const t = (r.type as string) ?? "UNKNOWN";
    if (!grouped.has(t)) grouped.set(t, []);
    grouped.get(t)!.push(r);
  }
  // Sort each group by order
  for (const group of grouped.values()) {
    group.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  }
  // Render in canonical label order, then any unknowns
  const canonicalTypes = Object.keys(CLOUD_APP_RULE_TYPE_LABELS);
  const orderedTypes = [
    ...canonicalTypes.filter((t) => grouped.has(t)),
    ...[...grouped.keys()].filter((t) => !canonicalTypes.includes(t)),
  ];

  if (rules.length === 0) {
    return <p className="text-sm text-gray-400 px-3 py-4 text-center">No cloud app control rules</p>;
  }

  return (
    <div className="space-y-2">
      {toggleErr && (
        <div className="px-3 py-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded">
          Toggle failed: {toggleErr}
          <button className="ml-2 underline" onClick={() => setToggleErr(null)}>Dismiss</button>
        </div>
      )}
      {orderedTypes.map((ruleType) => {
        const typeRules = grouped.get(ruleType)!;
        const label = CLOUD_APP_RULE_TYPE_LABELS[ruleType] ?? ruleType.replace(/_/g, " ");
        return (
          <div key={ruleType}>
            <div className="px-3 py-1.5 bg-gray-100 border-y border-gray-200 text-xs font-semibold text-gray-600 uppercase tracking-wide">
              {label}
            </div>
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">#</th>
                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50 bg-white">
                {typeRules.map((r) => (
                  <tr key={r.id}>
                    <td className="px-3 py-1.5 text-gray-400 text-xs">{r.order ?? "-"}</td>
                    <td className="px-3 py-1.5 text-gray-900">{r.name ?? "-"}</td>
                    <td className="px-3 py-1.5 text-gray-600 text-xs">{r.action ?? "-"}</td>
                    <td className="px-3 py-1.5" onClick={(e) => e.stopPropagation()}>
                      <StateToggle
                        ruleId={r.id!}
                        state={r.state ?? "DISABLED"}
                        pending={toggleMut.isPending}
                        onToggle={(_id, next) => toggleMut.mutate({ ruleType, id: r.id!, state: next })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

const CLOUD_APP_ADV_SKIP = new Set(["id", "name", "access_control"]);

function CloudAppAdvancedSettingsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-cloud-app-settings", tenantName],
    queryFn: () => fetchCloudAppSettings(tenantName),
    enabled: isOpen,
  });
  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  const record = data?.[0] as Record<string, unknown> | undefined;
  if (!record) return <p className="text-xs text-gray-400 px-1">No settings found.</p>;
  return (
    <div className="p-3">
      <RuleDetailGrid rule={record} skipKeys={CLOUD_APP_ADV_SKIP} />
    </div>
  );
}

function SnapshotsSection({ tenant, isOpen }: { tenant: Tenant; isOpen: boolean }) {
  const qc = useQueryClient();
  const [labelInput, setLabelInput] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<ConfigSnapshot | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-snapshots", tenant.name],
    queryFn: () => fetchSnapshots(tenant.name, "ZIA"),
    enabled: isOpen,
  });

  const createMut = useMutation({
    mutationFn: () => createSnapshot(tenant.name, labelInput.trim() || undefined, "ZIA"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-snapshots", tenant.name] });
      setLabelInput("");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteSnapshot(tenant.name, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zia-snapshots", tenant.name] });
      setDeleteTarget(null);
    },
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;

  const snaps = data ?? [];

  return (
    <div className="space-y-4">
      {deleteTarget !== null && (
        <ConfirmDialog
          title="Delete Snapshot"
          message="Delete this snapshot? This cannot be undone."
          onConfirm={() => deleteMut.mutate(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
          destructive
        />
      )}

      {restoreTarget && (
        <RestoreSnapshotModal
          tenant={tenant}
          snapshot={restoreTarget}
          onClose={() => setRestoreTarget(null)}
        />
      )}

      {/* Save new snapshot */}
      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Label (optional)</label>
          <input
            type="text"
            value={labelInput}
            onChange={(e) => setLabelInput(e.target.value)}
            placeholder="e.g. pre-change baseline"
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <button
          onClick={() => createMut.mutate()}
          disabled={createMut.isPending}
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
        >
          {createMut.isPending ? "Saving..." : "Save Snapshot"}
        </button>
      </div>
      {createMut.isError && (
        <ErrorMessage message={createMut.error instanceof Error ? createMut.error.message : "Failed to save"} />
      )}

      {/* List */}
      {snaps.length === 0 ? (
        <p className="text-sm text-gray-400">No snapshots saved yet.</p>
      ) : (
        <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
          {snaps.map((s: ConfigSnapshot) => (
            <div key={s.id} className="flex items-center justify-between px-4 py-3 bg-white">
              <div>
                <p className="text-sm font-medium text-gray-900">{s.label || <span className="italic text-gray-400">Unlabeled</span>}</p>
                <p className="text-xs text-gray-400">
                  {formatDateTime(s.created_at)} · {s.resource_count} resources
                </p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setRestoreTarget(s)}
                  className="text-xs text-zs-600 hover:text-zs-800"
                >
                  Restore
                </button>
                <button
                  onClick={() => setDeleteTarget(s.id)}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── RestoreSnapshotModal ───────────────────────────────────────────────────────

function RestoreSnapshotModal({
  tenant,
  snapshot,
  onClose,
}: {
  tenant: Tenant;
  snapshot: ConfigSnapshot;
  onClose: () => void;
}) {
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [applyJobId, setApplyJobId] = useState<string | null>(null);
  const [mutErr, setMutErr] = useState<string | null>(null);

  const previewMut = useMutation({
    mutationFn: () => previewApplySnapshot(tenant.id, tenant.id, snapshot.id),
    onSuccess: (data) => { setPreviewJobId(data.job_id); setMutErr(null); },
    onError: (e: Error) => setMutErr(e.message),
  });

  const applyMut = useMutation({
    mutationFn: (wipeMode: boolean) => applySnapshot(tenant.id, tenant.id, snapshot.id, wipeMode),
    onSuccess: (data) => { setApplyJobId(data.job_id); setMutErr(null); },
    onError: (e: Error) => setMutErr(e.message),
  });

  const {
    latestByPhase: previewProgress,
    jobStatus: previewJobStatus,
    result: previewResult,
    streamError: previewStreamError,
  } = useJobStream<SnapshotPreview>(previewJobId);

  const {
    latestByPhase: applyProgress,
    jobStatus: applyJobStatus,
    result: applyResult,
    streamError: applyStreamError,
  } = useJobStream<ApplySnapshotResult>(applyJobId);

  const preview = previewJobStatus === "done" ? previewResult : null;
  const isPreviewRunning = previewMut.isPending || previewJobStatus === "running";
  const isApplyRunning = applyMut.isPending || applyJobStatus === "running";
  const applyDone = applyJobStatus === "done";
  const applyCancelled = applyJobStatus === "cancelled" || (applyJobStatus === "done" && !!applyResult?.cancelled);

  function applyPhaseLabel() {
    const rollbackEv = applyProgress["rollback"];
    const pushEv = applyProgress["push"];
    const wipeEv = applyProgress["wipe"];
    const importEv = applyProgress["import"];
    if (rollbackEv) return `Rolling back ${rollbackEv.resource_type}: ${rollbackEv.name ?? ""}`;
    if (pushEv) return `Pushing ${pushEv.resource_type}: ${pushEv.name ?? ""}`;
    if (wipeEv) return `Wiping ${wipeEv.resource_type}: ${wipeEv.name ?? ""}`;
    if (importEv) return `Importing ${importEv.resource_type}… ${importEv.done}${importEv.total ? `/${importEv.total}` : ""}`;
    return "Applying changes…";
  }

  const err = mutErr ?? previewStreamError ?? applyStreamError ?? null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-200 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Restore Snapshot</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {snapshot.label || formatDateTime(snapshot.created_at)} · {snapshot.resource_count} resources
            </p>
          </div>
          {!isApplyRunning && (
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 ml-4">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {err && <p className="text-xs text-red-600">{err}</p>}

          {/* Result */}
          {(applyDone || applyCancelled) && (
            <div>
              {applyCancelled ? (
                <div className="p-3 rounded-md text-sm bg-amber-50 text-amber-800">
                  <p className="font-medium">Restore cancelled.</p>
                  {applyResult?.rolled_back !== undefined ? (
                    <p className="text-xs mt-1">
                      Rolled back {applyResult.rolled_back} change{applyResult.rolled_back !== 1 ? "s" : ""}.
                      {!!applyResult.rollback_failed && ` ${applyResult.rollback_failed} rollback${applyResult.rollback_failed !== 1 ? "s" : ""} failed — check ZIA manually.`}
                    </p>
                  ) : (
                    <p className="text-xs mt-1">Any changes already pushed to ZIA remain in effect and are not automatically rolled back.</p>
                  )}
                </div>
              ) : applyResult ? (
                <div className={`p-3 rounded-md text-sm ${applyResult.status === "SUCCESS" || applyResult.status === "PARTIAL" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
                  <p className="font-medium">
                    {applyResult.status} — Snapshot restored
                    <span className="ml-2 font-normal text-xs opacity-70">({applyResult.mode === "wipe" ? "Wipe & Push" : "Delta Push"})</span>
                  </p>
                  <p className="text-xs mt-1">
                    {applyResult.mode === "wipe" && applyResult.wiped > 0 && `${applyResult.wiped} wiped · `}
                    {applyResult.created} created · {applyResult.updated} updated
                    {applyResult.failed > 0 && ` · ${applyResult.failed} failed`}
                  </p>
                </div>
              ) : null}
              {applyResult?.failed_items && applyResult.failed_items.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-red-700 mb-1">Failed ({applyResult.failed_items.length}):</p>
                  <div className="max-h-32 overflow-y-auto border border-red-200 rounded-md divide-y divide-red-100 text-xs">
                    {applyResult.failed_items.map((item, i) => (
                      <div key={i} className="px-3 py-1.5 bg-white">
                        <span className="font-mono text-gray-500">{item.resource_type}</span> · {item.name}
                        <p className="text-red-700 font-mono break-all mt-0.5">{item.reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <button onClick={onClose} className="mt-3 text-xs text-zs-600 hover:underline">
                Close
              </button>
            </div>
          )}

          {/* Preview running */}
          {isPreviewRunning && (
            <div className="space-y-1.5">
              <p className="text-xs text-gray-500">
                {previewProgress["import"]
                  ? `Importing ${previewProgress["import"].resource_type}… ${previewProgress["import"].done}${previewProgress["import"].total ? `/${previewProgress["import"].total}` : ""}`
                  : "Importing current state and classifying changes…"}
              </p>
              <ImportProgressBar active />
            </div>
          )}

          {/* Preview button */}
          {!preview && !isPreviewRunning && !applyDone && !applyCancelled && (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                Preview what will change when this snapshot is restored to <span className="font-medium">{tenant.name}</span>.
              </p>
              <button
                onClick={() => previewMut.mutate()}
                disabled={isPreviewRunning}
                className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
              >
                Preview Changes
              </button>
            </div>
          )}

          {/* Preview result */}
          {preview && !applyDone && !applyCancelled && (
            <div className="space-y-3">
              <div className="flex gap-4 text-sm flex-wrap items-baseline">
                <span className="text-green-700 font-medium">{preview.creates} create{preview.creates !== 1 ? "s" : ""}</span>
                <span className="text-blue-700 font-medium">{preview.updates} update{preview.updates !== 1 ? "s" : ""}</span>
                <span className="text-red-700 font-medium">{preview.deletes} delete{preview.deletes !== 1 ? "s" : ""}</span>
                <span className="text-gray-500">{preview.skips} skipped</span>
                {preview.deletes > 0 && (
                  <span className="text-xs text-amber-600 italic">deletes only applied by Wipe &amp; Push</span>
                )}
              </div>

              {preview.items.length > 0 && (
                <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-md">
                  <table className="min-w-full text-xs divide-y divide-gray-100">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase w-20">Action</th>
                        <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Type</th>
                        <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Name</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {preview.items.map((item, i) => (
                        <tr key={i}>
                          <td className={`px-3 py-1 font-medium ${item.action === "create" ? "text-green-700" : item.action === "update" ? "text-blue-700" : "text-red-700"}`}>
                            {item.action}
                          </td>
                          <td className="px-3 py-1 font-mono text-gray-500">{item.resource_type}</td>
                          <td className="px-3 py-1 text-gray-800 truncate max-w-xs">{item.name}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {preview.creates === 0 && preview.updates === 0 && preview.deletes === 0 && (
                <p className="text-sm text-green-700 font-medium">Tenant already matches this snapshot — nothing to restore.</p>
              )}

              {/* Apply progress */}
              {isApplyRunning && (
                <div className="space-y-1.5">
                  <p className="text-xs text-gray-500">{applyPhaseLabel()}</p>
                  <ImportProgressBar active message="Applying changes — this may take several minutes." />
                  <button
                    onClick={() => applyJobId && cancelJob(applyJobId)}
                    className="px-3 py-1 text-xs rounded-md border border-gray-300 hover:bg-gray-50 text-gray-600"
                  >
                    Stop
                  </button>
                </div>
              )}

              {/* Apply buttons */}
              {!isApplyRunning && (preview.creates > 0 || preview.updates > 0 || preview.deletes > 0) && (
                <div className="space-y-2">
                  <p className="text-xs text-gray-500">Choose how to restore:</p>
                  <div className="flex gap-2 flex-wrap">
                    <button
                      onClick={() => applyMut.mutate(false)}
                      className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
                      title="Applies creates and updates only. Resources not in the snapshot are left untouched."
                    >
                      Delta Push
                    </button>
                    <button
                      onClick={() => applyMut.mutate(true)}
                      className="px-4 py-1.5 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white"
                      title="Delete all existing resources first, then push the full snapshot."
                    >
                      Wipe &amp; Push
                    </button>
                    <button
                      onClick={onClose}
                      className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
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
                    {expEpoch ? formatDate(new Date(expEpoch * 1000).toISOString()) : "-"}
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

function AppConnectorsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-app-connectors", tenantName],
    queryFn: () => listAppConnectors(tenantName),
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
          {data.map((c: ZpaAppConnector) => (
            <tr key={c.id}>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{c.id}</td>
              <td className="px-3 py-2 text-gray-900">{c.name}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No app connectors</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ServiceEdgesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-service-edges", tenantName],
    queryFn: () => listServiceEdges(tenantName),
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
          {data.map((e: ZpaServiceEdge) => (
            <tr key={e.id}>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{e.id}</td>
              <td className="px-3 py-2 text-gray-900">{e.name}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No service edges</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SegmentGroupsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-segment-groups", tenantName],
    queryFn: () => listSegmentGroups(tenantName),
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
          {data.map((g: ZpaSegmentGroup) => (
            <tr key={g.id}>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{g.id}</td>
              <td className="px-3 py-2 text-gray-900">{g.name}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No segment groups</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── ZDX sections ──────────────────────────────────────────────────────────────

function ZdxDeviceSearchSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [query, setQuery] = useState("");
  const [hours, setHours] = useState(2);
  const [submitted, setSubmitted] = useState(false);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["zdx-devices", tenantName, query, hours],
    queryFn: () => searchZdxDevices(tenantName, query || undefined, hours),
    enabled: isOpen && submitted,
  });

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    refetch();
  }

  if (!isOpen) return null;

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex items-end gap-3 flex-wrap">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Search query</label>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Device name or user..."
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Time range (hours)</label>
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          >
            {[1, 2, 6, 12, 24, 48].map((h) => (
              <option key={h} value={h}>{h}h</option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white"
        >
          Search
        </button>
      </form>
      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Search failed"} />}
      {data && (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">User</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {data.map((d: ZdxDevice, i: number) => (
                <tr key={d.id ?? i}>
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">{d.id ?? "-"}</td>
                  <td className="px-3 py-2 text-gray-900">{d.name ?? "-"}</td>
                  <td className="px-3 py-2 text-gray-600">{d.user ?? "-"}</td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No results</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ZdxUserLookupSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["zdx-users", tenantName, query],
    queryFn: () => lookupZdxUsers(tenantName, query || undefined),
    enabled: isOpen && submitted,
  });

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    refetch();
  }

  if (!isOpen) return null;

  return (
    <div className="space-y-4">
      <form onSubmit={handleSearch} className="flex items-end gap-3">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Search users</label>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Username or email..."
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <button
          type="submit"
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white"
        >
          Search
        </button>
      </form>
      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Lookup failed"} />}
      {data && (
        <ul className="divide-y divide-gray-100 border border-gray-200 rounded-md">
          {data.map((u: ZdxUser, i: number) => (
            <li key={u.id ?? i} className="px-3 py-2 text-sm">
              <span className="font-medium text-gray-900">{u.name ?? u.email ?? u.id ?? "Unknown"}</span>
              {u.email && u.name && (
                <span className="ml-2 text-gray-500 font-mono text-xs">{u.email}</span>
              )}
            </li>
          ))}
          {data.length === 0 && (
            <li className="px-3 py-4 text-center text-gray-400 text-sm">No results</li>
          )}
        </ul>
      )}
    </div>
  );
}

// ── ZCC sections ──────────────────────────────────────────────────────────────

const OS_TYPE_LABELS: Record<number, string> = {
  1: "Windows",
  2: "macOS",
  3: "iOS",
  4: "Android",
  5: "Linux",
  6: "ChromeOS",
};

function OtpModal({ tenantName, device, onClose }: { tenantName: string; device: ZccDevice; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zcc-otp", tenantName, device.udid],
    queryFn: () => getDeviceOtp(tenantName, device.udid),
    enabled: true,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4">
        <div className="px-6 py-5">
          <h3 className="text-base font-semibold text-gray-900 mb-1">OTP for {device.hostname ?? device.udid}</h3>
          {isLoading && <LoadingSpinner />}
          {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to get OTP"} />}
          {data && (
            <div className="mt-3 flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-md px-3 py-2">
              <span className="font-mono text-lg font-bold text-gray-900 flex-1">{data.otp}</span>
              <CopyButton text={data.otp} />
            </div>
          )}
        </div>
        <div className="flex justify-end px-6 pb-5">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function ZccDevicesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [usernameFilter, setUsernameFilter] = useState("");
  const [osFilter, setOsFilter] = useState<number | "">("");
  const [otpDevice, setOtpDevice] = useState<ZccDevice | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zcc-devices", tenantName, usernameFilter, osFilter],
    queryFn: () => listZccDevices(tenantName, {
      username: usernameFilter || undefined,
      os_type: osFilter !== "" ? osFilter : undefined,
    }),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-3">
      {otpDevice && (
        <OtpModal tenantName={tenantName} device={otpDevice} onClose={() => setOtpDevice(null)} />
      )}
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Username</label>
          <input
            type="text"
            value={usernameFilter}
            onChange={(e) => setUsernameFilter(e.target.value)}
            placeholder="Filter by username..."
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">OS</label>
          <select
            value={osFilter}
            onChange={(e) => setOsFilter(e.target.value === "" ? "" : Number(e.target.value))}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          >
            <option value="">All</option>
            {Object.entries(OS_TYPE_LABELS).map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Hostname</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">User</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">OS</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">State</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.map((d: ZccDevice) => (
              <tr key={d.udid}>
                <td className="px-3 py-2 text-gray-900">{d.hostname ?? "-"}</td>
                <td className="px-3 py-2 text-gray-600">{d.username ?? d.owner ?? "-"}</td>
                <td className="px-3 py-2 text-gray-500">
                  {d.os_type ? OS_TYPE_LABELS[d.os_type] ?? String(d.os_type) : "-"}
                </td>
                <td className="px-3 py-2 text-gray-500">{d.registration_state ?? "-"}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => setOtpDevice(d)}
                    className="text-xs px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-700"
                  >
                    Get OTP
                  </button>
                </td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-400">No devices</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ZccReadOnlySection<T extends { id?: string; name?: string }>({
  queryKey,
  queryFn,
  isOpen,
  emptyMessage,
}: {
  queryKey: unknown[];
  queryFn: () => Promise<T[]>;
  isOpen: boolean;
  emptyMessage: string;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn,
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
          {data.map((item: T, i: number) => (
            <tr key={item.id ?? i}>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{item.id ?? "-"}</td>
              <td className="px-3 py-2 text-gray-900">{item.name ?? "-"}</td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">{emptyMessage}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── ZID sections ──────────────────────────────────────────────────────────────

function ZidUsersSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [filter, setFilter] = useState("");
  const [resetResult, setResetResult] = useState<{ userId: string; password: string } | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zid-users", tenantName],
    queryFn: () => listZidUsers(tenantName),
    enabled: isOpen,
  });

  const resetMut = useMutation({
    mutationFn: (userId: string) => resetUserPassword(tenantName, userId),
    onSuccess: (result, userId) => {
      setResetResult({ userId, password: result.temporary_password });
    },
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const q = filter.toLowerCase();
  const filtered = data.filter((u: ZidUser) =>
    (u.login_name ?? "").toLowerCase().includes(q) ||
    (u.display_name ?? "").toLowerCase().includes(q) ||
    (u.primary_email ?? "").toLowerCase().includes(q)
  );

  return (
    <div className="space-y-3">
      {resetResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4">
            <div className="px-6 py-5">
              <h3 className="text-base font-semibold text-gray-900 mb-1">Temporary Password</h3>
              <p className="text-xs text-gray-500 mb-3">This password will not be shown again. Save it now.</p>
              <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-md px-3 py-2">
                <span className="font-mono text-sm font-bold text-gray-900 flex-1 break-all">
                  {resetResult.password}
                </span>
                <CopyButton text={resetResult.password} />
              </div>
            </div>
            <div className="flex justify-end px-6 pb-5">
              <button
                onClick={() => setResetResult(null)}
                className="px-4 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
      <input
        type="text"
        placeholder="Filter by login name, display name, or email..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
      />
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Login Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Display Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((u: ZidUser, i: number) => (
              <tr key={u.id ?? i}>
                <td className="px-3 py-2 text-gray-900 font-mono text-xs">{u.login_name ?? "-"}</td>
                <td className="px-3 py-2 text-gray-700">{u.display_name ?? "-"}</td>
                <td className="px-3 py-2 text-gray-500 font-mono text-xs">{u.primary_email ?? "-"}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => u.id && resetMut.mutate(u.id)}
                    disabled={resetMut.isPending}
                    className="text-xs px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 disabled:opacity-60"
                  >
                    Reset PW
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No results</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ZidGroupsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zid-groups", tenantName],
    queryFn: () => listZidGroups(tenantName),
    enabled: isOpen,
  });

  const membersQuery = useQuery({
    queryKey: ["zid-group-members", tenantName, expandedGroup],
    queryFn: () => getGroupMembers(tenantName, expandedGroup!),
    enabled: !!expandedGroup,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <div className="space-y-2">
      {data.map((g: ZidGroup, i: number) => {
        const gid = g.id ?? String(i);
        const isExpanded = expandedGroup === gid;
        return (
          <div key={gid} className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setExpandedGroup(isExpanded ? null : gid)}
              className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left text-sm"
            >
              <span className="font-medium text-gray-900">{g.name ?? gid}</span>
              <div className="flex items-center gap-3">
                {g.type && <span className="text-xs text-gray-400">{g.type}</span>}
                <svg
                  className={`h-4 w-4 text-gray-500 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>
            {isExpanded && (
              <div className="px-4 py-3">
                {membersQuery.isLoading && <LoadingSpinner />}
                {membersQuery.error && <ErrorMessage message="Failed to load members" />}
                {membersQuery.data && (
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Login Name</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {membersQuery.data.map((m: ZidUser, mi: number) => (
                        <tr key={m.id ?? mi}>
                          <td className="px-3 py-2 text-gray-900 font-mono text-xs">{m.login_name ?? "-"}</td>
                          <td className="px-3 py-2 text-gray-500 font-mono text-xs">{m.primary_email ?? "-"}</td>
                        </tr>
                      ))}
                      {membersQuery.data.length === 0 && (
                        <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No members</td></tr>
                      )}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        );
      })}
      {data.length === 0 && <p className="text-sm text-gray-400 text-center py-4">No groups</p>}
    </div>
  );
}

function ZidApiClientsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [expandedClient, setExpandedClient] = useState<string | null>(null);
  const [newSecret, setNewSecret] = useState<{ clientSecret: string; secretId: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["zid-api-clients", tenantName],
    queryFn: () => listApiClients(tenantName),
    enabled: isOpen,
  });

  const secretsQuery = useQuery({
    queryKey: ["zid-api-client-secrets", tenantName, expandedClient],
    queryFn: () => getApiClientSecrets(tenantName, expandedClient!),
    enabled: !!expandedClient,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  function handleDeleteConfirm() {
    // deleteTarget is a clientId here for simplicity
    if (deleteTarget) {
      qc.invalidateQueries({ queryKey: ["zid-api-clients", tenantName] });
    }
    setDeleteTarget(null);
  }

  return (
    <div className="space-y-2">
      {newSecret && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4">
            <div className="px-6 py-5">
              <h3 className="text-base font-semibold text-gray-900 mb-1">New Client Secret</h3>
              <p className="text-xs text-red-600 font-medium mb-3">This secret will not be shown again.</p>
              <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-md px-3 py-2">
                <span className="font-mono text-sm text-gray-900 flex-1 break-all">{newSecret.clientSecret}</span>
                <CopyButton text={newSecret.clientSecret} />
              </div>
              <p className="mt-2 text-xs text-gray-500">Secret ID: {newSecret.secretId}</p>
            </div>
            <div className="flex justify-end px-6 pb-5">
              <button
                onClick={() => setNewSecret(null)}
                className="px-4 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
      {deleteTarget && (
        <ConfirmDialog
          title="Delete API Client"
          message="Are you sure you want to delete this API client? This action cannot be undone."
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
          destructive
        />
      )}
      {data.map((client: ZidApiClient, i: number) => {
        const cid = client.id ?? String(i);
        const isExpanded = expandedClient === cid;
        return (
          <div key={cid} className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setExpandedClient(isExpanded ? null : cid)}
              className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left text-sm"
            >
              <span className="font-medium text-gray-900">{client.name ?? cid}</span>
              <svg
                className={`h-4 w-4 text-gray-500 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {isExpanded && (
              <div className="px-4 py-3 space-y-3">
                {secretsQuery.isLoading && <LoadingSpinner />}
                {secretsQuery.error && <ErrorMessage message="Failed to load secrets" />}
                {secretsQuery.data && (
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Secret ID</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Expires</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                      {secretsQuery.data.map((s: ZidApiClientSecret, si: number) => (
                        <tr key={s.secret_id ?? si}>
                          <td className="px-3 py-2 font-mono text-xs text-gray-500">{s.secret_id ?? "-"}</td>
                          <td className="px-3 py-2 text-gray-500 text-xs">{formatDateTime(s.created_at)}</td>
                          <td className="px-3 py-2 text-gray-500 text-xs">{s.expires_at ? formatDateTime(s.expires_at) : "Never"}</td>
                        </tr>
                      ))}
                      {secretsQuery.data.length === 0 && (
                        <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No secrets</td></tr>
                      )}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        );
      })}
      {data.length === 0 && <p className="text-sm text-gray-400 text-center py-4">No API clients</p>}
    </div>
  );
}

// ── License comparison ────────────────────────────────────────────────────────

interface LicenseDiff {
  onlyInSource: string[];
  onlyInTarget: string[];
}

function computeLicenseDiff(src: unknown, tgt: unknown): LicenseDiff | null {
  if (!src || !tgt) return null;
  if (JSON.stringify(src) === JSON.stringify(tgt)) return null;

  function extractFeatures(subs: unknown): Set<string> | null {
    const arr = Array.isArray(subs) ? subs : (subs && typeof subs === "object" && "features" in subs && Array.isArray((subs as Record<string, unknown>).features) ? (subs as Record<string, unknown>).features as unknown[] : null);
    if (!Array.isArray(arr)) return null;
    return new Set(arr.map((f) => (f && typeof f === "object" && "name" in f ? String((f as Record<string, unknown>).name) : String(f))).filter(Boolean));
  }

  const srcFeats = extractFeatures(src);
  const tgtFeats = extractFeatures(tgt);
  if (srcFeats && tgtFeats) {
    const onlyInSource = [...srcFeats].filter((f) => !tgtFeats.has(f)).sort();
    const onlyInTarget = [...tgtFeats].filter((f) => !srcFeats.has(f)).sort();
    if (onlyInSource.length === 0 && onlyInTarget.length === 0) return null;
    return { onlyInSource, onlyInTarget };
  }

  return { onlyInSource: [], onlyInTarget: [] };
}

function LicenseWarning({ diff }: { diff: LicenseDiff }) {
  const hasDetail = diff.onlyInSource.length > 0 || diff.onlyInTarget.length > 0;
  return (
    <div className="p-3 rounded-md bg-amber-50 border border-amber-200 text-xs text-amber-800 space-y-1.5">
      <p className="font-medium">License / subscription discrepancy detected</p>
      <p>Source and target tenants have different ZIA subscriptions. Some resources may be silently modified or skipped during push.</p>
      {hasDetail && (
        <div className="space-y-1 mt-1">
          {diff.onlyInSource.length > 0 && (
            <div>
              <span className="font-medium">Source-only features:</span>
              <span className="ml-1 font-mono">{diff.onlyInSource.join(", ")}</span>
            </div>
          )}
          {diff.onlyInTarget.length > 0 && (
            <div>
              <span className="font-medium">Target-only features:</span>
              <span className="ml-1 font-mono">{diff.onlyInTarget.join(", ")}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ImportProgressBar({ active, message }: { active: boolean; message?: string }) {
  if (!active) return null;
  return (
    <div className="mt-2 space-y-1.5">
      <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
        <div className="h-full w-2/5 bg-zs-500 rounded-full animate-indeterminate" />
      </div>
      <p className="text-xs text-gray-400 italic">
        {message ?? "This may take several minutes depending on the number of resources in the tenant."}
      </p>
    </div>
  );
}

// ── Import product modal ───────────────────────────────────────────────────────

function ImportProductModal({
  tenant,
  product,
  onClose,
}: {
  tenant: Tenant;
  product: "ZIA" | "ZPA";
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [mutErr, setMutErr] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () => (product === "ZIA" ? importZIA(tenant.id) : importZPA(tenant.id)),
    onSuccess: (data) => setJobId(data.job_id),
    onError: (e: Error) => setMutErr(e.message),
  });

  const { latestByPhase, jobStatus, result, streamError } = useJobStream<ImportResult>(jobId);
  const importProgress = latestByPhase["import"];
  const isRunning = mut.isPending || jobStatus === "running";
  const isDone = jobStatus === "done";

  useEffect(() => {
    if (isDone) qc.invalidateQueries({ queryKey: ["tenant", tenant.id] });
  }, [isDone, qc, tenant.id]);

  const err = mutErr ?? streamError;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">Import {product} — {tenant.name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4 space-y-4">
          {!isDone && !isRunning && !err && (
            <p className="text-sm text-gray-600">
              Pull the latest {product} configuration from Zscaler into the local database.
            </p>
          )}
          {isRunning && (
            <div className="space-y-2">
              <p className="text-sm text-gray-600">
                {importProgress
                  ? `Importing ${importProgress.resource_type}… ${importProgress.done}${importProgress.total ? `/${importProgress.total}` : ""}`
                  : `Importing ${product} configuration…`}
              </p>
              {importProgress?.total ? (
                <div className="space-y-1">
                  <div className="h-2 w-full bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-zs-500 rounded-full transition-all duration-300"
                      style={{ width: `${Math.min(100, Math.round((importProgress.done / importProgress.total) * 100))}%` }}
                    />
                  </div>
                  <p className="text-xs text-gray-400 text-right">{importProgress.done} / {importProgress.total}</p>
                </div>
              ) : (
                <div className="mt-2 space-y-1.5">
                  <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                    <div className="h-full w-2/5 bg-zs-500 rounded-full animate-indeterminate" />
                  </div>
                </div>
              )}
              <p className="text-xs text-gray-400 italic">This may take several minutes depending on the number of resources in the tenant.</p>
            </div>
          )}
          {err && <p className="text-xs text-red-600">{err}</p>}
          {isDone && result && (
            <div className={`p-3 rounded-md text-sm ${result.status === "SUCCESS" || result.status === "PARTIAL" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
              <p className="font-medium">{result.status}</p>
              <p className="text-xs mt-1">{result.resources_synced} synced, {result.resources_updated} updated</p>
              {result.error_message && <p className="text-xs mt-1">{result.error_message}</p>}
            </div>
          )}
          <div className="flex justify-end gap-2">
            {!isDone && (
              <button
                onClick={() => mut.mutate()}
                disabled={isRunning}
                className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
              >
                {isRunning ? "Importing…" : `Import ${product}`}
              </button>
            )}
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">
              {isDone ? "Done" : "Cancel"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Clone Config panel ────────────────────────────────────────────────────────

function CloneConfigPanel({ tenant }: { tenant: Tenant }) {
  const [sourceTenantId, setSourceTenantId] = useState<number | "">("");
  const [snapshotId, setSnapshotId] = useState<number | "">("");
  const [fullClone, setFullClone] = useState(false);
  const [mutErr, setMutErr] = useState<string | null>(null);

  // SSE job IDs
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [applyJobId, setApplyJobId] = useState<string | null>(null);

  const { data: allTenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
    staleTime: 60_000,
  });

  const { data: snapshots } = useQuery({
    queryKey: ["zia-snapshots-for-apply", sourceTenantId],
    queryFn: () => {
      const src = allTenants?.find((t) => t.id === sourceTenantId);
      return src ? fetchSnapshots(src.name, "ZIA") : Promise.resolve([]);
    },
    enabled: !!sourceTenantId && !!allTenants,
  });

  const previewMut = useMutation({
    mutationFn: () =>
      previewApplySnapshot(tenant.id, sourceTenantId as number, snapshotId as number, fullClone),
    onSuccess: (data) => { setPreviewJobId(data.job_id); setMutErr(null); },
    onError: (e: Error) => setMutErr(e.message),
  });

  const applyMut = useMutation({
    mutationFn: (wipeMode: boolean) =>
      applySnapshot(tenant.id, sourceTenantId as number, snapshotId as number, wipeMode, fullClone),
    onSuccess: (data) => { setApplyJobId(data.job_id); setMutErr(null); },
    onError: (e: Error) => setMutErr(e.message),
  });

  const {
    latestByPhase: previewProgress,
    jobStatus: previewJobStatus,
    result: previewResult,
    streamError: previewStreamError,
  } = useJobStream<SnapshotPreview>(previewJobId);

  const {
    latestByPhase: applyProgress,
    jobStatus: applyJobStatus,
    result: applyResult,
    streamError: applyStreamError,
  } = useJobStream<ApplySnapshotResult>(applyJobId);

  const preview = previewJobStatus === "done" ? previewResult : null;
  const isPreviewRunning = previewMut.isPending || previewJobStatus === "running";
  const isApplyRunning = applyMut.isPending || applyJobStatus === "running";
  const applyDone = applyJobStatus === "done";
  const applyCancelled = applyJobStatus === "cancelled" || (applyJobStatus === "done" && !!applyResult?.cancelled);

  function reset() {
    setPreviewJobId(null);
    setApplyJobId(null);
    setMutErr(null);
    setSnapshotId("");
    setFullClone(false);
  }

  const sortedTenants = allTenants
    ? [...allTenants].filter((t) => t.id !== tenant.id).sort((a, b) => a.name.localeCompare(b.name))
    : [];

  const err = mutErr ?? previewStreamError ?? applyStreamError ?? null;

  // ── Cancelled view ──────────────────────────────────────────────────────────
  if (applyCancelled) {
    return (
      <div className="space-y-3 p-1">
        <div className="p-3 rounded-md text-sm bg-amber-50 text-amber-800">
          <p className="font-medium">Push cancelled.</p>
          {applyResult?.rolled_back !== undefined ? (
            <p className="text-xs mt-1">
              Rolled back {applyResult.rolled_back} change{applyResult.rolled_back !== 1 ? "s" : ""}.
              {!!applyResult.rollback_failed && ` ${applyResult.rollback_failed} rollback${applyResult.rollback_failed !== 1 ? "s" : ""} failed — check ZIA manually.`}
            </p>
          ) : (
            <p className="text-xs mt-1">Any changes already pushed to ZIA remain in effect.</p>
          )}
        </div>
        <button onClick={reset} className="text-xs text-zs-600 hover:underline">Clone again</button>
      </div>
    );
  }

  // ── Apply result view ──────────────────────────────────────────────────────
  if (applyDone && applyResult) {
    const ok = applyResult.status === "SUCCESS" || applyResult.status === "PARTIAL";
    return (
      <div className="space-y-3 p-1">
        <div className={`p-3 rounded-md text-sm ${ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
          <p className="font-medium">
            {applyResult.status} — Snapshot &ldquo;{applyResult.snapshot_name}&rdquo; applied
            <span className="ml-2 font-normal text-xs opacity-70">({
              applyResult.mode === "full_clone_wipe" ? "Full Clone · Wipe & Push" :
              applyResult.mode === "full_clone" ? "Full Clone · Delta Push" :
              applyResult.mode === "wipe" ? "Wipe & Push" : "Delta Push"
            })</span>
          </p>
          <p className="text-xs mt-1">
            {(applyResult.mode === "wipe" || applyResult.mode === "full_clone_wipe") && applyResult.wiped > 0 && `${applyResult.wiped} wiped · `}
            {applyResult.created} created · {applyResult.updated} updated
            {applyResult.failed > 0 && ` · ${applyResult.failed} failed`}
          </p>
        </div>

        {/* Failed items */}
        {applyResult.failed_items?.length > 0 && (
          <div>
            <p className="text-xs font-medium text-red-700 mb-1">Failed resources ({applyResult.failed_items.length}):</p>
            <div className="max-h-40 overflow-y-auto border border-red-200 rounded-md">
              <table className="min-w-full text-xs divide-y divide-red-100">
                <thead className="bg-red-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium text-red-600 uppercase">Type</th>
                    <th className="px-3 py-1.5 text-left font-medium text-red-600 uppercase">Name</th>
                    <th className="px-3 py-1.5 text-left font-medium text-red-600 uppercase">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-red-100 bg-white">
                  {applyResult.failed_items.map((item, i) => (
                    <tr key={i}>
                      <td className="px-3 py-1 font-mono text-gray-500">{item.resource_type}</td>
                      <td className="px-3 py-1 text-gray-800">{item.name}</td>
                      <td className="px-3 py-1 text-red-700 font-mono text-xs break-all">{item.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Warnings */}
        {applyResult.warnings?.length > 0 && (
          <div>
            <p className="text-xs font-medium text-amber-700 mb-1">Push warnings ({applyResult.warnings.length} resources):</p>
            <div className="max-h-48 overflow-y-auto border border-amber-200 rounded-md divide-y divide-amber-100">
              {applyResult.warnings.map((w, i) => (
                <div key={i} className="px-3 py-2 bg-amber-50">
                  <p className="text-xs font-medium text-gray-700 font-mono">{w.resource_type}: {w.name}</p>
                  <ul className="mt-0.5 space-y-0.5">
                    {w.warnings.map((msg, j) => (
                      <li key={j} className="text-xs text-amber-800">{msg}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}

        <button
          onClick={() => { reset(); }}
          className="text-xs text-zs-600 hover:underline"
        >
          Clone again
        </button>
      </div>
    );
  }

  // ── License diff ───────────────────────────────────────────────────────────
  const sourceTenant = allTenants?.find((t) => t.id === sourceTenantId) ?? null;
  const licenseDiff = sourceTenant ? computeLicenseDiff(sourceTenant.zia_subscriptions, tenant.zia_subscriptions) : null;

  // ── Preview summary helpers ────────────────────────────────────────────────
  const actionCounts: Record<string, { create: number; update: number; delete: number }> = {};
  if (preview) {
    for (const item of preview.items) {
      if (!actionCounts[item.resource_type]) {
        actionCounts[item.resource_type] = { create: 0, update: 0, delete: 0 };
      }
      actionCounts[item.resource_type][item.action as "create" | "update" | "delete"]++;
    }
  }

  // Phase label for apply progress
  function applyPhaseLabel() {
    const rollbackEv = applyProgress["rollback"];
    const pushEv = applyProgress["push"];
    const wipeEv = applyProgress["wipe"];
    const importEv = applyProgress["import"];
    if (rollbackEv) return `Rolling back ${rollbackEv.resource_type}: ${rollbackEv.name ?? ""}`;
    if (pushEv) return `Pushing ${pushEv.resource_type}: ${pushEv.name ?? ""}`;
    if (wipeEv) return `Wiping ${wipeEv.resource_type}: ${wipeEv.name ?? ""}`;
    if (importEv) return `Importing ${importEv.resource_type}… ${importEv.done}${importEv.total ? `/${importEv.total}` : ""}`;
    return "Applying changes…";
  }

  return (
    <div className="space-y-4 p-1">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Source Tenant</label>
          <select
            value={sourceTenantId}
            onChange={(e) => {
              setSourceTenantId(e.target.value ? Number(e.target.value) : "");
              setSnapshotId("");
              reset();
            }}
            className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          >
            <option value="">Select tenant…</option>
            {sortedTenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">ZIA Snapshot</label>
          <select
            value={snapshotId}
            onChange={(e) => {
              setSnapshotId(e.target.value ? Number(e.target.value) : "");
              setPreviewJobId(null);
              setMutErr(null);
            }}
            disabled={!sourceTenantId || !snapshots}
            className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:bg-gray-100"
          >
            <option value="">Select snapshot…</option>
            {(snapshots ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {formatDateTime(s.created_at)}{s.label ? ` — ${s.label}` : ""}
              </option>
            ))}
            {snapshots?.length === 0 && <option disabled>No snapshots found</option>}
          </select>
        </div>
      </div>

      {/* Full Clone toggle */}
      <label className="flex items-start gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={fullClone}
          onChange={(e) => { setFullClone(e.target.checked); setPreviewJobId(null); setMutErr(null); }}
          disabled={!sourceTenantId || !snapshotId}
          className="mt-0.5"
        />
        <div>
          <span className="text-sm font-medium text-gray-800">Full Clone</span>
          <p className="text-xs text-gray-500 mt-0.5">
            Also copies tenant-specific resources (static IPs, VPN credentials, GRE tunnels, locations, sublocations) live from the source tenant.
            VPN credential pre-shared keys cannot be copied — manual action will be required in the target tenant.
          </p>
        </div>
      </label>

      {err && <p className="text-xs text-red-600">{err}</p>}

      {/* Preview progress */}
      {isPreviewRunning && (
        <div className="space-y-1.5">
          <p className="text-xs text-gray-500">
            {previewProgress["import"]
              ? `Importing ${previewProgress["import"].resource_type}… ${previewProgress["import"].done}${previewProgress["import"].total ? `/${previewProgress["import"].total}` : ""}`
              : "Importing target tenant and classifying changes…"}
          </p>
          {previewProgress["import"]?.total ? (
            <div className="space-y-0.5">
              <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-zs-500 rounded-full transition-all duration-300"
                  style={{ width: `${Math.min(100, Math.round((previewProgress["import"].done / previewProgress["import"].total!) * 100))}%` }}
                />
              </div>
              <p className="text-xs text-gray-400 text-right">{previewProgress["import"].done} / {previewProgress["import"].total}</p>
            </div>
          ) : (
            <ImportProgressBar active />
          )}
        </div>
      )}

      {!preview && !isPreviewRunning && (
        <button
          onClick={() => previewMut.mutate()}
          disabled={!sourceTenantId || !snapshotId || isPreviewRunning}
          className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
        >
          Preview Changes
        </button>
      )}

      {preview && (
        <div className="space-y-3">
          <div className="text-xs text-gray-500">
            Snapshot: <span className="font-medium text-gray-700">{preview.snapshot_name}</span>
            {preview.snapshot_comment && ` — ${preview.snapshot_comment}`}
          </div>

          <div className="flex gap-4 text-sm flex-wrap items-baseline">
            <span className="text-green-700 font-medium">{preview.creates} create{preview.creates !== 1 ? "s" : ""}</span>
            <span className="text-blue-700 font-medium">{preview.updates} update{preview.updates !== 1 ? "s" : ""}</span>
            <span className="text-red-700 font-medium">{preview.deletes} delete{preview.deletes !== 1 ? "s" : ""}</span>
            <span className="text-gray-500">{preview.skips} skipped</span>
            {preview.deletes > 0 && (
              <span className="text-xs text-amber-600 italic">deletes only applied by Wipe &amp; Push</span>
            )}
          </div>

          {/* Summary by resource type */}
          {Object.keys(actionCounts).length > 0 && (
            <div className="max-h-40 overflow-y-auto border border-gray-200 rounded-md">
              <table className="min-w-full text-xs divide-y divide-gray-100">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Resource Type</th>
                    <th className="px-3 py-1.5 text-center font-medium text-green-600 uppercase">Create</th>
                    <th className="px-3 py-1.5 text-center font-medium text-blue-600 uppercase">Update</th>
                    <th className="px-3 py-1.5 text-center font-medium text-red-600 uppercase">Delete</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {Object.entries(actionCounts).map(([rt, counts]) => (
                    <tr key={rt}>
                      <td className="px-3 py-1.5 font-mono text-gray-700">{rt}</td>
                      <td className="px-3 py-1.5 text-center text-green-700">{counts.create || "-"}</td>
                      <td className="px-3 py-1.5 text-center text-blue-700">{counts.update || "-"}</td>
                      <td className="px-3 py-1.5 text-center text-red-700">{counts.delete || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Full individual change list */}
          {preview.items.length > 0 && (
            <div className="max-h-56 overflow-y-auto border border-gray-200 rounded-md">
              <table className="min-w-full text-xs divide-y divide-gray-100">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase w-20">Action</th>
                    <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Type</th>
                    <th className="px-3 py-1.5 text-left font-medium text-gray-500 uppercase">Name</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {preview.items.map((item, i) => (
                    <tr key={i}>
                      <td className={`px-3 py-1 font-medium ${
                        item.action === "create" ? "text-green-700" :
                        item.action === "update" ? "text-blue-700" : "text-red-700"
                      }`}>
                        {item.action}
                      </td>
                      <td className="px-3 py-1 font-mono text-gray-500">{item.resource_type}</td>
                      <td className="px-3 py-1 text-gray-800 truncate max-w-xs">{item.name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview.creates === 0 && preview.updates === 0 && preview.deletes === 0 && (
            <p className="text-sm text-green-700 font-medium">
              Target already matches this snapshot — nothing to apply.
            </p>
          )}

          {/* Apply progress */}
          {isApplyRunning && (
            <div className="space-y-1.5">
              <p className="text-xs text-gray-500">{applyPhaseLabel()}</p>
              <ImportProgressBar active message="Applying changes — this may take several minutes depending on the number of resources in the tenant." />
              <button
                onClick={() => applyJobId && cancelJob(applyJobId)}
                className="px-3 py-1 text-xs rounded-md border border-gray-300 hover:bg-gray-50 text-gray-600"
              >
                Stop
              </button>
            </div>
          )}

          {licenseDiff && <LicenseWarning diff={licenseDiff} />}

          {!isApplyRunning && (preview.creates > 0 || preview.updates > 0 || preview.deletes > 0) && (
            <div className="space-y-2">
              <p className="text-xs text-gray-500">Choose how to apply:</p>
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={() => applyMut.mutate(false)}
                  className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
                  title="Non-destructive: applies creates and updates only. Existing resources not in the snapshot are left untouched."
                >
                  Delta Push
                </button>
                <button
                  onClick={() => applyMut.mutate(true)}
                  className="px-4 py-1.5 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white"
                  title="Delete all existing resources first, then push the full snapshot. More thorough but destructive."
                >
                  Wipe &amp; Push
                </button>
                <button
                  onClick={reset}
                  className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── SectionGroup — top-level grouped accordion ────────────────────────────────

function SectionGroup({
  title,
  isOpen,
  onToggle,
  children,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="border border-gray-300 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-100 hover:bg-gray-200 text-left transition-colors"
      >
        <span className="font-semibold text-gray-800 text-sm">{title}</span>
        <svg
          className={`h-4 w-4 text-gray-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && <div className="px-3 py-3 space-y-2 bg-gray-50">{children}</div>}
    </div>
  );
}


// ── Tab panels ────────────────────────────────────────────────────────────────

type TabId = "zia" | "zpa" | "zdx" | "zcc" | "zid";

function ZiaTab({ tenant }: { tenant: Tenant }) {
  const [groups, setGroups] = useState<Record<string, boolean>>({ activation: true });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  function toggleGroup(key: string) { setGroups((prev) => ({ ...prev, [key]: !prev[key] })); }
  function toggle(key: string) { setOpen((prev) => ({ ...prev, [key]: !prev[key] })); }

  // Keep activation status cache warm regardless of accordion state.
  useQuery({
    queryKey: ["zia-activation", tenant.name],
    queryFn: () => fetchActivationStatus(tenant.name),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-3">
      {/* Activation — standalone */}
      <Accordion title="Activation" isOpen={!!groups.activation} onToggle={() => toggleGroup("activation")}>
        <ActivationSection tenantName={tenant.name} isOpen={!!groups.activation} />
      </Accordion>

      {/* URL Filtering & Cloud App Controls */}
      <SectionGroup title="URL Filtering & Cloud App Controls" isOpen={!!groups.webFilter} onToggle={() => toggleGroup("webFilter")}>
        <Accordion title="URL Filtering Rules" isOpen={!!open.urlFilteringRules} onToggle={() => toggle("urlFilteringRules")}>
          <UrlFilteringRulesSection tenantName={tenant.name} isOpen={!!open.urlFilteringRules} />
        </Accordion>
        <Accordion title="URL Categories" isOpen={!!open.urlCategories} onToggle={() => toggle("urlCategories")}>
          <UrlCategoriesSection tenantName={tenant.name} isOpen={!!open.urlCategories} />
        </Accordion>
        <Accordion title="URL Lookup" isOpen={!!open.urlLookup} onToggle={() => toggle("urlLookup")}>
          <UrlLookupSection tenantName={tenant.name} />
        </Accordion>
        <Accordion title="Cloud App Instances" isOpen={!!open.cloudAppInstances} onToggle={() => toggle("cloudAppInstances")}>
          <CloudAppInstancesSection tenantName={tenant.name} isOpen={!!open.cloudAppInstances} />
        </Accordion>
        <Accordion title="Tenancy Restrictions" isOpen={!!open.tenancyRestrictions} onToggle={() => toggle("tenancyRestrictions")}>
          <TenancyRestrictionsSection tenantName={tenant.name} isOpen={!!open.tenancyRestrictions} />
        </Accordion>
        <Accordion title="Cloud App Rules" isOpen={!!open.cloudAppRules} onToggle={() => toggle("cloudAppRules")}>
          <CloudAppRulesSection tenantName={tenant.name} isOpen={!!open.cloudAppRules} />
        </Accordion>
        <Accordion title="URL & Cloud App Control Advanced Settings" isOpen={!!open.cloudAppAdvanced} onToggle={() => toggle("cloudAppAdvanced")}>
          <CloudAppAdvancedSettingsSection tenantName={tenant.name} isOpen={!!open.cloudAppAdvanced} />
        </Accordion>
      </SectionGroup>

      {/* Network Security */}
      <SectionGroup title="Network Security" isOpen={!!groups.networkSec} onToggle={() => toggleGroup("networkSec")}>
        <Accordion title="Allow / Deny Lists" isOpen={!!open.allowdeny} onToggle={() => toggle("allowdeny")}>
          <AllowDenySection tenantName={tenant.name} isOpen={!!open.allowdeny} />
        </Accordion>
        <Accordion title="Firewall Policy" isOpen={!!open.firewall} onToggle={() => toggle("firewall")}>
          <FirewallRulesSection tenantName={tenant.name} isOpen={!!open.firewall} />
        </Accordion>
        <Accordion title="SSL Inspection" isOpen={!!open.ssl} onToggle={() => toggle("ssl")}>
          <SslInspectionSection tenantName={tenant.name} isOpen={!!open.ssl} />
        </Accordion>
        <Accordion title="Traffic Forwarding" isOpen={!!open.forwarding} onToggle={() => toggle("forwarding")}>
          <ForwardingRulesSection tenantName={tenant.name} isOpen={!!open.forwarding} />
        </Accordion>
        <Accordion title="DNS Filter Rules" isOpen={!!open.dnsFilter} onToggle={() => toggle("dnsFilter")}>
          <FirewallDnsRulesSection tenantName={tenant.name} isOpen={!!open.dnsFilter} />
        </Accordion>
        <Accordion title="IPS Rules" isOpen={!!open.ipsRules} onToggle={() => toggle("ipsRules")}>
          <FirewallIpsRulesSection tenantName={tenant.name} isOpen={!!open.ipsRules} />
        </Accordion>
      </SectionGroup>

      {/* Identity & Access */}
      <SectionGroup title="Identity & Access" isOpen={!!groups.identity} onToggle={() => toggleGroup("identity")}>
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
      </SectionGroup>

      {/* DLP */}
      <SectionGroup title="DLP" isOpen={!!groups.dlp} onToggle={() => toggleGroup("dlp")}>
        <Accordion title="DLP Engines" isOpen={!!open.dlpEngines} onToggle={() => toggle("dlpEngines")}>
          <DlpEnginesSection tenantName={tenant.name} isOpen={!!open.dlpEngines} />
        </Accordion>
        <Accordion title="DLP Dictionaries" isOpen={!!open.dlpDicts} onToggle={() => toggle("dlpDicts")}>
          <DlpDictionariesSection tenantName={tenant.name} isOpen={!!open.dlpDicts} />
        </Accordion>
        <Accordion title="DLP Web Rules" isOpen={!!open.dlpWebRules} onToggle={() => toggle("dlpWebRules")}>
          <DlpWebRulesSection tenantName={tenant.name} isOpen={!!open.dlpWebRules} />
        </Accordion>
      </SectionGroup>

      {/* Config Snapshots */}
      <SectionGroup title="Config Snapshots" isOpen={!!groups.snapshots} onToggle={() => toggleGroup("snapshots")}>
        <Accordion title="Snapshots" isOpen={!!open.snapshots} onToggle={() => toggle("snapshots")}>
          <SnapshotsSection tenant={tenant} isOpen={!!open.snapshots} />
        </Accordion>
      </SectionGroup>

      {/* Clone Config */}
      <SectionGroup title="Clone Config from Another Tenant" isOpen={!!groups.applySnapshot} onToggle={() => toggleGroup("applySnapshot")}>
        <CloneConfigPanel tenant={tenant} />
      </SectionGroup>
    </div>
  );
}

function ZpaTab({ tenant }: { tenant: Tenant }) {
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  function toggleGroup(key: string) { setGroups((prev) => ({ ...prev, [key]: !prev[key] })); }
  function toggle(key: string) { setOpen((prev) => ({ ...prev, [key]: !prev[key] })); }

  return (
    <div className="space-y-3">
      {/* Infrastructure */}
      <SectionGroup title="Infrastructure" isOpen={!!groups.infra} onToggle={() => toggleGroup("infra")}>
        <Accordion title="App Connectors" isOpen={!!open.appConnectors} onToggle={() => toggle("appConnectors")}>
          <AppConnectorsSection tenantName={tenant.name} isOpen={!!open.appConnectors} />
        </Accordion>
        <Accordion title="Service Edges" isOpen={!!open.serviceEdges} onToggle={() => toggle("serviceEdges")}>
          <ServiceEdgesSection tenantName={tenant.name} isOpen={!!open.serviceEdges} />
        </Accordion>
      </SectionGroup>

      {/* Applications */}
      <SectionGroup title="Applications" isOpen={!!groups.apps} onToggle={() => toggleGroup("apps")}>
        <Accordion title="Application Segments" isOpen={!!open.applications} onToggle={() => toggle("applications")}>
          <ApplicationsSection tenantName={tenant.name} isOpen={!!open.applications} />
        </Accordion>
        <Accordion title="Segment Groups" isOpen={!!open.segmentGroups} onToggle={() => toggle("segmentGroups")}>
          <SegmentGroupsSection tenantName={tenant.name} isOpen={!!open.segmentGroups} />
        </Accordion>
      </SectionGroup>

      {/* Certificates */}
      <SectionGroup title="Certificates" isOpen={!!groups.certs} onToggle={() => toggleGroup("certs")}>
        <Accordion title="Browser Access Certificates" isOpen={!!open.certificates} onToggle={() => toggle("certificates")}>
          <CertificatesSection tenantName={tenant.name} isOpen={!!open.certificates} />
        </Accordion>
      </SectionGroup>

      {/* PRA */}
      <SectionGroup title="Privileged Remote Access (PRA)" isOpen={!!groups.pra} onToggle={() => toggleGroup("pra")}>
        <Accordion title="PRA Portals" isOpen={!!open.praPortals} onToggle={() => toggle("praPortals")}>
          <PraPortalsSection tenantName={tenant.name} isOpen={!!open.praPortals} />
        </Accordion>
      </SectionGroup>
    </div>
  );
}

function ZdxTab({ tenant }: { tenant: Tenant }) {
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  function toggleGroup(key: string) { setGroups((prev) => ({ ...prev, [key]: !prev[key] })); }
  function toggle(key: string) { setOpen((prev) => ({ ...prev, [key]: !prev[key] })); }

  return (
    <div className="space-y-3">
      {/* Devices */}
      <SectionGroup title="Devices" isOpen={!!groups.devices} onToggle={() => toggleGroup("devices")}>
        <Accordion title="Device Search" isOpen={!!open.deviceSearch} onToggle={() => toggle("deviceSearch")}>
          <ZdxDeviceSearchSection tenantName={tenant.name} isOpen={!!open.deviceSearch} />
        </Accordion>
      </SectionGroup>

      {/* Users */}
      <SectionGroup title="Users" isOpen={!!groups.users} onToggle={() => toggleGroup("users")}>
        <Accordion title="User Lookup" isOpen={!!open.userLookup} onToggle={() => toggle("userLookup")}>
          <ZdxUserLookupSection tenantName={tenant.name} isOpen={!!open.userLookup} />
        </Accordion>
      </SectionGroup>
    </div>
  );
}

function ZccTab({ tenant }: { tenant: Tenant }) {
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  function toggleGroup(key: string) { setGroups((prev) => ({ ...prev, [key]: !prev[key] })); }
  function toggle(key: string) { setOpen((prev) => ({ ...prev, [key]: !prev[key] })); }

  return (
    <div className="space-y-3">
      {/* Devices */}
      <SectionGroup title="Devices" isOpen={!!groups.devices} onToggle={() => toggleGroup("devices")}>
        <Accordion title="All Devices" isOpen={!!open.devices} onToggle={() => toggle("devices")}>
          <ZccDevicesSection tenantName={tenant.name} isOpen={!!open.devices} />
        </Accordion>
      </SectionGroup>

      {/* Network */}
      <SectionGroup title="Network" isOpen={!!groups.network} onToggle={() => toggleGroup("network")}>
        <Accordion title="Trusted Networks" isOpen={!!open.trustedNetworks} onToggle={() => toggle("trustedNetworks")}>
          <ZccReadOnlySection<ZccTrustedNetwork>
            queryKey={["zcc-trusted-networks", tenant.name]}
            queryFn={() => listTrustedNetworks(tenant.name)}
            isOpen={!!open.trustedNetworks}
            emptyMessage="No trusted networks"
          />
        </Accordion>
        <Accordion title="Forwarding Profiles" isOpen={!!open.forwardingProfiles} onToggle={() => toggle("forwardingProfiles")}>
          <ZccReadOnlySection<ZccForwardingProfile>
            queryKey={["zcc-forwarding-profiles", tenant.name]}
            queryFn={() => listForwardingProfiles(tenant.name)}
            isOpen={!!open.forwardingProfiles}
            emptyMessage="No forwarding profiles"
          />
        </Accordion>
      </SectionGroup>

      {/* Policy */}
      <SectionGroup title="Policy" isOpen={!!groups.policy} onToggle={() => toggleGroup("policy")}>
        <Accordion title="App Profiles (Web Policies)" isOpen={!!open.webPolicies} onToggle={() => toggle("webPolicies")}>
          <ZccReadOnlySection<ZccWebPolicy>
            queryKey={["zcc-web-policies", tenant.name]}
            queryFn={() => listWebPolicies(tenant.name)}
            isOpen={!!open.webPolicies}
            emptyMessage="No app profiles"
          />
        </Accordion>
        <Accordion title="Bypass App Services" isOpen={!!open.webAppServices} onToggle={() => toggle("webAppServices")}>
          <ZccReadOnlySection<ZccWebAppService>
            queryKey={["zcc-web-app-services", tenant.name]}
            queryFn={() => listWebAppServices(tenant.name)}
            isOpen={!!open.webAppServices}
            emptyMessage="No bypass app services"
          />
        </Accordion>
      </SectionGroup>
    </div>
  );
}

function ZidTab({ tenant }: { tenant: Tenant }) {
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  function toggleGroup(key: string) { setGroups((prev) => ({ ...prev, [key]: !prev[key] })); }
  function toggle(key: string) { setOpen((prev) => ({ ...prev, [key]: !prev[key] })); }

  return (
    <div className="space-y-3">
      {/* Directory */}
      <SectionGroup title="Directory" isOpen={!!groups.directory} onToggle={() => toggleGroup("directory")}>
        <Accordion title="Users" isOpen={!!open.users} onToggle={() => toggle("users")}>
          <ZidUsersSection tenantName={tenant.name} isOpen={!!open.users} />
        </Accordion>
        <Accordion title="Groups" isOpen={!!open.groups} onToggle={() => toggle("groups")}>
          <ZidGroupsSection tenantName={tenant.name} isOpen={!!open.groups} />
        </Accordion>
      </SectionGroup>

      {/* API Access */}
      <SectionGroup title="API Access" isOpen={!!groups.apiAccess} onToggle={() => toggleGroup("apiAccess")}>
        <Accordion title="API Clients" isOpen={!!open.apiClients} onToggle={() => toggle("apiClients")}>
          <ZidApiClientsSection tenantName={tenant.name} isOpen={!!open.apiClients} />
        </Accordion>
      </SectionGroup>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TenantWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { setActiveTenantId } = useActiveTenant();
  const [importModal, setImportModal] = useState<"ZIA" | "ZPA" | null>(null);

  // Determine active tab from URL segment
  const pathSegment = location.pathname.split("/").pop() as TabId | undefined;
  const activeTab: TabId = (["zia", "zpa", "zdx", "zcc", "zid"].includes(pathSegment ?? "") ? pathSegment : "zia") as TabId;

  const { data: tenant, isLoading, error } = useQuery({
    queryKey: ["tenant", Number(id)],
    queryFn: () => fetchTenant(Number(id)),
    enabled: !!id,
    retry: (failureCount, err: unknown) => {
      if (err instanceof Error && "status" in err && (err as { status: number }).status === 404) return false;
      return failureCount < 2;
    },
  });

  // Sync active tenant to context
  useEffect(() => {
    if (id) {
      setActiveTenantId(Number(id));
    }
  }, [id, setActiveTenantId]);

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

  const hasZpa = !!tenant.zpa_customer_id && !tenant.govcloud;

  const tabs: { id: TabId; label: string; show: boolean }[] = [
    { id: "zia", label: "ZIA", show: true },
    { id: "zpa", label: "ZPA", show: !!tenant.zpa_customer_id },
    { id: "zdx", label: "ZDX", show: true },
    { id: "zcc", label: "ZCC", show: true },
    { id: "zid", label: "ZID", show: true },
  ];

  // If trying to view ZPA tab but no ZPA, redirect to ZIA
  if (activeTab === "zpa" && !tenant.zpa_customer_id) {
    navigate(`/tenant/${id}/zia`, { replace: true });
    return null;
  }

  const importButtonLabel = activeTab === "zpa" ? "Import ZPA" : "Import ZIA";
  const importProduct = activeTab === "zpa" ? "ZPA" : "ZIA";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
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
        {(activeTab === "zia" || (activeTab === "zpa" && hasZpa)) && (
          <button
            onClick={() => setImportModal(importProduct)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white transition-colors"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            {importButtonLabel}
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {tabs.filter((t) => t.show).map((tab) => (
            <Link
              key={tab.id}
              to={`/tenant/${id}/${tab.id}`}
              className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-zs-500 text-zs-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === "zia" && <ZiaTab key={tenant.id} tenant={tenant} />}
      {activeTab === "zpa" && tenant.zpa_customer_id && <ZpaTab key={tenant.id} tenant={tenant} />}
      {activeTab === "zdx" && <ZdxTab key={tenant.id} tenant={tenant} />}
      {activeTab === "zcc" && <ZccTab key={tenant.id} tenant={tenant} />}
      {activeTab === "zid" && <ZidTab key={tenant.id} tenant={tenant} />}

      {importModal && (
        <ImportProductModal
          tenant={tenant}
          product={importModal}
          onClose={() => setImportModal(null)}
        />
      )}
    </div>
  );
}
