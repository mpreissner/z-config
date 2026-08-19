/**
 * Per-entry resource picker for scoped templates.
 *
 * A scoped template holds only what its author ticked here — the point being a
 * template narrow enough to describe one integration (an AI Guard rollout, say)
 * rather than a whole tenant.
 *
 * Two deliberate omissions:
 *
 * - Nothing is ticked for you. References between resources (a firewall rule's
 *   network services, a rule label) are closed over server-side at create time
 *   and reported back in the template's detail, so the boxes here stay a record
 *   of what the author actually chose.
 * - Predefined entries sit behind a disclosure. They exist in every tenant
 *   already and are matched rather than created on push, so including one is
 *   almost never what someone means — but occasionally it is, hence a
 *   disclosure and not an omission.
 */

import { useMemo, useState } from "react";
import { TemplateEntry } from "../api/templates";

interface Props {
  entries: Record<string, TemplateEntry[]>;
  selection: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
}

export default function TemplateResourcePicker({ entries, selection, onChange }: Props) {
  const types = useMemo(() => Object.keys(entries).sort(), [entries]);
  const [activeType, setActiveType] = useState<string>(types[0] ?? "");
  const [filter, setFilter] = useState("");
  const [showPredefined, setShowPredefined] = useState(false);

  const active = activeType && entries[activeType] ? activeType : types[0] ?? "";
  const rows = entries[active] ?? [];
  const picked = new Set(selection[active] ?? []);

  const needle = filter.trim().toLowerCase();
  const matches = needle
    ? rows.filter((e) => e.name.toLowerCase().includes(needle) || e.summary.toLowerCase().includes(needle))
    : rows;
  const custom = matches.filter((e) => !e.predefined);
  const predefined = matches.filter((e) => e.predefined);

  const totalSelected = Object.values(selection).reduce((n, ids) => n + ids.length, 0);

  function setIds(type: string, ids: string[]) {
    const next = { ...selection };
    if (ids.length === 0) delete next[type];
    else next[type] = ids;
    onChange(next);
  }

  function toggle(type: string, id: string) {
    const current = selection[type] ?? [];
    setIds(type, current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  }

  /** Select-all acts on what the filter is showing, not the whole type. */
  function selectVisible(add: boolean) {
    const current = new Set(selection[active] ?? []);
    const visible = showPredefined ? matches : custom;
    for (const e of visible) {
      if (add) current.add(e.id);
      else current.delete(e.id);
    }
    setIds(active, [...current]);
  }

  function switchType(t: string) {
    setActiveType(t);
    setFilter("");
    setShowPredefined(false);
  }

  if (types.length === 0) {
    return (
      <p className="text-xs text-gray-500 italic">
        No portable resources found in this snapshot.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-700">
          {totalSelected} resource{totalSelected !== 1 ? "s" : ""} selected
        </p>
        {totalSelected > 0 && (
          <button
            onClick={() => onChange({})}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            Clear all
          </button>
        )}
      </div>

      <div className="flex gap-3 border border-gray-200 rounded-md overflow-hidden" style={{ height: "320px" }}>
        {/* Type rail */}
        <div className="w-48 flex-shrink-0 overflow-y-auto border-r border-gray-200 bg-gray-50">
          {types.map((t) => {
            const n = (selection[t] ?? []).length;
            return (
              <button
                key={t}
                onClick={() => switchType(t)}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-100 transition-colors ${
                  active === t ? "bg-white border-l-2 border-zs-500 font-medium" : "border-l-2 border-transparent"
                }`}
              >
                <span className="font-mono text-gray-700 break-all">{t}</span>
                <span className="block text-gray-400 mt-0.5">
                  {n > 0 ? `${n} of ${entries[t].length} selected` : `${entries[t].length} available`}
                </span>
              </button>
            );
          })}
        </div>

        {/* Entries */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by name…"
              className="flex-1 min-w-0 border border-gray-300 rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-zs-500"
            />
            <button
              onClick={() => selectVisible(true)}
              className="text-xs text-zs-600 hover:text-zs-700 whitespace-nowrap"
            >
              Select all
            </button>
            <button
              onClick={() => selectVisible(false)}
              className="text-xs text-gray-500 hover:text-gray-700 whitespace-nowrap"
            >
              None
            </button>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
            {custom.length === 0 && predefined.length === 0 && (
              <p className="px-3 py-3 text-xs text-gray-400 italic">No entries match that filter.</p>
            )}

            {custom.map((e) => (
              <EntryRow key={e.id} entry={e} checked={picked.has(e.id)} onToggle={() => toggle(active, e.id)} />
            ))}

            {predefined.length > 0 && (
              <div>
                <button
                  onClick={() => setShowPredefined((v) => !v)}
                  className="w-full text-left px-3 py-2 text-xs text-gray-500 hover:bg-gray-50"
                >
                  {showPredefined ? "▾" : "▸"} {predefined.length} predefined entr
                  {predefined.length !== 1 ? "ies" : "y"} — already present in every tenant
                </button>
                {showPredefined &&
                  predefined.map((e) => (
                    <EntryRow key={e.id} entry={e} checked={picked.has(e.id)} onToggle={() => toggle(active, e.id)} />
                  ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function EntryRow({ entry, checked, onToggle }: {
  entry: TemplateEntry;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex items-start gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50">
      <input type="checkbox" checked={checked} onChange={onToggle} className="mt-0.5 flex-shrink-0" />
      <span className="min-w-0">
        <span className="block text-xs font-medium text-gray-800 break-words">
          {entry.order !== null && <span className="text-gray-400 mr-1">#{entry.order}</span>}
          {entry.name}
          {entry.predefined && (
            <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-400">predefined</span>
          )}
        </span>
        {entry.summary && <span className="block text-[11px] text-gray-500 break-words">{entry.summary}</span>}
      </span>
    </label>
  );
}
