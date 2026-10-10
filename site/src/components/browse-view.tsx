"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  columnWidth,
  type Group,
  type GroupOf,
  groupRows,
  layoutItems,
  visibleRange,
} from "@/lib/browse-groups";
import { loadCatalog, loadFieldValues, loadGroupTargets, loadSeriesIndex } from "@/lib/client-data";
import type { GroupTarget } from "@/lib/db/reference";
import { enumDisplay } from "@/lib/names";
import { recordHref, SERIES_BY_ID } from "@/lib/series";
import { displayFor } from "@/lib/series-display";
import type { CatalogEntry, Facet, SeriesCatalog, SeriesIndex } from "@/lib/types";
import { useUnitSystem } from "@/lib/unit-system";
import { convertValue, displayUnit, formatNumber, type UnitSystem } from "@/lib/units";
import { SearchIcon, TableIcon } from "@/ui/icons";
import { Markdown } from "./Markdown";
import { RefLink } from "./ref-link";

const ROW_H = 44;
const GROUP_H = 56;
/** Group key of rows with neither a group target nor a fallback value. */
const NO_GROUP = "\u0000none";
const OVERSCAN = 12;
const SCALAR = new Set(["number", "enum", "string", "boolean", "ref"]);

type Row = { slug: string; name: string; id: string; values: Map<string, unknown> };
type SortState = { key: string; dir: 1 | -1 };

const facetParam = (path: string) => `f.${path}`;
/** `?group=flat` lists a grouped series flat. */
const GROUP_PARAM = "group";

