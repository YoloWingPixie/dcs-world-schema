"use client";

import { useSearchParams } from "next/navigation";
import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  columnWidth,
  type Group,
  type GroupOf,
  groupRows,
  type Layout,
  layoutItems,
  visibleRange,
} from "@/lib/browse-groups";
import { cellText } from "@/lib/cell-text";
import {
  type LinkedField,
  loadCatalog,
  loadGroupTargets,
  loadLinkedField,
  loadSeriesIndex,
} from "@/lib/client-data";
import { browseEntry, fieldPaths, type GroupTarget } from "@/lib/db/reference";
import { pathLabel, resolveLink, sortableValue, type ValueContext } from "@/lib/format-field";
import { updateQuery } from "@/lib/history";
import { enumDisplay } from "@/lib/names";
import { facetParam, recordHref, SERIES_BY_ID } from "@/lib/series";
import { displayFor, offersFacet } from "@/lib/series-display";
import { capitalise, compareSortKeys, naturalCompare } from "@/lib/text";
import type { CatalogEntry, Facet, SeriesCatalog } from "@/lib/types";
import { useUnitSystem } from "@/lib/unit-system";
import { unitLabel } from "@/lib/units";
import { useLoaded } from "@/lib/use-loaded";
import { useQueryParam } from "@/lib/use-query-param";
import { SearchIcon, TableIcon } from "@/ui/icons";
import { Markdown } from "./Markdown";
import { RefLink } from "./ref-link";
import { SeeAlso } from "./see-also";
import { SortHeader, type SortState } from "./sort-header";

const ROW_H = 44;
const GROUP_H = 56;
/** Group key of rows with neither a group target nor a fallback value. */
const NO_GROUP = "\u0000none";
const OVERSCAN = 12;
/** Narrowest name column before trailing columns are left out. */
const NAME_MIN = 180;

type Row = { id: string; name: string; values: Map<string, unknown> };

/** A browse column or facet path as the catalog reads it (lib/db/reference `browseEntry`). */
type BrowseField = { entry: CatalogEntry; label: string };

/** Each path's entry and stand-alone label (`pathLabel`); a path the catalog has no browse entry for is left out. */
function browseFields(
  catalog: SeriesCatalog | null,
  paths: readonly string[],
  use: "column" | "facet",
): Map<string, BrowseField> {
  const out = new Map<string, BrowseField>();
  if (!catalog) return out;
  for (const path of paths) {
    const entry = browseEntry(catalog, path, use);
    if (entry) out.set(path, { entry, label: pathLabel(entry, path) });
  }
  return out;
}

/** `?group=flat` lists a grouped series flat. */
const GROUP_PARAM = "group";

/** A cell's sort key: lib/format-field `sortableValue`, or its text before the catalog loads. */
function sortKey(entry: CatalogEntry | undefined, value: unknown, ctx: ValueContext) {
  if (entry) return sortableValue(entry, value, ctx);
  if (value === undefined || value === null) return null;
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  return cellText(entry, value, ctx);
}

/**
 * The values a facet sees in one row, as text: none for an empty cell, each item of a
 * list, a ref's record by name (`links`: the column's link table).
 */
function facetValues(
  facet: Facet,
  value: unknown,
  entry: CatalogEntry | undefined,
  links: LinkedField["links"] | undefined,
): string[] {
  if (value === undefined || value === null) return [];
  const text = (v: unknown) =>
    (entry?.ref ? resolveLink(entry, v, links)?.name : undefined) ?? String(v);
  if (Array.isArray(value)) return value.map(text);
  if (facet.kind === "boolean") return [value ? "true" : "false"];
  return [text(value)];
}

function facetLabel(
  facet: Facet,
  value: string,
  entry: CatalogEntry | undefined,
  ctx: ValueContext,
): string {
  if (facet.kind === "boolean") return value === "true" ? "Yes" : "No";
  if (facet.kind === "enum" && entry) {
    const raw = /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
    return enumDisplay(entry, raw, ctx.enums).label;
  }
  return value;
}

