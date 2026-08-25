/**
 * Per-entry resource picker for scoped templates.
 *
 * One expandable section per resource type, collapsed until opened, so a
 * snapshot with two thousand entries still fits on a screen. The section header
 * carries a tri-state checkbox that selects or clears the whole type, which is
 * the fast path; expanding is for picking individual objects out of it.
 *
 * A scoped template holds only what was ticked here — the point being a
 * template narrow enough to describe one integration (an AI Guard rollout, say)
 * rather than a whole tenant.
 *
 * Two deliberate omissions:
 *
 * - Nothing is ticked for you. References between resources (a firewall rule's
 *   network services, a rule label) are closed over server-side at create time
 *   and reported back in the template's detail, so the boxes here stay a record
 *   of what the author actually chose.
 * - Predefined entries sit behind a disclosure inside their type, and the
 *   header checkbox skips them. They exist in every tenant already and are
 *   matched rather than created on push, so including one is almost never what
 *   someone means — but occasionally it is, hence a disclosure and not an
 *   omission.
 *
 * Settings singletons are the one type where the entry is not the unit anyone
 * picks. ZIA keeps advanced settings, URL/cloud-app settings and browser
 * control settings as one object each, holding dozens of unrelated toggles, so
 * an entry there opens into its own key list. Ticking keys ticks the entry;
 * ticking the entry alone carries every key.
 */

import { useMemo, useState } from "react";
import { TemplateEntry } from "../api/templates";

interface Props {
  entries: Record<string, TemplateEntry[]>;
  selection: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
  /** {settings_type: [key, …]} — empty or absent means every key of that type. */
  fieldSelection: Record<string, string[]>;
  onFieldChange: (next: Record<string, string[]>) => void;
  disabled?: boolean;
}

