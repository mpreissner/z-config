import React, { useState, useEffect, ReactNode, Fragment } from "react";
import { formatDateTime, formatDate } from "../utils/time";
import { Link, useParams, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchTenant,
  fetchTenants,
  importZIA,
  importZPA,
  importZCC,
  clearZCCDisabledResources,
  downloadTerraform,
  simulateTraffic,
  fetchSimApplications,
  fetchSimAppServiceGroups,
  fetchSimUsers,
  fetchSimDepartments,
  fetchSimGroups,
  fetchSimLocations,
  type SimulationResult,
  type PolicyCheck,
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
  fetchPacFiles,
  fetchPacFileVersions,
  validatePacFileContent,
  createPacFile,
  updatePacFile,
  deletePacFile,
  fetchOrgDomains,
  fetchSubClouds,
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
  PacFile,
  PacFileVersion,
  PacFileCreatePayload,
  PacFileUpdatePayload,
} from "../api/zia";
import {
  fetchCertificates,
  fetchApplications,
  patchApplicationEnabled,
  fetchPraPortals,
  fetchUserPortals,
  patchUserPortalEnabled,
  deleteUserPortal,
  fetchZpaSnapshotDiff,
  restoreZpaSnapshot,
  ZpaRestoreResult,
  listConnectors,
  patchConnectorEnabled,
  patchConnectorName,
  deleteConnector,
  listConnectorGroups,
  createConnectorGroup,
  patchConnectorGroupEnabled,
  deleteConnectorGroup,
  listServiceEdges,
  patchServiceEdgeEnabled,
  patchPraPortalEnabled,
  deletePraPortal,
  listPraConsoles,
  patchPraConsoleEnabled,
  deletePraConsole,
  listAccessPolicyRules,
  exportAccessPolicyCsv,
  listSamlAttributes,
  listScimAttributes,
  listScimGroups,
  listSegmentGroups,
  ZpaCertificate,
  ZpaApplication,
  ZpaPraPortal,
  ZpaUserPortal,
  ZpaAppConnector,
  ZpaServiceEdge,
  ZpaSegmentGroup,
  ZpaConnectorGroup,
  ZpaPraConsole,
  ZpaAccessPolicyRule,
  ZpaSamlAttribute,
  ZpaScimAttribute,
  ZpaScimGroup,
} from "../api/zpa";
import {
  listDevices as listZccDevices,
  listTrustedNetworks,
  listForwardingProfiles,
  listWebPolicies,
  listWebAppServices,
  listAdminRoles,
  listFailOpenPolicies,
  getWebPrivacy,
  listIpAppsPredefined,
  listIpAppsCustom,
  listProcessApps,
  getDeviceOtp,
  fetchTrafficProfile,
  listZccSnapshots,
  createZccSnapshot,
  deleteZccSnapshot,
  diffZccSnapshot,
  restoreZccSnapshot,
  ZccDevice,
  ZccTrustedNetwork,
  ZccForwardingProfile,
  ZccFpAction,
  ZccFpZpaAction,
  ZccWebPolicy,
  ZccWebAppService,
  ZccAdminRole,
  ZccFailOpenPolicy,
  ZccWebPrivacy,
  ZccIpApp,
  ZccProcessApp,
  TrafficProfile,
  TunnelMode,
  ZccSnapshot,
  ZccDiffEntry,
  ZccRestoreResponse,
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

function BoolToggle({
  enabled,
  onToggle,
  pending,
}: {
  enabled: boolean;
  onToggle: (next: boolean) => void;
  pending: boolean;
}) {
  return (
    <button
      onClick={() => onToggle(!enabled)}
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

// ── PAC Files ─────────────────────────────────────────────────────────────────

// ---------------------------------------------------------------------------
// PAC builder helpers
// ---------------------------------------------------------------------------

interface GatewayConfig {
  varType: "GATEWAY" | "GATEWAY_HOST" | "custom";
  customAddress: string;
  lbMode: "none" | "index" | "dynamic";
  lbIndex: number;             // 0–7, used when lbMode === "index"
  port: string;                // e.g. "9400" or "${ZS_CUSTOM_PORT}"
  useSubcloud: boolean;
  subcloudName: string;        // e.g. "myorg"
  subcloudCloud: string;       // e.g. "zscaler" — ".net" is always appended
  includeSecondary: boolean;
  fallbackDirect: boolean;
}

interface PacBuilderConfig {
  gateway: GatewayConfig;
  bypassPlainHostnames: boolean;
  bypassLocalhost: boolean;
  directSubnets: string[];   // CIDR, e.g. "10.0.0.0/8"
  directDomains: string[];   // e.g. ".corp.com", "*.internal", "host.local"
  defaultAction: "PROXY" | "DIRECT";
}

// Produces e.g. ".myorg.zscaler.net" — always appends ".net" per Zscaler spec.
function subcloudSuffix(gw: GatewayConfig): string {
  return gw.useSubcloud && gw.subcloudName && gw.subcloudCloud
    ? `.${gw.subcloudName}.${gw.subcloudCloud}.net` : "";
}

function buildGatewayVar(gw: GatewayConfig): string {
  if (gw.varType === "custom") return gw.customAddress || "gateway.zscaler.net";
  const sub = subcloudSuffix(gw);
  const hostSuffix = gw.varType === "GATEWAY_HOST" ? "_HOST" : "";
  const lbSuffix = gw.lbMode === "index" ? `_F${gw.lbIndex}` : gw.lbMode === "dynamic" ? "_FX" : "";
  return `\${GATEWAY${sub}${hostSuffix}${lbSuffix}}`;
}

function buildSecondaryVar(gw: GatewayConfig): string {
  const sub = subcloudSuffix(gw);
  // Standard (no subcloud): SECONDARY_GATEWAY; subcloud: SECONDARY.GATEWAY per Zscaler docs.
  const sep = sub ? "." : "_";
  const hostSuffix = gw.varType === "GATEWAY_HOST" ? "_HOST" : "";
  const lbSuffix = gw.lbMode === "index" ? `_F${gw.lbIndex}` : gw.lbMode === "dynamic" ? "_FX" : "";
  return `\${SECONDARY${sep}GATEWAY${sub}${hostSuffix}${lbSuffix}}`;
}

function cidrToNetMask(cidr: string): [string, string] | null {
  const parts = cidr.trim().split("/");
  if (parts.length !== 2) return null;
  const prefix = parseInt(parts[1], 10);
  if (isNaN(prefix) || prefix < 0 || prefix > 32) return null;
  const bits = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
  const mask = [(bits >>> 24) & 255, (bits >>> 16) & 255, (bits >>> 8) & 255, bits & 255].join(".");
  return [parts[0], mask];
}

function generatePac(cfg: PacBuilderConfig): string {
  const lines: string[] = ["function FindProxyForURL(url, host) {"];

  if (cfg.bypassPlainHostnames)
    lines.push('  if (isPlainHostName(host)) return "DIRECT";');

  if (cfg.bypassLocalhost)
    lines.push('  if (host === "localhost" || host === "127.0.0.1") return "DIRECT";');

  const validSubnets = cfg.directSubnets
    .map((s) => cidrToNetMask(s.trim()))
    .filter((r): r is [string, string] => r !== null);

  if (validSubnets.length > 0) {
    lines.push("  var ipAddr = dnsResolve(host);");
    lines.push("  if (ipAddr) {");
    for (const [net, mask] of validSubnets)
      lines.push(`    if (isInNet(ipAddr, "${net}", "${mask}")) return "DIRECT";`);
    lines.push("  }");
  }

  for (const raw of cfg.directDomains) {
    const p = raw.trim();
    if (!p) continue;
    if (p.startsWith("."))
      lines.push(`  if (dnsDomainIs(host, "${p}")) return "DIRECT";`);
    else if (p.includes("*") || p.includes("?"))
      lines.push(`  if (shExpMatch(host, "${p}")) return "DIRECT";`);
    else
      lines.push(`  if (host === "${p}" || dnsDomainIs(host, ".${p}")) return "DIRECT";`);
  }

  if (cfg.defaultAction === "PROXY") {
    const gw = cfg.gateway;
    const primary = buildGatewayVar(gw);
    let ret = `PROXY ${primary}:${gw.port || "9400"}`;
    if (gw.includeSecondary && gw.varType !== "custom") {
      const secondary = buildSecondaryVar(gw);
      ret += `; PROXY ${secondary}:${gw.port || "9400"}`;
    }
    if (gw.fallbackDirect) ret += "; DIRECT";
    lines.push(`  return "${ret}";`);
  } else {
    lines.push('  return "DIRECT";');
  }

  lines.push("}");
  return lines.join("\n");
}

function maskToCidr(net: string, mask: string): string {
  const parts = mask.split(".").map(Number);
  const n = ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
  let prefix = 0;
  let b = n;
  while (b & 0x80000000) { prefix++; b = (b << 1) >>> 0; }
  return `${net}/${prefix}`;
}

function defaultGatewayConfig(): GatewayConfig {
  return {
    varType: "GATEWAY", customAddress: "", lbMode: "none", lbIndex: 0,
    port: "9400", useSubcloud: false, subcloudName: "", subcloudCloud: "zscaler",
    includeSecondary: true, fallbackDirect: true,
  };
}

function parsePac(content: string): PacBuilderConfig {
  const lines = content.split("\n").map(l => l.trim()).filter(Boolean);
  const bypassPlainHostnames = lines.some(l => l.includes("isPlainHostName(host)"));
  const bypassLocalhost = lines.some(l => l.includes('host === "localhost"'));

  const directSubnets: string[] = [];
  const directDomains: string[] = [];

  for (const line of lines) {
    const subnetM = line.match(/isInNet\(ipAddr,\s*"([^"]+)",\s*"([^"]+)"\)/);
    if (subnetM) { directSubnets.push(maskToCidr(subnetM[1], subnetM[2])); continue; }

    // .domain → dnsDomainIs (no host === prefix)
    const dotM = line.match(/^if \(dnsDomainIs\(host, "(\.[^"]+)"\)\) return "DIRECT";$/);
    if (dotM) { directDomains.push(dotM[1]); continue; }

    // wildcard → shExpMatch
    const wcM = line.match(/^if \(shExpMatch\(host, "([^"]+)"\)\) return "DIRECT";$/);
    if (wcM) { directDomains.push(wcM[1]); continue; }

    // exact domain → host === "x" || dnsDomainIs
    const exactM = line.match(/^if \(host === "([^"]+)" \|\| dnsDomainIs/);
    if (exactM) { directDomains.push(exactM[1]); continue; }
  }

  const returnLine = lines.find(l => /^return "/.test(l));
  if (!returnLine || !returnLine.includes("PROXY")) {
    return { gateway: defaultGatewayConfig(), bypassPlainHostnames, bypassLocalhost, directSubnets, directDomains, defaultAction: "DIRECT" };
  }

  const proxyStr = returnLine.match(/^return "([^"]+)";$/)?.[1] ?? "";
  const tokens = proxyStr.split(";").map(t => t.trim());
  const primaryTok = tokens.find(t => t.startsWith("PROXY") && !t.includes("SECONDARY"));
  const fallbackDirect = tokens.includes("DIRECT");
  const includeSecondary = tokens.some(t => t.includes("SECONDARY"));

  const gw = defaultGatewayConfig();
  gw.fallbackDirect = fallbackDirect;
  gw.includeSecondary = includeSecondary;

  if (primaryTok) {
    const addrFull = primaryTok.replace(/^PROXY\s+/, "");
    const colonIdx = addrFull.lastIndexOf(":");
    const hostPart = colonIdx > -1 ? addrFull.slice(0, colonIdx) : addrFull;
    gw.port = colonIdx > -1 ? addrFull.slice(colonIdx + 1) : "9400";

    if (hostPart.startsWith("${") && hostPart.endsWith("}")) {
      const inner = hostPart.slice(2, -1);
      // Subcloud: GATEWAY.name.cloud.net or GATEWAY.name.cloud.net_FX / _F0
      const subM = inner.match(/^GATEWAY\.([^.]+)\.([^.]+)\.net(_FX|_F[0-7])?$/);
      if (subM) {
        gw.useSubcloud = true;
        gw.subcloudName = subM[1];
        gw.subcloudCloud = subM[2];
        if (subM[3] === "_FX") { gw.lbMode = "dynamic"; }
        else if (subM[3]) { gw.lbMode = "index"; gw.lbIndex = parseInt(subM[3][2]); }
      } else {
        // Strip lb suffix first, then check for _HOST
        const lbM = inner.match(/(_FX|_F[0-7])$/);
        const base = lbM ? inner.slice(0, -lbM[0].length) : inner;
        gw.varType = base === "GATEWAY_HOST" ? "GATEWAY_HOST" : "GATEWAY";
        if (lbM?.[0] === "_FX") { gw.lbMode = "dynamic"; }
        else if (lbM) { gw.lbMode = "index"; gw.lbIndex = parseInt(lbM[0][2]); }
      }
    } else {
      gw.varType = "custom";
      gw.customAddress = hostPart;
    }
  }

  return { gateway: gw, bypassPlainHostnames, bypassLocalhost, directSubnets, directDomains, defaultAction: "PROXY" };
}

function TagInput({
  label, placeholder, items, onChange, disabled, hint,
}: {
  label: string; placeholder: string; items: string[];
  onChange: (items: string[]) => void; disabled?: boolean; hint?: string;
}) {
  const [input, setInput] = useState("");
  function add() {
    const v = input.trim();
    if (v && !items.includes(v)) onChange([...items, v]);
    setInput("");
  }
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-500 mb-1">{hint}</p>}
      <div className="flex gap-2 mb-1.5">
        <input
          type="text" value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={placeholder} disabled={disabled}
          className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:opacity-60"
        />
        <button
          type="button" onClick={add}
          disabled={disabled || !input.trim()}
          className="px-3 py-1.5 text-xs rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60"
        >Add</button>
      </div>
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {items.map((item) => (
            <span key={item} className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 border border-blue-200 rounded text-xs text-blue-800">
              {item}
              <button
                type="button" disabled={disabled}
                onClick={() => onChange(items.filter((i) => i !== item))}
                className="text-blue-400 hover:text-blue-600 disabled:opacity-60 leading-none"
              >×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PacFileModal
// ---------------------------------------------------------------------------

function PacFileModal({
  tenantName,
  pac,
  onClose,
  onSaved,
}: {
  tenantName: string;
  pac: PacFile | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isCreate = pac === null;

  // Metadata fields
  const [name, setName] = useState(pac?.name ?? "");
  const [description, setDescription] = useState(pac?.description ?? "");
  const [commitMessage, setCommitMessage] = useState("");
  const [domain, setDomain] = useState(pac?.domain ?? "");

  // PAC builder state
  const [builder, setBuilder] = useState<PacBuilderConfig>({
    gateway: defaultGatewayConfig(),
    bypassPlainHostnames: true,
    bypassLocalhost: true,
    directSubnets: [],
    directDomains: [],
    defaultAction: "PROXY",
  });
  const [previewOpen, setPreviewOpen] = useState(false);

  // Validation
  const [validation, setValidation] = useState<{ success: boolean; message?: string; errorCount?: number } | null>(null);
  const [validating, setValidating] = useState(false);
  const [mutErr, setMutErr] = useState<string | null>(null);

  function patchBuilder(patch: Partial<PacBuilderConfig>) {
    setBuilder((b) => ({ ...b, ...patch }));
    setValidation(null);
  }

  function patchGateway(patch: Partial<GatewayConfig>) {
    setBuilder((b) => ({ ...b, gateway: { ...b.gateway, ...patch } }));
    setValidation(null);
  }

  const generatedPac = generatePac(builder);

  // Org domains dropdown
  const domainsQuery = useQuery({
    queryKey: ["zia-org-domains", tenantName],
    queryFn: () => fetchOrgDomains(tenantName),
    staleTime: 5 * 60 * 1000,
  });
  const orgDomains: string[] = domainsQuery.data ?? [];

  // Subclouds dropdown + auto-fill cloud name from zia_cloud
  const subCloudsQuery = useQuery({
    queryKey: ["zia-sub-clouds", tenantName],
    queryFn: () => fetchSubClouds(tenantName),
    staleTime: 5 * 60 * 1000,
  });
  const subClouds = subCloudsQuery.data?.subclouds ?? [];
  useEffect(() => {
    if (subCloudsQuery.data?.zia_cloud) {
      const cloud = subCloudsQuery.data.zia_cloud.replace(/\.net$/i, "");
      patchGateway({ subcloudCloud: cloud });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subCloudsQuery.data?.zia_cloud]);

  // Version history (edit mode)
  const versionsQuery = useQuery({
    queryKey: ["zia-pac-file-versions", tenantName, pac?.id],
    queryFn: () => fetchPacFileVersions(tenantName, pac!.id),
    enabled: !isCreate,
  });
  useEffect(() => {
    if (isCreate || !versionsQuery.data) return;
    const deployed = versionsQuery.data.find((v: PacFileVersion) => v.pacVersionStatus === "DEPLOYED");
    if (!deployed?.pacContent) return;
    setBuilder(parsePac(deployed.pacContent));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionsQuery.data]);

  const createMut = useMutation({
    mutationFn: (payload: PacFileCreatePayload) => createPacFile(tenantName, payload),
    onSuccess: () => { onSaved(); onClose(); },
    onError: (e: Error) => setMutErr(e.message),
  });
  const updateMut = useMutation({
    mutationFn: (payload: PacFileUpdatePayload) => updatePacFile(tenantName, pac!.id, payload),
    onSuccess: () => { onSaved(); onClose(); },
    onError: (e: Error) => setMutErr(e.message),
  });
  const isPending = createMut.isPending || updateMut.isPending;

  async function handleValidate() {
    setValidating(true);
    setValidation(null);
    try {
      const result = await validatePacFileContent(tenantName, generatedPac);
      setValidation(result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Validation request failed";
      setValidation({ success: false, message: msg });
    } finally {
      setValidating(false);
    }
  }

  function handleSubmit() {
    if (!name.trim() || !description.trim() || !commitMessage.trim()) return;
    setMutErr(null);
    const verifyStatus = validation?.success ? "VERIFY_NOERR" : "NOVERIFY";
    if (isCreate) {
      const payload: PacFileCreatePayload = {
        name: name.trim(),
        description: description.trim(),
        pac_commit_message: commitMessage.trim(),
        pac_content: generatedPac,
        pac_verification_status: verifyStatus,
        pac_version_status: "DEPLOYED",
      };
      if (domain) payload.domain = domain;
      createMut.mutate(payload);
    } else {
      updateMut.mutate({
        name: name.trim(),
        description: description.trim(),
        pac_commit_message: commitMessage.trim(),
        pac_content: generatedPac,
        pac_verification_status: verifyStatus,
        pac_version_status: "DEPLOYED",
      });
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-200 flex items-start justify-between">
          <h2 className="text-base font-semibold text-gray-900">
            {isCreate ? "Add PAC File" : `Edit PAC File: ${pac?.name}`}
          </h2>
          <button onClick={onClose} disabled={isPending} className="text-gray-400 hover:text-gray-600 ml-4">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {mutErr && <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{mutErr}</div>}

          {/* Version history (edit mode) */}
          {!isCreate && versionsQuery.data && versionsQuery.data.length > 0 && (
            <details className="border border-gray-200 rounded-md">
              <summary className="px-3 py-2 text-xs font-medium text-gray-600 cursor-pointer hover:bg-gray-50">
                Version History ({versionsQuery.data.length})
              </summary>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-1.5 text-left text-gray-500 uppercase">Ver</th>
                      <th className="px-3 py-1.5 text-left text-gray-500 uppercase">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {versionsQuery.data.map((v: PacFileVersion) => (
                      <tr key={v.pacVersion}>
                        <td className="px-3 py-1.5 font-mono text-gray-500">{v.pacVersion}</td>
                        <td className="px-3 py-1.5 text-gray-700">{v.pacVersionStatus}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(() => {
                const deployed = versionsQuery.data.find((v: PacFileVersion) => v.pacVersionStatus === "DEPLOYED");
                return deployed?.pacContent ? (
                  <details className="border-t border-gray-200">
                    <summary className="px-3 py-2 text-xs text-gray-500 cursor-pointer hover:bg-gray-50">
                      View current deployed content
                    </summary>
                    <pre className="px-3 py-2 text-xs text-gray-700 bg-gray-50 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                      {deployed.pacContent}
                    </pre>
                  </details>
                ) : null;
              })()}
            </details>
          )}

          {/* ── Metadata ── */}
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text" value={name} onChange={(e) => setName(e.target.value)}
                disabled={isPending}
                className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:opacity-60"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Description <span className="text-red-500">*</span>
              </label>
              <input
                type="text" value={description} onChange={(e) => setDescription(e.target.value)}
                disabled={isPending}
                className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:opacity-60"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Commit message <span className="text-red-500">*</span>
              </label>
              <input
                type="text" value={commitMessage} onChange={(e) => setCommitMessage(e.target.value)}
                placeholder="e.g. Initial version"
                disabled={isPending}
                className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:opacity-60"
              />
            </div>
            {isCreate && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Domain</label>
                <select
                  value={domain} onChange={(e) => setDomain(e.target.value)}
                  disabled={isPending || domainsQuery.isLoading}
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500 disabled:opacity-60 bg-white"
                >
                  <option value="">— None —</option>
                  {orgDomains.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <hr className="border-gray-200" />

          {/* ── Proxy server ── */}
          <div>
            <h3 className="text-xs font-semibold text-gray-800 uppercase tracking-wide mb-3">Proxy Configuration</h3>
            <fieldset disabled={isPending || builder.defaultAction === "DIRECT"} className="space-y-3 disabled:opacity-40">
              {/* Gateway variable type */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Gateway address</label>
                <div className="flex flex-col gap-1.5">
                  {([
                    ["GATEWAY", "${GATEWAY} — auto-resolved IP (recommended)"],
                    ["GATEWAY_HOST", "${GATEWAY_HOST} — hostname, required for Kerberos / IPv6"],
                    ["custom", "Custom hostname or IP"],
                  ] as const).map(([val, label]) => (
                    <label key={val} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                      <input
                        type="radio" name="gatewayType" value={val}
                        checked={builder.gateway.varType === val}
                        onChange={() => patchGateway({ varType: val })}
                      />
                      <span className="font-mono text-xs text-gray-600">{label}</span>
                    </label>
                  ))}
                </div>
                {builder.gateway.varType === "custom" && (
                  <input
                    type="text"
                    value={builder.gateway.customAddress}
                    onChange={(e) => patchGateway({ customAddress: e.target.value })}
                    placeholder="proxy.example.com"
                    className="mt-2 w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                  />
                )}
              </div>

              {/* Port */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Port</label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={builder.gateway.port}
                    onChange={(e) => patchGateway({ port: e.target.value })}
                    className="w-28 border border-gray-300 rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                    placeholder="9400"
                  />
                  <span className="text-xs text-gray-400">Common: 80 · 443 · 9400 · 9443 · 9480</span>
                </div>
              </div>

              {/* Load balancing — only for Zscaler variables */}
              {builder.gateway.varType !== "custom" && (
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Load balancing</label>
                  <div className="flex flex-col gap-1.5">
                    {([
                      ["none", "None — single gateway IP"],
                      ["index", "Index (F0–F7) — distribute across up to 8 VIPs"],
                      ["dynamic", "Dynamic (FX) — per-client fingerprint (ZCC only)"],
                    ] as const).map(([val, label]) => (
                      <label key={val} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                        <input
                          type="radio" name="lbMode" value={val}
                          checked={builder.gateway.lbMode === val}
                          onChange={() => patchGateway({ lbMode: val })}
                        />
                        <span className="text-xs text-gray-600">{label}</span>
                      </label>
                    ))}
                  </div>
                  {builder.gateway.lbMode === "index" && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <label className="text-xs text-gray-600">Index:</label>
                      <select
                        value={builder.gateway.lbIndex}
                        onChange={(e) => patchGateway({ lbIndex: parseInt(e.target.value, 10) })}
                        className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none"
                      >
                        {[0,1,2,3,4,5,6,7].map((i) => <option key={i} value={i}>F{i}</option>)}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {/* Subcloud */}
              {builder.gateway.varType !== "custom" && (
                <div>
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer mb-1">
                    <input
                      type="checkbox"
                      checked={builder.gateway.useSubcloud}
                      onChange={(e) => patchGateway({ useSubcloud: e.target.checked })}
                      className="rounded"
                    />
                    Organization uses a subcloud
                  </label>
                  {builder.gateway.useSubcloud && (
                    <div className="ml-5 mt-1.5 space-y-1.5">
                      <div className="flex gap-2 items-center">
                        {subClouds.length > 0 ? (
                          <select
                            value={builder.gateway.subcloudName}
                            onChange={(e) => patchGateway({ subcloudName: e.target.value })}
                            className="w-40 border border-gray-300 rounded-md px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                          >
                            <option value="">— select —</option>
                            {subClouds.map((sc) => (
                              <option key={sc.id} value={sc.name}>{sc.name}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type="text"
                            value={builder.gateway.subcloudName}
                            onChange={(e) => patchGateway({ subcloudName: e.target.value })}
                            placeholder="myorg"
                            className="w-32 border border-gray-300 rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zs-500"
                          />
                        )}
                        <span className="text-xs text-gray-400">.</span>
                        <span className="text-sm font-mono text-gray-600 min-w-[4rem]">
                          {builder.gateway.subcloudCloud || "zscaler"}
                        </span>
                        <span className="text-xs text-gray-400 font-mono">.net</span>
                      </div>
                      {subClouds.length === 0 && (
                        <p className="text-xs text-gray-400">No subclouds found in local DB — run an import first, or enter manually above.</p>
                      )}
                      {builder.gateway.subcloudName && builder.gateway.subcloudCloud && (
                        <p className="text-xs text-gray-500 font-mono">
                          → {`\${GATEWAY.${builder.gateway.subcloudName}.${builder.gateway.subcloudCloud}.net}`}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Secondary + fallback */}
              {builder.gateway.varType !== "custom" && (
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={builder.gateway.includeSecondary}
                    onChange={(e) => patchGateway({ includeSecondary: e.target.checked })}
                    className="rounded"
                  />
                  Include <code className="text-xs bg-gray-100 px-1 rounded">{"{SECONDARY_GATEWAY}"}</code> for failover
                </label>
              )}

              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={builder.gateway.fallbackDirect}
                  onChange={(e) => patchGateway({ fallbackDirect: e.target.checked })}
                  className="rounded"
                />
                Fall back to DIRECT if all proxies are unreachable
              </label>
            </fieldset>
          </div>

          <hr className="border-gray-200" />

          {/* ── DIRECT bypass rules ── */}
          <div>
            <h3 className="text-xs font-semibold text-gray-800 uppercase tracking-wide mb-3">Send DIRECT (bypass proxy)</h3>
            <div className="space-y-3">
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={builder.bypassPlainHostnames}
                    onChange={(e) => patchBuilder({ bypassPlainHostnames: e.target.checked })}
                    disabled={isPending}
                    className="rounded"
                  />
                  Plain hostnames (no dots — e.g. <code className="text-xs bg-gray-100 px-1 rounded">intranet</code>)
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={builder.bypassLocalhost}
                    onChange={(e) => patchBuilder({ bypassLocalhost: e.target.checked })}
                    disabled={isPending}
                    className="rounded"
                  />
                  Localhost (127.0.0.1)
                </label>
              </div>

              <TagInput
                label="IP subnets"
                placeholder="e.g. 10.0.0.0/8"
                hint="CIDR notation. Traffic to these ranges goes direct."
                items={builder.directSubnets}
                onChange={(v) => patchBuilder({ directSubnets: v })}
                disabled={isPending}
              />

              <TagInput
                label="Domains and host patterns"
                placeholder="e.g. .corp.example.com  or  *.internal"
                hint="Prefix with '.' for domain suffix match. Use '*' wildcards for shell-pattern match."
                items={builder.directDomains}
                onChange={(v) => patchBuilder({ directDomains: v })}
                disabled={isPending}
              />
            </div>
          </div>

          <hr className="border-gray-200" />

          {/* ── Default action ── */}
          <div>
            <h3 className="text-xs font-semibold text-gray-800 uppercase tracking-wide mb-2">Default action</h3>
            <p className="text-xs text-gray-500 mb-2">Applied to all traffic not matched by a DIRECT rule above.</p>
            <div className="flex gap-4">
              {(["PROXY", "DIRECT"] as const).map((opt) => (
                <label key={opt} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="radio"
                    name="defaultAction"
                    value={opt}
                    checked={builder.defaultAction === opt}
                    onChange={() => patchBuilder({ defaultAction: opt })}
                    disabled={isPending}
                  />
                  {opt}
                </label>
              ))}
            </div>
          </div>

          <hr className="border-gray-200" />

          {/* ── Generated PAC preview + validate ── */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-gray-800 uppercase tracking-wide">Generated PAC</h3>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleValidate}
                  disabled={validating || isPending}
                  className="px-3 py-1 text-xs rounded-md bg-blue-50 border border-blue-200 text-blue-700 hover:bg-blue-100 disabled:opacity-60"
                >
                  {validating ? "Validating…" : "Validate Syntax"}
                </button>
                {validation !== null && (
                  <span className={`text-xs font-medium ${validation.success ? "text-green-600" : "text-red-600"}`}>
                    {validation.success
                      ? "✓ Valid"
                      : `✗ ${validation.errorCount ?? 0} error(s)${validation.message ? `: ${validation.message}` : ""}`}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setPreviewOpen((o) => !o)}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  {previewOpen ? "Hide" : "Preview"}
                </button>
              </div>
            </div>
            {previewOpen && (
              <pre className="border border-gray-200 rounded-md px-3 py-3 text-xs font-mono text-gray-700 bg-gray-50 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre">
                {generatedPac}
              </pre>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-3">
          <button
            onClick={onClose} disabled={isPending}
            className="px-4 py-2 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isPending || !name.trim() || (builder.defaultAction === "PROXY" && builder.gateway.varType === "custom" && !builder.gateway.customAddress.trim())}
            className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
          >
            {isPending ? "Saving…" : isCreate ? "Create" : "Push New Version"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PacFileRow({
  tenantName,
  pac,
  onEdit,
  onDeleted,
}: {
  tenantName: string;
  pac: PacFile;
  onEdit: (p: PacFile) => void;
  onDeleted: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const deleteMut = useMutation({
    mutationFn: () => deletePacFile(tenantName, pac.id),
    onSuccess: () => onDeleted(),
    onError: (e: Error) => setDeleteErr(e.message),
  });

  const isReadOnly = pac.editable === false;

  return (
    <>
      <tr className="hover:bg-gray-50 cursor-pointer" onClick={() => setExpanded((e) => !e)}>
        <td className="px-3 py-2 font-mono text-xs text-gray-500">{pac.id}</td>
        <td className="px-3 py-2 text-gray-900">{pac.name}</td>
        <td className="px-3 py-2 text-gray-500">{pac.description ?? "-"}</td>
        <td className="px-3 py-2 text-gray-500">{pac.domain ?? "-"}</td>
        <td className="px-3 py-2 text-xs text-gray-500 font-mono">{pac.pacVersion ?? "-"}</td>
        <td className="px-3 py-2 text-xs text-gray-400 font-mono break-all">{pac.pacUrl ?? "-"}</td>
        <td className="px-3 py-2 text-xs text-gray-400">
          {pac.lastModifiedTime ? new Date(pac.lastModifiedTime * 1000).toLocaleDateString() : "-"}
        </td>
        <td className="px-3 py-2">
          <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => onEdit(pac)}
              disabled={isReadOnly || deleteMut.isPending}
              title={isReadOnly ? "Read-only (Zscaler-managed)" : "Edit"}
              className="px-2 py-1 text-xs rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40"
            >
              Edit
            </button>
            <button
              onClick={() => setConfirmDelete(true)}
              disabled={isReadOnly || deleteMut.isPending}
              title={isReadOnly ? "Read-only (Zscaler-managed)" : "Delete"}
              className="px-2 py-1 text-xs rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40"
            >
              Delete
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} className="px-3 py-2 bg-gray-50">
            {deleteErr && (
              <div className="mb-2 text-xs text-red-600">{deleteErr}</div>
            )}
            {isReadOnly && (
              <div className="text-xs text-amber-600 italic">This PAC file is read-only (Zscaler-managed).</div>
            )}
          </td>
        </tr>
      )}
      {confirmDelete && (
        <tr>
          <td colSpan={7} className="px-3 py-2 bg-red-50">
            <div className="flex items-center gap-3 text-sm text-red-700">
              <span>Delete &ldquo;{pac.name}&rdquo; and all its versions?</span>
              <button
                onClick={() => { setDeleteErr(null); deleteMut.mutate(); setConfirmDelete(false); }}
                disabled={deleteMut.isPending}
                className="px-3 py-1 text-xs rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
              >
                {deleteMut.isPending ? "Deleting..." : "Confirm Delete"}
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="px-3 py-1 text-xs rounded border border-gray-300 text-gray-700 hover:bg-white"
              >
                Cancel
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function PacFilesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [modalPac, setModalPac] = useState<PacFile | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zia-pac-files", tenantName],
    queryFn: () => fetchPacFiles(tenantName),
    enabled: isOpen,
  });

  function openCreate() { setModalPac(null); setModalOpen(true); }
  function openEdit(p: PacFile) { setModalPac(p); setModalOpen(true); }
  function closeModal() { setModalOpen(false); }
  function onSaved() { qc.invalidateQueries({ queryKey: ["zia-pac-files", tenantName] }); }

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          onClick={openCreate}
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white"
        >
          + Add PAC File
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Version</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">PAC URL</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Last Modified</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {(data ?? []).map((p: PacFile) => (
              <PacFileRow
                key={p.id}
                tenantName={tenantName}
                pac={p}
                onEdit={openEdit}
                onDeleted={() => qc.invalidateQueries({ queryKey: ["zia-pac-files", tenantName] })}
              />
            ))}
            {(data ?? []).length === 0 && (
              <tr><td colSpan={8} className="px-3 py-4 text-center text-gray-400">No PAC files</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {modalOpen && (
        <PacFileModal
          tenantName={tenantName}
          pac={modalPac}
          onClose={closeModal}
          onSaved={onSaved}
        />
      )}
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
              const expEpoch = c.valid_to_in_epoch_sec ?? null;
              const expired = expEpoch !== null && expEpoch < now;
              return (
                <tr key={c.id}>
                  <td className="px-3 py-2 text-gray-900">{c.name}</td>
                  <td className="px-3 py-2 text-gray-600">{c.issued_to ?? "-"}</td>
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

function ApplicationRow({
  a,
  onToggle,
  pending,
}: {
  a: ZpaApplication;
  onToggle: (id: string, next: boolean) => void;
  pending: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const appId = String(a.id);
  const domains = a.domain_names ?? a.domainNames ?? [];
  const serverGroups = (a.server_groups as Array<{ name?: string; id?: string }>) ?? [];
  const segmentGroupName = a.segment_group_name as string | undefined;
  const tcpPorts = (a.tcp_port_range as Array<{ from: string; to: string }>) ?? [];
  const udpPorts = (a.udp_port_range as Array<{ from: string; to: string }>) ?? [];
  const description = a.description as string | undefined;
  const shown = domains.slice(0, 3).join(", ");
  const extra = domains.length > 3 ? ` +${domains.length - 3} more` : "";

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {a.name}
        </td>
        <td className="px-3 py-2 text-gray-500">{a.application_type ?? a.applicationType ?? "-"}</td>
        <td className="px-3 py-2 text-gray-500 font-mono text-xs">{domains.length ? shown + extra : "-"}</td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <BoolToggle
            enabled={!!a.enabled}
            onToggle={(next) => onToggle(appId, next)}
            pending={pending}
          />
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3 text-xs space-y-3">
            {description && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Description</span>
                <p className="mt-0.5 text-gray-700">{description}</p>
              </div>
            )}
            {domains.length > 0 && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Domains / IPs</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {domains.map((d, i) => (
                    <span key={i} className="inline-block bg-gray-100 rounded px-2 py-0.5 font-mono">{d}</span>
                  ))}
                </div>
              </div>
            )}
            {(tcpPorts.length > 0 || udpPorts.length > 0) && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Ports</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {tcpPorts.map((p, i) => (
                    <span key={`tcp-${i}`} className="inline-block bg-blue-50 text-blue-700 rounded px-2 py-0.5 font-mono">TCP {p.from === p.to ? p.from : `${p.from}–${p.to}`}</span>
                  ))}
                  {udpPorts.map((p, i) => (
                    <span key={`udp-${i}`} className="inline-block bg-purple-50 text-purple-700 rounded px-2 py-0.5 font-mono">UDP {p.from === p.to ? p.from : `${p.from}–${p.to}`}</span>
                  ))}
                </div>
              </div>
            )}
            {serverGroups.length > 0 && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Server Groups</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {serverGroups.map((g, i) => (
                    <span key={i} className="inline-block bg-gray-100 rounded px-2 py-0.5 font-mono">{g.name ?? g.id}</span>
                  ))}
                </div>
              </div>
            )}
            {segmentGroupName && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Segment Group</span>
                <p className="mt-0.5 text-gray-700 font-mono">{segmentGroupName}</p>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function ApplicationsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-applications", tenantName],
    queryFn: () => fetchApplications(tenantName),
    enabled: isOpen,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchApplicationEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-applications", tenantName] });
    },
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
            {filtered.map((a: ZpaApplication) => (
              <ApplicationRow
                key={a.id}
                a={a}
                onToggle={(id, next) => { setPendingToggleId(id); toggleMut.mutate({ id, enabled: next }); }}
                pending={pendingToggleId === String(a.id)}
              />
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

function UserPortalsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-user-portals", tenantName],
    queryFn: () => fetchUserPortals(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchUserPortalEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-user-portals", tenantName] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteUserPortal(tenantName, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zpa-user-portals", tenantName] }),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const portalToDelete = confirmDeleteId ? data.find((p) => p.zpa_id === confirmDeleteId) : null;

  return (
    <div className="space-y-3">
      {confirmDeleteId && portalToDelete && (
        <ConfirmDialog
          title="Delete User Portal"
          message={`Delete user portal "${portalToDelete.name}"? This cannot be undone.`}
          onConfirm={() => { deleteMut.mutate(confirmDeleteId); setConfirmDeleteId(null); }}
          onCancel={() => setConfirmDeleteId(null)}
          destructive
        />
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Certificate</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.map((p: ZpaUserPortal) => (
              <tr key={p.zpa_id}>
                <td className="px-3 py-2 text-gray-900">{p.name}</td>
                <td className="px-3 py-2 text-gray-500 font-mono text-xs">{p.domain ?? "-"}</td>
                <td className="px-3 py-2 text-gray-500">{p.certificate_name ?? "-"}</td>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                  <BoolToggle
                    enabled={p.enabled ?? false}
                    onToggle={(next) => {
                      setPendingToggleId(p.zpa_id);
                      toggleMut.mutate({ id: p.zpa_id, enabled: next });
                    }}
                    pending={pendingToggleId === p.zpa_id}
                  />
                </td>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => setConfirmDeleteId(p.zpa_id)}
                    className="text-xs text-red-500 hover:underline"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-400">No user portals</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PraPortalsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-pra-portals", tenantName],
    queryFn: () => fetchPraPortals(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchPraPortalEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-pra-portals", tenantName] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePraPortal(tenantName, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zpa-pra-portals", tenantName] }),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const portalToDelete = confirmDeleteId ? data.find((p) => p.zpa_id === confirmDeleteId) : null;

  return (
    <div className="space-y-3">
      {confirmDeleteId && portalToDelete && (
        <ConfirmDialog
          title="Delete PRA Portal"
          message={`Delete PRA portal "${portalToDelete.name}"? This cannot be undone.`}
          onConfirm={() => { deleteMut.mutate(confirmDeleteId); setConfirmDeleteId(null); }}
          onCancel={() => setConfirmDeleteId(null)}
          destructive
        />
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Certificate</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.map((p: ZpaPraPortal) => (
              <tr key={p.zpa_id}>
                <td className="px-3 py-2 text-gray-900">{p.name}</td>
                <td className="px-3 py-2 text-gray-500 font-mono text-xs">{p.domain ?? "-"}</td>
                <td className="px-3 py-2 text-gray-500">{p.certificate_name ?? "-"}</td>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                  <BoolToggle
                    enabled={p.enabled ?? false}
                    onToggle={(next) => {
                      setPendingToggleId(p.zpa_id);
                      toggleMut.mutate({ id: p.zpa_id, enabled: next });
                    }}
                    pending={pendingToggleId === p.zpa_id}
                  />
                </td>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => setConfirmDeleteId(p.zpa_id)}
                    className="text-xs text-red-500 hover:underline"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-400">No PRA portals</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AppConnectorsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-connectors", tenantName],
    queryFn: () => listConnectors(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchConnectorEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-connectors", tenantName] });
    },
  });

  const renameMut = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      patchConnectorName(tenantName, id, name),
    onSuccess: () => {
      setRenamingId(null);
      qc.invalidateQueries({ queryKey: ["zpa-connectors", tenantName] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteConnector(tenantName, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zpa-connectors", tenantName] }),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((c: ZpaAppConnector) =>
    c.name.toLowerCase().includes(filter.toLowerCase())
  );
  const connectorToDelete = confirmDeleteId
    ? data.find((c) => (c.zpa_id ?? c.id) === confirmDeleteId)
    : null;

  return (
    <div className="space-y-3">
      {confirmDeleteId && connectorToDelete && (
        <ConfirmDialog
          title="Delete App Connector"
          message={`Delete connector "${connectorToDelete.name}"? This cannot be undone.`}
          onConfirm={() => { deleteMut.mutate(confirmDeleteId); setConfirmDeleteId(null); }}
          onCancel={() => setConfirmDeleteId(null)}
          destructive
        />
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
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((c: ZpaAppConnector) => {
              const rowId = c.zpa_id ?? c.id ?? "";
              return (
                <tr key={rowId}>
                  <td className="px-3 py-2 text-gray-900">
                    {renamingId === rowId ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          className="border border-gray-300 rounded px-2 py-0.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                          autoFocus
                        />
                        <button
                          onClick={() => renameMut.mutate({ id: rowId, name: renameValue })}
                          disabled={renameMut.isPending}
                          className="text-xs text-zs-500 hover:underline disabled:opacity-50"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setRenamingId(null)}
                          className="text-xs text-gray-500 hover:underline"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      c.name
                    )}
                  </td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <BoolToggle
                      enabled={c.enabled ?? false}
                      onToggle={(next) => {
                        setPendingToggleId(rowId);
                        toggleMut.mutate({ id: rowId, enabled: next });
                      }}
                      pending={pendingToggleId === rowId}
                    />
                  </td>
                  <td className="px-3 py-2 space-x-3" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => { setRenamingId(rowId); setRenameValue(c.name); }}
                      className="text-xs text-zs-500 hover:underline"
                    >
                      Rename
                    </button>
                    <button
                      onClick={() => setConfirmDeleteId(rowId)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No app connectors</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ServiceEdgesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-service-edges", tenantName],
    queryFn: () => listServiceEdges(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchServiceEdgeEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-service-edges", tenantName] });
    },
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((e: ZpaServiceEdge) =>
    e.name.toLowerCase().includes(filter.toLowerCase())
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
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((e: ZpaServiceEdge) => {
              const rowId = e.zpa_id ?? e.id ?? "";
              return (
                <tr key={rowId}>
                  <td className="px-3 py-2 text-gray-900">{e.name}</td>
                  <td className="px-3 py-2" onClick={(ev) => ev.stopPropagation()}>
                    <BoolToggle
                      enabled={e.enabled ?? false}
                      onToggle={(next) => {
                        setPendingToggleId(rowId);
                        toggleMut.mutate({ id: rowId, enabled: next });
                      }}
                      pending={pendingToggleId === rowId}
                    />
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No service edges</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SegmentGroupRow({ g }: { g: ZpaSegmentGroup }) {
  const [expanded, setExpanded] = useState(false);
  const apps = (g.applications as Array<{ id: string; name: string }>) ?? [];
  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 font-mono text-xs text-gray-500">{g.id}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {g.name}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={2} className="bg-gray-50 px-4 py-3">
            {apps.length === 0 ? (
              <p className="text-xs text-gray-400">No application segments.</p>
            ) : (
              <div className="text-xs text-gray-700">
                <div className="font-medium text-gray-500 uppercase tracking-wide mb-1">Application Segments</div>
                <div className="flex flex-wrap gap-1.5">
                  {apps.map((app) => (
                    <span key={app.id} className="inline-block bg-gray-100 rounded px-2 py-0.5 font-mono">{app.name}</span>
                  ))}
                </div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
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
            <SegmentGroupRow key={g.id} g={g} />
          ))}
          {data.length === 0 && (
            <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No segment groups</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ConnectorGroupsSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-connector-groups", tenantName],
    queryFn: () => listConnectorGroups(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchConnectorGroupEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-connector-groups", tenantName] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteConnectorGroup(tenantName, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zpa-connector-groups", tenantName] }),
  });

  const createMut = useMutation({
    mutationFn: () => createConnectorGroup(tenantName, newName, newDesc || undefined),
    onSuccess: () => {
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      qc.invalidateQueries({ queryKey: ["zpa-connector-groups", tenantName] });
    },
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((g: ZpaConnectorGroup) =>
    g.name.toLowerCase().includes(filter.toLowerCase())
  );
  const groupToDelete = confirmDeleteId
    ? data.find((g) => (g.zpa_id ?? g.id) === confirmDeleteId)
    : null;

  return (
    <div className="space-y-3">
      {confirmDeleteId && groupToDelete && (
        <ConfirmDialog
          title="Delete Connector Group"
          message={`Delete connector group "${groupToDelete.name}"? This cannot be undone.`}
          onConfirm={() => { deleteMut.mutate(confirmDeleteId); setConfirmDeleteId(null); }}
          onCancel={() => setConfirmDeleteId(null)}
          destructive
        />
      )}
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Filter by name..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="px-3 py-1.5 text-sm bg-zs-500 text-white rounded-md hover:bg-zs-600 transition-colors"
        >
          Create Group
        </button>
      </div>
      {showCreate && (
        <div className="border border-gray-200 rounded-md p-3 bg-gray-50 space-y-2">
          <h4 className="text-sm font-semibold text-gray-700">New Connector Group</h4>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Description (optional)</label>
              <input
                type="text"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              />
            </div>
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => createMut.mutate()}
              disabled={!newName.trim() || createMut.isPending}
              className="px-3 py-1.5 text-xs bg-zs-500 text-white rounded hover:bg-zs-600 disabled:opacity-50 transition-colors"
            >
              {createMut.isPending ? "Creating..." : "Create"}
            </button>
            <button
              onClick={() => { setShowCreate(false); setNewName(""); setNewDesc(""); }}
              className="px-3 py-1.5 text-xs border border-gray-300 text-gray-700 rounded hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
          </div>
          {createMut.isError && (
            <p className="text-xs text-red-500">
              {createMut.error instanceof Error ? createMut.error.message : "Create failed"}
            </p>
          )}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((g: ZpaConnectorGroup) => {
              const rowId = g.zpa_id ?? g.id ?? "";
              return (
                <tr key={rowId}>
                  <td className="px-3 py-2 text-gray-900">{g.name}</td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <BoolToggle
                      enabled={g.enabled ?? false}
                      onToggle={(next) => {
                        setPendingToggleId(rowId);
                        toggleMut.mutate({ id: rowId, enabled: next });
                      }}
                      pending={pendingToggleId === rowId}
                    />
                  </td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => setConfirmDeleteId(rowId)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No connector groups</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PraConsolesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [pendingToggleId, setPendingToggleId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-pra-consoles", tenantName],
    queryFn: () => listPraConsoles(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchPraConsoleEnabled(tenantName, id, enabled),
    onSettled: () => {
      setPendingToggleId(null);
      qc.invalidateQueries({ queryKey: ["zpa-pra-consoles", tenantName] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePraConsole(tenantName, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["zpa-pra-consoles", tenantName] }),
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((c: ZpaPraConsole) =>
    c.name.toLowerCase().includes(filter.toLowerCase())
  );
  const consoleToDelete = confirmDeleteId
    ? data.find((c) => (c.zpa_id ?? c.id) === confirmDeleteId)
    : null;

  return (
    <div className="space-y-3">
      {confirmDeleteId && consoleToDelete && (
        <ConfirmDialog
          title="Delete PRA Console"
          message={`Delete PRA console "${consoleToDelete.name}"? This cannot be undone.`}
          onConfirm={() => { deleteMut.mutate(confirmDeleteId); setConfirmDeleteId(null); }}
          onCancel={() => setConfirmDeleteId(null)}
          destructive
        />
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
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((c: ZpaPraConsole) => {
              const rowId = c.zpa_id ?? c.id ?? "";
              return (
                <tr key={rowId}>
                  <td className="px-3 py-2 text-gray-900">{c.name}</td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <BoolToggle
                      enabled={c.enabled ?? false}
                      onToggle={(next) => {
                        setPendingToggleId(rowId);
                        toggleMut.mutate({ id: rowId, enabled: next });
                      }}
                      pending={pendingToggleId === rowId}
                    />
                  </td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => setConfirmDeleteId(rowId)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No PRA consoles</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AccessPolicyRuleRow({ r }: { r: ZpaAccessPolicyRule }) {
  const [expanded, setExpanded] = useState(false);

  const conditions = (r.conditions as Array<{ operator?: string; operands?: Array<{ object_type?: string; entry_values?: Array<{ lhs: string; rhs: string }>; values?: Array<{ lhs: string; rhs: string }> }> }>) ?? [];
  const connectorGroups = (r.app_connector_groups as Array<{ name?: string; id?: string }>) ?? [];
  const serverGroups = (r.app_server_groups as Array<{ name?: string; id?: string }>) ?? [];
  const serviceEdgeGroups = (r.service_edge_groups as Array<{ name?: string; id?: string }>) ?? [];

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded((x) => !x)}>
        <td className="px-3 py-2 text-gray-500">{r.rule_order ?? "-"}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {r.name}
        </td>
        <td className="px-3 py-2">
          {r.action ? (
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                r.action === "ALLOW" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
              }`}
            >
              {r.action}
            </span>
          ) : (
            <span className="text-gray-400">-</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={3} className="bg-gray-50 px-4 py-3 text-xs space-y-3">
            {!!r.description && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Description</span>
                <p className="mt-0.5 text-gray-700">{String(r.description)}</p>
              </div>
            )}
            {conditions.length > 0 && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">
                  Conditions {r.operator ? `(${String(r.operator)})` : ""}
                </span>
                <div className="mt-1 space-y-1">
                  {conditions.map((cond, ci) => {
                    const operands = cond.operands ?? [];
                    return operands.map((op, oi) => {
                      const entries = (op.entry_values ?? op.values ?? []).slice(0, 6);
                      const label = op.object_type ?? "UNKNOWN";
                      return (
                        <div key={`${ci}-${oi}`} className="flex items-start gap-2">
                          <span className="inline-block bg-blue-50 text-blue-700 rounded px-1.5 py-0.5 font-mono uppercase flex-shrink-0">{label}</span>
                          <span className="text-gray-600">
                            {entries.map((e) => e.rhs ?? e.lhs).join(", ") || "(any)"}
                          </span>
                        </div>
                      );
                    });
                  })}
                </div>
              </div>
            )}
            {connectorGroups.length > 0 && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Connector Groups</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {connectorGroups.map((g, i) => (
                    <span key={i} className="inline-block bg-gray-100 rounded px-2 py-0.5 font-mono">{g.name ?? g.id}</span>
                  ))}
                </div>
              </div>
            )}
            {serverGroups.length > 0 && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Server Groups</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {serverGroups.map((g, i) => (
                    <span key={i} className="inline-block bg-gray-100 rounded px-2 py-0.5 font-mono">{g.name ?? g.id}</span>
                  ))}
                </div>
              </div>
            )}
            {serviceEdgeGroups.length > 0 && (
              <div>
                <span className="font-medium text-gray-500 uppercase tracking-wide">Service Edge Groups</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {serviceEdgeGroups.map((g, i) => (
                    <span key={i} className="inline-block bg-gray-100 rounded px-2 py-0.5 font-mono">{g.name ?? g.id}</span>
                  ))}
                </div>
              </div>
            )}
            {!r.description && conditions.length === 0 && connectorGroups.length === 0 && serverGroups.length === 0 && serviceEdgeGroups.length === 0 && (
              <p className="text-gray-400">No additional details.</p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function AccessPolicySection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [filter, setFilter] = useState("");
  const [exporting, setExporting] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-access-policy", tenantName],
    queryFn: () => listAccessPolicyRules(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  const filtered = data.filter((r: ZpaAccessPolicyRule) =>
    r.name.toLowerCase().includes(filter.toLowerCase())
  );

  async function handleExport() {
    setExporting(true);
    try {
      await exportAccessPolicyCsv(tenantName, tenantName);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Filter by name..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
        <button
          onClick={handleExport}
          disabled={exporting}
          className="px-3 py-1.5 text-sm border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          {exporting ? "Exporting..." : "Export to CSV"}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Order</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {filtered.map((r: ZpaAccessPolicyRule) => {
              const rowId = r.zpa_id ?? r.id ?? r.name;
              return <AccessPolicyRuleRow key={rowId} r={r} />;
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={3} className="px-3 py-4 text-center text-gray-400">No access policy rules</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IdentitySection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const [samlFilter, setSamlFilter] = useState("");
  const [scimAttrFilter, setScimAttrFilter] = useState("");
  const [scimGroupFilter, setScimGroupFilter] = useState("");

  const { data: samlData, isLoading: samlLoading, error: samlError } = useQuery({
    queryKey: ["zpa-saml-attrs", tenantName],
    queryFn: () => listSamlAttributes(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const { data: scimAttrData, isLoading: scimAttrLoading, error: scimAttrError } = useQuery({
    queryKey: ["zpa-scim-attrs", tenantName],
    queryFn: () => listScimAttributes(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const { data: scimGroupData, isLoading: scimGroupLoading, error: scimGroupError } = useQuery({
    queryKey: ["zpa-scim-groups", tenantName],
    queryFn: () => listScimGroups(tenantName),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const filteredSaml = (samlData ?? []).filter((a: ZpaSamlAttribute) =>
    a.name.toLowerCase().includes(samlFilter.toLowerCase())
  );
  const filteredScimAttrs = (scimAttrData ?? []).filter((a: ZpaScimAttribute) =>
    a.name.toLowerCase().includes(scimAttrFilter.toLowerCase())
  );
  const filteredScimGroups = (scimGroupData ?? []).filter((g: ZpaScimGroup) =>
    g.name.toLowerCase().includes(scimGroupFilter.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* SAML Attributes */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">SAML Attributes</h4>
        <input
          type="text"
          placeholder="Filter SAML attributes..."
          value={samlFilter}
          onChange={(e) => setSamlFilter(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
        {samlLoading ? (
          <LoadingSpinner />
        ) : samlError ? (
          <ErrorMessage message={samlError instanceof Error ? samlError.message : "Failed to load"} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">IdP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filteredSaml.map((a: ZpaSamlAttribute) => {
                  const rowId = a.zpa_id ?? a.id ?? a.name;
                  return (
                    <tr key={rowId}>
                      <td className="px-3 py-2 text-gray-900">{a.name}</td>
                      <td className="px-3 py-2 text-gray-500">{(a.idpName as string) ?? (a.idp_name as string) ?? "-"}</td>
                    </tr>
                  );
                })}
                {filteredSaml.length === 0 && (
                  <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No SAML attributes</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* SCIM Attributes */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">SCIM Attributes</h4>
        <input
          type="text"
          placeholder="Filter SCIM attributes..."
          value={scimAttrFilter}
          onChange={(e) => setScimAttrFilter(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
        {scimAttrLoading ? (
          <LoadingSpinner />
        ) : scimAttrError ? (
          <ErrorMessage message={scimAttrError instanceof Error ? scimAttrError.message : "Failed to load"} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Data Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filteredScimAttrs.map((a: ZpaScimAttribute) => {
                  const rowId = a.zpa_id ?? a.id ?? a.name;
                  return (
                    <tr key={rowId}>
                      <td className="px-3 py-2 text-gray-900">{a.name}</td>
                      <td className="px-3 py-2 text-gray-500">{(a.dataType as string) ?? (a.data_type as string) ?? "-"}</td>
                    </tr>
                  );
                })}
                {filteredScimAttrs.length === 0 && (
                  <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No SCIM attributes</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* SCIM Groups */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">SCIM Groups</h4>
        <input
          type="text"
          placeholder="Filter SCIM groups..."
          value={scimGroupFilter}
          onChange={(e) => setScimGroupFilter(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
        {scimGroupLoading ? (
          <LoadingSpinner />
        ) : scimGroupError ? (
          <ErrorMessage message={scimGroupError instanceof Error ? scimGroupError.message : "Failed to load"} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">IdP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filteredScimGroups.map((g: ZpaScimGroup) => {
                  const rowId = g.zpa_id ?? g.id ?? g.name;
                  return (
                    <tr key={rowId}>
                      <td className="px-3 py-2 text-gray-900">{g.name}</td>
                      <td className="px-3 py-2 text-gray-500">{(g.idpName as string) ?? (g.idp_name as string) ?? "-"}</td>
                    </tr>
                  );
                })}
                {filteredScimGroups.length === 0 && (
                  <tr><td colSpan={2} className="px-3 py-4 text-center text-gray-400">No SCIM groups</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
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
  1: "iOS",
  2: "Android",
  3: "Windows",
  4: "macOS",
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
          <h3 className="text-base font-semibold text-gray-900 mb-1">OTP for {device.machine_hostname as string ?? device.udid}</h3>
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
                <td className="px-3 py-2 text-gray-900">{d.machine_hostname as string ?? "-"}</td>
                <td className="px-3 py-2 text-gray-600">{d.user as string ?? "-"}</td>
                <td className="px-3 py-2 text-gray-500">
                  {(d.type as number) ? OS_TYPE_LABELS[d.type as number] ?? String(d.type) : "-"}
                </td>
                <td className="px-3 py-2 text-gray-500">{d.registration_state as string ?? "-"}</td>
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

// ── Forwarding Profiles expandable section ────────────────────────────────────

const FP_NET_TYPE: Record<number, string> = {
  0: "Off Network",
  1: "On Trusted Network",
  2: "VPN Trusted Network",
};

function fpModeLabel(action: ZccFpAction): string {
  if ((action.action_type ?? 0) === 3) return "ZCC Bypass";
  if (action.enable_packet_tunnel === 1) return "Z-Tunnel 2.0";
  const spd = action.system_proxy_data;
  if ((action.system_proxy ?? 0) === 2 || spd?.enable_proxy_server) return "Proxy";
  return "Z-Tunnel 1.0";
}

function fpModeClass(mode: string): string {
  if (mode === "Z-Tunnel 2.0") return "bg-green-50 text-green-700";
  if (mode === "Z-Tunnel 1.0") return "bg-blue-50 text-blue-700";
  if (mode === "Proxy") return "bg-yellow-50 text-yellow-700";
  return "bg-gray-100 text-gray-500";
}

function ForwardingProfileRow({ fp }: { fp: ZccForwardingProfile }) {
  const [expanded, setExpanded] = useState(false);
  const actions = (fp.forwarding_profile_actions ?? []) as ZccFpAction[];
  const zpaActions = (fp.forwarding_profile_zpa_actions ?? []) as ZccFpZpaAction[];
  const sortedActions = [...actions]
    .filter(a => (a.network_type ?? 0) in FP_NET_TYPE)
    .sort((a, b) => (a.network_type ?? 0) - (b.network_type ?? 0));
  const tnList = (fp.trusted_networks ?? []) as string[];
  const isActive = fp.active === "1" || fp.active === 1 || fp.active === true;

  return (
    <>
      <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setExpanded(x => !x)}>
        <td className="px-3 py-2 font-mono text-xs text-gray-500">{fp.id ?? "-"}</td>
        <td className="px-3 py-2 text-gray-900 flex items-center gap-1.5">
          <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
          {fp.name ?? "-"}
        </td>
        <td className="px-3 py-2">
          <span className={`px-1.5 py-0.5 rounded-full text-xs ${isActive ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"}`}>
            {isActive ? "Active" : "Inactive"}
          </span>
        </td>
        <td className="px-3 py-2 text-xs text-gray-500">
          {fp.predefined_tn_all ? "All" : tnList.length > 0 ? tnList.join(", ") : "—"}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} className="bg-gray-50 px-4 py-3">
            <div className="overflow-x-auto rounded border border-gray-200">
              <table className="min-w-full text-xs divide-y divide-gray-200">
                <thead className="bg-white">
                  <tr>
                    <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Network Context</th>
                    <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Tunnel Mode</th>
                    <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Transport</th>
                    <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">ZPA</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {sortedActions.map((action, ai) => {
                    const netType = action.network_type ?? 0;
                    const mode = fpModeLabel(action);
                    const transport = action.primary_transport === 1 ? "DTLS" : "TLS";
                    const zpaAction = zpaActions.find(z => z.network_type === netType);
                    const zpaOn = zpaAction && (zpaAction.action_type ?? 0) !== 0;
                    return (
                      <tr key={ai}>
                        <td className="px-3 py-1.5 font-medium text-gray-700">{FP_NET_TYPE[netType] ?? `Type ${netType}`}</td>
                        <td className="px-3 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${fpModeClass(mode)}`}>{mode}</span>
                        </td>
                        <td className="px-3 py-1.5 text-gray-600">{mode !== "ZCC Bypass" ? transport : "—"}</td>
                        <td className="px-3 py-1.5">
                          {zpaOn
                            ? <span className="px-1.5 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700">On</span>
                            : <span className="text-gray-400">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function ForwardingProfilesSection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["zcc-forwarding-profiles", tenantName],
    queryFn: () => listForwardingProfiles(tenantName),
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
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Trusted Networks</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {(data as ZccForwardingProfile[]).map((fp, i) => (
            <ForwardingProfileRow key={fp.id ?? i} fp={fp} />
          ))}
          {data.length === 0 && (
            <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">No forwarding profiles</td></tr>
          )}
        </tbody>
      </table>
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
  product: "ZIA" | "ZPA" | "ZCC";
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [mutErr, setMutErr] = useState<string | null>(null);
  const [resetMsg, setResetMsg] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      product === "ZIA" ? importZIA(tenant.id) :
      product === "ZPA" ? importZPA(tenant.id) :
      importZCC(tenant.id),
    onSuccess: (data) => setJobId(data.job_id),
    onError: (e: Error) => setMutErr(e.message),
  });

  const resetMut = useMutation({
    mutationFn: () => clearZCCDisabledResources(tenant.id),
    onSuccess: (data) => setResetMsg(
      data.cleared.length > 0
        ? `Cleared: ${data.cleared.join(", ")}. Run import to retry.`
        : "No disabled resources to clear."
    ),
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
          {resetMsg && <p className="text-xs text-blue-700 bg-blue-50 px-3 py-2 rounded">{resetMsg}</p>}
          {isDone && result && (
            <div className={`p-3 rounded-md text-sm ${result.status === "SUCCESS" || result.status === "PARTIAL" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
              <p className="font-medium">{result.status}</p>
              <p className="text-xs mt-1">{result.resources_synced} synced, {result.resources_updated} updated</p>
              {result.error_message && <p className="text-xs mt-1">{result.error_message}</p>}
            </div>
          )}
          <div className="flex justify-between gap-2">
            {product === "ZCC" && !isDone && !isRunning && (
              <button
                onClick={() => { setResetMsg(null); resetMut.mutate(); }}
                disabled={resetMut.isPending}
                title="Clear any resource types that were auto-disabled after a previous API error, so they will be retried on the next import"
                className="px-3 py-2 text-xs rounded-md border border-gray-300 hover:bg-gray-50 text-gray-600 disabled:opacity-60"
              >
                {resetMut.isPending ? "Clearing…" : "Reset N/A Resources"}
              </button>
            )}
            <div className="flex gap-2 ml-auto">
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

type TabId = "zia" | "zpa" | "zdx" | "zcc" | "zid" | "sim";

// ── Traffic Simulator tab ─────────────────────────────────────────────────────

const PROTOCOLS = ["HTTPS", "HTTP", "TCP", "UDP", "DNS", "FTP", "SMTP", "SSH"];

const VERDICT_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  ZPA:                { bg: "bg-blue-50",  text: "text-blue-800",  label: "ZPA" },
  ZIA_ALLOW:          { bg: "bg-green-50", text: "text-green-800", label: "ZIA Allow" },
  ZIA_BLOCK_FIREWALL: { bg: "bg-red-50",   text: "text-red-800",   label: "ZIA Block" },
  ZIA_BLOCK_DNS:      { bg: "bg-red-50",   text: "text-red-800",   label: "ZIA Block" },
  ZIA_BLOCK_URL:      { bg: "bg-red-50",   text: "text-red-800",   label: "ZIA Block" },
  INTERNET:           { bg: "bg-gray-50",  text: "text-gray-700",  label: "Internet" },
};

function PolicyCheckCard({ check }: { check: PolicyCheck }) {
  const actionColor =
    check.action && ["BLOCK", "BLOCK_DROP", "BLOCK_ICMP", "BLOCK_RESET", "BLOCK_BYPASS"].includes(check.action.toUpperCase())
      ? "text-red-700 bg-red-50"
      : check.action === "ALLOW"
      ? "text-green-700 bg-green-50"
      : "text-gray-700 bg-gray-100";

  return (
    <div className={`rounded-lg border p-4 space-y-2 ${check.matched ? "border-gray-300 bg-white" : "border-gray-200 bg-gray-50"}`}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-sm font-medium text-gray-800">{check.engine}</span>
        <div className="flex items-center gap-2">
          {check.matched ? (
            <>
              {check.action && (
                <span className={`text-xs font-semibold px-2 py-0.5 rounded ${actionColor}`}>
                  {check.action}
                </span>
              )}
              <span className="text-xs bg-gray-200 text-gray-700 px-2 py-0.5 rounded">Matched</span>
            </>
          ) : (
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">No match</span>
          )}
        </div>
      </div>
      <p className="text-xs text-gray-600">{check.reason}</p>
      {check.rule_name && (
        <p className="text-xs text-gray-500">Rule: <span className="font-medium text-gray-700">{check.rule_name}</span></p>
      )}
      {check.category && (
        <p className="text-xs text-gray-500">Category: <span className="font-medium text-gray-700">{check.category}</span></p>
      )}
      {check.caveats.length > 0 && (
        <div className="mt-1 space-y-1">
          {check.caveats.map((c, i) => (
            <p key={i} className="text-xs text-amber-700 bg-amber-50 px-2 py-1 rounded">⚠ {c}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function SimulatorTab({ tenant }: { tenant: Tenant }) {
  const [dest, setDest] = useState("");
  const [port, setPort] = useState("443");
  const [protocol, setProtocol] = useState("HTTPS");
  const [nwApp, setNwApp] = useState("");
  const [appSvcGroup, setAppSvcGroup] = useState("");
  const [srcIp, setSrcIp] = useState("");
  const [userName, setUserName] = useState("");
  const [deptName, setDeptName] = useState("");
  const [groupName, setGroupName] = useState("");
  const [locationName, setLocationName] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const { data: appOptions = [] } = useQuery({ queryKey: ["sim-applications", tenant.id], queryFn: () => fetchSimApplications(tenant.id) });
  const { data: appSvcGroupOptions = [] } = useQuery({ queryKey: ["sim-app-service-groups", tenant.id], queryFn: () => fetchSimAppServiceGroups(tenant.id) });
  const { data: userOptions = [] } = useQuery({ queryKey: ["sim-users", tenant.id], queryFn: () => fetchSimUsers(tenant.id) });
  const { data: deptOptions = [] } = useQuery({ queryKey: ["sim-depts", tenant.id], queryFn: () => fetchSimDepartments(tenant.id) });
  const { data: groupOptions = [] } = useQuery({ queryKey: ["sim-groups", tenant.id], queryFn: () => fetchSimGroups(tenant.id) });
  const { data: locationOptions = [] } = useQuery({ queryKey: ["sim-locations", tenant.id], queryFn: () => fetchSimLocations(tenant.id) });

  const mut = useMutation({
    mutationFn: () => simulateTraffic(tenant.id, {
      destination: dest.trim(), port: parseInt(port) || 443, protocol,
      nwApplication: nwApp.trim() || undefined,
      appServiceGroup: appSvcGroup.trim() || undefined,
      srcIp: srcIp.trim() || undefined,
      userName: userName.trim() || undefined,
      deptName: deptName.trim() || undefined,
      groupName: groupName.trim() || undefined,
      locationName: locationName.trim() || undefined,
    }),
    onSuccess: (data) => { setResult(data); setErr(null); },
    onError: (e: Error) => setErr(e.message),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!dest.trim()) return;
    setResult(null);
    mut.mutate();
  }

  // Auto-set port when protocol changes
  function handleProtocol(p: string) {
    setProtocol(p);
    const defaults: Record<string, string> = { HTTPS: "443", HTTP: "80", DNS: "53", FTP: "21", SMTP: "25", SSH: "22" };
    if (defaults[p]) setPort(defaults[p]);
  }

  const verdictStyle = result ? (VERDICT_STYLES[result.verdict] ?? VERDICT_STYLES.INTERNET) : null;

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Traffic Simulator</h2>
        <p className="mt-1 text-sm text-gray-500">
          Evaluate how a connection would be handled against ZPA application segments and ZIA firewall,
          DNS, and URL filtering policies — based on your last imported data.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="sm:col-span-1">
            <label className="block text-xs font-medium text-gray-700 mb-1">Destination</label>
            <input
              type="text"
              value={dest}
              onChange={e => setDest(e.target.value)}
              placeholder="8.8.8.8 or example.com"
              className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Protocol</label>
            <select
              value={protocol}
              onChange={e => handleProtocol(e.target.value)}
              className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500"
            >
              {PROTOCOLS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Port</label>
            <input
              type="number"
              min={1}
              max={65535}
              value={port}
              onChange={e => setPort(e.target.value)}
              className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500"
            />
          </div>
        </div>
        {/* Advanced Options toggle */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(v => !v)}
            className="text-xs text-zs-600 hover:text-zs-700 font-medium flex items-center gap-1"
          >
            <svg className={`h-3 w-3 transition-transform ${showAdvanced ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Advanced Options
          </button>
        </div>

        {showAdvanced && (
          <div className="space-y-3 pt-1 border-t border-gray-100">
            {/* Row 1: app-layer */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Network Application</label>
                <input list="nw-app-options" type="text" value={nwApp} onChange={e => setNwApp(e.target.value)}
                  placeholder="e.g. QUIC, HTTP2"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <datalist id="nw-app-options">{appOptions.map(a => <option key={a} value={a} />)}</datalist>
                <p className="mt-0.5 text-xs text-gray-400">Matches nw_applications rules (e.g. BLOCK_QUIC)</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">App Service Group</label>
                <input list="app-svc-group-options" type="text" value={appSvcGroup} onChange={e => setAppSvcGroup(e.target.value)}
                  placeholder="e.g. OFFICE365, ZOOM"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <datalist id="app-svc-group-options">{appSvcGroupOptions.map(g => <option key={g} value={g} />)}</datalist>
                <p className="mt-0.5 text-xs text-gray-400">Matches app_service_groups rules (e.g. Office365, UCaaS)</p>
              </div>
            </div>
            {/* Row 2: source */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Source IP</label>
                <input type="text" value={srcIp} onChange={e => setSrcIp(e.target.value)}
                  placeholder="e.g. 10.0.0.5"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <p className="mt-0.5 text-xs text-gray-400">Evaluates src_ip_groups constraints</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Location</label>
                <input list="location-options" type="text" value={locationName} onChange={e => setLocationName(e.target.value)}
                  placeholder="e.g. HQ, Branch-NYC"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <datalist id="location-options">{locationOptions.map(l => <option key={l} value={l} />)}</datalist>
                <p className="mt-0.5 text-xs text-gray-400">Evaluates location-scoped rules</p>
              </div>
            </div>
            {/* Row 3: identity */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">User</label>
                <input list="user-options" type="text" value={userName} onChange={e => setUserName(e.target.value)}
                  placeholder="username or email"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <datalist id="user-options">{userOptions.map(u => <option key={u} value={u} />)}</datalist>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Department</label>
                <input list="dept-options" type="text" value={deptName} onChange={e => setDeptName(e.target.value)}
                  placeholder="department name"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <datalist id="dept-options">{deptOptions.map(d => <option key={d} value={d} />)}</datalist>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Group</label>
                <input list="group-options" type="text" value={groupName} onChange={e => setGroupName(e.target.value)}
                  placeholder="group name"
                  className="w-full text-sm px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-zs-500" />
                <datalist id="group-options">{groupOptions.map(g => <option key={g} value={g} />)}</datalist>
              </div>
            </div>
            <p className="text-xs text-gray-400">
              Identity and location fields narrow scoped rules. If left blank, scoped rules are evaluated permissively (worst-case assumption).
            </p>
          </div>
        )}
        {err && <p className="text-xs text-red-600">{err}</p>}
        <button
          type="submit"
          disabled={mut.isPending || !dest.trim()}
          className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
        >
          {mut.isPending ? "Simulating…" : "Simulate"}
        </button>
      </form>

      {result && (
        <div className="space-y-4">
          {/* Verdict banner */}
          <div className={`rounded-xl border p-4 ${verdictStyle!.bg}`}>
            <div className="flex items-center gap-3">
              <span className={`text-sm font-bold px-3 py-1 rounded-full border ${verdictStyle!.text} border-current`}>
                {verdictStyle!.label}
              </span>
              <span className={`text-sm font-medium ${verdictStyle!.text}`}>{result.verdict_label}</span>
            </div>
          </div>

          {/* Step-by-step checks */}
          <div className="space-y-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Policy Evaluation Chain</p>
            <PolicyCheckCard check={result.zpa} />
            <PolicyCheckCard check={result.zia_firewall} />
            <PolicyCheckCard check={result.zia_dns} />
            <PolicyCheckCard check={result.zia_url} />
          </div>

          <p className="text-xs text-gray-400">
            Results are based on your last imported policy snapshot. Predefined URL categories,
            user/group scoping, and time-based rules require a live ZIA lookup for full accuracy.
          </p>
        </div>
      )}
    </div>
  );
}

function TerraformExportPanel({ tenant, product }: { tenant: Tenant; product: "zia" | "zpa" }) {
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleExport() {
    setErr(null);
    setPending(true);
    try {
      await downloadTerraform(tenant.id, product, tenant.name);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Export failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3 p-1">
      <p className="text-sm text-gray-600">
        Generate a <code className="text-xs bg-gray-100 px-1 rounded">.tf</code> file from your
        imported {product.toUpperCase()} configuration using the{" "}
        <a
          href="https://registry.terraform.io/providers/zscaler/zscaler/latest"
          target="_blank"
          rel="noopener noreferrer"
          className="text-zs-600 hover:underline"
        >
          Zscaler Terraform provider
        </a>
        . Cross-references between resources are flagged as comments for manual wiring.
      </p>
      {err && <p className="text-xs text-red-600">{err}</p>}
      <button
        onClick={handleExport}
        disabled={pending}
        className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
      >
        {pending ? "Generating…" : `Export ${product.toUpperCase()} as Terraform`}
      </button>
      <p className="text-xs text-gray-400">
        Requires a completed import. Run import first if your data is stale.
      </p>
    </div>
  );
}

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

      {/* Traffic Forwarding */}
      <SectionGroup title="Traffic Forwarding" isOpen={!!groups.trafficFwd} onToggle={() => toggleGroup("trafficFwd")}>
        <Accordion title="Forwarding Rules" isOpen={!!open.forwarding} onToggle={() => toggle("forwarding")}>
          <ForwardingRulesSection tenantName={tenant.name} isOpen={!!open.forwarding} />
        </Accordion>
        <Accordion title="PAC Files" isOpen={!!open.pacFiles} onToggle={() => toggle("pacFiles")}>
          <PacFilesSection tenantName={tenant.name} isOpen={!!open.pacFiles} />
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

      {/* Terraform Export */}
      <SectionGroup title="Terraform Export" isOpen={!!groups.terraform} onToggle={() => toggleGroup("terraform")}>
        <TerraformExportPanel tenant={tenant} product="zia" />
      </SectionGroup>
    </div>
  );
}

// ── ZpaRestoreModal ────────────────────────────────────────────────────────────

function ZpaRestoreModal({
  tenant,
  snapshot,
  onClose,
}: {
  tenant: Tenant;
  snapshot: ConfigSnapshot;
  onClose: () => void;
}) {
  const [restoreJobId, setRestoreJobId] = useState<string | null>(null);
  const [mutErr, setMutErr] = useState<string | null>(null);

  const diffQuery = useQuery({
    queryKey: ["zpa-snapshot-diff", tenant.name, snapshot.id],
    queryFn: () => fetchZpaSnapshotDiff(tenant.name, snapshot.id),
    staleTime: 30_000,
  });

  const restoreMut = useMutation({
    mutationFn: () => restoreZpaSnapshot(tenant.name, snapshot.id),
    onSuccess: (data) => { setRestoreJobId(data.job_id); setMutErr(null); },
    onError: (e: Error) => setMutErr(e.message),
  });

  const {
    latestByPhase: restoreProgress,
    jobStatus: restoreJobStatus,
    result: restoreResult,
    streamError: restoreStreamError,
  } = useJobStream<ZpaRestoreResult>(restoreJobId);

  const isRestoreRunning = restoreMut.isPending || restoreJobStatus === "running";
  const restoreDone = restoreJobStatus === "done";
  const diff = diffQuery.data;
  const err = mutErr ?? restoreStreamError ?? null;

  const ACTION_COLORS: Record<string, string> = {
    create: "text-green-700 bg-green-50",
    update: "text-blue-700 bg-blue-50",
    delete: "text-red-700 bg-red-50",
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-200 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Restore ZPA Snapshot</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {snapshot.label || formatDateTime(snapshot.created_at)} · {snapshot.resource_count} resources
            </p>
          </div>
          {!isRestoreRunning && (
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

          {/* Restore result */}
          {restoreDone && restoreResult && (
            <div className="space-y-3">
              <div className={`p-3 rounded-md text-sm ${restoreResult.failed > 0 ? "bg-amber-50 text-amber-800" : "bg-green-50 text-green-800"}`}>
                <p className="font-medium">Restore complete</p>
                <p className="text-xs mt-1">
                  {restoreResult.applied} applied · {restoreResult.skipped} skipped
                  {restoreResult.failed > 0 && ` · ${restoreResult.failed} failed`}
                </p>
              </div>
              {restoreResult.items.filter(i => i.status === "manual").length > 0 && (
                <div>
                  <p className="text-xs font-medium text-amber-700 mb-1">Manual action required:</p>
                  <div className="max-h-32 overflow-y-auto border border-amber-200 rounded-md divide-y divide-amber-100 text-xs">
                    {restoreResult.items.filter(i => i.status === "manual").map((item, i) => (
                      <div key={i} className="px-3 py-1.5 bg-white">
                        <span className="font-mono text-gray-500">{item.resource_type}</span> · {item.name}
                        <p className="text-amber-700 mt-0.5">{item.reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {restoreResult.items.filter(i => i.status === "failed").length > 0 && (
                <div>
                  <p className="text-xs font-medium text-red-700 mb-1">Failed:</p>
                  <div className="max-h-32 overflow-y-auto border border-red-200 rounded-md divide-y divide-red-100 text-xs">
                    {restoreResult.items.filter(i => i.status === "failed").map((item, i) => (
                      <div key={i} className="px-3 py-1.5 bg-white">
                        <span className="font-mono text-gray-500">{item.resource_type}</span> · {item.name}
                        <p className="text-red-700 font-mono break-all mt-0.5">{item.reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <button onClick={onClose} className="text-xs text-zs-600 hover:underline">Close</button>
            </div>
          )}

          {/* Restore running */}
          {isRestoreRunning && (
            <div className="space-y-1.5">
              <p className="text-xs text-gray-500">
                {restoreProgress["restore"]
                  ? `${(restoreProgress["restore"] as any).action ?? ""} ${restoreProgress["restore"].resource_type}: ${restoreProgress["restore"].name ?? ""} (${restoreProgress["restore"].done}/${restoreProgress["restore"].total})`
                  : "Applying changes…"}
              </p>
              <ImportProgressBar active />
            </div>
          )}

          {/* Diff preview + confirm */}
          {!restoreDone && !isRestoreRunning && (
            <>
              {diffQuery.isLoading && <LoadingSpinner />}
              {diffQuery.error && <ErrorMessage message={diffQuery.error instanceof Error ? diffQuery.error.message : "Failed to load diff"} />}
              {diff && (
                <div className="space-y-3">
                  <div className="flex gap-4 text-xs">
                    <span className="text-green-700 font-medium">{diff.creates} to create</span>
                    <span className="text-blue-700 font-medium">{diff.updates} to update</span>
                    <span className="text-red-700 font-medium">{diff.deletes} to delete</span>
                  </div>

                  {diff.creates + diff.updates + diff.deletes === 0 ? (
                    <p className="text-sm text-gray-500">Current state already matches this snapshot.</p>
                  ) : (
                    <>
                      <div className="max-h-56 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100 text-xs">
                        {diff.items.map((item, i) => (
                          <div key={i} className="flex items-center justify-between px-3 py-1.5 bg-white">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className={`shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_COLORS[item.action] ?? ""}`}>
                                {item.action}
                              </span>
                              <span className="font-mono text-gray-400 shrink-0">{item.resource_type}</span>
                              <span className="text-gray-700 truncate">{item.name}</span>
                            </div>
                            {!item.supported && (
                              <span className="shrink-0 text-amber-600 ml-2">manual</span>
                            )}
                          </div>
                        ))}
                      </div>
                      <p className="text-xs text-gray-400">
                        Items marked "manual" (creates, complex config updates) must be applied outside the web UI.
                        Only supported operations (enable/disable, delete) will be executed automatically.
                      </p>
                      <button
                        onClick={() => restoreMut.mutate()}
                        disabled={restoreMut.isPending}
                        className="w-full px-3 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
                      >
                        Apply Restore
                      </button>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ZpaSnapshotsSection({ tenant, isOpen }: { tenant: Tenant; isOpen: boolean }) {
  const qc = useQueryClient();
  const [labelInput, setLabelInput] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<ConfigSnapshot | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["zpa-snapshots", tenant.name],
    queryFn: () => fetchSnapshots(tenant.name, "ZPA"),
    enabled: isOpen,
  });

  const createMut = useMutation({
    mutationFn: () => createSnapshot(tenant.name, labelInput.trim() || undefined, "ZPA"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zpa-snapshots", tenant.name] });
      setLabelInput("");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteSnapshot(tenant.name, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zpa-snapshots", tenant.name] });
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
        <ZpaRestoreModal
          tenant={tenant}
          snapshot={restoreTarget}
          onClose={() => setRestoreTarget(null)}
        />
      )}

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
        <Accordion title="Connector Groups" isOpen={!!open.connectorGroups} onToggle={() => toggle("connectorGroups")}>
          <ConnectorGroupsSection tenantName={tenant.name} isOpen={!!open.connectorGroups} />
        </Accordion>
        <Accordion title="Service Edges" isOpen={!!open.serviceEdges} onToggle={() => toggle("serviceEdges")}>
          <ServiceEdgesSection tenantName={tenant.name} isOpen={!!open.serviceEdges} />
        </Accordion>
      </SectionGroup>

      {/* Access Policy */}
      <SectionGroup title="Access Policy" isOpen={!!groups.accessPolicy} onToggle={() => toggleGroup("accessPolicy")}>
        <Accordion title="Access Policy Rules" isOpen={!!open.accessPolicyRules} onToggle={() => toggle("accessPolicyRules")}>
          <AccessPolicySection tenantName={tenant.name} isOpen={!!open.accessPolicyRules} />
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

      {/* Identity */}
      <SectionGroup title="Identity" isOpen={!!groups.identity} onToggle={() => toggleGroup("identity")}>
        <Accordion title="SAML / SCIM" isOpen={!!open.identity} onToggle={() => toggle("identity")}>
          <IdentitySection tenantName={tenant.name} isOpen={!!open.identity} />
        </Accordion>
      </SectionGroup>

      {/* Certificates */}
      <SectionGroup title="Certificates" isOpen={!!groups.certs} onToggle={() => toggleGroup("certs")}>
        <Accordion title="Browser Access Certificates" isOpen={!!open.certificates} onToggle={() => toggle("certificates")}>
          <CertificatesSection tenantName={tenant.name} isOpen={!!open.certificates} />
        </Accordion>
      </SectionGroup>

      {/* User Portals */}
      <SectionGroup title="User Portals" isOpen={!!groups.userPortals} onToggle={() => toggleGroup("userPortals")}>
        <Accordion title="User Portals" isOpen={!!open.userPortals} onToggle={() => toggle("userPortals")}>
          <UserPortalsSection tenantName={tenant.name} isOpen={!!open.userPortals} />
        </Accordion>
      </SectionGroup>

      {/* PRA */}
      <SectionGroup title="Privileged Remote Access (PRA)" isOpen={!!groups.pra} onToggle={() => toggleGroup("pra")}>
        <Accordion title="PRA Portals" isOpen={!!open.praPortals} onToggle={() => toggle("praPortals")}>
          <PraPortalsSection tenantName={tenant.name} isOpen={!!open.praPortals} />
        </Accordion>
        <Accordion title="PRA Consoles" isOpen={!!open.praConsoles} onToggle={() => toggle("praConsoles")}>
          <PraConsolesSection tenantName={tenant.name} isOpen={!!open.praConsoles} />
        </Accordion>
      </SectionGroup>

      {/* Config Snapshots */}
      <SectionGroup title="Config Snapshots" isOpen={!!groups.snapshots} onToggle={() => toggleGroup("snapshots")}>
        <Accordion title="Snapshots" isOpen={!!open.snapshots} onToggle={() => toggle("snapshots")}>
          <ZpaSnapshotsSection tenant={tenant} isOpen={!!open.snapshots} />
        </Accordion>
      </SectionGroup>

      {/* Terraform Export */}
      <SectionGroup title="Terraform Export" isOpen={!!groups.terraform} onToggle={() => toggleGroup("terraform")}>
        <TerraformExportPanel tenant={tenant} product="zpa" />
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

// ── App Profile Visualizer ────────────────────────────────────────────────────

const OS_DISPLAY: Record<string, { label: string; cls: string }> = {
  windows: { label: "Windows",  cls: "bg-blue-50 text-blue-700" },
  macos:   { label: "macOS",    cls: "bg-gray-100 text-gray-700" },
  ios:     { label: "iOS",      cls: "bg-indigo-50 text-indigo-700" },
  android: { label: "Android",  cls: "bg-green-50 text-green-700" },
  linux:   { label: "Linux",    cls: "bg-yellow-50 text-yellow-700" },
};

function OsBadge({ os }: { os: string }) {
  const d = OS_DISPLAY[os.toLowerCase()] ?? { label: os, cls: "bg-gray-50 text-gray-600" };
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${d.cls}`}>{d.label}</span>
  );
}

function AppProfileVisualizer({
  tenantName,
  policyId,
  policyName,
  onClose,
}: {
  tenantName: string;
  policyId: string;
  policyName: string;
  onClose: () => void;
}) {
  const [activeSection, setActiveSection] = useState<string>("tunnel");
  const [hovered, setHovered] = useState<string | null>(null);
  const [networkContext, setNetworkContext] = useState<"off" | "on" | "vpn">("off");
  const [simDest, setSimDest] = useState("");
  const [simPort, setSimPort] = useState("443");
  const [simResult, setSimResult] = useState<{ outcome: string; color: string; reasons: { text: string; source: string }[] } | null>(null);

  const { data, isLoading, error } = useQuery<TrafficProfile>({
    queryKey: ["traffic-profile", tenantName, policyId],
    queryFn: () => fetchTrafficProfile(tenantName, policyId),
  });

  const { data: zpaApps } = useQuery<ZpaApplication[]>({
    queryKey: ["zpa-applications", tenantName],
    queryFn: () => fetchApplications(tenantName),
    enabled: data?.zpaEnabled === true,
  });

  useEffect(() => {
    if (!data) return;
    const candidates: Array<[string, number | boolean]> = [
      ["tunnel",  data.tunnelRoutes.filter(r => r.direction === "include").length],
      ["dns",     data.dnsRoutes.length],
      ["zpa",     data.zpaEnabled],
      ["process", data.processBypasses.length],
      ["port",    data.portBypasses.length],
      ["pac",     data.pac.enablePac || !!data.pac.url || !!data.pac.profilePacUrl],
    ];
    const first = candidates.find(([, v]) => Boolean(v));
    if (first) setActiveSection(first[0]);
  }, [data]);

  const TUNNEL_COLOR: Record<TunnelMode, string> = {
    "Z-Tunnel 2.0": "#22c55e",
    "Z-Tunnel 1.0": "#3b82f6",
    "Proxy":        "#eab308",
    "Unknown":      "#9ca3af",
  };

  const tc = data ? (TUNNEL_COLOR[data.tunnelMode] ?? "#9ca3af") : "#9ca3af";
  const bypassCount = data
    ? data.processBypasses.length + data.portBypasses.length + data.vpnGatewayBypasses.length
    : 0;
  const excludeCount = data ? data.tunnelRoutes.filter(r => r.direction === "exclude").length : 0;
  const totalBypassCount = bypassCount;

  const tunnelActive = ["tunnel", "dns", "pac"].includes(activeSection);
  const bypassActive = ["process", "port"].includes(activeSection);
  const zpaActive = activeSection === "zpa";

  const tabs: Array<{ key: string; label: string; count: number | null; group: string }> = [];
  if (data) {
    if (data.dnsRoutes.length > 0)          tabs.push({ key: "dns",     label: "DNS Routes",        count: data.dnsRoutes.length,          group: "zia"    });
    if (data.processBypasses.length > 0)    tabs.push({ key: "process", label: "Process Bypasses",  count: data.processBypasses.length,    group: "bypass" });
    if (data.pac.enablePac || data.pac.url || data.pac.profilePacUrl) tabs.push({ key: "pac",     label: "PAC Config",        count: null,                          group: "zia"    });
  }

  const tabBtnClass = (key: string, group: string) => {
    const active = activeSection === key;
    const base = "px-3 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer";
    if (!active) return `${base} bg-gray-100 text-gray-600 hover:bg-gray-200`;
    if (group === "zia")     return `${base} bg-green-100 text-green-800 ring-1 ring-green-300`;
    if (group === "bypass")  return `${base} bg-orange-100 text-orange-800 ring-1 ring-orange-300`;
    if (group === "zpa")     return `${base} bg-indigo-100 text-indigo-800 ring-1 ring-indigo-300`;
    return `${base} bg-purple-100 text-purple-800 ring-1 ring-purple-300`;
  };

  const ZIA_MODE_LABEL: Record<TunnelMode, string> = {
    "Z-Tunnel 2.0": "All traffic — web + non-web",
    "Z-Tunnel 1.0": "Web traffic only (HTTP/S)",
    "Proxy":        "PAC-controlled proxy",
    "Unknown":      "Unknown routing mode",
  };

  // Per-context forwarding profile actions from rawForwardingSnippet
  const fpRaw = data?.rawForwardingSnippet;
  const fpAllActions = (fpRaw
    ? ((fpRaw.forwardingProfileActions as unknown[]) ?? (fpRaw.forwarding_profile_actions as unknown[]) ?? [])
    : []) as Array<Record<string, unknown>>;
  const fpZpaActionsRaw = (fpRaw
    ? ((fpRaw.forwardingProfileZpaActions as unknown[]) ?? (fpRaw.forwarding_profile_zpa_actions as unknown[]) ?? [])
    : []) as Array<Record<string, unknown>>;
  const NC_INT: Record<string, number> = { on: 1, vpn: 2, off: 0 };
  const getCtxFpAction = (ctx: string): Record<string, unknown> =>
    fpAllActions.find(a => Number(a.networkType ?? a.network_type) === NC_INT[ctx]) ?? {};
  // Base Z-Tunnel 2.0 mode per context — enable_packet_tunnel is the overall ZT2 switch
  const ctxIsZT2Base = (ctx: string): boolean => {
    const a = getCtxFpAction(ctx);
    if (Object.keys(a).length === 0) return data?.tunnelMode === "Z-Tunnel 2.0";
    return a.enablePacketTunnel === 1 || a.enable_packet_tunnel === 1;
  };

  // "Redirect Web Traffic to ZCC Listening Proxy" checkbox per context
  // API field: redirect_web_traffic (snake_case DB) or redirectWebTraffic (camelCase HTTP)
  const ctxHasLP = (ctx: string): boolean => {
    const a = getCtxFpAction(ctx);
    if (Object.keys(a).length === 0) return data?.listeningProxy ?? false;
    return Boolean(a.redirectWebTraffic || a.redirect_web_traffic);
  };

  // "Use Z-Tunnel 2.0 for Proxied Web Traffic" checkbox per context
  // API field: use_tunnel2_for_proxied_web_traffic (snake_case DB) or useTunnel2ForProxiedWebTraffic (camelCase HTTP)
  const ctxHasZT2Proxied = (ctx: string): boolean => {
    const a = getCtxFpAction(ctx);
    if (Object.keys(a).length === 0) return false;
    return Boolean(a.useTunnel2ForProxiedWebTraffic || a.use_tunnel2_for_proxied_web_traffic);
  };

  const ctxModeStr = (ctx: string): string => {
    const a = getCtxFpAction(ctx);
    if (Object.keys(a).length === 0) return data?.tunnelMode ?? "";
    if ((a.actionType ?? a.action_type) === 3) return "ZCC Bypass";
    // Base tunnel mode is determined by enable_packet_tunnel
    if (a.enablePacketTunnel === 1 || a.enable_packet_tunnel === 1) return "Z-Tunnel 2.0";
    const spd = (a.systemProxyData ?? a.system_proxy_data ?? {}) as Record<string, unknown>;
    if (spd.enableProxyServer || spd.enable_proxy_server) return "Proxy";
    return "Z-Tunnel 1.0";
  };
  const ctxTransStr = (ctx: string): string =>
    (getCtxFpAction(ctx).primaryTransport ?? getCtxFpAction(ctx).primary_transport) === 1 ? "DTLS" : "TLS";
  const ctxZpaOn = (ctx: string): boolean => {
    if (fpZpaActionsRaw.length === 0) return data?.zpaEnabled ?? false;
    const getAt = (c: string): number | null => {
      const a = fpZpaActionsRaw.find(x => Number(x.networkType ?? x.network_type) === NC_INT[c]);
      if (!a) return null;
      const v = a.actionType ?? a.action_type;
      return v === null || v === undefined ? null : Number(v);
    };
    // on-trusted:  0=None(off),  1=Tunnel(on)
    // vpn-trusted: 0=None(off),  1=Same-as-On
    // off-trusted: 0=Tunnel(on), 1=Same-as-On
    const onAt  = getAt("on");
    const onOn  = onAt === 1;
    if (ctx === "on")  return onOn;
    if (ctx === "vpn") { const at = getAt("vpn"); return at === 1 ? onOn : at === 0 ? false : (data?.zpaEnabled ?? false); }
    if (ctx === "off") { const at = getAt("off"); return at === 0 ? true  : at === 1 ? onOn  : (data?.zpaEnabled ?? false); }
    return data?.zpaEnabled ?? false;
  };

  const ctxDetailedMode = (ctx: string): "T2.0+LP" | "T2.0" | "T1.0" | "LP+T1.0" | "Proxy" | "Bypass" | "Unknown" => {
    const a = getCtxFpAction(ctx);
    if (Object.keys(a).length === 0) {
      if (!data) return "Unknown";
      if (data.tunnelMode === "Z-Tunnel 2.0") return data.listeningProxy ? "T2.0+LP" : "T2.0";
      if (data.tunnelMode === "Proxy") return "Proxy";
      return "T1.0";
    }
    if ((a.actionType ?? a.action_type) === 3) return "Bypass";
    const isZT2Base = ctxIsZT2Base(ctx);
    const hasLP     = ctxHasLP(ctx);
    const hasZT2P   = ctxHasZT2Proxied(ctx);
    if (isZT2Base) {
      if (hasLP) return hasZT2P ? "T2.0+LP" : "LP+T1.0";
      return "T2.0";
    }
    if (hasLP) return "Proxy";
    return "T1.0";
  };
  const detailedMode = ctxDetailedMode(networkContext);
  // PAC is evaluated when LP is active (web hits the listening proxy which applies app profile PAC)
  // or when the base mode is not ZT2 (ZT1/Proxy always evaluate PAC).
  // Pure ZT2 with no LP skips PAC entirely.
  const lpActive = ctxHasLP(networkContext);
  const zt2ProxiedActive = ctxHasZT2Proxied(networkContext);
  const pacEvaluated = detailedMode !== "T2.0" && detailedMode !== "Bypass" && detailedMode !== "Unknown";
  const pacBypasses: Array<{ label: string; detail: string }> = data?.pac?.bypasses ?? [];
  const pacAppBypasses: Array<{ label: string; detail: string }> = data?.pac?.appProfileBypasses ?? [];
  const totalPacBypasses = pacBypasses.length + pacAppBypasses.length;
  const localActive = pacEvaluated || excludeCount > 0;

  const localSubtitle = data
    ? pacEvaluated
      ? (() => {
          const parts: string[] = [];
          if (excludeCount > 0) parts.push(`${excludeCount} exclusion${excludeCount !== 1 ? "s" : ""}`);
          if (totalPacBypasses > 0) parts.push(`${totalPacBypasses} PAC bypass${totalPacBypasses !== 1 ? "es" : ""}`);
          const suffix = parts.length ? ` · ${parts.join(" · ")}` : "";
          return lpActive ? `PAC DIRECT — web only${suffix}` : `PAC DIRECT${suffix}`;
        })()
      : excludeCount > 0 || pacBypasses.length > 0
        ? (() => {
            const parts: string[] = [];
            if (excludeCount > 0) parts.push(`${excludeCount} tunnel exclusion${excludeCount !== 1 ? "s" : ""}`);
            if (totalPacBypasses > 0) parts.push(`${totalPacBypasses} PAC bypass${totalPacBypasses !== 1 ? "es" : ""}`);
            return parts.join(" · ");
          })()
        : "No explicit exclusions"
    : "";

  // ── Traffic simulator helpers ──────────────────────────────────────────────
  const _ipToNum = (ip: string): number => {
    const p = ip.split(".").map(Number);
    if (p.length !== 4 || p.some(isNaN)) return -1;
    return ((p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]) >>> 0;
  };
  const _isValidIP = (s: string) =>
    /^\d{1,3}(\.\d{1,3}){3}$/.test(s) && s.split(".").every(x => +x <= 255);
  const _inCIDR = (ip: string, cidr: string): boolean => {
    const [net, bits] = cidr.split("/");
    const prefix = parseInt(bits);
    if (isNaN(prefix)) return false;
    const ipN = _ipToNum(ip), netN = _ipToNum(net);
    if (ipN < 0 || netN < 0) return false;
    const mask = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
    return (ipN & mask) === (netN & mask);
  };
  const _isRFC1918 = (ip: string) =>
    _inCIDR(ip, "10.0.0.0/8") || _inCIDR(ip, "172.16.0.0/12") ||
    _inCIDR(ip, "192.168.0.0/16") || _inCIDR(ip, "127.0.0.0/8") ||
    _inCIDR(ip, "169.254.0.0/16") || _inCIDR(ip, "192.88.99.0/24");
  const _shExp = (host: string, pat: string): boolean => {
    const re = pat.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
    return new RegExp(`^${re}$`, "i").test(host);
  };

  const runSimulator = () => {
    if (!data || !simDest.trim()) return;
    const dest = simDest.trim().toLowerCase();
    const port = parseInt(simPort) || 443;
    const isIP = _isValidIP(dest);
    const reasons: { text: string; source: string }[] = [];

    // 1. Port bypass
    for (const pb of data.portBypasses) {
      if (pb.port === String(port) || pb.port === "*") {
        setSimResult({ outcome: "Direct", color: "orange", reasons: [{ text: `Port ${port} matches port bypass rule`, source: "Port Bypass" }] });
        return;
      }
    }

    // 2. Tunnel CIDR exclusion
    if (isIP) {
      for (const r of data.tunnelRoutes.filter(r => r.direction === "exclude")) {
        if (_inCIDR(dest, r.cidr)) {
          setSimResult({ outcome: "Direct", color: "orange", reasons: [{ text: `${dest} falls within tunnel exclusion ${r.cidr}`, source: "Tunnel Exclusion" }] });
          return;
        }
      }
    }

    // 3. PAC bypass rules
    const allPac = [
      ...pacBypasses.map(b => ({ ...b, src: "Forwarding Profile PAC", url: data.pac.profilePacUrl })),
      ...pacAppBypasses.map(b => ({ ...b, src: "App Profile PAC", url: data.pac.url })),
    ];
    for (const rule of allPac) {
      const lbl = rule.label;
      const srcDetail = rule.src;
      // RFC1918
      if (lbl.includes("RFC1918") && isIP && _isRFC1918(dest)) {
        reasons.push({ text: `${dest} is an RFC1918 private IP`, source: srcDetail });
        setSimResult({ outcome: "Direct", color: "orange", reasons });
        return;
      }
      // isInNet CIDR rule (label starts with x.x.x.x/n)
      const cidrM = lbl.match(/^(\d[\d.]+\/\d+)/);
      if (cidrM && isIP && _inCIDR(dest, cidrM[1])) {
        reasons.push({ text: `${dest} matches isInNet rule ${cidrM[1]}`, source: srcDetail });
        setSimResult({ outcome: "Direct", color: "orange", reasons });
        return;
      }
      // Plain hostname
      if (lbl.includes("Plain hostnames") && !isIP && !dest.includes(".")) {
        reasons.push({ text: `"${dest}" is a plain (unqualified) hostname`, source: srcDetail });
        setSimResult({ outcome: "Direct", color: "orange", reasons });
        return;
      }
      // shExpMatch domain pattern
      if (lbl.endsWith("→ DIRECT") && !isIP) {
        const pat = lbl.replace(/\s*→\s*DIRECT$/, "").trim();
        if ((pat.includes("*") || pat.includes(".")) && _shExp(dest, pat)) {
          reasons.push({ text: `"${dest}" matches domain pattern "${pat}"`, source: srcDetail });
          setSimResult({ outcome: "Direct", color: "orange", reasons });
          return;
        }
      }
      // Non-HTTP/S
      if (lbl.includes("Non-HTTP/S") && port !== 80 && port !== 443 && port !== 8080) {
        reasons.push({ text: `Port ${port} is not HTTP/HTTPS — bypassed by PAC`, source: srcDetail });
        setSimResult({ outcome: "Direct", color: "orange", reasons });
        return;
      }
    }

    // 4. Default → ZIA
    const tunnelLabel = detailedMode === "T2.0" ? "Z-Tunnel 2.0 (DTLS)" : detailedMode === "T2.0+LP" ? "Z-Tunnel 2.0 via LP" : data.tunnelMode;
    setSimResult({
      outcome: "ZIA",
      color: "green",
      reasons: [{ text: `No bypass rules matched — routed to ZIA via ${tunnelLabel}`, source: "Default" }],
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-6xl max-h-[90vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <h2 className="text-base font-semibold text-gray-900">ZCC — Traffic Profile</h2>
            <p className="text-xs text-gray-500 mt-0.5">{policyName}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          {isLoading && <LoadingSpinner />}
          {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load traffic profile"} />}

          {data && (
            <>
              {/* ── Node-map diagram ──────────────────────────────────────── */}
              {/* Layout (viewBox 0 0 860 225):
                  Device (8,86) — ZCC (136,76) — junction x=305 trunk y=50..166
                  3 Network Context nodes (314, y=27/85/143) w=172 h=46
                  All 3 connect → right fork trunk x=510 y=38..180
                  Fork → ZIA(524,14) / ZPA(524,73) / Local(524,156)
                  Bypass branch: junction dot on Device→ZCC wire (x=122,y=108) → down */}
              <div className="rounded-xl border border-gray-200 bg-gradient-to-br from-gray-50 to-white overflow-hidden select-none">
                <svg
                  viewBox="0 0 908 225"
                  xmlns="http://www.w3.org/2000/svg"
                  className="w-full"
                  style={{ display: "block" }}
                >
                  <defs>
                    <marker id="tp3-arr-gray"  markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill="#d1d5db"/></marker>
                    <marker id="tp3-arr-zia"   markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill={tc}/></marker>
                    <marker id="tp3-arr-zpa"   markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill="#4f46e5"/></marker>
                    <marker id="tp3-arr-local" markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill="#f97316"/></marker>
                    <marker id="tp3-arr-on"   markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill="#7c3aed"/></marker>
                    <marker id="tp3-arr-off"  markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill="#0d9488"/></marker>
                    <marker id="tp3-arr-lp"   markerWidth="7" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3z" fill="#2563eb"/></marker>
                    <filter id="tp3-shadow"><feDropShadow dx="0" dy="1" stdDeviation="2" floodOpacity="0.08"/></filter>
                  </defs>

                  {/* ── Left-side edges ──────────────────────────────────────── */}
                  <line x1="108" y1="108" x2="186" y2="108" stroke={tc} strokeWidth="2" markerEnd="url(#tp3-arr-zia)"/>
                  <line x1="336" y1="108" x2="358" y2="108" stroke={tc} strokeWidth="2"/>
                  <line x1="358" y1="50"  x2="358" y2="166" stroke="#e5e7eb" strokeWidth="2"/>
                  {/* Colored overlay from junction center to selected context */}
                  {networkContext !== "vpn" && (
                    <line x1="358" y1="108" x2="358"
                      y2={networkContext === "on" ? 50 : 166}
                      stroke={networkContext === "on" ? "#7c3aed" : "#0d9488"} strokeWidth="2"/>
                  )}
                  <line x1="358" y1="50"  x2="385" y2="50"
                    stroke={networkContext === "on" ? "#7c3aed" : "#d1d5db"} strokeWidth="1.5"
                    markerEnd={networkContext === "on" ? "url(#tp3-arr-on)" : "url(#tp3-arr-gray)"}/>
                  <line x1="358" y1="108" x2="385" y2="108"
                    stroke={networkContext === "vpn" ? "#4f46e5" : "#d1d5db"} strokeWidth="1.5"
                    markerEnd={networkContext === "vpn" ? "url(#tp3-arr-zpa)" : "url(#tp3-arr-gray)"}/>
                  <line x1="358" y1="166" x2="385" y2="166"
                    stroke={networkContext === "off" ? "#0d9488" : "#d1d5db"} strokeWidth="1.5"
                    markerEnd={networkContext === "off" ? "url(#tp3-arr-off)" : "url(#tp3-arr-gray)"}/>


                  {/* ── App bypass branch: L-shape from Device→ZCC wire to Local/Direct ─ */}
                  {totalBypassCount > 0 && (
                    <>
                      <circle cx="147" cy="108" r="3.5" fill="#fff7ed" stroke="#f97316" strokeWidth="1.5"/>
                      <path d="M147 112 L147 207 L650 207 L650 190"
                        stroke="#f97316" strokeWidth="1.5" strokeDasharray="3,3" fill="none"
                        markerEnd="url(#tp3-arr-local)"/>
                      <text x="175" y="204" fontSize="7" fill="#f97316">
                        {`${totalBypassCount} bypass rule${totalBypassCount !== 1 ? "s" : ""} → Direct`}
                      </text>
                    </>
                  )}

                  {/* ── Context → right fork: only selected context connects ─── */}
                  {(() => {
                    const ctxY = networkContext === "on" ? 50 : networkContext === "vpn" ? 108 : 166;
                    const col = networkContext === "on" ? "#7c3aed" : networkContext === "vpn" ? "#4f46e5" : "#0d9488";
                    return <line x1="566" y1={ctxY} x2="596" y2={ctxY} stroke={col} strokeWidth="2"/>;
                  })()}

                  {/* ── Right fork: trunk from selected context to destinations ─ */}
                  {(() => {
                    const ctxY = networkContext === "on" ? 50 : networkContext === "vpn" ? 108 : 166;
                    const zpaCtxOn = ctxZpaOn(networkContext);
                    return (
                      <>
                        {/* Trunk up to junction at y=50 */}
                        <line x1="596" y1={ctxY} x2="596" y2="50"
                          stroke={tc} strokeWidth="1.5"/>

                        {lpActive ? (
                          <>
                            {/* Non-web: direct Z-Tunnel to ZIA (upper branch from junction) */}
                            <line x1="596" y1="50" x2="596" y2="36" stroke={tc} strokeWidth="1.5"/>
                            <line x1="596" y1="36" x2="644" y2="36"
                              stroke={tc} strokeWidth="2"
                              markerEnd="url(#tp3-arr-zia)" className="pointer-events-none"/>
                            {/* Web: via listening proxy (lower branch from junction) */}
                            <line x1="596" y1="50" x2="596" y2="64" stroke="#2563eb" strokeWidth="1.5"/>
                            <line x1="596" y1="64" x2="608" y2="64" stroke="#2563eb" strokeWidth="1.5"/>
                            {/* LP node badge */}
                            <rect x="608" y="58" width="24" height="12" rx="3"
                              fill="#dbeafe" stroke="#2563eb" strokeWidth="1" className="pointer-events-none"/>
                            <text x="620" y="67" fontSize="7" fontWeight="600" fill="#1d4ed8"
                              textAnchor="middle" className="pointer-events-none">LP</text>
                            {/* LP → ZIA */}
                            <line x1="632" y1="64" x2="644" y2="64"
                              stroke="#2563eb" strokeWidth="2"
                              markerEnd="url(#tp3-arr-lp)" className="pointer-events-none"/>
                          </>
                        ) : (
                          /* → ZIA (single path when LP inactive) */
                          <line x1="596" y1="50" x2="644" y2="50"
                            stroke={tc} strokeWidth="2"
                            markerEnd="url(#tp3-arr-zia)" className="pointer-events-none"/>
                        )}

                        {/* Trunk down to Local (only when ZPA or Local destination active) */}
                        {(localActive || (data.zpaEnabled && zpaCtxOn)) && (
                          <line x1="596" y1={ctxY} x2="596" y2="166"
                            stroke={localActive ? "#f97316" : "#4f46e5"} strokeWidth="1.5"/>
                        )}
                        {/* → ZPA (only when ZPA active for this context) */}
                        {data.zpaEnabled && zpaCtxOn && (
                          <line x1="596" y1="108" x2="644" y2="108"
                            stroke="#4f46e5"
                            strokeWidth="2"
                            markerEnd="url(#tp3-arr-zpa)" className="pointer-events-none"/>
                        )}
                        {/* → Local / Direct (only when local bypass is active) */}
                        {localActive && (
                          <line x1="596" y1="166" x2="644" y2="166"
                            stroke="#f97316"
                            strokeWidth="2"
                            markerEnd="url(#tp3-arr-local)"
                            className="pointer-events-none"/>
                        )}
                      </>
                    );
                  })()}

                  {/* ── PAC path labels near fork arrows ─────────────────────── */}
                  {pacEvaluated && !lpActive && (
                    <>
                      <text x="599" y="45" fontSize="7" fill="#9ca3af" className="pointer-events-none">PAC PROXY → ZT1</text>
                      <text x="599" y="178" fontSize="7" fill="#9ca3af" className="pointer-events-none">PAC DIRECT → bypass</text>
                    </>
                  )}
                  {lpActive && (
                    <>
                      {/* Non-web: LWF/TAP path label above arrow at y=36 */}
                      <text x="599" y="31" fontSize="6" fill="#6b7280" className="pointer-events-none">Non-proxy-aware</text>
                      <text x="599" y="39" fontSize="6" fill="#9ca3af" className="pointer-events-none">LWF/TAP · ZT2</text>
                      {/* Web: proxy-aware label left of LP badge */}
                      <text x="598" y="61" fontSize="6" fill="#1d4ed8" className="pointer-events-none">Proxy-aware →</text>
                      {/* Tunnel type after LP badge */}
                      <text x="634" y="61" fontSize="6" fontWeight="600" fill="#1d4ed8" className="pointer-events-none">
                        {zt2ProxiedActive ? "ZT2" : "ZT1"}
                      </text>
                      {/* PAC results below web path */}
                      <text x="598" y="76" fontSize="6" fill="#9ca3af" className="pointer-events-none">
                        {zt2ProxiedActive ? "PAC default→ZT2 · proxy→ZT1" : "PAC default→ZT1 · proxy→ZT1"}
                      </text>
                      <text x="599" y="178" fontSize="7" fill="#9ca3af" className="pointer-events-none">PAC DIRECT → bypass (L7)</text>
                    </>
                  )}

                  {/* ── Node: Device ────────────────────────────────────────── */}
                  <g filter="url(#tp3-shadow)">
                    <rect x="8" y="86" width="100" height="44" rx="8" fill="white" stroke="#e5e7eb" strokeWidth="1.5"/>
                  </g>
                  <rect x="16" y="95" width="18" height="12" rx="1.5" fill="none" stroke="#9ca3af" strokeWidth="1.3"/>
                  <line x1="13" y1="107" x2="37" y2="107" stroke="#9ca3af" strokeWidth="1.3"/>
                  <line x1="23" y1="108" x2="27" y2="111" stroke="#9ca3af" strokeWidth="1.3"/>
                  <text x="40" y="102" fontSize="11" fontWeight="600" fill="#374151">Device</text>
                  <text x="40" y="115" fontSize="9" fill="#9ca3af">Endpoint</text>

                  {/* ── Node: ZCC ───────────────────────────────────────────── */}
                  <g filter="url(#tp3-shadow)">
                    <rect x="186" y="76" width="150" height="64" rx="8" fill="white" stroke="#93c5fd" strokeWidth="1.5"/>
                  </g>
                  <path d="M197 105 L197 92 L207 89 L217 92 L217 105 C217 111 207 114 207 114 C207 114 197 111 197 105Z"
                    fill="none" stroke="#3b82f6" strokeWidth="1.4"/>
                  <text x="224" y="96" fontSize="11" fontWeight="600" fill="#1d4ed8">ZCC</text>
                  <circle cx="326" cy="84" r="5" fill={data.active ? "#22c55e" : "#d1d5db"}/>
                  {data.deviceType && (
                    <text x="224" y="110" fontSize="8" fill="#9ca3af">
                      {`${data.deviceType.charAt(0).toUpperCase()}${data.deviceType.slice(1)} policy`}
                    </text>
                  )}
                  {lpActive && (
                    <>
                      <rect x="286" y="120" width="28" height="13" rx="3"
                        fill="#dbeafe" stroke="#2563eb" strokeWidth="0.8" className="pointer-events-none"/>
                      <text x="300" y="130" fontSize="7.5" fontWeight="600" fill="#1d4ed8"
                        textAnchor="middle" className="pointer-events-none">LP</text>
                    </>
                  )}

                  {/* ── 3 Network Context Nodes ─────────────────────────────── */}
                  <g transform="translate(80, 0)">

                  {/* On Trusted Network (y=27, h=46, center=50) */}
                  <g filter="url(#tp3-shadow)" className="cursor-pointer"
                    onClick={() => setNetworkContext("on")}
                    onMouseEnter={() => setHovered("on-node")} onMouseLeave={() => setHovered(null)}>
                    <rect x="314" y="27" width="172" height="46" rx="7"
                      fill={networkContext === "on" ? "#faf5ff" : "white"}
                      stroke={networkContext === "on" ? "#7c3aed" : hovered === "on-node" ? "#c4b5fd" : "#e5e7eb"}
                      strokeWidth={networkContext === "on" ? 2 : 1.5}/>
                  </g>
                  <text x="330" y="46" fontSize="10" fontWeight="600"
                    fill={networkContext === "on" ? "#5b21b6" : "#374151"} className="pointer-events-none">
                    On Trusted Network
                  </text>
                  <text x="330" y="61" fontSize="8"
                    fill={networkContext === "on" ? "#7c3aed" : "#9ca3af"} className="pointer-events-none">
                    {ctxModeStr("on")}{ctxHasLP("on") ? " · LP" : ""}{ctxModeStr("on") ? ` · ${ctxTransStr("on")}` : ""}
                  </text>

                  {/* VPN Trusted Network (y=85, h=46, center=108) */}
                  <g filter="url(#tp3-shadow)" className="cursor-pointer"
                    onClick={() => setNetworkContext("vpn")}
                    onMouseEnter={() => setHovered("vpn-node")} onMouseLeave={() => setHovered(null)}>
                    <rect x="314" y="85" width="172" height="46" rx="7"
                      fill={networkContext === "vpn" ? "#eef2ff" : "white"}
                      stroke={networkContext === "vpn" ? "#4f46e5" : hovered === "vpn-node" ? "#a5b4fc" : "#e5e7eb"}
                      strokeWidth={networkContext === "vpn" ? 2 : 1.5}/>
                  </g>
                  <text x="330" y="104" fontSize="10" fontWeight="600"
                    fill={networkContext === "vpn" ? "#3730a3" : "#374151"} className="pointer-events-none">
                    VPN Trusted Network
                  </text>
                  <text x="330" y="119" fontSize="8"
                    fill={networkContext === "vpn" ? "#4f46e5" : "#9ca3af"} className="pointer-events-none">
                    {ctxModeStr("vpn")}{ctxHasLP("vpn") ? " · LP" : ""}{ctxModeStr("vpn") ? ` · ${ctxTransStr("vpn")}` : ""}
                  </text>

                  {/* Off Trusted Network (y=143, h=46, center=166) */}
                  <g filter="url(#tp3-shadow)" className="cursor-pointer"
                    onClick={() => setNetworkContext("off")}
                    onMouseEnter={() => setHovered("off-node")} onMouseLeave={() => setHovered(null)}>
                    <rect x="314" y="143" width="172" height="46" rx="7"
                      fill={networkContext === "off" ? "#f0fdfa" : "white"}
                      stroke={networkContext === "off" ? "#0d9488" : hovered === "off-node" ? "#99f6e4" : "#e5e7eb"}
                      strokeWidth={networkContext === "off" ? 2 : 1.5}/>
                  </g>
                  <text x="330" y="162" fontSize="10" fontWeight="600"
                    fill={networkContext === "off" ? "#0f766e" : "#374151"} className="pointer-events-none">
                    Off Trusted Network
                  </text>
                  <text x="330" y="176" fontSize="8"
                    fill={networkContext === "off" ? "#0d9488" : "#9ca3af"} className="pointer-events-none">
                    {ctxModeStr("off")}{ctxHasLP("off") ? " · LP" : ""}{ctxModeStr("off") ? ` · ${ctxTransStr("off")}` : ""}
                  </text>
                  </g>{/* end translate(80, 0) context nodes */}

                  {/* ── Destination nodes (translated +126 for arrow lead room) ── */}
                  <g transform="translate(126, 0)">

                  {/* ── ZIA Cloud ────────────────────────────────────────────── */}
                  <g filter="url(#tp3-shadow)" className="cursor-pointer"
                    onClick={() => setActiveSection(tabs.find(t => t.group === "zia")?.key ?? "tunnel")}
                    onMouseEnter={() => setHovered("zia")} onMouseLeave={() => setHovered(null)}>
                    <rect x="524" y="26" width="240" height="48" rx="8"
                      fill={tunnelActive || hovered === "zia" ? "#f0fdf4" : "white"}
                      stroke={tunnelActive ? tc : "#86efac"}
                      strokeWidth={tunnelActive ? 2 : 1.5}/>
                  </g>
                  <path d="M533 56 C530 56 529 53 531 50 C529 48 530 45 534 44 C534 40 539 37 544 39 C545 36 551 35 554 38 C559 36 564 40 562 45 C565 45 567 48 565 51 C566 54 564 57 561 57Z"
                    fill="none" stroke="#22c55e" strokeWidth="1.2" className="pointer-events-none"/>
                  <text x="571" y="42" fontSize="10" fontWeight="600" fill="#15803d" className="pointer-events-none">ZIA Cloud</text>
                  <text x="571" y="57" fontSize="8.5" fill="#6b7280" className="pointer-events-none">
                    {lpActive && zt2ProxiedActive
                      ? "Proxy-aware: LP→ZT2 (default) / ZT1 (PAC proxy)  ·  Non-proxy-aware: LWF→ZT2"
                      : lpActive && !zt2ProxiedActive
                        ? "Proxy-aware: LP→ZT1  ·  Non-proxy-aware: LWF→ZT2"
                        : detailedMode === "T2.0"
                          ? (data.pac.enablePac || data.pac.profilePacUrl || data.pac.url)
                            ? "All traffic via ZT2  ·  System PAC active"
                            : "All traffic via ZT2 (no PAC)"
                          : ZIA_MODE_LABEL[data.tunnelMode]}
                  </text>
                  {(data.pac.enablePac || data.pac.url || data.pac.profilePacUrl) && (
                    <g className="cursor-pointer" onClick={(e) => { e.stopPropagation(); setActiveSection("pac"); }}>
                      <rect x="730" y="28" width="30" height="16" rx="4" fill="#fef3c7" stroke="#fbbf24" strokeWidth="1"/>
                      <text x="745" y="39" fontSize="8" fontWeight="600" fill="#92400e" textAnchor="middle" className="pointer-events-none">PAC</text>
                    </g>
                  )}

                  {/* ── ZPA Private Apps ─────────────────────────────────────── */}
                  {data.zpaEnabled && (() => {
                    const zpaCtxOn = ctxZpaOn(networkContext);
                    const zpaBorderColor = zpaCtxOn ? (zpaActive ? "#4f46e5" : "#a5b4fc") : "#d1d5db";
                    const zpaIconColor   = zpaCtxOn ? "#4f46e5" : "#d1d5db";
                    const zpaLabelColor  = zpaCtxOn ? "#3730a3" : "#9ca3af";
                    return (
                      <g filter="url(#tp3-shadow)" className="cursor-pointer"
                        onClick={() => setActiveSection("zpa")}
                        onMouseEnter={() => setHovered("zpa")} onMouseLeave={() => setHovered(null)}>
                        <rect x="524" y="84" width="240" height="48" rx="8"
                          fill={zpaCtxOn && (zpaActive || hovered === "zpa") ? "#eef2ff" : "white"}
                          stroke={zpaBorderColor}
                          strokeWidth={zpaCtxOn && zpaActive ? 2 : 1.5}/>
                        <rect x="533" y="100" width="14" height="11" rx="2" fill="none" stroke={zpaIconColor} strokeWidth="1.3"/>
                        <path d="M536 100 A4 4 0 0 1 544 100" fill="none" stroke={zpaIconColor} strokeWidth="1.3"/>
                        <circle cx="540" cy="106" r="1.5" fill={zpaIconColor}/>
                        <text x="554" y="102" fontSize="10" fontWeight="600" fill={zpaLabelColor}>ZPA Private Apps</text>
                        <text x="554" y="117" fontSize="8.5" fill={zpaCtxOn ? "#6b7280" : "#d1d5db"}>ZPA-enrolled private access</text>
                        {zpaCtxOn && <rect x="726" y="86" width="34" height="15" rx="4" fill="#eef2ff" stroke="#a5b4fc" strokeWidth="0.8"/>}
                        {zpaCtxOn
                          ? <text x="743" y="96" fontSize="7.5" fill="#4f46e5" textAnchor="middle" className="pointer-events-none">active</text>
                          : <text x="743" y="96" fontSize="7.5" fill="#d1d5db" textAnchor="middle" className="pointer-events-none">off</text>
                        }
                      </g>
                    );
                  })()}

                  {/* ── Local / Direct ───────────────────────────────────────── */}
                  <g filter="url(#tp3-shadow)" className="cursor-pointer"
                    onClick={() => setActiveSection("local")}
                    onMouseEnter={() => setHovered("local")} onMouseLeave={() => setHovered(null)}>
                    <rect x="524" y="142" width="240" height="48" rx="8"
                      fill={bypassActive || hovered === "local" ? "#fff7ed" : "white"}
                      stroke={localActive ? (bypassActive ? "#f97316" : "#fdba74") : "#e5e7eb"}
                      strokeWidth={bypassActive ? 2 : 1.5}/>
                  </g>
                  <circle cx="538" cy="166" r="9" fill="none"
                    stroke={localActive ? "#f97316" : "#d1d5db"} strokeWidth="1.3" className="pointer-events-none"/>
                  <ellipse cx="538" cy="166" rx="4.5" ry="9" fill="none"
                    stroke={localActive ? "#f97316" : "#d1d5db"} strokeWidth="1" className="pointer-events-none"/>
                  <line x1="529" y1="166" x2="547" y2="166"
                    stroke={localActive ? "#f97316" : "#d1d5db"} strokeWidth="1" className="pointer-events-none"/>
                  <text x="555" y="161" fontSize="10" fontWeight="600"
                    fill={localActive ? "#c2410c" : "#9ca3af"} className="pointer-events-none">Local / Direct</text>
                  <text x="555" y="175" fontSize="8" fill="#6b7280" className="pointer-events-none">{localSubtitle}</text>

                  </g>{/* end translate(126, 0) */}

                  {/* ── Legend ──────────────────────────────────────────────── */}
                  <circle cx="10" cy="217" r="4" fill={data.active ? "#22c55e" : "#d1d5db"}/>
                  <text x="18" y="221" fontSize="8.5" fill="#9ca3af">{data.active ? "Active" : "Inactive"}</text>
                  <line x1="64" y1="217" x2="78" y2="217" stroke={tc} strokeWidth="2"/>
                  <text x="82" y="221" fontSize="8.5" fill="#9ca3af">ZIA tunnel</text>
                  <line x1="130" y1="217" x2="144" y2="217"
                    stroke={localActive ? "#f97316" : "#d1d5db"} strokeWidth="2"/>
                  <text x="148" y="221" fontSize="8.5" fill="#9ca3af">
                    {pacEvaluated ? "PAC DIRECT" : "Local/direct"}
                  </text>
                  {data.zpaEnabled && (
                    <>
                      <line x1="220" y1="217" x2="234" y2="217" stroke="#4f46e5" strokeWidth="2"/>
                      <text x="238" y="221" fontSize="8.5" fill="#9ca3af">ZPA</text>
                    </>
                  )}
                </svg>
                {/* ── System proxy footnote (ZT2proxied=on, LP=off) ─────────── */}
                {!lpActive && zt2ProxiedActive && (
                  <div className="flex items-start gap-1.5 px-3 py-2 border-t border-gray-100 bg-amber-50/60">
                    <svg className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M12 2a10 10 0 100 20A10 10 0 0012 2z"/>
                    </svg>
                    <p className="text-xs text-amber-800 leading-snug">
                      <span className="font-medium">Device system proxy note:</span> If the endpoint OS has a system proxy configured pointing to the ZCC listening address (e.g. 127.0.0.1:9000), web traffic will route through the listening proxy and then Z-Tunnel 2.0 — even though <em>Redirect Web Traffic to Listening Proxy</em> is disabled in the forwarding profile.
                    </p>
                  </div>
                )}
              </div>

              {/* ── Targeting bar ─────────────────────────────────────────────── */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs px-1">
                {data.deviceType && (
                  <span className="flex items-center gap-1.5">
                    <span className="text-gray-500 font-medium">OS:</span>
                    <OsBadge os={data.deviceType} />
                  </span>
                )}
                <span className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-gray-500 font-medium">Targets:</span>
                  {data.targetUsers.length === 0 && data.targetGroups.length === 0 && data.targetDepartments.length === 0 ? (
                    <span className="text-gray-400">All users</span>
                  ) : (
                    <>
                      {data.targetUsers.map((u, i) => (
                        <span key={i} className="px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700">{u.name || u.id}</span>
                      ))}
                      {data.targetGroups.map((g, i) => (
                        <span key={i} className="px-1.5 py-0.5 rounded-full bg-green-50 text-green-700">Group: {g.name || g.id}</span>
                      ))}
                      {data.targetDepartments.map((d, i) => (
                        <span key={i} className="px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-700">Dept: {d.name || d.id}</span>
                      ))}
                    </>
                  )}
                </span>
              </div>

              {/* ── Traffic Simulator ────────────────────────────────────────── */}
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-gray-500 uppercase">Traffic Simulator</p>
                  <p className="text-xs text-gray-400 italic">Results based on parsed PAC rules — complex PAC logic may not be fully represented</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    placeholder="Destination IP or hostname"
                    value={simDest}
                    onChange={e => { setSimDest(e.target.value); setSimResult(null); }}
                    onKeyDown={e => e.key === "Enter" && runSimulator()}
                    className="flex-1 min-w-[180px] px-2.5 py-1.5 text-xs rounded border border-gray-300 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 font-mono"
                  />
                  <input
                    type="text"
                    placeholder="Port"
                    value={simPort}
                    onChange={e => { setSimPort(e.target.value); setSimResult(null); }}
                    onKeyDown={e => e.key === "Enter" && runSimulator()}
                    className="w-20 px-2.5 py-1.5 text-xs rounded border border-gray-300 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 font-mono"
                  />
                  <button
                    onClick={runSimulator}
                    className="px-3 py-1.5 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 transition-colors"
                  >
                    Check
                  </button>
                </div>
                {simResult && (
                  <div className="mt-2 flex flex-col gap-1">
                    {simResult.reasons.map((r, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-semibold ${
                          simResult.color === "green"
                            ? "bg-green-100 text-green-800"
                            : "bg-orange-100 text-orange-800"
                        }`}>
                          {simResult.outcome}
                        </span>
                        <span className="text-xs text-gray-500 italic shrink-0">{r.source}</span>
                        <span className="text-xs text-gray-700">{r.text}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* ── Tab bar + detail panels (always visible) ─────────────────── */}
              {tabs.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {tabs.map(tab => (
                    <button key={tab.key} onClick={() => setActiveSection(tab.key)} className={tabBtnClass(tab.key, tab.group)}>
                      {tab.label}{tab.count !== null ? ` (${tab.count})` : ""}
                    </button>
                  ))}
                </div>
              )}

              {activeSection === "tunnel" && data.tunnelRoutes.some(r => r.direction === "include") && (
                <div className="overflow-x-auto rounded border border-gray-100">
                  <table className="min-w-full text-sm divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">CIDR</th>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">IP Version</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-100">
                      {data.tunnelRoutes.filter(r => r.direction === "include").map((r, i) => (
                        <tr key={i}>
                          <td className="px-3 py-1.5 font-mono text-xs">{r.cidr}</td>
                          <td className="px-3 py-1.5 text-gray-600 text-xs">{r.ipVersion}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {activeSection === "dns" && data.dnsRoutes.length > 0 && (
                <div className="overflow-x-auto rounded border border-gray-100">
                  <table className="min-w-full text-sm divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Suffix</th>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Direction</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-100">
                      {data.dnsRoutes.map((r, i) => (
                        <tr key={i}>
                          <td className="px-3 py-1.5 font-mono text-xs">{r.suffix}</td>
                          <td className="px-3 py-1.5">
                            <span className={`px-1.5 py-0.5 rounded text-xs ${r.direction === "include" ? "bg-green-50 text-green-700" : "bg-orange-50 text-orange-700"}`}>
                              {r.direction === "include" ? "→ ZIA" : "→ Local"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {activeSection === "zpa" && (
                <div className="space-y-3">
                  <div className="bg-indigo-50 border border-indigo-200 rounded p-3 space-y-2">
                    <p className="text-sm font-medium text-indigo-800">ZPA Private Access</p>
                    <div className="flex gap-4 text-xs">
                      {(["on", "vpn", "off"] as const).map(ctx => (
                        <div key={ctx} className="flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-full ${ctxZpaOn(ctx) ? "bg-indigo-500" : "bg-gray-300"}`}/>
                          <span className="text-gray-600">
                            {ctx === "on" ? "On network" : ctx === "vpn" ? "VPN" : "Off network"}:
                          </span>
                          <span className={ctxZpaOn(ctx) ? "text-indigo-700 font-medium" : "text-gray-400"}>
                            {ctxZpaOn(ctx) ? "active" : "off"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  {zpaApps && zpaApps.length > 0 && (() => {
                    const summarize = zpaApps.length > 20;
                    if (!summarize) {
                      return (
                        <div>
                          <p className="text-xs font-medium text-gray-500 uppercase mb-1">Private Applications ({zpaApps.length})</p>
                          <div className="overflow-x-auto rounded border border-gray-100">
                            <table className="min-w-full text-sm divide-y divide-gray-200">
                              <thead className="bg-gray-50">
                                <tr>
                                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Domains / IPs</th>
                                  <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
                                </tr>
                              </thead>
                              <tbody className="bg-white divide-y divide-gray-100">
                                {zpaApps.map((app, i) => {
                                  const domains = app.domain_names ?? app.domainNames ?? [];
                                  return (
                                    <tr key={i}>
                                      <td className="px-3 py-1.5 font-medium text-xs">{app.name}</td>
                                      <td className="px-3 py-1.5 font-mono text-xs text-gray-600">
                                        {domains.length > 0 ? domains.join(", ") : <span className="text-gray-400">—</span>}
                                      </td>
                                      <td className="px-3 py-1.5">
                                        <span className={`px-1.5 py-0.5 rounded text-xs ${app.enabled ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                                          {app.enabled ? "yes" : "no"}
                                        </span>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      );
                    }
                    // Summarize by 2nd-level domain
                    const domainMap = new Map<string, number>();
                    zpaApps.forEach(app => {
                      const domains = app.domain_names ?? app.domainNames ?? [];
                      const seen = new Set<string>();
                      domains.forEach(d => {
                        const parts = d.replace(/\/.*/, "").split(".");
                        const sld = parts.length >= 2 ? parts.slice(-2).join(".") : d;
                        if (!seen.has(sld)) { seen.add(sld); domainMap.set(sld, (domainMap.get(sld) ?? 0) + 1); }
                      });
                    });
                    const summaryRows = [...domainMap.entries()].sort((a, b) => b[1] - a[1]);
                    return (
                      <div>
                        <p className="text-xs font-medium text-gray-500 uppercase mb-1">
                          Private Applications — {zpaApps.length} segments summarized by domain
                        </p>
                        <div className="overflow-x-auto rounded border border-gray-100">
                          <table className="min-w-full text-sm divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">App segments</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-100">
                              {summaryRows.map(([sld, count], i) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5 font-mono text-xs">*.{sld}</td>
                                  <td className="px-3 py-1.5 text-xs text-gray-600">{count}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    );
                  })()}
                  {zpaApps && zpaApps.length === 0 && (
                    <p className="text-xs text-gray-400">No ZPA applications found. Run Import Config to pull ZPA application data.</p>
                  )}
                  {data.dnsRoutes.filter(r => r.direction === "include").length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-gray-500 uppercase mb-1">Tunneled DNS Suffixes</p>
                      <div className="overflow-x-auto rounded border border-gray-100">
                        <table className="min-w-full text-sm divide-y divide-gray-200">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Suffix</th>
                            </tr>
                          </thead>
                          <tbody className="bg-white divide-y divide-gray-100">
                            {data.dnsRoutes.filter(r => r.direction === "include").map((r, i) => (
                              <tr key={i}>
                                <td className="px-3 py-1.5 font-mono text-xs">{r.suffix}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeSection === "local" && (() => {
                const tunnelExclusions = data.tunnelRoutes.filter(r => r.direction === "exclude");
                const hasAny = data.processBypasses.length > 0 || data.portBypasses.length > 0 ||
                  data.vpnGatewayBypasses.length > 0 || tunnelExclusions.length > 0 || pacBypasses.length > 0;
                return (
                  <div className="space-y-4">
                    {!hasAny && <p className="text-xs text-gray-400">No local/direct bypass rules configured.</p>}
                    {[
                      { label: "Forwarding Profile PAC — Bypass Rules", url: data.pac.profilePacUrl, items: pacBypasses },
                      { label: "App Profile PAC — Bypass Rules",        url: data.pac.url,           items: pacAppBypasses },
                    ].filter(s => s.items.length > 0).map(section => (
                      <div key={section.label}>
                        <p className="text-xs font-medium text-blue-700 uppercase mb-1">{section.label}</p>
                        <div className="overflow-x-auto rounded border border-blue-100 bg-blue-50/30">
                          <table className="min-w-full text-sm divide-y divide-blue-100">
                            <thead className="bg-blue-50">
                              <tr>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-blue-600 uppercase">Rule</th>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-blue-600 uppercase">Detail</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-blue-50">
                              {section.items.map((b, i) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5 font-mono text-xs text-gray-800">{b.label}</td>
                                  <td className="px-3 py-1.5 text-xs text-gray-500">{b.detail}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className="text-xs text-gray-400 mt-1">
                          Parsed from: <span className="font-mono">{section.url}</span>
                        </p>
                      </div>
                    ))}
                    {data.processBypasses.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-orange-700 uppercase mb-1">App Profile Bypasses (Process)</p>
                        <div className="overflow-x-auto rounded border border-gray-100">
                          <table className="min-w-full text-sm divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Process</th>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Platform</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-100">
                              {data.processBypasses.map((pb, i) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5 font-mono text-xs">{pb.processName}</td>
                                  <td className="px-3 py-1.5 text-gray-600 text-xs capitalize">{pb.platform}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    {data.portBypasses.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-orange-700 uppercase mb-1">Port Bypasses</p>
                        <div className="overflow-x-auto rounded border border-gray-100">
                          <table className="min-w-full text-sm divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Port</th>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Protocol</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-100">
                              {data.portBypasses.map((pb, i) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5 font-mono text-xs">{pb.port}</td>
                                  <td className="px-3 py-1.5 text-gray-600 text-xs">{pb.protocol}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    {data.vpnGatewayBypasses.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-orange-700 uppercase mb-1">VPN Gateway Bypasses</p>
                        <div className="overflow-x-auto rounded border border-gray-100">
                          <table className="min-w-full text-sm divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Gateway</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-100">
                              {data.vpnGatewayBypasses.map((vb, i) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5 font-mono text-xs">{vb.gateway}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    {tunnelExclusions.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-orange-700 uppercase mb-1">Tunnel Exclusions (CIDR)</p>
                        <div className="overflow-x-auto rounded border border-gray-100">
                          <table className="min-w-full text-sm divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">CIDR</th>
                                <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">IP Version</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-100">
                              {tunnelExclusions.map((r, i) => (
                                <tr key={i}>
                                  <td className="px-3 py-1.5 font-mono text-xs">{r.cidr}</td>
                                  <td className="px-3 py-1.5 text-gray-600 text-xs">{r.ipVersion}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}

              {activeSection === "process" && data.processBypasses.length > 0 && (
                <div className="overflow-x-auto rounded border border-gray-100">
                  <table className="min-w-full text-sm divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Process</th>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Platform</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-100">
                      {data.processBypasses.map((pb, i) => (
                        <tr key={i}>
                          <td className="px-3 py-1.5 font-mono text-xs">{pb.processName}</td>
                          <td className="px-3 py-1.5 text-gray-600 text-xs capitalize">{pb.platform}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {activeSection === "port" && data.portBypasses.length > 0 && (
                <div className="overflow-x-auto rounded border border-gray-100">
                  <table className="min-w-full text-sm divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Port</th>
                        <th className="px-3 py-1.5 text-left text-xs font-medium text-gray-500 uppercase">Protocol</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-100">
                      {data.portBypasses.map((pb, i) => (
                        <tr key={i}>
                          <td className="px-3 py-1.5 font-mono text-xs">{pb.port}</td>
                          <td className="px-3 py-1.5 text-gray-600 text-xs">{pb.protocol}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {activeSection === "pac" && (
                <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm space-y-1.5">
                  {data.pac.enablePac && <div><span className="text-gray-500 mr-1">PAC enabled:</span><span className="text-green-700 font-medium">Yes</span></div>}
                  {data.pac.url && <div><span className="text-gray-500 mr-1">PAC URL:</span><span className="font-mono text-xs text-gray-800">{data.pac.url}</span></div>}
                  {data.pac.profilePacUrl && <div><span className="text-gray-500 mr-1">Profile PAC URL:</span><span className="font-mono text-xs text-gray-800">{data.pac.profilePacUrl}</span></div>}
                  {data.pac.ziaPacFileName && <div><span className="text-gray-500 mr-1">ZIA PAC file:</span><span className="text-gray-800">{data.pac.ziaPacFileName}</span></div>}
                  {data.pac.customPacContent !== null && data.pac.customPacContent !== undefined && (
                    <div><span className="text-gray-500 mr-1">Custom PAC:</span><span className="text-gray-800">{data.pac.customPacContent} bytes</span></div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-sm rounded-md bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── App Profiles section with traffic profile button ──────────────────────────

function AppProfilesSection({
  tenantName,
  isOpen,
}: {
  tenantName: string;
  isOpen: boolean;
}) {
  const [visualizerPolicy, setVisualizerPolicy] = useState<{ id: string; name: string } | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery<ZccWebPolicy[]>({
    queryKey: ["zcc-web-policies", tenantName],
    queryFn: () => listWebPolicies(tenantName),
    enabled: isOpen,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data) return null;

  return (
    <>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="w-8 px-2 py-2"></th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">OS</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.map((policy: ZccWebPolicy, i: number) => {
              const rowKey = String(policy.id ?? i);
              const isExpanded = expandedId === rowKey;

              // Derived helpers from raw_config fields
              const onNetPolicy = policy.onNetPolicy as Record<string, unknown> | undefined;
              const fpActions = (onNetPolicy?.forwardingProfileActions as Array<Record<string, unknown>>) ?? [];
              const zpaActions = (onNetPolicy?.forwardingProfileZpaActions as Array<Record<string, unknown>>) ?? [];
              const tunnelMode = (() => {
                if (!fpActions.length) return null;
                const f = fpActions[0];
                if (f.enablePacketTunnel && f.enablePacketTunnel !== 0) return "Z-Tunnel 2.0";
                if (f.systemProxy && f.systemProxy !== 0) return "Proxy";
                return "Z-Tunnel 1.0";
              })();
              const zpaEnabled = zpaActions.some(a => a.actionType && a.actionType !== 0);
              const trustedNetworks = (onNetPolicy?.trustedNetworks as string[]) ?? [];

              const rawGroups = policy.groups as Array<Record<string, unknown>> | undefined;
              const groupList = Array.isArray(rawGroups)
                ? rawGroups.filter(g => typeof g === "object" && g !== null).map(g => String(g.name || g.id || ""))
                : [];

              const pe = policy.policyExtension as Record<string, unknown> | undefined;
              const splitCsv = (v: unknown) =>
                typeof v === "string" && v ? v.split(",").map(s => s.trim().replace(/^\[|\]$/g, "")).filter(Boolean) : [];
              const includeList = splitCsv(pe?.packetTunnelIncludeList);
              const excludeList = splitCsv(pe?.packetTunnelExcludeList);
              const vpnGateways = splitCsv(pe?.vpnGateways);
              const portBypasses = splitCsv(pe?.sourcePortBasedBypasses);
              const sslCertInstall = !!(policy.install_ssl_certs && policy.install_ssl_certs !== 0 && policy.install_ssl_certs !== "0");

              return (
                <Fragment key={rowKey}>
                  <tr className={isExpanded ? "bg-blue-50/40" : "hover:bg-gray-50/50"}>
                    <td className="px-2 py-2 text-center">
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : rowKey)}
                        className="text-gray-400 hover:text-gray-600 transition-colors inline-flex items-center justify-center"
                        title={isExpanded ? "Collapse" : "Expand"}
                      >
                        <span className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}>{CHEVRON}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-500">{policy.id ?? "-"}</td>
                    <td className="px-3 py-2 text-gray-900">{policy.name ?? "-"}</td>
                    <td className="px-3 py-2">
                      {policy.device_type
                        ? <OsBadge os={String(policy.device_type)} />
                        : <span className="text-gray-400 text-xs">-</span>}
                    </td>
                    <td className="px-3 py-2">
                      {policy.id && (
                        <button
                          onClick={() => setVisualizerPolicy({ id: String(policy.id), name: policy.name ?? String(policy.id) })}
                          className="text-xs text-zs-600 hover:text-zs-800 underline underline-offset-2 transition-colors"
                        >
                          Visualize Traffic Profile
                        </button>
                      )}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="bg-blue-50/30 border-b border-blue-100">
                      <td colSpan={5} className="px-6 pt-2 pb-4">
                        <div className="space-y-3 text-xs">

                          {/* Row 1: Policy overview */}
                          <div className="grid grid-cols-2 md:grid-cols-5 gap-x-6 gap-y-2">
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">Status</div>
                              {policy.active
                                ? <span className="bg-green-50 text-green-700 px-1.5 py-0.5 rounded">Active</span>
                                : <span className="bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">Inactive</span>}
                            </div>
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">Priority</div>
                              <div className="text-gray-900">{String(policy.ruleOrder ?? "—")}</div>
                            </div>
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">Tunnel Mode</div>
                              {tunnelMode
                                ? <span className={`px-1.5 py-0.5 rounded font-medium ${tunnelMode === "Z-Tunnel 2.0" ? "bg-blue-50 text-blue-700" : tunnelMode === "Proxy" ? "bg-orange-50 text-orange-700" : "bg-gray-100 text-gray-600"}`}>{tunnelMode}</span>
                                : <span className="text-gray-400">—</span>}
                            </div>
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">ZPA</div>
                              {zpaEnabled
                                ? <span className="bg-purple-50 text-purple-700 px-1.5 py-0.5 rounded">Enabled</span>
                                : <span className="text-gray-400">Disabled</span>}
                            </div>
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">SSL Inspect</div>
                              {sslCertInstall
                                ? <span className="bg-green-50 text-green-700 px-1.5 py-0.5 rounded">Installing</span>
                                : <span className="text-gray-400">Off</span>}
                            </div>
                          </div>

                          {/* Row 2: Forwarding profile + targeting */}
                          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2">
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">Forwarding Profile</div>
                              <div className="text-gray-900">{String(onNetPolicy?.name ?? "—")}</div>
                            </div>
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">Trusted Networks</div>
                              {trustedNetworks.length > 0
                                ? <div className="flex flex-wrap gap-1">{trustedNetworks.map((n, ni) => <span key={ni} className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">{n}</span>)}</div>
                                : <span className="text-gray-400">None (always active)</span>}
                            </div>
                            <div>
                              <div className="text-gray-500 font-medium mb-0.5">Groups</div>
                              {groupList.length === 0
                                ? <span className="text-gray-400">All users</span>
                                : <div className="flex flex-wrap gap-1">{groupList.map((g, gi) => <span key={gi} className="bg-green-50 text-green-700 px-1.5 py-0.5 rounded">{g}</span>)}</div>}
                            </div>
                          </div>

                          {/* Row 3: Routing */}
                          {(includeList.length > 0 || excludeList.length > 0) && (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2">
                              {includeList.length > 0 && (
                                <div>
                                  <div className="text-gray-500 font-medium mb-0.5">Tunnel Includes ({includeList.length})</div>
                                  <div className="text-gray-700 font-mono leading-relaxed">
                                    {includeList.slice(0, 4).join(", ")}
                                    {includeList.length > 4 && <span className="text-gray-400"> +{includeList.length - 4} more</span>}
                                  </div>
                                </div>
                              )}
                              {excludeList.length > 0 && (
                                <div>
                                  <div className="text-gray-500 font-medium mb-0.5">Tunnel Excludes ({excludeList.length})</div>
                                  <div className="text-gray-700 font-mono leading-relaxed">
                                    {excludeList.slice(0, 4).join(", ")}
                                    {excludeList.length > 4 && <span className="text-gray-400"> +{excludeList.length - 4} more</span>}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}

                          {/* Row 4: Bypasses */}
                          {(vpnGateways.length > 0 || portBypasses.length > 0 || !!policy.pac_url) && (
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-2">
                              {vpnGateways.length > 0 && (
                                <div>
                                  <div className="text-gray-500 font-medium mb-0.5">VPN Bypasses ({vpnGateways.length})</div>
                                  <div className="text-gray-700 font-mono">{vpnGateways.join(", ")}</div>
                                </div>
                              )}
                              {portBypasses.length > 0 && (
                                <div>
                                  <div className="text-gray-500 font-medium mb-0.5">Port Bypasses ({portBypasses.length})</div>
                                  <div className="text-gray-700 font-mono">{portBypasses.join(", ")}</div>
                                </div>
                              )}
                              {!!policy.pac_url && (
                                <div>
                                  <div className="text-gray-500 font-medium mb-0.5">PAC URL</div>
                                  <div className="text-gray-700 font-mono truncate">{String(policy.pac_url)}</div>
                                </div>
                              )}
                            </div>
                          )}

                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {data.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-400">No app profiles</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {visualizerPolicy && (
        <AppProfileVisualizer
          tenantName={tenantName}
          policyId={visualizerPolicy.id}
          policyName={visualizerPolicy.name}
          onClose={() => setVisualizerPolicy(null)}
        />
      )}
    </>
  );
}

// ── ZCC Tab ───────────────────────────────────────────────────────────────────

function ZccTab({
  tenant,
}: {
  tenant: Tenant;
}) {
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
          <ForwardingProfilesSection tenantName={tenant.name} isOpen={!!open.forwardingProfiles} />
        </Accordion>
      </SectionGroup>

      {/* Policy */}
      <SectionGroup title="Policy" isOpen={!!groups.policy} onToggle={() => toggleGroup("policy")}>
        <Accordion title="App Profiles (Web Policies)" isOpen={!!open.webPolicies} onToggle={() => toggle("webPolicies")}>
          <AppProfilesSection tenantName={tenant.name} isOpen={!!open.webPolicies} />
        </Accordion>
        <Accordion title="Bypass App Services" isOpen={!!open.webAppServices} onToggle={() => toggle("webAppServices")}>
          <ZccReadOnlySection<ZccWebAppService>
            queryKey={["zcc-web-app-services", tenant.name]}
            queryFn={() => listWebAppServices(tenant.name)}
            isOpen={!!open.webAppServices}
            emptyMessage="No bypass app services"
          />
        </Accordion>
        <Accordion title="Predefined IP Apps" isOpen={!!open.ipAppsPredefined} onToggle={() => toggle("ipAppsPredefined")}>
          <ZccReadOnlySection<ZccIpApp>
            queryKey={["zcc-ip-apps-predefined", tenant.name]}
            queryFn={() => listIpAppsPredefined(tenant.name)}
            isOpen={!!open.ipAppsPredefined}
            emptyMessage="No predefined IP apps"
          />
        </Accordion>
        <Accordion title="Custom IP Apps" isOpen={!!open.ipAppsCustom} onToggle={() => toggle("ipAppsCustom")}>
          <ZccReadOnlySection<ZccIpApp>
            queryKey={["zcc-ip-apps-custom", tenant.name]}
            queryFn={() => listIpAppsCustom(tenant.name)}
            isOpen={!!open.ipAppsCustom}
            emptyMessage="No custom IP apps"
          />
        </Accordion>
        <Accordion title="Process Apps" isOpen={!!open.processApps} onToggle={() => toggle("processApps")}>
          <ZccReadOnlySection<ZccProcessApp>
            queryKey={["zcc-process-apps", tenant.name]}
            queryFn={() => listProcessApps(tenant.name)}
            isOpen={!!open.processApps}
            emptyMessage="No process apps"
          />
        </Accordion>
      </SectionGroup>

      {/* Configuration */}
      <SectionGroup title="Configuration" isOpen={!!groups.configuration} onToggle={() => toggleGroup("configuration")}>
        <Accordion title="Admin Roles" isOpen={!!open.adminRoles} onToggle={() => toggle("adminRoles")}>
          <ZccReadOnlySection<ZccAdminRole>
            queryKey={["zcc-admin-roles", tenant.name]}
            queryFn={() => listAdminRoles(tenant.name)}
            isOpen={!!open.adminRoles}
            emptyMessage="No admin roles"
          />
        </Accordion>
        <Accordion title="Fail Open Policy" isOpen={!!open.failOpenPolicy} onToggle={() => toggle("failOpenPolicy")}>
          <ZccFailOpenPolicySection tenantName={tenant.name} isOpen={!!open.failOpenPolicy} />
        </Accordion>
        <Accordion title="Web Privacy" isOpen={!!open.webPrivacy} onToggle={() => toggle("webPrivacy")}>
          <ZccWebPrivacySection tenantName={tenant.name} isOpen={!!open.webPrivacy} />
        </Accordion>
      </SectionGroup>

      {/* Config Snapshots */}
      <SectionGroup title="Config Snapshots" isOpen={!!groups.snapshots} onToggle={() => toggleGroup("snapshots")}>
        <Accordion title="Snapshots" isOpen={!!open.snapshots} onToggle={() => toggle("snapshots")}>
          <ZccSnapshotsSection tenant={tenant} isOpen={!!open.snapshots} />
        </Accordion>
      </SectionGroup>
    </div>
  );
}

// ── ZCC Restore Modal ─────────────────────────────────────────────────────────

function ZccRestoreModal({
  tenant,
  snapshot,
  onClose,
}: {
  tenant: Tenant;
  snapshot: ZccSnapshot;
  onClose: () => void;
}) {
  const [dryRun, setDryRun] = useState(true);
  const [targetTenant, setTargetTenant] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [result, setResult] = useState<ZccRestoreResponse | null>(null);

  const diffQuery = useQuery<ZccDiffEntry[]>({
    queryKey: ["zcc-snapshot-diff", tenant.name, snapshot.id],
    queryFn: () => diffZccSnapshot(tenant.name, snapshot.id),
  });

  const restorableDiff = (diffQuery.data ?? []).filter((e) => e.restorable);

  const allRestorableTypes = restorableDiff.map((e) => e.resource_type);

  const toggleType = (t: string) =>
    setSelectedTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
    );

  const selectAll = () => setSelectedTypes([...allRestorableTypes]);
  const clearAll = () => setSelectedTypes([]);

  const restoreMut = useMutation({
    mutationFn: () =>
      restoreZccSnapshot(tenant.name, snapshot.id, {
        resource_types: selectedTypes.length > 0 ? selectedTypes : undefined,
        dry_run: dryRun,
        target_tenant: targetTenant.trim() || undefined,
      }),
    onSuccess: (data) => setResult(data),
  });

  const ACTION_COLOR: Record<string, string> = {
    created: "text-green-700",
    updated: "text-blue-700",
    deleted: "text-red-700",
    skipped: "text-gray-500",
    unrestorable: "text-yellow-700",
    failed: "text-red-700",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h2 className="text-base font-semibold text-gray-900">
            Restore: {snapshot.label || "Snapshot"} ({snapshot.resource_count} resources)
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          {!result ? (
            <>
              {diffQuery.isLoading && <LoadingSpinner />}
              {diffQuery.error && (
                <ErrorMessage message={diffQuery.error instanceof Error ? diffQuery.error.message : "Failed to load diff"} />
              )}
              {diffQuery.data && (
                <div className="space-y-3">
                  <div className="overflow-x-auto border border-gray-200 rounded-lg">
                    <table className="min-w-full text-sm divide-y divide-gray-100">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                          <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Added</th>
                          <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Removed</th>
                          <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Changed</th>
                          <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Unchanged</th>
                          <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">Restore?</th>
                          <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">Include</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-100">
                        {diffQuery.data.map((e) => (
                          <tr key={e.resource_type}>
                            <td className="px-3 py-2 font-mono text-xs text-gray-700">{e.resource_type}</td>
                            <td className="px-3 py-2 text-right text-yellow-600">{e.added_since > 0 ? e.added_since : "—"}</td>
                            <td className="px-3 py-2 text-right text-red-600">{e.removed_since > 0 ? e.removed_since : "—"}</td>
                            <td className="px-3 py-2 text-right text-blue-600">{e.changed_since > 0 ? e.changed_since : "—"}</td>
                            <td className="px-3 py-2 text-right text-gray-500">{e.unchanged}</td>
                            <td className="px-3 py-2 text-center">
                              {e.restorable
                                ? <span className="text-xs text-green-700 font-medium">Yes</span>
                                : <span className="text-xs text-gray-400">No</span>}
                            </td>
                            <td className="px-3 py-2 text-center">
                              {e.restorable && (
                                <input
                                  type="checkbox"
                                  checked={selectedTypes.includes(e.resource_type)}
                                  onChange={() => toggleType(e.resource_type)}
                                  className="h-4 w-4 accent-zs-500"
                                />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {allRestorableTypes.length > 0 && (
                    <div className="flex gap-2 text-xs">
                      <button onClick={selectAll} className="text-zs-600 hover:text-zs-800">Select all</button>
                      <span className="text-gray-300">|</span>
                      <button onClick={clearAll} className="text-gray-500 hover:text-gray-700">Clear</button>
                    </div>
                  )}

                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Target tenant (leave blank for same tenant)
                    </label>
                    <input
                      type="text"
                      value={targetTenant}
                      onChange={(e) => setTargetTenant(e.target.value)}
                      placeholder="tenant name"
                      className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
                    />
                  </div>

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={dryRun}
                      onChange={(e) => setDryRun(e.target.checked)}
                      className="h-4 w-4 accent-zs-500"
                    />
                    Dry run (preview only — no changes applied)
                  </label>
                </div>
              )}
              {restoreMut.isError && (
                <ErrorMessage message={restoreMut.error instanceof Error ? restoreMut.error.message : "Restore failed"} />
              )}
            </>
          ) : (
            <div className="space-y-3">
              <p className="text-sm font-medium text-gray-700">
                {result.dry_run ? "Dry run complete" : "Restore complete"} —{" "}
                Created: {result.summary.created}, Updated: {result.summary.updated}, Deleted: {result.summary.deleted},
                Skipped: {result.summary.skipped}, Failed: {result.summary.failed}, Unrestorable: {result.summary.unrestorable}
              </p>
              <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="min-w-full text-sm divide-y divide-gray-100">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                      <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">OK</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Reason</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-100">
                    {result.results.map((r, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2 font-mono text-xs text-gray-700">{r.resource_type}</td>
                        <td className={`px-3 py-2 text-xs font-medium ${ACTION_COLOR[r.action] ?? ""}`}>{r.action}</td>
                        <td className="px-3 py-2 text-xs text-gray-600">{r.name ?? "—"}</td>
                        <td className="px-3 py-2 text-center">{r.success ? "✓" : "✗"}</td>
                        <td className="px-3 py-2 text-xs text-gray-500">{r.reason ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t">
          {!result ? (
            <>
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => restoreMut.mutate()}
                disabled={restoreMut.isPending || selectedTypes.length === 0}
                className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
              >
                {restoreMut.isPending ? "Running..." : dryRun ? "Run Dry Run" : "Restore"}
              </button>
            </>
          ) : (
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white"
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── ZCC Snapshots Section ─────────────────────────────────────────────────────

function ZccSnapshotsSection({ tenant, isOpen }: { tenant: Tenant; isOpen: boolean }) {
  const qc = useQueryClient();
  const [labelInput, setLabelInput] = useState("");
  const [noteInput, setNoteInput] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<ZccSnapshot | null>(null);

  const { data, isLoading, error } = useQuery<ZccSnapshot[]>({
    queryKey: ["zcc-snapshots", tenant.name],
    queryFn: () => listZccSnapshots(tenant.name),
    enabled: isOpen,
  });

  const createMut = useMutation({
    mutationFn: () =>
      createZccSnapshot(tenant.name, {
        label: labelInput.trim() || "Snapshot",
        note: noteInput.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zcc-snapshots", tenant.name] });
      setLabelInput("");
      setNoteInput("");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteZccSnapshot(tenant.name, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zcc-snapshots", tenant.name] });
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
        <ZccRestoreModal
          tenant={tenant}
          snapshot={restoreTarget}
          onClose={() => setRestoreTarget(null)}
        />
      )}

      <div className="space-y-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Label</label>
          <input
            type="text"
            value={labelInput}
            onChange={(e) => setLabelInput(e.target.value)}
            placeholder="e.g. pre-change baseline"
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Note (optional)</label>
          <input
            type="text"
            value={noteInput}
            onChange={(e) => setNoteInput(e.target.value)}
            placeholder=""
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <button
          onClick={() => createMut.mutate()}
          disabled={createMut.isPending || !labelInput.trim()}
          className="px-3 py-1.5 text-xs rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
        >
          {createMut.isPending ? "Saving..." : "Save Snapshot"}
        </button>
      </div>
      {createMut.isError && (
        <ErrorMessage message={createMut.error instanceof Error ? createMut.error.message : "Failed to save"} />
      )}

      {snaps.length === 0 ? (
        <p className="text-sm text-gray-400">No snapshots saved yet.</p>
      ) : (
        <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
          {snaps.map((s: ZccSnapshot) => (
            <div key={s.id} className="flex items-center justify-between px-4 py-3 bg-white">
              <div>
                <p className="text-sm font-medium text-gray-900">{s.label || <span className="italic text-gray-400">Unlabeled</span>}</p>
                <p className="text-xs text-gray-400">
                  {formatDateTime(s.created_at)} · {s.resource_count} resources
                  {s.note && <span className="ml-2 italic text-gray-400">{s.note}</span>}
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

function ZccFailOpenPolicySection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery<ZccFailOpenPolicy[]>({
    queryKey: ["zcc-fail-open-policies", tenantName],
    queryFn: () => listFailOpenPolicies(tenantName),
    enabled: isOpen,
  });
  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data || data.length === 0) return <p className="text-sm text-gray-400 px-3 py-4">No fail open policy configured</p>;
  const p = data[0];
  const rows: [string, string][] = [
    ["Fail Open Enabled", (p as Record<string, unknown>)["enable_fail_open"] ? "Yes" : "No"],
    ["Active", p.active ? "Yes" : "No"],
    ...(Object.entries(p)
      .filter(([k]) => !["id", "name", "enable_fail_open", "active"].includes(k))
      .map(([k, v]): [string, string] => [k, String(v ?? "-")])),
  ];
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Setting</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Value</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="px-3 py-2 text-gray-600 font-medium">{k}</td>
              <td className="px-3 py-2 text-gray-900">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ZccWebPrivacySection({ tenantName, isOpen }: { tenantName: string; isOpen: boolean }) {
  const { data, isLoading, error } = useQuery<ZccWebPrivacy>({
    queryKey: ["zcc-web-privacy", tenantName],
    queryFn: () => getWebPrivacy(tenantName),
    enabled: isOpen,
  });
  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Failed to load"} />;
  if (!data || Object.keys(data).length === 0) return <p className="text-sm text-gray-400 px-3 py-4">No web privacy settings imported</p>;
  const rows = Object.entries(data).filter(([k]) => k !== "id" && k !== "name");
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Setting</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Value</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="px-3 py-2 text-gray-600 font-medium">{k}</td>
              <td className="px-3 py-2 text-gray-900">{String(v ?? "-")}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
  const [importModal, setImportModal] = useState<"ZIA" | "ZPA" | "ZCC" | null>(null);

  // Determine active tab from URL segment
  const pathSegment = location.pathname.split("/").pop() as TabId | undefined;
  const activeTab: TabId = (["zia", "zpa", "zdx", "zcc", "zid", "sim"].includes(pathSegment ?? "") ? pathSegment : "zia") as TabId;

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
    { id: "sim", label: "Simulator", show: true },
  ];

  // If trying to view ZPA tab but no ZPA, redirect to ZIA
  if (activeTab === "zpa" && !tenant.zpa_customer_id) {
    navigate(`/tenant/${id}/zia`, { replace: true });
    return null;
  }

  const importButtonLabel =
    activeTab === "zpa" ? "Import ZPA" :
    activeTab === "zcc" ? "Import ZCC" :
    "Import ZIA";
  const importProduct: "ZIA" | "ZPA" | "ZCC" =
    activeTab === "zpa" ? "ZPA" :
    activeTab === "zcc" ? "ZCC" :
    "ZIA";

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
        {(activeTab === "zia" || (activeTab === "zpa" && hasZpa) || activeTab === "zcc") && (
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
      {activeTab === "sim" && <SimulatorTab key={tenant.id} tenant={tenant} />}

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