export function BrowseView({ series, count }: { series: string; count: number }) {
  const info = SERIES_BY_ID.get(series);
  const params = useSearchParams();
  const system = useUnitSystem();

  const loaded = useLoaded(
    (s) =>
      loadSeriesIndex(s).then(
        (index) => ({ index, error: null }),
        () => ({ index: null, error: "Failed to load data." }),
      ),
    series,
  );
  const index = loaded?.index ?? null;
  const error = loaded?.error ?? null;
  const catalog = useLoaded(loadCatalog, series);
  const [extra, setExtra] = useState<Record<string, LinkedField>>({});
  // The text filter, kept in the URL (debounced) so a filtered list is shareable.
  const [query, setQuery] = useQueryParam("q");
  const [sort, setSort] = useState<SortState>({ key: "name", dir: 1 });
  const [filtersOpen, setFiltersOpen] = useState(true);
  const groupBy = displayFor(series).groupBy;
  const targets = useLoaded((s): Promise<Record<string, GroupTarget> | null> => {
    const path = displayFor(s).groupBy?.path;
    return path ? loadGroupTargets(s, path).catch(() => ({})) : Promise.resolve(null);
  }, series);
  const grouped = Boolean(groupBy) && params.get(GROUP_PARAM) !== "flat";

  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 860px)");
    setFiltersOpen(!narrow.matches);
    const onChange = () => setFiltersOpen(!narrow.matches);
    narrow.addEventListener("change", onChange);
    return () => narrow.removeEventListener("change", onChange);
  }, []);

  // Columns: URL `cols`, else the series default.
  const colsParam = params.get("cols");
  const columns = useMemo(() => {
    if (colsParam !== null) return colsParam.split(",").filter(Boolean);
    if (grouped && groupBy?.columns) return groupBy.columns;
    return index?.visible ?? [];
  }, [colsParam, index, grouped, groupBy]);

  // Lazily load what the index does not carry (nested or list-valued fields, picked
  // columns): the shown columns, and a facet once the filters show or the address
  // selects in it (the filters start closed on phones). Each path is asked for once.
  const inAddress = (index?.facets ?? [])
    .filter((f) => params.has(facetParam(f.path)))
    .map((f) => f.path)
    .join("\n");
  const missing = useMemo(() => {
    if (!index) return "";
    const facetPaths = index.facets
      .map((f) => f.path)
      .filter((p) => filtersOpen || inAddress.split("\n").includes(p));
    const paths = new Set([...columns, ...facetPaths].filter((p) => !index.columns.includes(p)));
    return [...paths].join("\n");
  }, [index, columns, filtersOpen, inAddress]);
  const requested = useRef(new Set<string>());
  useEffect(() => {
    for (const path of missing ? missing.split("\n") : []) {
      const key = `${series}\n${path}`;
      if (requested.current.has(key)) continue;
      requested.current.add(key);
      loadLinkedField(series, path).then(
        (field) => setExtra((e) => ({ ...e, [path]: field })),
        () => setExtra((e) => ({ ...e, [path]: { values: {}, links: {} } })),
      );
    }
  }, [missing, series]);

  const rows = useMemo<Row[]>(() => {
    if (!index) return [];
    return index.rows.map((r) => {
      const [id, name] = r;
      const values = new Map<string, unknown>();
      for (let i = 0; i < index.columns.length; i++) {
        values.set(index.columns[i] as string, r[2 + i]);
      }
      for (const [path, field] of Object.entries(extra)) values.set(path, field.values[id]);
      return { id, name, values };
    });
  }, [index, extra]);
  const columnFields = useMemo(() => browseFields(catalog, columns, "column"), [catalog, columns]);
  const facetFields = useMemo(
    () => browseFields(catalog, index?.facets.map((f) => f.path) ?? [], "facet"),
    [catalog, index],
  );
  /** The value context of a column or facet: a lazily loaded one's link table. */
  const ctxFor = useCallback(
    (path: string, ctx: ValueContext): ValueContext => {
      const links = extra[path]?.links;
      return links ? { ...ctx, links } : ctx;
    },
    [extra],
  );

  // Each row's group: the record its group-by ref names, else its fallback column.
  const groupOf = useMemo(() => {
    const cache = new Map<string, GroupOf>();
    return (row: Row): GroupOf => {
      const hit = cache.get(row.id);
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
      cache.set(row.id, g);
      return g;
    };
  }, [targets, groupBy]);

  // The values a facet sees in a row.
  const valuesOf = useCallback(
    (row: Row, facet: Facet) =>
      facetValues(
        facet,
        row.values.get(facet.path),
        facetFields.get(facet.path)?.entry,
        extra[facet.path]?.links,
      ),
    [facetFields, extra],
  );
  // A facet is offered when its values hold enough distinct ones (`offersFacet`); one
  // outside the index is kept until its values load.
  const facets = useMemo(() => {
    if (!index) return [];
    return index.facets.filter((f) => {
      if (!index.columns.includes(f.path) && !extra[f.path]) return true;
      return offersFacet(new Set(rows.flatMap((r) => valuesOf(r, f))).size);
    });
  }, [index, extra, rows, valuesOf]);
  // The facet selections as one string: `selected` changes only when they do.
  const facetQuery = JSON.stringify(facets.map((f) => params.getAll(facetParam(f.path))));
  const selected = useMemo(() => {
    const values = JSON.parse(facetQuery) as string[][];
    return Object.fromEntries(facets.map((f, i) => [f.path, values[i] ?? []]));
  }, [facetQuery, facets]);

  const matchesFacet = useCallback(
    (row: Row, facet: Facet) => {
      const sel = selected[facet.path] ?? [];
      if (sel.length === 0) return true;
      return valuesOf(row, facet).some((v) => sel.includes(v));
    },
    [selected, valuesOf],
  );

  const ctx = useMemo<ValueContext>(
    () => ({ enums: catalog?.enums ?? {}, system }),
    [catalog, system],
  );

  // Each row's cell texts (every column, not only those that fit) and its lowercased
  // filter text, built once per data, column or unit change rather than per keystroke.
  const texts = useMemo(() => {
    const entries = columns.map((c) => columnFields.get(c)?.entry);
    const ctxs = columns.map((c) => ctxFor(c, ctx));
    const cells = new Map<Row, string[]>();
    const hay = new Map<Row, string>();
    for (const row of rows) {
      const own = columns.map((c, i) =>
        cellText(entries[i], row.values.get(c), ctxs[i] as ValueContext),
      );
      cells.set(row, own);
      hay.set(
        row,
        [row.name, row.id, groupBy ? groupOf(row).label : "", ...own].join(" ").toLowerCase(),
      );
    }
    return { cells, hay };
  }, [rows, columns, columnFields, ctx, ctxFor, groupBy, groupOf]);

  const textMatched = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!tokens.length) return rows;
    return rows.filter((row) => {
      const hay = texts.hay.get(row) ?? "";
      return tokens.every((t) => hay.includes(t));
    });
  }, [rows, query, texts]);

  // Facet options with counts, all facets in one pass: a facet counts the rows every
  // other facet lets through (so its own options stay selectable).
  const facetOptions = useMemo(() => {
    const counts = new Map(facets.map((f) => [f.path, new Map<string, number>()]));
    const filtered: Row[] = [];
    for (const row of textMatched) {
      const failing = facets.filter((f) => !matchesFacet(row, f));
      if (failing.length === 0) filtered.push(row);
      if (failing.length > 1) continue;
      for (const f of failing.length ? failing : facets) {
        const map = counts.get(f.path);
        if (!map) continue;
        for (const v of new Set(valuesOf(row, f))) {
          map.set(v, (map.get(v) ?? 0) + 1);
        }
      }
    }
    const options = new Map(
      facets.map((f) => {
        const c = counts.get(f.path) ?? new Map<string, number>();
        const list = [...c.keys()].sort(
          (a, b) => (c.get(b) ?? 0) - (c.get(a) ?? 0) || naturalCompare(a, b),
        );
        for (const v of selected[f.path] ?? []) if (!list.includes(v)) list.push(v);
        return [f.path, { counts: c, options: list }] as const;
      }),
    );
    return { filtered, options };
  }, [textMatched, facets, matchesFacet, selected, valuesOf]);
  const filtered = facetOptions.filtered;

  // Sort keys computed once per row, then indices sorted with one shared collator.
  const sorted = useMemo(() => {
    const key = sort.key;
    const entry = columnFields.get(key)?.entry;
    const keyCtx = ctxFor(key, ctx);
    const keys = filtered.map((row) =>
      key === "name" ? row.name : sortKey(entry, row.values.get(key), keyCtx),
    );
    const order = filtered.map((_, i) => i);
    order.sort((i, j) => compareSortKeys(keys[i], keys[j], sort.dir));
    return order.map((i) => filtered[i] as Row);
  }, [filtered, sort, columnFields, ctx, ctxFor]);

  const toggle = (path: string, value: string) =>
    updateQuery((next) => {
      const key = facetParam(path);
      const current = next.getAll(key);
      next.delete(key);
      for (const v of current.includes(value)
        ? current.filter((c) => c !== value)
        : [...current, value]) {
        next.append(key, v);
      }
    });

  const anyFilter = facets.some((f) => (selected[f.path] ?? []).length > 0);
  const clearFilters = () =>
    updateQuery((next) => {
      for (const f of facets) next.delete(facetParam(f.path));
    });

  const setColumns = (cols: string[]) => updateQuery((next) => next.set("cols", cols.join(",")));

  // One value per record (`browseEntry`): a table column's curve is no browse column.
  const pickable = useMemo(() => {
    const paths = catalog ? fieldPaths(catalog).map((fp) => fp.path) : [];
    return [...browseFields(catalog, paths, "column")]
      .map(([path, field]) => ({ path, ...field }))
      .sort((a, b) => naturalCompare(a.path, b.path));
  }, [catalog]);

  // ---- virtualization: the page scrolls; <BrowseBody> renders the rows in the window's
  // view of the body and owns the scroll position, so scrolling re-renders the body only.
  const wrapRef = useRef<HTMLElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const chRef = useRef<HTMLSpanElement>(null);
  const [headH, setHeadH] = useState(0);
  const [tableW, setTableW] = useState(0);
  const [chPx, setChPx] = useState(8);
  const hasIndex = Boolean(index);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the browse subtree remounts when the index arrives; observe the new nodes
  useEffect(() => {
    const resized = () => {
      if (wrapRef.current) setTableW(wrapRef.current.clientWidth);
      if (chRef.current) setChPx(chRef.current.getBoundingClientRect().width || 8);
      if (headRef.current) setHeadH(headRef.current.offsetHeight);
    };
    const observer = new ResizeObserver(resized);
    if (wrapRef.current) observer.observe(wrapRef.current);
    if (headRef.current) observer.observe(headRef.current);
    resized();
    return () => observer.disconnect();
  }, [hasIndex]);
  // A new result set starts at its top: bring the table head back under the sticky bars.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset when the result set changes
  useEffect(() => {
    const wrap = wrapRef.current;
    const head = headRef.current;
    if (!wrap) return;
    const header = Number.parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--header-h"),
    );
    const stuck = head && getComputedStyle(head).position === "sticky" ? head.offsetHeight : 0;
    const offset = (Number.isFinite(header) ? header : 0) + stuck;
    const top = wrap.getBoundingClientRect().top;
    if (top < offset) window.scrollTo({ top: window.scrollY + top - offset });
  }, [query, facetQuery, grouped]);

  const ready = Boolean(index) && (!grouped || targets !== null);
  const groups = useMemo<Group<Row>[] | null>(
    () => (grouped && targets ? groupRows(sorted, groupOf, (k) => k === NO_GROUP) : null),
    [grouped, targets, sorted, groupOf],
  );
  const layout = useMemo(
    () => layoutItems<Row>(groups ? { groups } : { rows: sorted }, ROW_H, GROUP_H),
    [groups, sorted],
  );

  const setGrouped = (on: boolean) =>
    updateQuery((next) => {
      if (on) next.delete(GROUP_PARAM);
      else next.set(GROUP_PARAM, "flat");
    });

  const headerLabel = (path: string) => {
    const field = columnFields.get(path);
    if (!field) return path;
    return field.entry.kind === "number"
      ? unitLabel(field.label, field.entry, system)
      : field.label;
  };
  const numeric = (path: string) => columnFields.get(path)?.entry.kind === "number";

  // Column widths from every row (not the rendered slice), so scrolling never reflows.
  // biome-ignore lint/correctness/useExhaustiveDependencies: headerLabel reads columnFields and system
  const allWidths = useMemo(
    () =>
      columns.map((c, i) => {
        const lengths = rows.map((r) => texts.cells.get(r)?.[i]?.length ?? 0);
        return columnWidth(lengths, headerLabel(c).length);
      }),
    [columns, rows, texts, columnFields, system],
  );
  // The columns that fit beside a usable name column (the first always shows), so the
  // table never scrolls sideways; the rest stay in the Columns menu.
  const visibleCols = useMemo(() => {
    if (!tableW) return columns;
    let used = NAME_MIN;
    const out: string[] = [];
    for (const [i, c] of columns.entries()) {
      const w = (allWidths[i] ?? 6) * chPx + 24;
      if (i > 0 && used + w > tableW) break;
      used += w;
      out.push(c);
    }
    return out;
  }, [columns, allWidths, tableW, chPx]);
  const colSpan = visibleCols.length + 1;

  const sortHeader = (key: string, label: string, num: boolean, className?: string) => (
    <SortHeader
      key={key}
      sortKey={key}
      label={label}
      sort={sort}
      onSort={setSort}
      num={num}
      className={className}
      title={columnFields.get(key)?.entry.description}
    />
  );

  // While the index loads, the filters column is kept (most series have facets). The loaded
  // view is a new subtree (keyed below), so a series without facets replaces the loading
  // layout instead of shifting it sideways.
  const showFacets = index ? facets.length > 0 : !error;
  const total = index?.count ?? count;
  const plural = info?.label.toLowerCase() ?? series;

  return (
    <div>
      <h1 className="page-title">{info?.label ?? series}</h1>
      {index?.intro ? (
        <div className="browse-intro">
          <Markdown html={index.intro.html} handWritten />
          <SeeAlso links={index.intro.seeAlso} />
        </div>
      ) : null}

      <div
        key={index ? "loaded" : "loading"}
        className={showFacets ? "browse" : "browse browse-nofacets"}
      >
        {showFacets ? (
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
                const { counts: c, options } = facetOptions.options.get(facet.path) ?? {
                  counts: new Map<string, number>(),
                  options: [],
                };
                const sel = selected[facet.path] ?? [];
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
                        <span className="facet-label">
                          {facetLabel(facet, v, facetFields.get(facet.path)?.entry, ctx)}
                        </span>
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

        <div className="browse-main" style={{ "--browse-head-h": `${headH}px` } as CSSProperties}>
          <div className="browse-head" ref={headRef}>
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
                    {pickable.map(({ path, entry, label }) => (
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
                          {label}
                          <span className="col-picker-path">{path}</span>
                        </span>
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
                <fieldset className="seg-slash group-toggle">
                  <legend className="visually-hidden">List layout</legend>
                  <button
                    type="button"
                    className="seg-btn"
                    aria-pressed={grouped}
                    onClick={() => setGrouped(true)}
                  >
                    Group by {groupBy.label}
                  </button>
                  <span className="seg-sep" aria-hidden="true">
                    /
                  </span>
                  <button
                    type="button"
                    className="seg-btn"
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
          </div>

          {error ? (
            <div className="empty-state">
              <p>{error} Reload the page.</p>
            </div>
          ) : (
            <section
              className="table-wrap vtable"
              ref={wrapRef}
              aria-label={`${info?.label ?? series} table`}
            >
              <span ref={chRef} className="ch-probe" aria-hidden="true">
                0
              </span>
              <table className="table" aria-rowcount={layout.items.length + 1}>
                <colgroup>
                  <col className="col-name" />
                  {visibleCols.map((c, i) => (
                    <col
                      key={c}
                      className={i === 0 ? "col-keep" : "col-opt"}
                      style={{ "--col-w": `calc(${allWidths[i]}ch + 24px)` } as CSSProperties}
                    />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    {sortHeader("name", info?.singular ? capitalise(info.singular) : "Name", false)}
                    {visibleCols.map((c, i) =>
                      sortHeader(c, headerLabel(c), numeric(c), i === 0 ? "col-keep" : "col-opt"),
                    )}
                  </tr>
                </thead>
                <BrowseBody
                  layout={layout}
                  ready={ready}
                  empty={sorted.length === 0}
                  colSpan={colSpan}
                  visibleCols={visibleCols}
                  cells={texts.cells}
                  numeric={numeric}
                  series={series}
                  singular={info?.singular}
                  plural={plural}
                />
              </table>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * The virtualised table body: the page scrolls, and only the items in the window's view
 * of the body (plus overscan) render. Owns the scroll position, so a scroll step
 * re-renders this body alone, not the toolbar, facets or head.
 */
function BrowseBody({
  layout,
  ready,
  empty,
  colSpan,
  visibleCols,
  cells,
  numeric,
  series,
  singular,
  plural,
}: {
  layout: Layout<Row>;
  ready: boolean;
  empty: boolean;
  colSpan: number;
  visibleCols: string[];
  /** Each row's cell texts, in column order (visible columns come first). */
  cells: Map<Row, string[]>;
  /** Whether a column holds numbers (right-aligned). */
  numeric: (path: string) => boolean;
  series: string;
  singular: string | undefined;
  plural: string;
}) {
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(800);
  const measure = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    // Whole rows only, so a few pixels of scroll do not re-render.
    const past = Math.max(0, -body.getBoundingClientRect().top);
    setScrollTop(Math.floor(past / ROW_H) * ROW_H);
    setViewH(window.innerHeight);
  }, []);
  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        measure();
      });
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    // Anything above the table changing height (filters panel, intro) moves the body.
    const observer = new ResizeObserver(schedule);
    observer.observe(document.body);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [measure]);
  // The body's position or contents changed without a scroll: re-read the view.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure when the layout changes
  useEffect(() => measure(), [layout, ready, measure]);

  const [start, end] = visibleRange(layout.tops, scrollTop, viewH, OVERSCAN);
  const visibleItems = layout.items.slice(start, end);
  const totalH = layout.tops[layout.items.length] ?? 0;

  return (
    <tbody ref={bodyRef}>
      {!ready ? (
        Array.from({ length: 10 }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: placeholder rows
          <tr key={i} className="vrow">
            <td colSpan={colSpan || 1}>
              <span className="sk-bar" />
            </td>
          </tr>
        ))
      ) : empty ? (
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
              <tr key={`g:${item.group.key}`} className="vgroup" aria-rowindex={start + i + 2}>
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
                      {item.group.sub ? <span className="vgroup-sub">{item.group.sub}</span> : null}
                    </span>
                    <span className="contents-leader" aria-hidden="true" />
                    <span className="vgroup-count">
                      {item.group.rows.length.toLocaleString("en-US")}
                      <span className="visually-hidden">
                        {" "}
                        {item.group.rows.length === 1 ? singular : plural}
                      </span>
                    </span>
                  </span>
                </th>
              </tr>
            ) : (
              <tr
                key={item.row.id}
                className={item.group ? "vrow vrow-grouped" : "vrow"}
                aria-rowindex={start + i + 2}
              >
                <td className="name-cell">
                  <RefLink href={recordHref(series, item.row.id)} title={item.row.name}>
                    {item.row.name}
                  </RefLink>
                  {item.row.id !== item.row.name ? (
                    <span className="sub mono">{item.row.id}</span>
                  ) : null}
                </td>
                {visibleCols.map((c, ci) => {
                  const text = cells.get(item.row)?.[ci] ?? "";
                  return (
                    <td
                      key={c}
                      className={[numeric(c) ? "num" : "", ci === 0 ? "col-keep" : "col-opt"]
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
              <td colSpan={colSpan} style={{ height: totalH - (layout.tops[end] ?? 0) }} />
            </tr>
          ) : null}
        </>
      )}
    </tbody>
  );
}
