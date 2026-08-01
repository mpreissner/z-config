import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchEntitlements,
  createEntitlementsBulk,
  deleteEntitlement,
  fetchAdminUsers,
  AdminUser,
  Entitlement,
} from "../api/admin";
import { fetchTenants, Tenant } from "../api/tenants";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

// ── Grant Modal ───────────────────────────────────────────────────────────────

function GrantModal({
  users,
  tenants,
  entitlements,
  onClose,
}: {
  users: AdminUser[];
  tenants: Tenant[];
  entitlements: Entitlement[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [userId, setUserId] = useState<number | "">("");
  const [selectedTenantIds, setSelectedTenantIds] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  const grantedSet = new Set(entitlements.map((e) => `${e.user_id}:${e.tenant_id}`));

  const availableTenants =
    userId !== ""
      ? tenants.filter((t) => !grantedSet.has(`${userId}:${t.id}`))
      : tenants;

  function toggleTenant(id: number) {
    setSelectedTenantIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (userId === "" || selectedTenantIds.size === 0) return;
    setError(null);
    setIsPending(true);
    try {
      // One request for the whole selection. Sending these in parallel put the
      // concurrent writes into each other's transactions and failed the grant.
      await createEntitlementsBulk(userId as number, Array.from(selectedTenantIds));
      qc.invalidateQueries({ queryKey: ["entitlements"] });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to grant access");
    } finally {
      setIsPending(false);
    }
  }

  const nonAdminUsers = users.filter((u) => u.role !== "admin" && u.is_active);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">Grant Access</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">User</label>
            <select
              value={userId}
              onChange={(e) => { setUserId(e.target.value ? Number(e.target.value) : ""); setSelectedTenantIds(new Set()); }}
              required
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
            >
              <option value="">Select a user...</option>
              {nonAdminUsers.map((u) => (
                <option key={u.id} value={u.id}>{u.username}</option>
              ))}
            </select>
            {nonAdminUsers.length === 0 && (
              <p className="text-xs text-gray-400 mt-1">No non-admin users found. Admins have access to all tenants.</p>
            )}
          </div>

          {userId !== "" && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-2">
                Tenants
                {selectedTenantIds.size > 0 && (
                  <span className="ml-2 text-zs-600 font-normal">{selectedTenantIds.size} selected</span>
                )}
              </label>
              {availableTenants.length === 0 ? (
                <p className="text-xs text-gray-400">This user already has access to all tenants.</p>
              ) : (
                <div className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-48 overflow-y-auto">
                  {availableTenants.map((t) => (
                    <label key={t.id} className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50">
                      <input
                        type="checkbox"
                        checked={selectedTenantIds.has(t.id)}
                        onChange={() => toggleTenant(t.id)}
                        className="accent-zs-500"
                      />
                      <span className="text-sm text-gray-800">{t.name}</span>
                      {t.govcloud && (
                        <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">GovCloud</span>
                      )}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {error && <p className="text-red-600 text-xs">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">Cancel</button>
            <button
              type="submit"
              disabled={isPending || userId === "" || selectedTenantIds.size === 0}
              className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
            >
              {isPending ? "Granting..." : `Grant Access${selectedTenantIds.size > 1 ? ` (${selectedTenantIds.size})` : ""}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminEntitlementsPage() {
  const qc = useQueryClient();
  const [showGrant, setShowGrant] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [filterUser, setFilterUser] = useState<number | "">("");

  const { data: entitlements, isLoading: loadingEnts, error: entsError } = useQuery({
    queryKey: ["entitlements"],
    queryFn: fetchEntitlements,
  });

  const { data: users } = useQuery({
    queryKey: ["admin-users"],
    queryFn: fetchAdminUsers,
  });

  const { data: tenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
  });

  const revokeMut = useMutation({
    mutationFn: deleteEntitlement,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["entitlements"] }),
    onError: (e: Error) => setRevokeError(e.message),
  });

  const nonAdminUsers = users?.filter((u) => u.role !== "admin") ?? [];
  const filtered = filterUser !== ""
    ? (entitlements ?? []).filter((e) => e.user_id === filterUser)
    : (entitlements ?? []);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Tenant Access</h1>
        <button
          onClick={() => setShowGrant(true)}
          className="bg-zs-500 hover:bg-zs-600 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
        >
          Grant Access
        </button>
      </div>

      <p className="text-sm text-gray-500 mb-4">
        Admin users have access to all tenants. Use this page to grant non-admin users access to specific tenants.
      </p>

      {loadingEnts && <LoadingSpinner />}
      {entsError && <ErrorMessage message={entsError instanceof Error ? entsError.message : "Failed to load entitlements"} />}
      {revokeError && <ErrorMessage message={revokeError} />}

      {entitlements && (
        <>
          {nonAdminUsers.length > 0 && (
            <div className="mb-4 flex items-center gap-3">
              <label className="text-sm text-gray-600">Filter by user:</label>
              <select
                value={filterUser}
                onChange={(e) => setFilterUser(e.target.value ? Number(e.target.value) : "")}
                className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
              >
                <option value="">All users</option>
                {nonAdminUsers.map((u) => (
                  <option key={u.id} value={u.id}>{u.username}</option>
                ))}
              </select>
            </div>
          )}

          <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
            <table className="min-w-full divide-y divide-gray-300">
              <thead className="bg-gray-50">
                <tr>
                  <th className="py-3 pl-4 pr-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">User</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Tenant</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Granted</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-sm text-gray-500">
                      No entitlements configured.
                    </td>
                  </tr>
                )}
                {filtered.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap py-3 pl-4 pr-3 text-sm font-medium text-gray-900">{e.username}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-700">{e.tenant_name}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                      {new Date(e.granted_at).toLocaleDateString()}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-sm">
                      <button
                        onClick={() => { setRevokeError(null); revokeMut.mutate(e.id); }}
                        disabled={revokeMut.isPending}
                        className="text-red-600 hover:text-red-700 font-medium text-xs disabled:opacity-60"
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {showGrant && users && tenants && entitlements && (
        <GrantModal
          users={users}
          tenants={tenants}
          entitlements={entitlements}
          onClose={() => setShowGrant(false)}
        />
      )}
    </div>
  );
}
