import { useState } from "react";
import { formatDateTime } from "../utils/time";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchAdminUsers,
  createAdminUser,
  updateAdminUser,
  deleteAdminUser,
  AdminUser,
  UserCreate,
  UserUpdate,
} from "../api/admin";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import { useAuth } from "../context/AuthContext";

// ── Modal wrapper ─────────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4">{children}</div>
      </div>
    </div>
  );
}

// ── Create Modal ──────────────────────────────────────────────────────────────

function CreateModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<UserCreate>({
    username: "",
    password: "",
    email: "",
    role: "user",
    force_password_change: true,
  });
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: createAdminUser,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    mut.mutate({ ...form, email: form.email || undefined });
  }

  return (
    <Modal title="Create User" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Username</label>
          <input
            value={form.username}
            onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
            required
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Email (optional)</label>
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            required
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
          <select
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as "admin" | "user" }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={form.force_password_change}
            onChange={(e) => setForm((f) => ({ ...f, force_password_change: e.target.checked }))}
            className="accent-zs-500"
          />
          Require password change on first login
        </label>
        {error && <p className="text-red-600 text-xs">{error}</p>}
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

// ── Edit Modal ────────────────────────────────────────────────────────────────

function EditModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<UserUpdate & { password: string }>({
    email: user.email ?? "",
    role: user.role as "admin" | "user",
    is_active: user.is_active,
    force_password_change: user.force_password_change,
    password: "",
  });
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: (body: UserUpdate) => updateAdminUser(user.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const body: UserUpdate = {
      email: form.email || undefined,
      role: form.role,
      is_active: form.is_active,
      force_password_change: form.force_password_change,
    };
    if (form.password) body.password = form.password;
    mut.mutate(body);
  }

  return (
    <Modal title={`Edit: ${user.username}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        {user.scim_managed && (
          <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
            This account is provisioned by your identity provider. Changes made here are
            overwritten on the next SCIM sync — edit the user in the IdP instead.
          </div>
        )}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Email (optional)</label>
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">New Password (leave blank to keep)</label>
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            placeholder="(unchanged)"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
          <select
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as "admin" | "user" }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
            className="accent-zs-500"
          />
          Active
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={form.force_password_change}
            onChange={(e) => setForm((f) => ({ ...f, force_password_change: e.target.checked }))}
            className="accent-zs-500"
          />
          Require password change on next login
        </label>
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

// ── MFA Toggle Modal ──────────────────────────────────────────────────────────

function MfaToggleModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const qc = useQueryClient();
  const enabling = !user.mfa_required;
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () => updateAdminUser(user.id, { mfa_required: enabling }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Modal title={enabling ? "Require MFA for User" : "Remove MFA Requirement"} onClose={onClose}>
      <div className="space-y-3">
        {enabling ? (
          <>
            <p className="text-sm text-gray-700">
              You are about to require FIDO2 / passkey authentication for <strong>{user.username}</strong>.
            </p>
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-md text-sm text-amber-800 space-y-1.5">
              <p className="font-semibold">Important: key loss = unrecoverable account</p>
              <p>
                If this user loses access to all enrolled security keys, their account cannot be
                recovered without admin intervention (deleting and re-creating the account).
              </p>
              <p>
                Recommend that the user enrolls a <strong>passkey</strong> stored in iOS, Android,
                or a password manager (1Password, Bitwarden, etc.) rather than relying solely on
                a hardware security key, as passkeys are backed up and transferable.
              </p>
            </div>
            <p className="text-sm text-gray-600">
              Once enabled, <strong>{user.username}</strong> must have a passkey/security key
              enrolled to log in via password. If they have no key enrolled, login will be blocked
              until a key is registered (you may need to temporarily disable this requirement).
            </p>
          </>
        ) : (
          <p className="text-sm text-gray-700">
            Remove the MFA requirement from <strong>{user.username}</strong>? They will be able to
            log in with just a password.
          </p>
        )}
        {error && <p className="text-red-600 text-xs">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50">Cancel</button>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending}
            className={`px-4 py-2 text-sm rounded-md text-white disabled:opacity-60 ${enabling ? "bg-amber-600 hover:bg-amber-700" : "bg-gray-600 hover:bg-gray-700"}`}
          >
            {mut.isPending ? "Saving…" : enabling ? "Enable MFA Requirement" : "Remove MFA Requirement"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── Delete Modal ──────────────────────────────────────────────────────────────

function DeleteModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () => deleteAdminUser(user.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Modal title="Delete User" onClose={onClose}>
      <p className="text-gray-700 text-sm mb-4">
        Are you sure you want to delete <strong>{user.username}</strong>? This cannot be undone.
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

// ── Main page ─────────────────────────────────────────────────────────────────

type ModalState =
  | { type: "none" }
  | { type: "create" }
  | { type: "edit"; user: AdminUser }
  | { type: "delete"; user: AdminUser }
  | { type: "mfa"; user: AdminUser };

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const { data: users, isLoading, error } = useQuery({
    queryKey: ["admin-users"],
    queryFn: fetchAdminUsers,
  });

  const [modal, setModal] = useState<ModalState>({ type: "none" });
  const closeModal = () => setModal({ type: "none" });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Users</h1>
        <button
          onClick={() => setModal({ type: "create" })}
          className="bg-zs-500 hover:bg-zs-600 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
        >
          Add User
        </button>
      </div>

      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load users"} />}

      {users && (
        <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
          <table className="min-w-full divide-y divide-gray-300">
            <thead className="bg-gray-50">
              <tr>
                <th className="py-3 pl-4 pr-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Username</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Email</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Role</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">MFA</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Last Login</th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {users.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-sm text-gray-500">No users found.</td>
                </tr>
              )}
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap py-3 pl-4 pr-3 text-sm font-medium text-gray-900">
                    {u.username}
                    {u.id === currentUser?.sub && (
                      <span className="ml-2 text-xs text-gray-400">(you)</span>
                    )}
                    {u.scim_managed && (
                      <span
                        title="Provisioned by your identity provider"
                        className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700"
                      >
                        SCIM
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">{u.email ?? "-"}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      u.role === "admin"
                        ? "bg-purple-100 text-purple-800"
                        : "bg-gray-100 text-gray-700"
                    }`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    {u.is_active ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">Active</span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">Inactive</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    <button
                      onClick={() => setModal({ type: "mfa", user: u })}
                      title={u.mfa_required ? "MFA required — click to remove requirement" : "MFA not required — click to require"}
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium cursor-pointer transition-colors ${
                        u.mfa_required
                          ? "bg-amber-100 text-amber-800 hover:bg-amber-200"
                          : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                      }`}
                    >
                      {u.mfa_required ? "Required" : "Off"}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {formatDateTime(u.last_login_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setModal({ type: "edit", user: u })}
                        className="text-zs-500 hover:text-zs-600 font-medium text-xs"
                      >
                        Edit
                      </button>
                      {u.id !== currentUser?.sub && (
                        <button
                          onClick={() => setModal({ type: "delete", user: u })}
                          className="text-red-600 hover:text-red-700 font-medium text-xs"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal.type === "create" && <CreateModal onClose={closeModal} />}
      {modal.type === "edit" && <EditModal user={modal.user} onClose={closeModal} />}
      {modal.type === "delete" && <DeleteModal user={modal.user} onClose={closeModal} />}
      {modal.type === "mfa" && <MfaToggleModal user={modal.user} onClose={closeModal} />}
    </div>
  );
}
