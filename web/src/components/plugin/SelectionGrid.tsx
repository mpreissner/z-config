/**
 * The checkbox grid behind a plugin's `selection` parameter.
 *
 * A plugin loads the rows and the user ticks the ones to act on; the parameter's
 * value is the list of ticked row values. Nothing here decides what may be
 * submitted — the server re-asks the plugin for the same rows when the action
 * runs and refuses any value it did not just offer.
 *
 * Built to hold a rulebase, not a short list: only the rows on screen are in the
 * DOM, so a grid of tens of thousands scrolls the same as one of ten.
 */

import { useMemo, useRef, useState } from "react";
import type { PluginOption, PluginParam } from "../../api/plugins";

const ROW_H = 36;
const OVERSCAN = 8;

type Item =
  | { kind: "header"; group: string; values: string[]; selected: number }
  | { kind: "row"; option: PluginOption };

/** Whether one row satisfies every active filter and the search box. */
function matches(
  option: PluginOption,
  columns: string[],
  declared: PluginParam["filters"],
  chosen: Record<string, string>,
  search: string,
): boolean {
  for (const filter of declared ?? []) {
    const wanted = chosen[filter.name];
    if (!wanted) continue;
    // A filter names one of the grid's columns; the server checks that when it
    // describes the parameter, so the lookup here always lands.
    const i = columns.findIndex((c) => c.toLowerCase() === filter.name.toLowerCase());
    const cell = (i >= 0 ? option.cells?.[i] : "")?.toLowerCase() ?? "";
    // Matched against either side on purpose: a plugin is free to show
    // "ZIA firewall" in the cell while the filter carries "zia_firewall".
    const label = filter.options.find((o) => o.value === wanted)?.label ?? wanted;
    if (cell !== wanted.toLowerCase() && cell !== label.toLowerCase()) return false;
  }
  if (!search) return true;
  const hay = [option.label, option.note ?? "", ...(option.cells ?? [])]
    .join(" ")
    .toLowerCase();
  return hay.includes(search.toLowerCase());
}

