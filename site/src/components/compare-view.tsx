"use client";

import { type KeyboardEvent, type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { catalogKeyFor, companionLabel, comparableValues } from "@/lib/catalog";
import { cellText } from "@/lib/cell-text";
import {
  loadCatalog,
  loadFieldPaths,
  loadFieldValues,
  loadNames,
  loadRecord,
  loadSeriesIndex,
  useModel,
} from "@/lib/client-data";
import {
  addRecords,
  type CompareState,
  compareQuery,
  getCompare,
  removeRecord,
  setCompare,
  useCompareOnClient,
} from "@/lib/compare-store";
import { fieldPaths } from "@/lib/db/reference";
import {
  isXY,
  machAxis,
  pathLabel,
  plainValue,
  sortableValue,
  type ValueContext,
} from "@/lib/format-field";
import { replaceQuery } from "@/lib/history";
import { perObject } from "@/lib/once";
import { sectionFor } from "@/lib/placement";
import { asSurfaces } from "@/lib/record-tables";
import { recordHref, SERIES_BY_ID } from "@/lib/series";
import { capitalise, compareSortKeys, naturalCompare, squash } from "@/lib/text";
import type { CatalogEntry, FieldValues, RecordDoc, SeriesCatalog } from "@/lib/types";
import { useUnitSystem } from "@/lib/unit-system";
import {
  convertNumber,
  displayUnit,
  formatNumber,
  formatPlain,
  type UnitSystem,
  unitLabel,
} from "@/lib/units";
import { useLoaded } from "@/lib/use-loaded";
import { CloseIcon, SearchIcon } from "@/ui/icons";
import { SERIES_COLORS } from "./chart-colors";
import { fieldDataAttrs, renderDescription } from "./field-view";
import { type ChartSeries, LineChart } from "./line-chart";
import { Markdown } from "./Markdown";
import { surfaceRow } from "./record/envelope";
import { RefLink } from "./ref-link";
import { SortHeader, type SortState } from "./sort-header";

const MAX_SERIES = SERIES_COLORS.length;

type RecordInfo = { name: string; id: string; sub: string };

/**
 * A field's group: the record page's section of it (lib/placement.ts `sectionFor`), a
 * companion section named with the companion ("Flight model: Aerodynamics").
 */
function sectionOf(catalog: SeriesCatalog, key: string): { id: string; label: string } {
  const section = sectionFor(catalog, key);
  const label =
    section.companion && section.kind !== "overview"
      ? `${companionLabel(catalog)}: ${section.title}`
      : section.title;
  return { id: section.id, label };
}

function entryFor(catalog: SeriesCatalog, path: string): CatalogEntry | null {
  const key = catalogKeyFor(path, catalog);
  return key ? (catalog.entries[key] ?? null) : null;
}

export function CompareView() {
  // The store has already read a comparison the address names (lib/compare-store.ts);
  // from here on the store's state is written to the address.
  const state = useCompareOnClient();
  useEffect(() => {
    if (state) replaceQuery(compareQuery(state));
  }, [state]);
  return state ? <Comparison state={state} /> : <p className="muted">Loading…</p>;
}

function Comparison({ state }: { state: CompareState }) {
  const system = useUnitSystem();
  const series = state.series;
  const info = SERIES_BY_ID.get(series);
  const catalog = useLoaded(loadCatalog, series);
  const { model } = useModel();
  const index = useLoaded(loadSeriesIndex, series);

  // Each record's name, id and subtitle (its first browse column, as browse shows it).
  const records = useMemo(() => {
    const map = new Map<string, RecordInfo>();
    if (!index || !catalog) return map;
    const firstCol = index.visible[0];
    const col = firstCol ? index.columns.indexOf(firstCol) : -1;
    const colEntry = firstCol ? catalog.entries[firstCol] : undefined;
    const ctx: ValueContext = { enums: catalog.enums, system };
    for (const row of index.rows) {
      const [slug, name, id] = row;
      const sub = col >= 0 && colEntry ? cellText(colEntry, row[3 + col], ctx) : "";
      map.set(slug, { name, id, sub });
    }
    return map;
  }, [index, catalog, system]);

  const color = (slug: string) => {
    const i = state.records.indexOf(slug);
    return i >= 0 && i < MAX_SERIES ? SERIES_COLORS[i] : "var(--ink-3)";
  };
  const update = (patch: Partial<CompareState>) => setCompare({ ...getCompare(series), ...patch });
  const add = (slug: string) => addRecords(series, slug);
  const remove = (slug: string) => removeRecord(series, slug);
  const toggle = (slug: string) => (state.records.includes(slug) ? remove(slug) : add(slug));
  const name = (slug: string) => records.get(slug)?.name ?? slug;

  const entry = state.field && catalog ? entryFor(catalog, state.field) : null;
  const singular = info?.singular ?? "record";
  const plural = info?.label.toLowerCase() ?? "records";

  return (
    <div>
      <div className="compare-head">
        <div>
          <h1 className="page-title">Compare</h1>
        </div>
        <div className="compare-controls compare-controls-3">
          <div>
            <label className="control-label" htmlFor="series-select">
              Series
            </label>
            <div className="field-pick">
              <select
                id="series-select"
                className="input"
                value={series}
                onChange={(e) => setCompare(getCompare(e.target.value))}
              >
                {(
                  model?.series.filter((s) => !s.parent) ?? [
                    { id: series, label: info?.label ?? series },
                  ]
                ).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <span className="control-label" id="records-label">
              {info?.label ?? "Records"}
            </span>
            <AddPicker
              label={`Add ${singular}`}
              placeholder={`Add ${singular}`}
              records={records}
              exclude={state.records}
              onPick={add}
            />
          </div>
          <div>
            <label className="control-label" htmlFor="field-select">
              Field
            </label>
            <div className="field-pick">
              <FieldSelect
                series={series}
                catalog={catalog}
                value={state.field}
                onChange={(field) => update({ field })}
              />
            </div>
          </div>
        </div>
        {/* biome-ignore lint/a11y/useSemanticElements: a labelled group of removable chips */}
        <div className="selection" role="group" aria-labelledby="records-label">
          {state.records.length === 0 ? (
            <span className="muted">No {plural} selected.</span>
          ) : (
            state.records.map((slug) => (
              <span className="sel-chip" key={slug}>
                <span className="swatch" style={{ background: color(slug) }} />
                <RefLink href={recordHref(series, slug)}>{name(slug)}</RefLink>
                <button
                  type="button"
                  aria-label={`Remove ${name(slug)}`}
                  onClick={() => remove(slug)}
                >
                  <CloseIcon />
                </button>
              </span>
            ))
          )}
          {state.records.length > 1 ? (
            <button
              type="button"
              className="btn btn-compact btn-quiet"
              onClick={() => update({ records: [] })}
            >
              Clear all
            </button>
          ) : null}
        </div>
      </div>

      {state.field && catalog && !entry ? (
        <div className="empty-state">
          <h2>Unknown field</h2>
          <p>
            <code>{state.field}</code>
          </p>
        </div>
      ) : null}

      {entry && state.field && catalog ? (
        <FieldCompare
          key={`${series}|${state.field}`}
          series={series}
          path={state.field}
          entry={entry}
          catalog={catalog}
          selected={state.records}
          records={records}
          color={color}
          toggle={toggle}
          system={system}
        />
      ) : null}

      {!state.field && catalog ? (
        state.records.length === 0 ? null : (
          <Matrix
            series={series}
            catalog={catalog}
            slugs={state.records}
            onPickField={(field) => update({ field })}
            color={color}
            system={system}
          />
        )
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pickers

function AddPicker({
  label,
  placeholder,
  records,
  exclude,
  onPick,
}: {
  label: string;
  placeholder: string;
  records: Map<string, RecordInfo>;
  exclude: string[];
  onPick: (slug: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const listId = useId();

  const hits = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const skip = new Set(exclude);
    const sq = squash(q);
    const scored: Array<{ slug: string; info: RecordInfo; score: number }> = [];
    for (const [slug, info] of records) {
      if (skip.has(slug)) continue;
      const n = info.name.toLowerCase();
      const id = info.id.toLowerCase();
      let score = -1;
      if (n === q || id === q) score = 0;
      else if (n.startsWith(q) || id.startsWith(q)) score = 1;
      else if (n.includes(q) || id.includes(q)) score = 2;
      else if (sq && (squash(n).includes(sq) || squash(id).includes(sq))) score = 3;
      if (score >= 0) scored.push({ slug, info, score });
    }
    return scored
      .sort((a, b) => a.score - b.score || naturalCompare(a.info.name, b.info.name))
      .slice(0, 12);
  }, [query, records, exclude]);

  const pick = (slug: string | undefined) => {
    if (!slug) return;
    onPick(slug);
    setQuery("");
    setActive(0);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(hits.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(hits[active]?.slug);
    } else if (event.key === "Escape") {
      setQuery("");
      setOpen(false);
    }
  };

  const showList = open && query.trim() !== "";
  const activeId = hits[active] ? `${listId}-${active}` : undefined;

  return (
    <div className="combo combo-compact">
      <div className="combo-field">
        <SearchIcon />
        <input
          className="combo-input"
          role="combobox"
          aria-label={label}
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={showList ? activeId : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={query}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      {showList ? (
        <div className="combo-popup">
          <div className="results" id={listId} role="listbox" aria-label={`${label} results`}>
            {hits.map((hit, i) => (
              // biome-ignore lint/a11y/useKeyWithClickEvents: keyboard is handled on the input
              <div
                key={hit.slug}
                id={`${listId}-${i}`}
                role="option"
                tabIndex={-1}
                aria-selected={i === active}
                aria-label={[hit.info.name, hit.info.sub, hit.info.id].filter(Boolean).join(", ")}
                className="result"
                onMouseDown={(e) => e.preventDefault()}
                onMouseMove={() => setActive(i)}
                onClick={() => pick(hit.slug)}
              >
                <span className="result-name">{hit.info.name}</span>
                <span className="result-meta">{hit.info.sub}</span>
                <span className="result-id">{hit.info.id}</span>
              </div>
            ))}
          </div>
          {records.size === 0 ? <div className="results-empty">Loading…</div> : null}
          {records.size > 0 && hits.length === 0 ? (
            <div className="results-empty">No results for “{query}”.</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function FieldSelect({
  series,
  catalog,
  value,
  onChange,
}: {
  series: string;
  catalog: SeriesCatalog | null;
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  // Keyed paths (`flight.motorStages.march.impulseS`) take a scan of the series: read once
  // the list opens, or when the address names one.
  const [opened, setOpened] = useState(false);
  const keyedValue = Boolean(value && catalog && catalogKeyFor(value, catalog)?.includes("*"));
  const allPaths = useLoaded(() => loadFieldPaths(series), opened || keyedValue ? series : null);
  const paths = useMemo(
    () => allPaths ?? (catalog ? fieldPaths(catalog) : []),
    [allPaths, catalog],
  );
  const groups = useMemo(() => {
    if (!catalog) return [];
    const order = new Map(Object.keys(catalog.entries).map((k, i) => [k, i]));
    type Option = { path: string; label: string; rank: number };
    const map = new Map<string, { section: string; options: Option[] }>();
    for (const fp of paths) {
      const entry = catalog.entries[fp.key];
      if (!entry?.comparable) continue;
      const { id, label } = sectionOf(catalog, fp.key);
      const group = map.get(id) ?? { section: label, options: [] };
      group.options.push({
        path: fp.path,
        label: pathLabel(entry, fp.path),
        rank: order.get(fp.key) ?? 0,
      });
      map.set(id, group);
    }
    return [...map.entries()]
      .map(([id, { section, options }]) => ({
        id,
        section,
        options: options.sort((a, b) => a.rank - b.rank || naturalCompare(a.path, b.path)),
      }))
      .sort((a, b) => (a.options[0]?.rank ?? 0) - (b.options[0]?.rank ?? 0));
  }, [catalog, paths]);
  return (
    <select
      id="field-select"
      className="input"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      onFocus={() => setOpened(true)}
      onPointerDown={() => setOpened(true)}
      disabled={!catalog}
    >
      <option value="">All fields</option>
      {value && catalog && !paths.some((f) => f.path === value) ? (
        <option value={value}>{value}</option>
      ) : null}
      {groups.map((g) => (
        <optgroup key={g.id} label={g.section}>
          {g.options.map((o) => (
            <option key={o.path} value={o.path}>
              {o.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// One field across records

type FieldProps = {
  series: string;
  path: string;
  entry: CatalogEntry;
  catalog: SeriesCatalog;
  selected: string[];
  records: Map<string, RecordInfo>;
  color: (slug: string) => string | undefined;
  toggle: (slug: string) => void;
  system: UnitSystem;
};

/**
 * Link table for a ref field's values: the names of the ids `all` holds, one IN query per
 * target series (not the targets' whole browse indexes).
 */
function useRefLinks(
  entry: CatalogEntry,
  all: Record<string, unknown>,
): RecordDoc["links"] | undefined {
  const targets = entry.ref ?? [];
  const ids = useMemo(() => {
    const found = new Set<string>();
    for (const v of Object.values(all)) {
      for (const x of Array.isArray(v) ? v : [v]) {
        if (typeof x === "string" || typeof x === "number") found.add(String(x));
      }
    }
    return [...found].sort();
  }, [all]);
  const links = useLoaded(
    async () => {
      const wanted = new Set(ids);
      const names = await loadNames(new Map(targets.map((t) => [t, wanted])));
      const out: RecordDoc["links"] = {};
      for (const [t, byId] of names) {
        // Browse slugs are record ids.
        out[t] = Object.fromEntries([...byId].map(([id, name]) => [id, [id, name]]));
      }
      return out;
    },
    targets.length && ids.length ? `${targets.join(",")}:${ids.join(",")}` : null,
  );
  return links ?? undefined;
}

function FieldCompare(props: FieldProps) {
  const { series, path, entry, catalog, selected, records, color, system } = props;
  const values = useLoaded<FieldValues | null>(() => loadFieldValues(series, path), path);
  // A Mach-sampled field's step: its sibling step field per record (catalog `axis.step`).
  const sampled = entry.axis?.kind === "sampled" ? entry.axis : null;
  const stepPath = sampled ? path.replace(/[^.]+$/, sampled.step.field) : "";
  const stepKey = stepPath ? catalogKeyFor(stepPath, catalog) : null;
  const hasStep = Boolean(stepKey && catalog.entries[stepKey]?.comparable);
  const steps = useLoaded<FieldValues | null>(
    (p) => (p ? loadFieldValues(series, p) : Promise.resolve(null)),
    hasStep ? stepPath : null,
  );
  const all = useMemo(() => values?.values ?? {}, [values]);
  const have = useMemo(() => selected.filter((s) => all[s] !== undefined), [selected, all]);
  const missing = selected.filter((s) => all[s] === undefined);
  const name = (slug: string) => records.get(slug)?.name ?? slug;
  const label = pathLabel(entry, path);
  const links = useRefLinks(entry, all);
  const vctx = useMemo<ValueContext>(
    () => (links ? { enums: catalog.enums, system, links } : { enums: catalog.enums, system }),
    [catalog, system, links],
  );

  let selection: ReactNode;
  if (!values) selection = <p className="muted">Loading…</p>;
  else if (sampled) {
    selection = (
      <MachCompare
        slugs={have}
        all={all}
        steps={steps?.values ?? {}}
        fallback={sampled.step.fallback}
        xLabel={sampled.label}
        name={name}
        color={color}
        label={label}
        entry={entry}
        system={system}
      />
    );
  } else if (entry.axis?.kind === "surface") {
    selection = (
      <EnvelopeCompare
        slugs={have}
        all={all}
        name={name}
        color={color}
        entry={entry}
        catalog={catalog}
        path={path}
        system={system}
      />
    );
  } else if (entry.axis?.kind === "column") {
    selection = (
      <CurveCompare
        slugs={have}
        all={all}
        name={name}
        color={color}
        entry={entry}
        catalog={catalog}
        path={path}
        system={system}
      />
    );
  } else {
    selection = (
      <SelectedTable
        series={series}
        slugs={have}
        all={all}
        entry={entry}
        name={name}
        color={color}
        vctx={vctx}
      />
    );
  }

  return (
    <div>
      <div className="panel compare-field-head">
        <div className="compare-field-title">
          <h2>{label}</h2>
          {entry.dcsKey ? <span className="field-key">{entry.dcsKey}</span> : null}
          {displayUnit(entry, system) ? (
            <span className="chip">{displayUnit(entry, system)}</span>
          ) : null}
          {entry.unitNotStated ? <span className="chip">unit not stated</span> : null}
          <span className="field-key">{path}</span>
        </div>
        <p className="compare-desc">{renderDescription(entry.description)}</p>
        {entry.note ? <Markdown html={entry.note} handWritten className="compare-note" /> : null}
      </div>

      {selected.length > 0 ? (
        <section className="panel" aria-labelledby="sel-h">
          <div className="panel-head">
            <h3 id="sel-h">Selected</h3>
            {missing.length && values ? (
              <span className="muted">No value for {missing.map(name).join(", ")}.</span>
            ) : null}
          </div>
          {selection}
        </section>
      ) : null}

      <AllRecordsTable {...props} all={all} loading={!values} vctx={vctx} />
    </div>
  );
}

function ChartLegend({ series }: { series: ChartSeries[] }) {
  return (
    <div className="legend" aria-hidden="true">
      {series.map((s) => (
        <span className="legend-item" key={s.id}>
          <span className="swatch" style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

function TooMany({ slugs }: { slugs: string[] }) {
  return slugs.length > MAX_SERIES ? (
    <p className="muted">Chart shows the first {MAX_SERIES}.</p>
  ) : null;
}

/** Mach-indexed lists (`numbers` on the Mach axis): each record's values at its own step. */
function MachCompare({
  slugs,
  all,
  steps,
  fallback,
  xLabel,
  name,
  color,
  label,
  entry,
  system,
}: {
  slugs: string[];
  all: Record<string, unknown>;
  /** Each record's step (catalog `axis.step.field`), else `fallback`. */
  steps: Record<string, unknown>;
  fallback: number;
  /** The axis' name ("Mach"). */
  xLabel: string;
  name: (s: string) => string;
  color: (s: string) => string | undefined;
  label: string;
  entry: CatalogEntry;
  system: UnitSystem;
}) {
  const series = slugs.map((slug): ChartSeries => {
    const own = steps[slug];
    const step = typeof own === "number" ? own : fallback;
    const values = (Array.isArray(all[slug]) ? (all[slug] as unknown[]) : [])
      .filter((v): v is number => typeof v === "number")
      .map((v) => convertNumber(v, entry, system));
    return {
      id: slug,
      label: name(slug),
      color: color(slug) ?? "var(--ink-3)",
      x: machAxis(values.length, step),
      values,
    };
  });
  return (
    <SeriesCompare
      series={series}
      title={label}
      xLabel={xLabel}
      yUnit={displayUnit(entry, system)}
    />
  );
}

/** Axis-table columns (`flight.aerodynamics.table[].cx0`): `{x, y}` curves per record. */
function CurveCompare({
  slugs,
  all,
  name,
  color,
  entry,
  catalog,
  path,
  system,
}: {
  slugs: string[];
  all: Record<string, unknown>;
  name: (s: string) => string;
  color: (s: string) => string | undefined;
  entry: CatalogEntry;
  catalog: SeriesCatalog;
  path: string;
  system: UnitSystem;
}) {
  const axis = entry.axis?.kind === "column" ? entry.axis : null;
  const axisEntry = axis ? catalog.entries[axis.path] : undefined;
  const xLabel = axis ? unitLabel(axis.label, axisEntry, system) : "x";
  const series = slugs.flatMap((slug): ChartSeries[] => {
    const v = all[slug];
    if (!isXY(v)) return [];
    const values = v.y.map((y) => convertNumber(y, entry, system));
    return [
      {
        id: slug,
        label: name(slug),
        color: color(slug) ?? "var(--ink-3)",
        x: v.x.map((x) => convertNumber(x, axisEntry, system)),
        values,
      },
    ];
  });
  return (
    <SeriesCompare
      series={series}
      title={pathLabel(entry, path)}
      xLabel={xLabel}
      yUnit={displayUnit(entry, system)}
    />
  );
}

/**
 * Records' series over one x axis: a chart of the first `MAX_SERIES`, and a table of
 * every record with a row per x any of them has.
 */
function SeriesCompare({
  series,
  title,
  xLabel,
  yUnit,
}: {
  /** Each with explicit `x`. */
  series: ChartSeries[];
  title: string;
  xLabel: string;
  yUnit: string | null;
}) {
  if (series.length === 0) return <p className="muted">No data.</p>;
  const charted = series.slice(0, MAX_SERIES);
  const xs = [...new Set(series.flatMap((s) => s.x ?? []))].sort((a, b) => a - b);
  const valueAt = (s: ChartSeries, x: number) => {
    const i = (s.x ?? []).findIndex((v) => Math.abs(v - x) < 1e-9);
    return i >= 0 ? s.values[i] : undefined;
  };
  return (
    <div>
      <ChartLegend series={charted} />
      <LineChart title={title} series={charted} xLabel={xLabel} yUnit={yUnit} />
      <TooMany slugs={series.map((s) => s.id)} />
      <details className="exact series-table">
        <summary>Table</summary>
        <div className="exact-scroll">
          <table className="exact-table">
            <thead>
              <tr>
                <th scope="col">{xLabel}</th>
                {series.map((s) => (
                  <th scope="col" key={s.id}>
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {xs.map((x) => (
                <tr key={x}>
                  <td>{formatNumber(x)}</td>
                  {series.map((s) => {
                    const v = valueAt(s, x);
                    return <td key={s.id}>{v === undefined ? "" : formatNumber(v)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/** Envelope grids: pick a row (altitude), chart the row over the column axis (speed). */
function EnvelopeCompare({
  slugs,
  all,
  name,
  color,
  entry,
  catalog,
  path,
  system,
}: {
  slugs: string[];
  all: Record<string, unknown>;
  name: (s: string) => string;
  color: (s: string) => string | undefined;
  entry: CatalogEntry;
  catalog: SeriesCatalog;
  path: string;
  system: UnitSystem;
}) {
  const surface = entry.axis?.kind === "surface" ? entry.axis : null;
  const rowEntry = surface ? catalog.entries[surface.paths.rows] : undefined;
  const colEntry = surface ? catalog.entries[surface.paths.cols] : undefined;
  const rows = useMemo(() => {
    const set = new Set<number>();
    for (const s of slugs.length ? slugs : Object.keys(all))
      for (const surface of asSurfaces(all[s])) for (const r of surface.rows) set.add(r);
    return [...set].sort((a, b) => a - b);
  }, [slugs, all]);
  const [row, setRow] = useState<number | null>(null);
  const chosen = row !== null && rows.includes(row) ? row : (rows[0] ?? null);

  const series: ChartSeries[] = [];
  const without: string[] = [];
  if (chosen !== null) {
    for (const slug of slugs) {
      const line = surfaceRow(asSurfaces(all[slug]), chosen);
      if (!line) {
        without.push(slug);
        continue;
      }
      if (series.length >= MAX_SERIES) continue;
      series.push({
        id: slug,
        label: name(slug),
        color: color(slug) ?? "var(--ink-3)",
        x: line.x.map((x) => convertNumber(x, colEntry, system)),
        values: line.y.map((y) => convertNumber(y, entry, system)),
      });
    }
  }
  return (
    <div>
      <div className="toolbar envelope-pick">
        <label className="control-label" htmlFor="envelope-row">
          {rowEntry?.label ?? "Row"}
        </label>
        <select
          id="envelope-row"
          className="input"
          value={chosen ?? ""}
          onChange={(e) => setRow(Number(e.target.value))}
        >
          {rows.map((r) => (
            <option key={r} value={r}>
              {formatPlain(r, rowEntry, system)}
            </option>
          ))}
        </select>
      </div>
      {series.length === 0 ? (
        <p className="muted">No data.</p>
      ) : (
        <>
          <ChartLegend series={series} />
          <LineChart
            title={`${pathLabel(entry, path)} at ${chosen === null ? "" : formatPlain(chosen, rowEntry, system)}`}
            series={series}
            xLabel={unitLabel(colEntry?.label ?? "Column", colEntry, system)}
            yUnit={displayUnit(entry, system)}
          />
        </>
      )}
      {without.length ? (
        <p className="muted">No value for {without.map(name).join(", ")}.</p>
      ) : null}
    </div>
  );
}

function SelectedTable({
  series,
  slugs,
  all,
  entry,
  name,
  color,
  vctx,
}: {
  series: string;
  slugs: string[];
  all: Record<string, unknown>;
  entry: CatalogEntry;
  name: (s: string) => string;
  color: (s: string) => string | undefined;
  vctx: ValueContext;
}) {
  const nums = slugs
    .map((s) => all[s])
    .filter((v): v is number => typeof v === "number" && entry.kind === "number")
    .map((v) => convertNumber(v, entry, vctx.system));
  const max = nums.length ? Math.max(...nums.map(Math.abs)) : 0;
  if (slugs.length === 0) return <p className="muted">No data.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{SERIES_BY_ID.get(series)?.singular ?? "Record"}</th>
            <th scope="col" className="num">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {slugs.map((s) => {
            const v = all[s];
            const n =
              typeof v === "number" && entry.kind === "number"
                ? convertNumber(v, entry, vctx.system)
                : null;
            return (
              <tr key={s}>
                <td className="name-cell">
                  <span className="swatch" style={{ background: color(s) }} />
                  <RefLink href={recordHref(series, s)}>{name(s)}</RefLink>
                </td>
                <td className="num">
                  <span className="bar-cell">
                    {plainValue(entry, v, vctx)}
                    {n !== null && max > 0 ? (
                      <span className="bar-track" aria-hidden="true">
                        <span
                          className="bar"
                          style={{ width: `${(Math.abs(n) / max) * 100}%`, background: color(s) }}
                        />
                      </span>
                    ) : null}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AllRecordsTable({
  series,
  entry,
  all,
  loading,
  records,
  selected,
  toggle,
  system,
  vctx,
}: FieldProps & { all: Record<string, unknown>; loading: boolean; vctx: ValueContext }) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortState<"name" | "value" | "sub">>({
    key: "value",
    dir: -1,
  });
  const info = SERIES_BY_ID.get(series);
  const plural = info?.label.toLowerCase() ?? "records";
  const curve = entry.kind === "numbers" || entry.axis !== undefined;
  const surface = entry.axis?.kind === "surface";
  const valueLabel = surface ? "Largest value" : curve ? "Peak" : "Value";

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const list = Object.entries(all).map(([slug, value]) => {
      const r = records.get(slug);
      const sortValue = sortableValue(entry, value, vctx);
      const text =
        curve && typeof sortValue === "number"
          ? formatNumber(sortValue)
          : plainValue(entry, value, vctx);
      return {
        slug,
        value,
        text,
        name: r?.name ?? slug,
        id: r?.id ?? slug,
        sub: r?.sub ?? "",
        sort: sortValue,
      };
    });
    const visible = f
      ? list.filter((r) => `${r.name} ${r.id} ${r.sub} ${r.text}`.toLowerCase().includes(f))
      : list;
    const key = (r: (typeof list)[number]) =>
      sort.key === "name" ? r.name : sort.key === "sub" ? r.sub : r.sort;
    visible.sort((a, b) => compareSortKeys(key(a), key(b), sort.dir));
    return visible;
  }, [all, filter, sort, entry, records, vctx, curve]);

  const header = (key: "name" | "value" | "sub", label: string, num = false) => (
    <SortHeader sortKey={key} label={label} sort={sort} onSort={setSort} num={num} />
  );

  const total = Object.keys(all).length;
  return (
    <section className="panel" aria-labelledby="all-h">
      <div className="panel-head">
        <h3 id="all-h">{loading ? `All ${plural}` : `All ${plural} (${total})`}</h3>
        <div className="toolbar">
          <input
            className="input"
            type="search"
            placeholder="Filter"
            aria-label={`Filter ${plural}`}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </div>
      <div className="table-wrap records-scroll">
        <table className="table">
          <thead>
            <tr>
              <th scope="col" className="check-col">
                <span className="visually-hidden">In compare</span>
              </th>
              {header("name", info?.singular ? capitalise(info.singular) : "Record")}
              {header("sub", "Kind")}
              {header("value", curve ? unitLabel(valueLabel, entry, system) : valueLabel, true)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const checked = selected.includes(r.slug);
              return (
                <tr key={r.slug}>
                  <td>
                    <input
                      type="checkbox"
                      className="row-check"
                      checked={checked}
                      onChange={() => toggle(r.slug)}
                      aria-label={`${checked ? "Remove" : "Add"} ${r.name} ${checked ? "from" : "to"} compare`}
                    />
                  </td>
                  <td className="name-cell">
                    <RefLink href={recordHref(series, r.slug)}>{r.name}</RefLink>
                    <span className="sub mono">{r.id}</span>
                  </td>
                  <td>{r.sub || <span className="muted">—</span>}</td>
                  <td className="num">{r.text}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Side by side

type ComparableValue = ReturnType<typeof comparableValues>[number];

/** A record's comparable values by path, built once per loaded record (its series' catalog). */
const valueMaps = perObject<RecordDoc, Map<string, ComparableValue>>();

const valueMapOf = (catalog: SeriesCatalog, doc: RecordDoc) =>
  valueMaps.cachedBy(
    doc,
    catalog.series,
    () => new Map(comparableValues(catalog, doc.data, doc.companion).map((v) => [v.path, v])),
  );

function Matrix({
  series,
  catalog,
  slugs,
  onPickField,
  color,
  system,
}: {
  series: string;
  catalog: SeriesCatalog;
  slugs: string[];
  onPickField: (path: string) => void;
  color: (slug: string) => string | undefined;
  system: UnitSystem;
}) {
  const [diffOnly, setDiffOnly] = useState(false);
  const loaded = useLoaded<Array<RecordDoc | null>>(
    () => Promise.all(slugs.map((s) => loadRecord(series, s).catch(() => null))),
    `${series}:${slugs.join(",")}`,
  );
  // While a changed selection loads, the previous records stay (minus any removed).
  const [kept, setKept] = useState(loaded);
  if (loaded && loaded !== kept) setKept(loaded);
  const docs = loaded ?? kept;
  const records = useMemo(
    () => (docs ?? []).filter((d): d is RecordDoc => Boolean(d && slugs.includes(d.slug))),
    [docs, slugs],
  );
  const maps = useMemo(() => records.map((r) => valueMapOf(catalog, r)), [records, catalog]);
  const vctxs = useMemo(
    () => records.map((rec): ValueContext => ({ enums: catalog.enums, system, links: rec.links })),
    [records, catalog, system],
  );

  const rows = useMemo(() => {
    const order = new Map(Object.keys(catalog.entries).map((k, i) => [k, i]));
    const paths = new Map<string, string>();
    for (const m of maps)
      for (const v of m.values()) if (!paths.has(v.path)) paths.set(v.path, v.key);
    return [...paths.entries()]
      .map(([path, key]) => ({ path, key, entry: catalog.entries[key] }))
      .filter((r): r is { path: string; key: string; entry: CatalogEntry } =>
        // The record's name heads its column already.
        Boolean(r.entry && !catalog.titleFields.includes(r.key)),
      )
      .map((r) => ({ ...r, section: sectionOf(catalog, r.key) }))
      .sort(
        (a, b) =>
          (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0) || naturalCompare(a.path, b.path),
      );
  }, [catalog, maps]);

  if (!docs) return <p className="muted">Loading…</p>;
  if (records.length === 0) return <p className="muted">Failed to load data. Reload the page.</p>;

  // Sections in the order their first field appears.
  const sectionOrder = new Map<string, string>();
  for (const r of rows)
    if (!sectionOrder.has(r.section.id)) sectionOrder.set(r.section.id, r.section.label);

  return (
    <section className="panel" aria-labelledby="matrix-h">
      <div className="panel-head">
        <h3 id="matrix-h">Side by side</h3>
        <label className="check">
          <input
            type="checkbox"
            checked={diffOnly}
            onChange={(e) => setDiffOnly(e.target.checked)}
          />
          Differences only
        </label>
      </div>
      <div className="table-wrap matrix-scroll">
        <table className="table matrix">
          <thead>
            <tr>
              <th scope="col">Field</th>
              {records.map((r) => (
                <th scope="col" key={r.slug}>
                  <span className="swatch" style={{ background: color(r.slug) }} />
                  <RefLink href={recordHref(series, r.slug)}>{r.name}</RefLink>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...sectionOrder].map(([section, sectionLabel]) => {
              const body = rows
                .filter((r) => r.section.id === section)
                .map(({ path, entry }) => {
                  const values = maps.map((m) => m.get(path)?.value);
                  const texts = values.map((v, i) =>
                    v === undefined ? null : plainValue(entry, v, vctxs[i] as ValueContext),
                  );
                  const differs = new Set(texts).size > 1;
                  if (diffOnly && !differs) return null;
                  const label = pathLabel(entry, path);
                  return (
                    <tr key={path} className={differs && records.length > 1 ? "diff" : undefined}>
                      <th scope="row">
                        <button
                          type="button"
                          className="sort-btn"
                          onClick={() => onPickField(path)}
                        >
                          {label}
                        </button>
                      </th>
                      {records.map((r, i) => (
                        <td
                          key={r.slug}
                          tabIndex={texts[i] === null ? undefined : 0}
                          {...fieldDataAttrs(
                            entry,
                            path,
                            values[i],
                            { series, slug: r.slug, recordName: r.name },
                            vctxs[i] as ValueContext,
                            label,
                          )}
                        >
                          {texts[i] === null ? <span className="muted">—</span> : texts[i]}
                        </td>
                      ))}
                    </tr>
                  );
                })
                .filter(Boolean);
              if (body.length === 0) return null;
              return [
                <tr key={`h-${section}`}>
                  <th colSpan={records.length + 1} scope="colgroup" className="matrix-section">
                    {sectionLabel}
                  </th>
                </tr>,
                ...body,
              ];
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
