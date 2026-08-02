/**
 * Groups: who is in them, what role they carry, and which tenants they grant.
 *
 * A group is either pushed by the identity provider over SCIM or created here.
 * The IdP owns the name, description and its own memberships of a SCIM group,
 * so those controls are disabled rather than left to fail server-side — but
 * role mapping and tenant grants are ours for every group, whatever its source.
 */

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Group,
  GroupMember,
  addGroupMembers,
  createGroup,
  deleteGroup,
  fetchGroupMembers,
  fetchGroupTenants,
  fetchGroups,
  grantGroupTenants,
  removeGroupMember,
  revokeGroupTenant,
  setGroupRole,
  updateGroup,
} from "../api/groups";
import { fetchAdminUsers } from "../api/admin";
import { fetchTenants } from "../api/tenants";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

function SourceBadge({ source }: { source: "scim" | "local" }) {
  return source === "scim" ? (
    <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">SCIM</span>
  ) : (
    <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">Local</span>
  );
}

// ── Create group ──────────────────────────────────────────────────────────────

function CreateGroupModal({ onClose }: { onClose: (created?: Group) => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [role, setRole] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => createGroup(name.trim(), description.trim() || null, role || null),
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ["admin-groups"] });
      onClose(g);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">New Group</h3>
          <button onClick={() => onClose()} className="text-gray-400 hover:text-gray-600 text-xl leading-none">
            &times;
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            create.mutate();
          }}
          className="px-6 py-4 space-y-4"
        >
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Role mapping</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
            >
              <option value="">Not mapped</option>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Members take this role as soon as they join the group.
            </p>
          </div>
          {error && <p className="text-red-600 text-xs">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => onClose()}
              className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={create.isPending || !name.trim()}
              className="px-4 py-2 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
            >
              {create.isPending ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Members ───────────────────────────────────────────────────────────────────

function MembersPanel({ group }: { group: Group }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const { data: members, isLoading } = useQuery({
    queryKey: ["group-members", group.id],
    queryFn: () => fetchGroupMembers(group.id),
  });
  const { data: users } = useQuery({ queryKey: ["admin-users"], queryFn: fetchAdminUsers });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["group-members", group.id] });
    qc.invalidateQueries({ queryKey: ["admin-groups"] });
    // A mapped group changes roles as people come and go.
    qc.invalidateQueries({ queryKey: ["admin-users"] });
  };

  const add = useMutation({
    mutationFn: (ids: number[]) => addGroupMembers(group.id, ids),
    onSuccess: () => {
      setAdding(new Set());
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const remove = useMutation({
    mutationFn: (userId: number) => removeGroupMember(group.id, userId),
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const memberIds = new Set((members ?? []).map((m: GroupMember) => m.user_id));
  const candidates = (users ?? []).filter((u) => !memberIds.has(u.id));

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-gray-700">Members</p>
      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error} />}

      {members && members.length > 0 ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-200">
              <th className="py-1.5 font-medium">User</th>
              <th className="py-1.5 font-medium">Role</th>
              <th className="py-1.5 font-medium">Added by</th>
              <th className="py-1.5" />
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id} className="border-b border-gray-100">
                <td className="py-1.5 text-gray-700">
                  {m.username}
                  {!m.is_active && <span className="ml-2 text-gray-400">(inactive)</span>}
                </td>
                <td className="py-1.5 text-gray-500">{m.role}</td>
                <td className="py-1.5 text-gray-500">
                  {m.source === "scim" ? "identity provider" : m.added_by || "—"}
                </td>
                <td className="py-1.5 text-right">
                  {m.source === "scim" ? (
                    <span className="text-gray-400" title="Remove this person in the identity provider">
                      managed
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setError(null);
                        remove.mutate(m.user_id);
                      }}
                      disabled={remove.isPending}
                      className="text-red-600 hover:underline disabled:opacity-50"
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        !isLoading && <p className="text-xs text-gray-400">No members yet.</p>
      )}

      {candidates.length > 0 && (
        <div className="pt-2 space-y-2">
          <p className="text-xs font-medium text-gray-600">Add members</p>
          <div className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-40 overflow-y-auto">
            {candidates.map((u) => (
              <label key={u.id} className="flex items-center gap-3 px-3 py-1.5 cursor-pointer hover:bg-gray-50">
                <input
                  type="checkbox"
                  checked={adding.has(u.id)}
                  onChange={() =>
                    setAdding((prev) => {
                      const next = new Set(prev);
                      if (next.has(u.id)) next.delete(u.id);
                      else next.add(u.id);
                      return next;
                    })
                  }
                  className="accent-zs-500"
                />
                <span className="text-sm text-gray-800">{u.username}</span>
                <span className="ml-auto text-xs text-gray-400">{u.role}</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              setError(null);
              add.mutate(Array.from(adding));
            }}
            disabled={add.isPending || adding.size === 0}
            className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
          >
            {add.isPending ? "Adding…" : `Add${adding.size > 0 ? ` (${adding.size})` : ""}`}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Tenant grants ─────────────────────────────────────────────────────────────

function TenantsPanel({ group }: { group: Group }) {
  const qc = useQueryClient();
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const { data: grants, isLoading } = useQuery({
    queryKey: ["group-tenants", group.id],
    queryFn: () => fetchGroupTenants(group.id),
  });
  const { data: tenants } = useQuery({ queryKey: ["tenants"], queryFn: fetchTenants });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["group-tenants", group.id] });
    qc.invalidateQueries({ queryKey: ["admin-groups"] });
  };

  const grant = useMutation({
    mutationFn: (ids: number[]) => grantGroupTenants(group.id, ids),
    onSuccess: () => {
      setPicked(new Set());
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const revoke = useMutation({
    mutationFn: (tenantId: number) => revokeGroupTenant(group.id, tenantId),
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const grantedIds = new Set((grants ?? []).map((g) => g.tenant_id));
  const available = (tenants ?? []).filter((t) => !grantedIds.has(t.id));

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-gray-700">Tenant access</p>
      <p className="text-xs text-gray-500">
        Everyone in this group can reach these tenants, on top of anything granted to them
        individually on the Tenant Access page.
      </p>
      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error} />}

      {grants && grants.length > 0 ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-200">
              <th className="py-1.5 font-medium">Tenant</th>
              <th className="py-1.5 font-medium">Granted</th>
              <th className="py-1.5" />
            </tr>
          </thead>
          <tbody>
            {grants.map((g) => (
              <tr key={g.id} className="border-b border-gray-100">
                <td className="py-1.5 text-gray-700">{g.tenant_name}</td>
                <td className="py-1.5 text-gray-500">
                  {g.granted_at ? new Date(g.granted_at).toLocaleDateString() : "—"}
                </td>
                <td className="py-1.5 text-right">
                  <button
                    type="button"
                    onClick={() => {
                      setError(null);
                      revoke.mutate(g.tenant_id);
                    }}
                    disabled={revoke.isPending}
                    className="text-red-600 hover:underline disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        !isLoading && <p className="text-xs text-gray-400">No tenants granted to this group.</p>
      )}

      {available.length > 0 && (
        <div className="pt-2 space-y-2">
          <p className="text-xs font-medium text-gray-600">Grant tenants</p>
          <div className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-40 overflow-y-auto">
            {available.map((t) => (
              <label key={t.id} className="flex items-center gap-3 px-3 py-1.5 cursor-pointer hover:bg-gray-50">
                <input
                  type="checkbox"
                  checked={picked.has(t.id)}
                  onChange={() =>
                    setPicked((prev) => {
                      const next = new Set(prev);
                      if (next.has(t.id)) next.delete(t.id);
                      else next.add(t.id);
                      return next;
                    })
                  }
                  className="accent-zs-500"
                />
                <span className="text-sm text-gray-800">{t.name}</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              setError(null);
              grant.mutate(Array.from(picked));
            }}
            disabled={grant.isPending || picked.size === 0}
            className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
          >
            {grant.isPending ? "Granting…" : `Grant${picked.size > 0 ? ` (${picked.size})` : ""}`}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Detail ────────────────────────────────────────────────────────────────────

function GroupDetail({ group }: { group: Group }) {
  const qc = useQueryClient();
  const [name, setName] = useState(group.display_name);
  const [description, setDescription] = useState(group.description ?? "");
  const [error, setError] = useState<string | null>(null);

  // Switching groups reuses this component, so the fields have to follow.
  useEffect(() => {
    setName(group.display_name);
    setDescription(group.description ?? "");
    setError(null);
  }, [group.id, group.display_name, group.description]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin-groups"] });
    qc.invalidateQueries({ queryKey: ["admin-users"] });
  };

  const save = useMutation({
    mutationFn: () =>
      updateGroup(group.id, { display_name: name.trim(), description: description.trim() || null }),
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const role = useMutation({
    mutationFn: (r: string | null) => setGroupRole(group.id, r),
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const del = useMutation({
    mutationFn: () => deleteGroup(group.id),
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const managed = group.source === "scim";
  const dirty = name.trim() !== group.display_name || description.trim() !== (group.description ?? "");

  return (
    <div className="bg-white rounded-lg shadow ring-1 ring-black ring-opacity-5 p-5 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-900">{group.display_name}</h2>
          <SourceBadge source={group.source} />
        </div>
        {!managed && (
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm(
                  `Delete "${group.display_name}"? Its members lose any tenant and plugin access this group granted.`,
                )
              ) {
                setError(null);
                del.mutate();
              }
            }}
            disabled={del.isPending}
            className="text-xs text-red-600 hover:underline disabled:opacity-50"
          >
            {del.isPending ? "Deleting…" : "Delete group"}
          </button>
        )}
      </div>

      {error && <ErrorMessage message={error} />}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
          <input
            type="text"
            value={name}
            disabled={managed}
            onChange={(e) => setName(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm disabled:bg-gray-50 disabled:text-gray-500 focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
          <input
            type="text"
            value={description}
            disabled={managed}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm disabled:bg-gray-50 disabled:text-gray-500 focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
      </div>
      {managed ? (
        <p className="text-xs text-gray-400">
          This group is provisioned over SCIM — rename it in your identity provider.
        </p>
      ) : (
        dirty && (
          <button
            type="button"
            onClick={() => {
              setError(null);
              save.mutate();
            }}
            disabled={save.isPending || !name.trim()}
            className="px-3 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-60"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        )
      )}

      <div className="pt-4 border-t border-gray-100 space-y-2">
        <label className="block text-xs font-medium text-gray-600">Role mapping</label>
        <select
          value={group.mapped_role ?? ""}
          onChange={(e) => {
            setError(null);
            role.mutate(e.target.value || null);
          }}
          disabled={role.isPending}
          className="border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        >
          <option value="">Not mapped</option>
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
        <p className="text-xs text-gray-400">
          Applies to every member immediately. Unmapped groups leave members on their own role.
        </p>
      </div>

      <div className="pt-4 border-t border-gray-100">
        <MembersPanel group={group} />
      </div>

      <div className="pt-4 border-t border-gray-100">
        <TenantsPanel group={group} />
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminGroupsPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const { data: groups, isLoading, error } = useQuery({
    queryKey: ["admin-groups"],
    queryFn: fetchGroups,
  });

  // Keep a selection pointing at a group that still exists — deleting the
  // selected one would otherwise leave the detail pane on a stale record.
  const selected = groups?.find((g) => g.id === selectedId) ?? null;
  useEffect(() => {
    if (selectedId !== null && groups && !groups.some((g) => g.id === selectedId)) {
      setSelectedId(null);
    }
  }, [groups, selectedId]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Groups</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-zs-500 hover:bg-zs-600 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
        >
          New Group
        </button>
      </div>

      <p className="text-sm text-gray-500 mb-4">
        Groups carry a role and a set of tenants for everyone in them. Those your identity
        provider pushes over SCIM appear here automatically; you can also create your own and
        pick the members by hand.
      </p>

      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load groups"} />}

      {groups && (
        <div className="grid gap-6 lg:grid-cols-[20rem_1fr] items-start">
          <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg bg-white divide-y divide-gray-100">
            {groups.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-gray-500">No groups yet.</p>
            )}
            {groups.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => setSelectedId(g.id)}
                className={`w-full text-left px-4 py-3 hover:bg-gray-50 ${
                  g.id === selectedId ? "bg-zs-50" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900">{g.display_name}</span>
                  <SourceBadge source={g.source} />
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {g.member_count} member{g.member_count === 1 ? "" : "s"} · {g.tenant_count} tenant
                  {g.tenant_count === 1 ? "" : "s"}
                  {g.mapped_role && ` · ${g.mapped_role}`}
                </div>
              </button>
            ))}
          </div>

          {selected ? (
            <GroupDetail group={selected} />
          ) : (
            <p className="text-sm text-gray-400 px-1 py-6">Select a group to manage it.</p>
          )}
        </div>
      )}

      {showCreate && (
        <CreateGroupModal
          onClose={(created) => {
            setShowCreate(false);
            if (created) setSelectedId(created.id);
          }}
        />
      )}
    </div>
  );
}
