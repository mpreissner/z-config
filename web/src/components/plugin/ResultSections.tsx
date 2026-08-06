/**
 * The richer blocks a plugin can put in a result: stat tiles, tables, grouped
 * proposals and callouts.
 *
 * A plugin picks the shape and the tone, never the markup — everything drawn
 * here comes from a fixed set the server normalises against (see
 * `normalise_result` in lib/plugin_web.py), so a section it gets wrong is
 * dropped rather than rendered.
 */

import { useState } from "react";
import type { PluginSection, PluginTone } from "../../api/plugins";

const TONE_TILE: Record<PluginTone, string> = {
  neutral: "border-gray-200 bg-white text-gray-900",
  good: "border-green-200 bg-green-50 text-green-900",
  warn: "border-amber-200 bg-amber-50 text-amber-900",
  bad: "border-red-200 bg-red-50 text-red-900",
};

const TONE_NOTE: Record<PluginTone, string> = {
  neutral: "border-gray-200 bg-gray-50 text-gray-700",
  good: "border-green-200 bg-green-50 text-green-800",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  bad: "border-red-200 bg-red-50 text-red-800",
};

const TONE_BADGE: Record<PluginTone, string> = {
  neutral: "bg-gray-100 text-gray-700",
  good: "bg-green-100 text-green-800",
  warn: "bg-amber-100 text-amber-800",
  bad: "bg-red-100 text-red-800",
};

function Heading({ title, subtitle }: { title: string | null; subtitle: string | null }) {
  if (!title && !subtitle) return null;
  return (
    <div className="mb-2">
      {title && <h3 className="text-sm font-medium text-gray-900">{title}</h3>}
      {subtitle && <p className="text-xs text-gray-500">{subtitle}</p>}
    </div>
  );
}

function Rows({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-gray-200 bg-white">
      <table className="min-w-full text-sm">
        {columns.length > 0 && (
          <thead className="bg-gray-50">
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-3 py-2 text-left font-medium text-gray-600">{c}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody className="divide-y divide-gray-100">
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-1.5 text-gray-800">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <p className="px-3 py-2 text-sm italic text-gray-400">No rows</p>
      )}
    </div>
  );
}

function GroupBlock({ group }: { group: Extract<PluginSection, { kind: "groups" }>["groups"][0] }) {
  // Collapsed by default: a consolidation proposal is a headline with the
  // evidence behind it, and forty of them open at once is not a review surface.
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-gray-50"
      >
        <span className="text-gray-400">{open ? "▾" : "▸"}</span>
        <span className="text-sm font-medium text-gray-900">{group.title}</span>
        {group.badge && (
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${TONE_BADGE[group.tone]}`}>
            {group.badge}
          </span>
        )}
        {group.subtitle && (
          <span className="ml-auto truncate text-xs text-gray-500">{group.subtitle}</span>
        )}
      </button>
      {open && (
        <div className="border-t border-gray-100 p-3">
          <Rows columns={group.columns} rows={group.rows} />
        </div>
      )}
    </div>
  );
}

export default function ResultSections({ sections, onAction, canAction }: {
  sections: PluginSection[];
  /** Goes to the action a note points at. Opens a form; authorizes nothing. */
  onAction?: (key: string) => void;
  /**
   * Whether that action has a screen to go to. An action left out of every step
   * has nowhere to send anyone, so its note is drawn as the sentence it is
   * rather than as a button that would do nothing.
   */
  canAction?: (key: string) => boolean;
}) {
  if (sections.length === 0) return null;

  return (
    <div className="space-y-4">
      {sections.map((section, i) => (
        <div key={i}>
          <Heading title={section.title} subtitle={section.subtitle} />

          {section.kind === "stats" && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {section.items.map((item, j) => (
                <div key={j} className={`rounded-md border p-3 ${TONE_TILE[item.tone]}`}>
                  <div className="text-2xl font-semibold tabular-nums">
                    {typeof item.value === "number"
                      ? item.value.toLocaleString()
                      : String(item.value ?? "")}
                  </div>
                  <div className="mt-0.5 text-xs font-medium uppercase tracking-wide opacity-70">
                    {item.label}
                  </div>
                  {item.detail && <div className="mt-1 text-xs opacity-70">{item.detail}</div>}
                </div>
              ))}
            </div>
          )}

          {section.kind === "table" && (
            <Rows columns={section.columns} rows={section.rows} />
          )}

          {section.kind === "groups" && (
            <div className="space-y-2">
              {section.groups.map((g) => <GroupBlock key={g.key} group={g} />)}
            </div>
          )}

          {section.kind === "notes" && (
            <div className="space-y-2">
              {section.notes.map((note, j) => (
                <div
                  key={j}
                  className={`flex items-center gap-3 rounded-md border px-3 py-2 text-sm ${TONE_NOTE[note.tone]}`}
                >
                  <span className="flex-1">{note.text}</span>
                  {note.action && onAction && (canAction?.(note.action.key) ?? true) && (
                    <button
                      type="button"
                      onClick={() => onAction(note.action!.key)}
                      className="shrink-0 rounded border border-black/10 bg-white/70 px-2 py-1 text-xs font-medium hover:bg-white"
                    >
                      {note.action.label}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