/** Display text of a cell value. */
function cellText(
  entry: CatalogEntry | undefined,
  value: unknown,
  catalog: SeriesCatalog | null,
  system: UnitSystem,
): string {
  if (value === undefined || value === null) return "";
  if (entry?.kind === "enum" && catalog) return enumDisplay(entry, value, catalog.enums).label;
  if (typeof value === "number") {
    return formatNumber(convertValue(value, entry?.unit ?? null, system, entry?.name).value);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Values a facet sees for one row (a list for `strings`). */
function facetValues(facet: Facet, value: unknown): string[] {
  if (value === undefined || value === null) return [];
  if (Array.isArray(value)) return value.map(String);
  if (facet.kind === "boolean") return [value ? "true" : "false"];
  return [String(value)];
}

function facetLabel(facet: Facet, value: string, catalog: SeriesCatalog | null): string {
  if (facet.kind === "boolean") return value === "true" ? "Yes" : "No";
  const entry = catalog?.entries[facet.path];
  if (facet.kind === "enum" && entry && catalog) {
    const raw = /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
    return enumDisplay(entry, raw, catalog.enums).label;
  }
  return value;
}

export function BrowseView({ series, count }: { series: string; count: number }) {
  const info = SERIES_BY_ID.get(series);
  const params = useSearchParams();
  const pathname = usePathname();
  const system = useUnitSystem();

  const [index, setIndex] = useState<SeriesIndex | null>(null);
  const [catalog, setCatalog] = useState<SeriesCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extra, setExtra] = useState<Record<string, Record<string, unknown>>>({});
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [sort, setSort] = useState<SortState>({ key: "name", dir: 1 });
  const [filtersOpen, setFiltersOpen] = useState(true);
  const groupBy = displayFor(series).groupBy;
  const [targets, setTargets] = useState<Record<string, GroupTarget> | null>(null);
  const grouped = Boolean(groupBy) && params.get(GROUP_PARAM) !== "flat";

  useEffect(() => {
    let live = true;
    setIndex(null);
    setError(null);
    loadSeriesIndex(series).then(
      (i) => live && setIndex(i),
      () => live && setError("Failed to load data."),
    );
    loadCatalog(series).then(
      (c) => live && setCatalog(c),
      () => undefined,
    );
    setTargets(null);
    const path = displayFor(series).groupBy?.path;
    if (path) {
      loadGroupTargets(series, path).then(
        (t) => live && setTargets(t),
        () => live && setTargets({}),
      );
    }
    return () => {
      live = false;
    };
  }, [series]);

  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 860px)");
    setFiltersOpen(!narrow.matches);
    const onChange = () => setFiltersOpen(!narrow.matches);
    narrow.addEventListener("change", onChange);
    return () => narrow.removeEventListener("change", onChange);
  }, []);

  const replaceParams = useCallback(
    (next: URLSearchParams) => {
      const qs = next.toString();
      // Native history: Next.js syncs useSearchParams, and the shell route has no RSC payload.
      window.history.replaceState(
        null,
        "",
        `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}${pathname}${qs ? `?${qs}` : ""}`,
      );
    },
    [pathname],
  );

  // Keep the text filter in the URL (debounced) so a filtered list is shareable.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = new URLSearchParams(params.toString());
      if (query.trim()) next.set("q", query.trim());
      else next.delete("q");
      if (next.toString() !== params.toString()) replaceParams(next);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, params, replaceParams]);

  // Columns: URL `cols`, else the series default.
  const columns = useMemo(() => {
    const fromUrl = params.get("cols");
    if (fromUrl !== null) return fromUrl.split(",").filter(Boolean);
    if (grouped && groupBy?.columns) return groupBy.columns;
    return index?.visible ?? [];
  }, [params, index, grouped, groupBy]);

  // Phones show the name and the first column only; the rest are not rendered at all
  // (a hidden <col> still takes its width in a fixed-layout table).
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 560px)");
    const update = () => setNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  const visibleCols = useMemo(() => (narrow ? columns.slice(0, 1) : columns), [narrow, columns]);

  // Lazily load values of picked columns the index does not carry.
  useEffect(() => {
    if (!index) return;
    for (const path of columns) {
      if (index.columns.includes(path) || extra[path]) continue;
      loadFieldValues(series, path).then(
        (fv) => setExtra((e) => ({ ...e, [path]: fv.values })),
        () => setExtra((e) => ({ ...e, [path]: {} })),
      );
    }
  }, [columns, index, series, extra]);

  const rows = useMemo<Row[]>(() => {
    if (!index) return [];
    return index.rows.map((r) => {
      const [slug, name, id] = r;
      const values = new Map<string, unknown>();
      for (let i = 0; i < index.columns.length; i++) {
        values.set(index.columns[i] as string, r[3 + i]);
      }
      for (const [path, map] of Object.entries(extra)) values.set(path, map[slug]);
      return { slug, name, id, values };
    });
  }, [index, extra]);

  // Each row's group: the record its group-by ref names, else its fallback column.
  const groupOf = useMemo(() => {
    const cache = new Map<string, GroupOf>();
    return (row: Row): GroupOf => {
      const hit = cache.get(row.slug);
      if (hit) return hit;
      const t = targets?.[row.id];
      const fallback = groupBy?.fallback ? row.values.get(groupBy.fallback) : undefined;
      const folder = fallback === undefined || fallback === null ? "" : String(fallback);
      let g: GroupOf;
      if (t) {
        g = { key: `${t[0]}:${t[1]}`, label: t[2], href: recordHref(t[0], t[1]) };
        if (t[1] !== t[2]) g.sub = t[1];
      } else if (folder) g = { key: `~${folder.toLowerCase()}`, label: folder };
      else g = { key: NO_GROUP, label: `No ${groupBy?.label ?? "group"}` };
      cache.set(row.slug, g);
      return g;
    };
  }, [targets, groupBy]);

  const facets = index?.facets ?? [];
  const selected = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const f of facets) out[f.path] = params.getAll(facetParam(f.path));
    return out;
  }, [params, facets]);

  const matchesFacet = useCallback(
    (row: Row, facet: Facet) => {
      const sel = selected[facet.path] ?? [];
      if (sel.length === 0) return true;
      const vals = facetValues(facet, row.values.get(facet.path));
      return vals.some((v) => sel.includes(v));
    },
    [selected],
  );

  const textMatched = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!tokens.length) return rows;
    return rows.filter((row) => {
      const hay = [
        row.name,
        row.id,
        groupBy ? groupOf(row).label : "",
        ...columns.map((c) => cellText(catalog?.entries[c], row.values.get(c), catalog, system)),
      ]
        .join(" ")
        .toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  }, [rows, query, columns, catalog, system, groupBy, groupOf]);

  const filtered = useMemo(
    () => textMatched.filter((row) => facets.every((f) => matchesFacet(row, f))),
    [textMatched, facets, matchesFacet],
  );

  const sorted = useMemo(() => {
    const out = [...filtered];
    const key = sort.key;
    const entry = catalog?.entries[key];
    const value = (row: Row): number | string | null => {
      if (key === "name") return row.name;
      const v = row.values.get(key);
      if (v === undefined || v === null) return null;
      if (typeof v === "number" && entry?.kind !== "enum") {
        return convertValue(v, entry?.unit ?? null, system, entry?.name).value;
      }
      if (typeof v === "boolean") return v ? 1 : 0;
      return cellText(entry, v, catalog, system);
    };
    out.sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (av === null && bv === null) return 0;
      if (av === null || av === "") return 1;
      if (bv === null || bv === "") return -1;
      if (typeof av === "number" && typeof bv === "number") return sort.dir * (av - bv);
      return sort.dir * String(av).localeCompare(String(bv), "en", { numeric: true });
    });
    return out;
  }, [filtered, sort, catalog, system]);

  const counts = (facet: Facet) => {
    const pool = textMatched.filter((row) =>
      facets.every((f) => f.path === facet.path || matchesFacet(row, f)),
    );
    const map = new Map<string, number>();
    for (const row of pool) {
      for (const v of new Set(facetValues(facet, row.values.get(facet.path)))) {
        map.set(v, (map.get(v) ?? 0) + 1);
      }
    }
    return map;
  };

  const toggle = (path: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    const key = facetParam(path);
    const current = next.getAll(key);
    next.delete(key);
    for (const v of current.includes(value)
      ? current.filter((c) => c !== value)
      : [...current, value]) {
      next.append(key, v);
    }
    replaceParams(next);
  };

  const anyFilter = facets.some((f) => (selected[f.path] ?? []).length > 0);
  const clearFilters = () => {
    const next = new URLSearchParams(params.toString());
    for (const f of facets) next.delete(facetParam(f.path));
    replaceParams(next);
  };

  const setColumns = (cols: string[]) => {
    const next = new URLSearchParams(params.toString());
    next.set("cols", cols.join(","));
    replaceParams(next);
  };

  const pickable = useMemo(() => {
    if (!catalog) return [];
    const seen = new Set<string>();
    const out: Array<{ path: string; entry: CatalogEntry; count: number }> = [];
    for (const fp of catalog.fieldPaths) {
      if (fp.path.includes("*") || fp.path.includes("[]") || seen.has(fp.path)) continue;
      const entry = catalog.entries[fp.key];
      if (!entry?.comparable || !SCALAR.has(entry.kind)) continue;
      seen.add(fp.path);
      out.push({ path: fp.path, entry, count: fp.count });
    }
    return out.sort((a, b) => a.path.localeCompare(b.path));
  }, [catalog]);

  // ---- virtualization
  const scrollRef = useRef<HTMLElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(600);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => setViewH(el.clientHeight || 600);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset scroll when the result set changes
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    setScrollTop(0);
  }, [query, params]);

  const ready = Boolean(index) && (!grouped || targets !== null);
  const groups = useMemo<Group<Row>[] | null>(
    () => (grouped && targets ? groupRows(sorted, groupOf, (k) => k === NO_GROUP) : null),
    [grouped, targets, sorted, groupOf],
  );
  const layout = useMemo(
    () => layoutItems<Row>(groups ? { groups } : { rows: sorted }, ROW_H, GROUP_H),
    [groups, sorted],
  );
  const [start, end] = visibleRange(layout.tops, scrollTop, viewH, OVERSCAN);
  const visibleItems = layout.items.slice(start, end);
  const totalH = layout.tops[layout.items.length] ?? 0;
  const colSpan = visibleCols.length + 1;

  const setGrouped = (on: boolean) => {
    const next = new URLSearchParams(params.toString());
    if (on) next.delete(GROUP_PARAM);
    else next.set(GROUP_PARAM, "flat");
    replaceParams(next);
  };

  const headerLabel = (path: string) => {
    const entry = catalog?.entries[path];
    const label = entry?.label ?? path;
    const unit = entry ? displayUnit(entry.unit, system, entry.name) : null;
    return unit && entry?.kind === "number" ? `${label} (${unit})` : label;
  };

  // Column widths from every row (not the rendered slice), so scrolling never reflows.
  // biome-ignore lint/correctness/useExhaustiveDependencies: headerLabel reads catalog and system
  const widths = useMemo(
    () =>
      visibleCols.map((c) => {
        const entry = catalog?.entries[c];
        const texts = rows.map((r) => cellText(entry, r.values.get(c), catalog, system).length);
        return columnWidth(texts, headerLabel(c).length);
      }),
    [visibleCols, rows, catalog, system],
  );

  const sortHeader = (key: string, label: string, num: boolean, className?: string) => (
    <th
      scope="col"
      key={key}
      className={[num ? "num" : "", className ?? ""].filter(Boolean).join(" ") || undefined}
      aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      title={catalog?.entries[key]?.description}
    >
      <button
        type="button"
        className="sort-btn"
        data-active={sort.key === key}
        onClick={() =>
          setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : num ? -1 : 1 }))
        }
      >
        {label}
        <span aria-hidden="true">{sort.key === key ? (sort.dir === 1 ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );

  const total = index?.count ?? count;
  const plural = info?.label.toLowerCase() ?? series;

  return (
    <div>
      <h1 className="page-title">{info?.label ?? series}</h1>
      {index?.intro ? (
        <div className="browse-intro">
          <Markdown html={index.intro.html} handWritten />
          {index.intro.seeAlso?.length ? (
            <p className="see-also">
              See also{" "}
              {index.intro.seeAlso.map((s, i) => (
                <span key={s.href}>
                  {i ? ", " : ""}
                  {/^[a-z]+:/i.test(s.href) ? (
                    <a href={s.href} rel="noopener noreferrer">
                      {s.label}
                    </a>
                  ) : (
                    <Link href={s.href}>{s.label}</Link>
                  )}
                </span>
              ))}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className={facets.length ? "browse" : "browse browse-nofacets"}>
        {facets.length ? (
          <details
            className="facets-panel"
            open={filtersOpen}
            onToggle={(e) => setFiltersOpen((e.currentTarget as HTMLDetailsElement).open)}
          >
            <summary className="facets-toggle">
              Filters
              {anyFilter
                ? ` (${facets.reduce((n, f) => n + (selected[f.path] ?? []).length, 0)})`
                : ""}
            </summary>
            <aside className="facets" aria-label="Filters">
              {facets.map((facet) => {
                const c = counts(facet);
                const sel = selected[facet.path] ?? [];
                const options = [...c.keys()].sort(
                  (a, b) => (c.get(b) ?? 0) - (c.get(a) ?? 0) || a.localeCompare(b),
                );
                for (const v of sel) if (!options.includes(v)) options.push(v);
                const shown = options.slice(0, 40);
                return (
                  <fieldset className="facet" key={facet.path}>
                    <legend>{facet.label}</legend>
                    {shown.map((v) => (
                      <label className="facet-option" key={v}>
                        <input
                          type="checkbox"
                          checked={sel.includes(v)}
                          onChange={() => toggle(facet.path, v)}
                        />
                        <span className="facet-label">{facetLabel(facet, v, catalog)}</span>
                        <span className="facet-count">{c.get(v) ?? 0}</span>
                      </label>
                    ))}
                    {options.length > shown.length ? (
                      <span className="muted facet-more">{options.length - shown.length} more</span>
                    ) : null}
                  </fieldset>
                );
              })}
            </aside>
          </details>
        ) : null}

        <div className="browse-main">
          <div className="browse-tools">
            <div className="combo combo-compact">
              <div className="combo-field">
                <SearchIcon />
                <input
                  className="combo-input"
                  type="search"
                  aria-label={`Filter ${plural}`}
                  placeholder="Filter"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
            </div>
            {pickable.length ? (
              <details className="col-picker">
                <summary className="btn btn-compact">
                  <TableIcon />
                  Columns
                </summary>
                <fieldset className="col-picker-menu">
                  <legend className="visually-hidden">Visible columns</legend>
                  {pickable.map(({ path, entry, count: n }) => (
                    <label className="facet-option" key={path} title={entry.description}>
                      <input
                        type="checkbox"
                        checked={columns.includes(path)}
                        onChange={() =>
                          setColumns(
                            columns.includes(path)
                              ? columns.filter((c) => c !== path)
                              : [...columns, path],
                          )
                        }
                      />
                      <span className="col-picker-label">
                        {entry.label}
                        <span className="col-picker-path">{path}</span>
                      </span>
                      <span className="facet-count">{n}</span>
                    </label>
                  ))}
                </fieldset>
              </details>
            ) : null}
          </div>

          <div className="browse-bar">
            <span aria-live="polite">
              <strong>{index ? sorted.length.toLocaleString("en-US") : "…"}</strong> of{" "}
              {total.toLocaleString("en-US")} {plural}
              {groups ? (
                <span className="muted">
                  {" "}
                  in {groups.length.toLocaleString("en-US")}{" "}
                  {groups.length === 1 ? groupBy?.label : `${groupBy?.label}s`}
                </span>
              ) : null}
            </span>
            {groupBy ? (
              <fieldset className="group-toggle">
                <legend className="visually-hidden">List layout</legend>
                <button
                  type="button"
                  className="group-opt"
                  aria-pressed={grouped}
                  onClick={() => setGrouped(true)}
                >
                  Group by {groupBy.label}
                </button>
                <span className="group-sep" aria-hidden="true">
                  /
                </span>
                <button
                  type="button"
                  className="group-opt"
                  aria-pressed={!grouped}
                  onClick={() => setGrouped(false)}
                >
                  Flat list
                </button>
              </fieldset>
            ) : null}
            {anyFilter ? (
              <button type="button" className="btn btn-compact btn-quiet" onClick={clearFilters}>
                Clear filters
              </button>
            ) : null}
          </div>

          {error ? (
            <div className="empty-state">
              <p>{error} Reload the page.</p>
            </div>
          ) : (
            <section
              className="table-wrap vtable"
              ref={scrollRef}
              tabIndex={0}
              aria-label={`${info?.label ?? series} table`}
              onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            >
              <table
                className="table"
                aria-rowcount={layout.items.length + 1}
                style={
                  {
                    // Room for every column plus a usable name column; the box scrolls past it.
                    "--table-min": `calc(${widths.reduce((n, w) => n + w, 0)}ch + ${visibleCols.length * 24 + 180}px)`,
                  } as CSSProperties
                }
              >
                <colgroup>
                  <col className="col-name" />
                  {visibleCols.map((c, i) => (
                    <col
                      key={c}
                      className={i === 0 ? "col-keep" : "col-opt"}
                      style={{ "--col-w": `calc(${widths[i]}ch + 24px)` } as CSSProperties}
                    />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    {sortHeader("name", info?.singular ? capitalise(info.singular) : "Name", false)}
                    {visibleCols.map((c, i) =>
                      sortHeader(
                        c,
                        headerLabel(c),
                        catalog?.entries[c]?.kind === "number",
                        i === 0 ? "col-keep" : "col-opt",
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {!ready ? (
                    Array.from({ length: 10 }, (_, i) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: placeholder rows
                      <tr key={i} className="vrow">
                        <td colSpan={colSpan || 1}>
                          <span className="sk-bar" />
                        </td>
                      </tr>
                    ))
                  ) : sorted.length === 0 ? (
                    <tr>
                      <td colSpan={colSpan} className="results-empty">
                        No matches.
                      </td>
                    </tr>
                  ) : (
                    <>
                      {start > 0 ? (
                        <tr className="vspacer">
                          <td colSpan={colSpan} style={{ height: layout.tops[start] }} />
                        </tr>
                      ) : null}
                      {visibleItems.map((item, i) =>
                        item.kind === "group" ? (
                          <tr
                            key={`g:${item.group.key}`}
                            className="vgroup"
                            aria-rowindex={start + i + 2}
                          >
                            <th colSpan={colSpan} scope="colgroup">
                              <span className="vgroup-head">
                                <span className="contents-num">{item.number}</span>
                                <span className="vgroup-name">
                                  {item.group.href ? (
                                    <RefLink href={item.group.href} title={item.group.label}>
                                      {item.group.label}
                                    </RefLink>
                                  ) : (
                                    item.group.label
                                  )}
                                  {item.group.sub ? (
                                    <span className="vgroup-sub">{item.group.sub}</span>
                                  ) : null}
                                </span>
                                <span className="contents-leader" aria-hidden="true" />
                                <span className="vgroup-count">
                                  {item.group.rows.length.toLocaleString("en-US")}
                                  <span className="visually-hidden">
                                    {" "}
                                    {item.group.rows.length === 1 ? info?.singular : plural}
                                  </span>
                                </span>
                              </span>
                            </th>
                          </tr>
                        ) : (
                          <tr
                            key={item.row.slug}
                            className={item.group ? "vrow vrow-grouped" : "vrow"}
                            aria-rowindex={start + i + 2}
                          >
                            <td className="name-cell">
                              <RefLink
                                href={recordHref(series, item.row.slug)}
                                title={item.row.name}
                              >
                                {item.row.name}
                              </RefLink>
                              {item.row.id !== item.row.name ? (
                                <span className="sub mono">{item.row.id}</span>
                              ) : null}
                            </td>
                            {visibleCols.map((c, ci) => {
                              const entry = catalog?.entries[c];
                              const text = cellText(entry, item.row.values.get(c), catalog, system);
                              return (
                                <td
                                  key={c}
                                  className={[
                                    entry?.kind === "number" ? "num" : "",
                                    ci === 0 ? "col-keep" : "col-opt",
                                  ]
                                    .filter(Boolean)
                                    .join(" ")}
                                  title={text}
                                >
                                  {text || <span className="muted">—</span>}
                                </td>
                              );
                            })}
                          </tr>
                        ),
                      )}
                      {end < layout.items.length ? (
                        <tr className="vspacer">
                          <td
                            colSpan={colSpan}
                            style={{ height: totalH - (layout.tops[end] ?? 0) }}
                          />
                        </tr>
                      ) : null}
                    </>
                  )}
                </tbody>
              </table>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function capitalise(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
