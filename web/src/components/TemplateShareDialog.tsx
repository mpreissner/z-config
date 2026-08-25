/**
 * Sharing controls for one template: who it reaches, and how.
 *
 * Visibility and the grant list are separate settings that interact, which is
 * the one thing this dialog has to make legible. Granting to a user or group
 * promotes a private template to "shared" automatically (the API does it), but
 * going back to private leaves the grants in place and dormant — so the
 * template can be un-published without losing the list of who had it.
 *
 * Reading and applying are one permission: anyone here can push the template
 * into any tenant they already have access to. There is no view-only share,
 * because it would not restrict anything.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ZIATemplate,
  TemplateShare,
  fetchTemplateShares,
  fetchShareTargets,
  addTemplateShares,
  removeTemplateShare,
  updateTemplate,
} from "../api/templates";
import LoadingSpinner from "./LoadingSpinner";
import ErrorMessage from "./ErrorMessage";

const VISIBILITY_LABELS: Record<string, { title: string; blurb: string }> = {
  private: {
    title: "Private",
    blurb: "Only you and administrators can see this template.",
  },
  shared: {
    title: "Shared",
    blurb: "Visible to the users and groups granted below.",
  },
  org: {
    title: "Org-wide",
    blurb: "Every account in this deployment can see and apply it.",
  },
};

export default function TemplateShareDialog({ template, onClose, onChanged }: {
  template: ZIATemplate;
  onClose: () => void;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const [pickedUsers, setPickedUsers] = useState<Set<number>>(new Set());
  const [pickedGroups, setPickedGroups] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const { data: shares, isLoading: sharesLoading } = useQuery<TemplateShare[]>({
    queryKey: ["template-shares", template.id],
    queryFn: () => fetchTemplateShares(template.id),
  });

  const { data: targets } = useQuery({
    queryKey: ["template-share-targets"],
    queryFn: fetchShareTargets,
    staleTime: 60_000,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["template-shares", template.id] });
    onChanged();
  }

  const addMut = useMutation({
    mutationFn: () =>
      addTemplateShares(template.id, {
        user_ids: [...pickedUsers],
        group_ids: [...pickedGroups],
      }),
    onSuccess: () => {
      setPickedUsers(new Set());
      setPickedGroups(new Set());
      setErr(null);
      refresh();
    },
    onError: (e: Error) => setErr(e.message),
  });

  const removeMut = useMutation({
    mutationFn: (shareId: number) => removeTemplateShare(template.id, shareId),
    onSuccess: () => { setErr(null); refresh(); },
    onError: (e: Error) => setErr(e.message),
  });

  const visibilityMut = useMutation({
    mutationFn: (visibility: "private" | "shared" | "org") =>
      updateTemplate(template.id, { visibility }),
    onSuccess: () => { setErr(null); refresh(); },
    onError: (e: Error) => setErr(e.message),
  });

  const visibility = visibilityMut.data?.visibility ?? template.visibility;

  const sharedUserIds = new Set((shares ?? []).map((s) => s.user_id).filter((x): x is number => x !== null));
  const sharedGroupIds = new Set((shares ?? []).map((s) => s.group_id).filter((x): x is number => x !== null));

  const needle = filter.trim().toLowerCase();
  const availableUsers = (targets?.users ?? []).filter(
    (u) =>
      u.id !== template.owner_user_id &&
      !sharedUserIds.has(u.id) &&
      (!needle || u.username.toLowerCase().includes(needle)),
  );
  const availableGroups = (targets?.groups ?? []).filter(
    (g) => !sharedGroupIds.has(g.id) && (!needle || g.display_name.toLowerCase().includes(needle)),
  );

  const pickedCount = pickedUsers.size + pickedGroups.size;

  function toggleUser(id: number) {
    setPickedUsers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleGroup(id: number) {
    setPickedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">Share &ldquo;{template.name}&rdquo;</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {err && <ErrorMessage message={err} />}

          {/* Visibility */}
          <div>
            <p className="text-xs font-medium text-gray-600 mb-1.5">Visibility</p>
            <div className="space-y-1.5">
              {(["private", "shared", "org"] as const).map((v) => (
                <label key={v} className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="visibility"
                    checked={visibility === v}
                    onChange={() => visibilityMut.mutate(v)}
                    disabled={visibilityMut.isPending}
                    className="mt-0.5"
                  />
                  <div>
                    <span className="text-sm font-medium text-gray-800">{VISIBILITY_LABELS[v].title}</span>
                    <p className="text-xs text-gray-500">{VISIBILITY_LABELS[v].blurb}</p>
                  </div>
                </label>
              ))}
            </div>
            {visibility === "private" && (shares?.length ?? 0) > 0 && (
              <p className="mt-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                The grants below are kept but not in effect while the template is private.
              </p>
            )}
          </div>

          {/* Current grants */}
          <div>
            <p className="text-xs font-medium text-gray-600 mb-1.5">
              Shared with ({shares?.length ?? 0})
            </p>
            {sharesLoading ? (
              <LoadingSpinner />
            ) : (shares?.length ?? 0) === 0 ? (
              <p className="text-xs text-gray-400 italic">Not shared with anyone yet.</p>
            ) : (
              <div className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-40 overflow-y-auto">
                {shares!.map((s) => (
                  <div key={s.id} className="flex items-center justify-between px-3 py-1.5">
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-gray-800 truncate">
                        {s.username ?? s.group_name ?? "—"}
                        <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-400">
                          {s.user_id !== null ? "user" : "group"}
                        </span>
                      </p>
                      {s.shared_by && (
                        <p className="text-[11px] text-gray-400 truncate">granted by {s.shared_by}</p>
                      )}
                    </div>
                    <button
                      onClick={() => removeMut.mutate(s.id)}
                      disabled={removeMut.isPending}
                      className="text-xs text-red-600 hover:text-red-700 disabled:opacity-50 flex-shrink-0 ml-2"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Add grants */}
          <div>
            <p className="text-xs font-medium text-gray-600 mb-1.5">Add people or groups</p>
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by name…"
              className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
            />
            <div className="mt-1.5 border border-gray-200 rounded-md max-h-48 overflow-y-auto divide-y divide-gray-100">
              {availableGroups.length === 0 && availableUsers.length === 0 && (
                <p className="px-3 py-2 text-xs text-gray-400 italic">Nobody left to share with.</p>
              )}
              {availableGroups.length > 0 && (
                <div className="px-3 py-1 bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
                  Groups
                </div>
              )}
              {availableGroups.map((g) => (
                <label key={`g${g.id}`} className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-50">
                  <input type="checkbox" checked={pickedGroups.has(g.id)} onChange={() => toggleGroup(g.id)} />
                  <span className="text-xs text-gray-800 truncate">{g.display_name}</span>
                </label>
              ))}
              {availableUsers.length > 0 && (
                <div className="px-3 py-1 bg-gray-50 text-[11px] uppercase tracking-wide text-gray-500">
                  Users
                </div>
              )}
              {availableUsers.map((u) => (
                <label key={`u${u.id}`} className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-gray-50">
                  <input type="checkbox" checked={pickedUsers.has(u.id)} onChange={() => toggleUser(u.id)} />
                  <span className="text-xs text-gray-800 truncate">{u.username}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between px-5 py-4 border-t border-gray-200">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded-md border border-gray-300 hover:bg-gray-50">
            Close
          </button>
          <button
            onClick={() => addMut.mutate()}
            disabled={pickedCount === 0 || addMut.isPending}
            className="px-4 py-1.5 text-sm rounded-md bg-zs-500 hover:bg-zs-600 text-white disabled:opacity-50"
          >
            Share with {pickedCount || ""} {pickedCount === 1 ? "recipient" : "recipients"}
          </button>
        </div>
      </div>
    </div>
  );
}