/** "firewall_rule" → "Firewall Rule". The raw type is still shown alongside. */
function humanize(t: string): string {
  return t
    .split("_")
    .map((w) => (w.length <= 3 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(" ");
}

export default function TemplateResourcePicker({
  entries,
  selection,
  onChange,
  fieldSelection,
  onFieldChange,
  disabled,
}: Props) {
  const types = useMemo(() => Object.keys(entries).sort(), [entries]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");

  const needle = filter.trim().toLowerCase();
  const totalSelected = Object.values(selection).reduce((n, ids) => n + ids.length, 0);

  function setIds(type: string, ids: string[]) {
    const next = { ...selection };
    if (ids.length === 0) delete next[type];
    else next[type] = ids;
    onChange(next);
    // Dropping a settings type drops the keys chosen inside it: leaving them
    // behind would silently re-narrow the type if it were ticked again later.
    if (ids.length === 0 && fieldSelection[type]) {
      const nextFields = { ...fieldSelection };
      delete nextFields[type];
      onFieldChange(nextFields);
    }
  }

  function setFields(type: string, keys: string[]) {
    const next = { ...fieldSelection };
    if (keys.length === 0) delete next[type];
    else next[type] = keys;
    onFieldChange(next);
  }

  function toggleEntry(type: string, id: string) {
    const current = selection[type] ?? [];
    setIds(type, current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  }

  function toggleExpanded(type: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  if (types.length === 0) {
    return <p className="text-xs text-gray-500 italic">No portable resources found in this snapshot.</p>;
  }

  // While filtering, a type with no matching entries is hidden rather than
  // shown empty — otherwise the list barely shrinks and the filter looks broken.
  const visibleTypes = needle
    ? types.filter((t) =>
        entries[t].some(
          (e) => e.name.toLowerCase().includes(needle) || e.summary.toLowerCase().includes(needle),
        ),
      )
    : types;

  return (
    <div className={`space-y-2 ${disabled ? "opacity-40 pointer-events-none" : ""}`}>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter resources by name…"
          className="flex-1 min-w-0 border border-gray-300 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-zs-500"
        />
        <span className="text-xs text-gray-500 whitespace-nowrap">
          {totalSelected} selected
        </span>
        {totalSelected > 0 && (
          <button onClick={() => { onChange({}); onFieldChange({}); }} className="text-xs text-gray-500 hover:text-gray-700 underline whitespace-nowrap">
            Clear all
          </button>
        )}
      </div>

      <div className="border border-gray-200 rounded-md divide-y divide-gray-100 overflow-y-auto" style={{ maxHeight: "380px" }}>
        {visibleTypes.length === 0 && (
          <p className="px-3 py-3 text-xs text-gray-400 italic">Nothing matches that filter.</p>
        )}
        {visibleTypes.map((type) => (
          <TypeSection
            key={type}
            type={type}
            rows={entries[type]}
            picked={selection[type] ?? []}
            needle={needle}
            open={expanded.has(type) || (!!needle && visibleTypes.length <= 5)}
            onToggleOpen={() => toggleExpanded(type)}
            onToggleEntry={(id) => toggleEntry(type, id)}
            onSetIds={(ids) => setIds(type, ids)}
            pickedFields={fieldSelection[type] ?? []}
            onSetFields={(keys) => setFields(type, keys)}
          />
        ))}
      </div>
    </div>
  );
}

function TypeSection({
  type, rows, picked, needle, open, onToggleOpen, onToggleEntry, onSetIds,
  pickedFields, onSetFields,
}: {
  type: string;
  rows: TemplateEntry[];
  picked: string[];
  needle: string;
  open: boolean;
  onToggleOpen: () => void;
  onToggleEntry: (id: string) => void;
  onSetIds: (ids: string[]) => void;
  pickedFields: string[];
  onSetFields: (keys: string[]) => void;
}) {
  const [showPredefined, setShowPredefined] = useState(false);

  const matches = needle
    ? rows.filter((e) => e.name.toLowerCase().includes(needle) || e.summary.toLowerCase().includes(needle))
    : rows;
  const custom = matches.filter((e) => !e.predefined);
  const predefined = matches.filter((e) => e.predefined);

  const pickedSet = new Set(picked);
  const selectable = custom.map((e) => e.id);
  // A settings singleton is always one entry; its key count is what the header
  // should count, since the keys are what someone is choosing between.
  const settingsCount = rows.length === 1 && rows[0].fields ? rows[0].fields.length : null;
  const allSelected = selectable.length > 0 && selectable.every((id) => pickedSet.has(id));
  const someSelected = picked.length > 0 && !allSelected;

  function toggleAll() {
    if (allSelected) {
      onSetIds(picked.filter((id) => !selectable.includes(id)));
    } else {
      onSetIds([...new Set([...picked, ...selectable])]);
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50">
        <input
          type="checkbox"
          checked={allSelected}
          ref={(el) => { if (el) el.indeterminate = someSelected; }}
          onChange={toggleAll}
          disabled={selectable.length === 0}
          title={selectable.length === 0 ? "Only predefined entries here — expand to include one" : "Select every entry of this type"}
          className="flex-shrink-0"
        />
        <button onClick={onToggleOpen} className="flex-1 min-w-0 flex items-center gap-2 text-left">
          <span className="text-gray-400 text-xs w-3 flex-shrink-0">{open ? "▾" : "▸"}</span>
          <span className="min-w-0">
            <span className="block text-sm font-medium text-gray-800 truncate">
              {humanize(type)}
              <span className="ml-2 text-xs font-normal font-mono text-gray-400">{type}</span>
            </span>
            <span className="block text-xs text-gray-500">
              {settingsCount !== null
                ? picked.length === 0
                  ? `${settingsCount} setting${settingsCount !== 1 ? "s" : ""}`
                  : pickedFields.length > 0
                    ? `${pickedFields.length} of ${settingsCount} settings selected`
                    : `all ${settingsCount} settings selected`
                : picked.length > 0
                  ? `${picked.length} of ${rows.length} selected`
                  : `${rows.length} resource${rows.length !== 1 ? "s" : ""}`}
              {needle && matches.length !== rows.length && ` · ${matches.length} match the filter`}
            </span>
          </span>
        </button>
      </div>

      {open && (
        <div className="bg-gray-50 border-t border-gray-100 divide-y divide-gray-100">
          {custom.length === 0 && predefined.length === 0 && (
            <p className="px-9 py-2 text-xs text-gray-400 italic">No entries match that filter.</p>
          )}
          {custom.map((e) =>
            e.fields ? (
              <SettingsEntryRow
                key={e.id}
                entry={e}
                checked={pickedSet.has(e.id)}
                onToggle={() => onToggleEntry(e.id)}
                pickedFields={pickedFields}
                onSetFields={onSetFields}
              />
            ) : (
              <EntryRow key={e.id} entry={e} checked={pickedSet.has(e.id)} onToggle={() => onToggleEntry(e.id)} />
            ),
          )}
          {predefined.length > 0 && (
            <div>
              <button
                onClick={() => setShowPredefined((v) => !v)}
                className="w-full text-left px-9 py-1.5 text-xs text-gray-500 hover:bg-gray-100"
              >
                {showPredefined ? "▾" : "▸"} {predefined.length} predefined entr
                {predefined.length !== 1 ? "ies" : "y"} — already present in every tenant
              </button>
              {showPredefined &&
                predefined.map((e) => (
                  <EntryRow key={e.id} entry={e} checked={pickedSet.has(e.id)} onToggle={() => onToggleEntry(e.id)} />
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A settings singleton: the object checkbox plus its key list.
 *
 * The keys are the point, so they are shown expanded by default once the object
 * is ticked. No keys ticked means the whole object travels — which is what the
 * object checkbox on its own has always meant, and stays the way to say "take
 * the source tenant's settings wholesale".
 */
function SettingsEntryRow({ entry, checked, onToggle, pickedFields, onSetFields }: {
  entry: TemplateEntry;
  checked: boolean;
  onToggle: () => void;
  pickedFields: string[];
  onSetFields: (keys: string[]) => void;
}) {
  const fields = entry.fields ?? [];
  const [open, setOpen] = useState(false);
  const [fieldFilter, setFieldFilter] = useState("");

  const pickedFieldSet = new Set(pickedFields);
  const needle = fieldFilter.trim().toLowerCase();
  const visible = needle
    ? fields.filter(
        (f) => f.label.toLowerCase().includes(needle) || f.key.toLowerCase().includes(needle),
      )
    : fields;

  function toggleField(key: string) {
    const next = pickedFieldSet.has(key)
      ? pickedFields.filter((k) => k !== key)
      : [...pickedFields, key];
    onSetFields(next);
    // Picking a key implies picking the object it lives in — nobody ticks a
    // toggle meaning "and leave the settings out".
    if (next.length > 0 && !checked) onToggle();
  }

  return (
    <div>
      <div className="flex items-start gap-2 pl-9 pr-3 py-1.5 hover:bg-gray-100">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 flex-shrink-0"
        />
        <button onClick={() => setOpen((v) => !v)} className="min-w-0 flex-1 text-left">
          <span className="block text-xs font-medium text-gray-800 break-words">
            <span className="text-gray-400 mr-1">{open ? "▾" : "▸"}</span>
            {entry.name}
          </span>
          <span className="block text-[11px] text-gray-500">
            {pickedFields.length > 0
              ? `${pickedFields.length} of ${fields.length} settings`
              : checked
                ? `all ${fields.length} settings — open to pick individual ones`
                : `${fields.length} settings`}
          </span>
        </button>
      </div>

      {open && (
        <div className="bg-white border-t border-gray-100">
          <div className="flex items-center gap-2 px-3 py-1.5 pl-12">
            <input
              type="text"
              value={fieldFilter}
              onChange={(e) => setFieldFilter(e.target.value)}
              placeholder="Filter settings…"
              className="flex-1 min-w-0 border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-zs-500"
            />
            {pickedFields.length > 0 && (
              <button
                onClick={() => onSetFields([])}
                className="text-[11px] text-gray-500 hover:text-gray-700 underline whitespace-nowrap"
              >
                Take all
              </button>
            )}
          </div>
          {visible.length === 0 && (
            <p className="px-12 py-2 text-[11px] text-gray-400 italic">Nothing matches that filter.</p>
          )}
          {visible.map((f) => (
            <label
              key={f.key}
              className="flex items-start gap-2 pl-12 pr-3 py-1 cursor-pointer hover:bg-gray-50"
            >
              <input
                type="checkbox"
                checked={pickedFieldSet.has(f.key)}
                onChange={() => toggleField(f.key)}
                className="mt-0.5 flex-shrink-0"
              />
              <span className="min-w-0 flex-1 flex items-baseline justify-between gap-3">
                <span className="text-[11px] text-gray-700 break-words">{f.label}</span>
                <span className="text-[11px] font-mono text-gray-400 whitespace-nowrap">{f.value}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function EntryRow({ entry, checked, onToggle }: {
  entry: TemplateEntry;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex items-start gap-2 pl-9 pr-3 py-1.5 cursor-pointer hover:bg-gray-100">
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