export default function SelectionGrid({ param, options, value, onChange, loading }: {
  param: PluginParam;
  options: PluginOption[];
  value: string[];
  onChange: (next: string[]) => void;
  loading: boolean;
}) {
  const columns = param.columns ?? [];
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [scrollTop, setScrollTop] = useState(0);
  const viewport = useRef<HTMLDivElement>(null);

  const picked = useMemo(() => new Set(value), [value]);

  const visible = useMemo(
    () => options.filter((o) => matches(o, columns, param.filters, filters, search)),
    [options, columns, param.filters, filters, search],
  );

  // Group headers are rows in the same scrolling list, so one windowing pass
  // covers both and a group boundary cannot land outside the rendered slice.
  const items = useMemo<Item[]>(() => {
    const order: string[] = [];
    const byGroup = new Map<string, PluginOption[]>();
    for (const o of visible) {
      const g = o.group ?? "";
      if (!byGroup.has(g)) {
        byGroup.set(g, []);
        order.push(g);
      }
      byGroup.get(g)!.push(o);
    }
    const out: Item[] = [];
    for (const g of order) {
      const rows = byGroup.get(g)!;
      if (g) {
        const values = rows.filter((r) => !r.disabled).map((r) => r.value);
        out.push({
          kind: "header",
          group: g,
          values,
          selected: values.filter((v) => picked.has(v)).length,
        });
      }
      for (const o of rows) out.push({ kind: "row", option: o });
    }
    return out;
  }, [visible, picked]);

  const height = Math.min(items.length * ROW_H, 460);
  const first = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const last = Math.min(items.length, Math.ceil((scrollTop + height) / ROW_H) + OVERSCAN);
  const slice = items.slice(first, last);

  function toggle(values: string[], on: boolean) {
    const next = new Set(picked);
    for (const v of values) {
      if (on) next.add(v);
      else next.delete(v);
    }
    // Kept in the order the plugin listed them, so what goes back is stable
    // whatever order the user happened to tick things in.
    onChange(options.filter((o) => next.has(o.value)).map((o) => o.value));
  }

  const selectable = visible.filter((o) => !o.disabled).map((o) => o.value);
  const allVisible = selectable.length > 0 && selectable.every((v) => picked.has(v));

  return (
    <div className="rounded-md border border-gray-300">
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 bg-gray-50 px-3 py-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-zs-500 focus:outline-none focus:ring-1 focus:ring-zs-500"
        />
        {(param.filters ?? []).map((f) => (
          <select
            key={f.name}
            value={filters[f.name] ?? ""}
            onChange={(e) =>
              setFilters((prev) => ({ ...prev, [f.name]: e.target.value }))
            }
            className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-zs-500 focus:outline-none focus:ring-1 focus:ring-zs-500"
          >
            <option value="">All {f.label.toLowerCase()}</option>
            {f.options.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        ))}
        <div className="ml-auto flex items-center gap-3 text-xs text-gray-600">
          <span>
            {picked.size.toLocaleString()} of {options.length.toLocaleString()} selected
          </span>
          <button
            type="button"
            onClick={() => toggle(selectable, !allVisible)}
            disabled={selectable.length === 0}
            className="rounded border border-gray-300 bg-white px-2 py-1 font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            {allVisible ? "Clear shown" : "Select shown"}
          </button>
        </div>
      </div>

      {columns.length > 0 && (
        <div
          className="flex items-center gap-3 border-b border-gray-200 bg-white px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-gray-500"
          style={{ paddingLeft: 40 }}
        >
          {columns.map((c) => (
            <span key={c} className="flex-1 truncate">{c}</span>
          ))}
        </div>
      )}

      <div
        ref={viewport}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        className="overflow-y-auto"
        style={{ height: items.length ? height : undefined }}
      >
        {loading && (
          <p className="px-3 py-4 text-sm italic text-gray-400">Loading rows…</p>
        )}
        {!loading && items.length === 0 && (
          <p className="px-3 py-4 text-sm italic text-gray-400">
            {options.length === 0 ? "Nothing to choose from here yet." : "No rows match."}
          </p>
        )}
        <div style={{ height: items.length * ROW_H, position: "relative" }}>
          {slice.map((item, i) => {
            const top = (first + i) * ROW_H;
            if (item.kind === "header") {
              const all = item.values.length > 0 && item.selected === item.values.length;
              return (
                <div
                  key={`h:${item.group}`}
                  style={{ position: "absolute", top, height: ROW_H, width: "100%" }}
                  className="flex items-center gap-3 border-b border-gray-200 bg-gray-100 px-3"
                >
                  <input
                    type="checkbox"
                    checked={all}
                    ref={(el) => {
                      if (el) el.indeterminate = item.selected > 0 && !all;
                    }}
                    onChange={() => toggle(item.values, !all)}
                    className="h-4 w-4 rounded border-gray-300 text-zs-500 focus:ring-zs-500"
                  />
                  <span className="text-sm font-medium text-gray-800">{item.group}</span>
                  <span className="text-xs text-gray-500">
                    {item.selected} of {item.values.length}
                  </span>
                </div>
              );
            }
            const o = item.option;
            const on = picked.has(o.value);
            return (
              <label
                key={o.value}
                style={{ position: "absolute", top, height: ROW_H, width: "100%" }}
                className={`flex items-center gap-3 border-b border-gray-100 px-3 text-sm ${
                  o.disabled ? "text-gray-400" : "cursor-pointer text-gray-800 hover:bg-gray-50"
                }`}
              >
                <input
                  type="checkbox"
                  checked={on}
                  disabled={o.disabled}
                  onChange={() => toggle([o.value], !on)}
                  className="h-4 w-4 rounded border-gray-300 text-zs-500 focus:ring-zs-500"
                />
                {(o.cells?.length ? o.cells : [o.label]).map((cell, j) => (
                  <span key={j} className="flex-1 truncate" title={cell}>
                    {cell}
                    {j === 0 && o.note && (
                      <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
                        {o.note}
                      </span>
                    )}
                  </span>
                ))}
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}
