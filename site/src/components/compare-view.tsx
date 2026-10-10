"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type KeyboardEvent, type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { COMPANION_PREFIX, catalogKeyFor, comparableValues } from "@/lib/catalog";
import {
  loadCatalog,
  loadFieldPaths,
  loadFieldValues,
  loadNames,
  loadRecord,
  loadSeriesIndex,
} from "@/lib/client-data";
import {
  type CompareState,
  compareHref,
  getCompare,
  parseCompareParams,
  setCompare,
  useCompare,
} from "@/lib/compare-store";
import {
  isXY,
  machAxis,
  pathLabel,
  plainValue,
  sortableValue,
  type ValueContext,
} from "@/lib/format-field";
import { enumDisplay } from "@/lib/names";
import { recordHref, SERIES_BY_ID } from "@/lib/series";
import { capitalise, naturalCompare, squash } from "@/lib/text";
import type { CatalogEntry, FieldValues, RecordDoc, SeriesCatalog } from "@/lib/types";
import { useUnitSystem } from "@/lib/unit-system";
import {
  convertValue,
  displayUnit,
  formatNumber,
  type UnitSystem,
  unitLabel,
  withUnit,
} from "@/lib/units";
import { useLoaded } from "@/lib/use-loaded";
import { CloseIcon, SearchIcon } from "@/ui/icons";
import { renderDescription } from "./field-view";
import { type ChartSeries, LineChart, SERIES_COLORS } from "./line-chart";
import { Markdown } from "./Markdown";
import { asSurfaces, surfaceRow } from "./record/envelope";
import { RefLink } from "./ref-link";
import { useModel } from "./series-directory";

const MAX_SERIES = SERIES_COLORS.length;

type RecordInfo = { name: string; id: string; sub: string };

const conv = (entry: CatalogEntry, v: number, system: UnitSystem) =>
  convertValue(v, entry, system).value;

/** "Overview", a top-level group's label, or "Flight model: <group>". */
function sectionOf(catalog: SeriesCatalog, key: string): string {
  const parts = key.split(".");
  if (parts[0] === COMPANION_PREFIX) {
    const group = parts.length > 2 ? catalog.entries[`${COMPANION_PREFIX}.${parts[1]}`] : null;
    return group && (group.kind === "record" || group.kind === "records")
      ? `Flight model: ${group.label}`
      : "Flight model";
  }
  const head = parts.length > 1 ? catalog.entries[(parts[0] ?? "").replace(/\[\]$/, "")] : null;
  return head && (head.kind === "record" || head.kind === "records") ? head.label : "Overview";
}

function entryFor(catalog: SeriesCatalog, path: string): CatalogEntry | null {
  const key = catalogKeyFor(path, catalog);
  return key ? (catalog.entries[key] ?? null) : null;
}

export function CompareView() {
  const router = useRouter();
  const params = useSearchParams();
  const state = useCompare();
  const system = useUnitSystem();
  // Until the URL has been read, the store holds the last or default comparison: nothing
  // loads for it, so a shared link's series is the first one read.
  const [hydrated, setHydrated] = useState(false);

  // URL wins on arrival (shared links); afterwards the store drives the URL.
  useEffect(() => {
    if (hydrated) return;
    setHydrated(true);
    const fromUrl = parseCompareParams(new URLSearchParams(params.toString()));
    if (fromUrl) setCompare(fromUrl);
    else router.replace(compareHref(getCompare()), { scroll: false });
  }, [hydrated, params, router]);

  useEffect(() => {
    if (!hydrated) return;
    const href = compareHref(state);
    const query = params.toString().replace(/%2C/g, ",");
    const current = `/compare/${query ? `?${query}` : ""}`;
    if (href !== current) router.replace(href, { scroll: false });
  }, [hydrated, state, params, router]);

  const series = state.series;
  const loadKey = hydrated ? series : "";
  const info = SERIES_BY_ID.get(series);
  const baseCatalog = useLoaded((s) => (s ? loadCatalog(s) : Promise.resolve(null)), loadKey);
  const fieldPaths = useLoaded((s) => (s ? loadFieldPaths(s) : Promise.resolve(null)), loadKey);
  const { model } = useModel();
  const catalog = useMemo(
    () => (baseCatalog && fieldPaths ? { ...baseCatalog, fieldPaths } : baseCatalog),
    [baseCatalog, fieldPaths],
  );
  const index = useLoaded((s) => (s ? loadSeriesIndex(s) : Promise.resolve(null)), loadKey);

  const records = useMemo(() => {
    const map = new Map<string, RecordInfo>();
    if (!index || !catalog) return map;
    const firstCol = index.visible[0];
    const col = firstCol ? index.columns.indexOf(firstCol) : -1;
    const colEntry = firstCol ? catalog.entries[firstCol] : undefined;
    for (const row of index.rows) {
      const [slug, name, id] = row;
      const raw = col >= 0 ? row[3 + col] : null;
      let sub = "";
      if (raw !== null && raw !== undefined && colEntry) {
        sub =
          colEntry.kind === "enum"
            ? enumDisplay(colEntry, raw, catalog.enums).label
            : typeof raw === "number"
              ? formatNumber(raw)
              : String(raw);
      }
      map.set(slug, { name, id, sub });
    }
    return map;
  }, [index, catalog]);

  const color = (slug: string) => {
    const i = state.records.indexOf(slug);
    return i >= 0 && i < MAX_SERIES ? SERIES_COLORS[i] : "var(--ink-3)";
  };
  const update = (patch: Partial<CompareState>) => setCompare({ ...getCompare(series), ...patch });
  const add = (slug: string) => update({ records: [...getCompare(series).records, slug] });
  const remove = (slug: string) =>
    update({ records: getCompare(series).records.filter((r) => r !== slug) });
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
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
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
  catalog,
  value,
  onChange,
}: {
  catalog: SeriesCatalog | null;
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  const groups = useMemo(() => {
    if (!catalog) return [];
    const order = new Map(Object.keys(catalog.entries).map((k, i) => [k, i]));
    const map = new Map<
      string,
      Array<{ path: string; label: string; count: number; rank: number }>
    >();
    for (const fp of catalog.fieldPaths) {
      const entry = catalog.entries[fp.key];
      if (!entry?.comparable) continue;
      const section = sectionOf(catalog, fp.key);
      const list = map.get(section) ?? [];
      list.push({
        path: fp.path,
        label: pathLabel(entry, fp.path),
        count: fp.count,
        rank: order.get(fp.key) ?? 0,
      });
      map.set(section, list);
    }
    return [...map.entries()]
      .map(([section, options]) => ({
        section,
        options: options.sort((a, b) => a.rank - b.rank || a.path.localeCompare(b.path)),
      }))
      .sort((a, b) => (a.options[0]?.rank ?? 0) - (b.options[0]?.rank ?? 0));
  }, [catalog]);
  return (
    <select
      id="field-select"
      className="input"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      disabled={!catalog}
    >
      <option value="">All fields</option>
      {value && catalog && !catalog.fieldPaths.some((f) => f.path === value) ? (
        <option value={value}>{value}</option>
      ) : null}
      {groups.map((g) => (
        <optgroup key={g.section} label={g.section}>
          {g.options.map((o) => (
            <option key={o.path} value={o.path}>
              {o.label}
              {o.count ? ` (${o.count})` : ""}
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
  const targets = (entry.ref ?? []).filter((t) => !SERIES_BY_ID.get(t)?.parent).join(",");
  const key = useMemo(() => {
    if (!targets) return "";
    const ids = new Set<string>();
    for (const v of Object.values(all)) {
      for (const x of Array.isArray(v) ? v : [v]) {
        if (typeof x === "string" || typeof x === "number") ids.add(String(x));
      }
    }
    return ids.size ? `${targets}\n${[...ids].sort().join("\n")}` : "";
  }, [targets, all]);
  const links = useLoaded(async (k) => {
    if (!k) return null;
    const [list = "", ...ids] = k.split("\n");
    const wanted = new Set(ids);
    const names = await loadNames(new Map(list.split(",").map((t) => [t, wanted])));
    const out: RecordDoc["links"] = {};
    for (const [t, byId] of names) {
      // Browse slugs are record ids.
      out[t] = Object.fromEntries([...byId].map(([id, name]) => [id, [id, name]]));
    }
    return out;
  }, key);
  return links ?? undefined;
}

function FieldCompare(props: FieldProps) {
  const { series, path, entry, catalog, selected, records, color, system } = props;
  const values = useLoaded<FieldValues | null>((p) => loadFieldValues(series, p), path);
  // A Mach-sampled field's step: its sibling step field per record (catalog `step`).
  const stepPath = entry.step ? path.replace(/[^.]+$/, entry.step.field) : "";
  const hasStep = Boolean(stepPath) && catalog.fieldPaths.some((f) => f.path === stepPath);
  const steps = useLoaded<FieldValues | null>(
    (p) => (p ? loadFieldValues(series, p) : Promise.resolve(null)),
    hasStep ? stepPath : "",
  );
  const all = values?.values ?? {};
  const have = selected.filter((s) => all[s] !== undefined);
  const missing = selected.filter((s) => all[s] === undefined);
  const name = (slug: string) => records.get(slug)?.name ?? slug;
  const label = pathLabel(entry, path);
  const links = useRefLinks(entry, all);
  const vctx: ValueContext = links
    ? { enums: catalog.enums, system, links }
    : { enums: catalog.enums, system };
  const isEnvelope = entry.axis?.startsWith("grid:") ?? false;

  let selection: ReactNode;
  if (!values) selection = <p className="muted">Loading…</p>;
  else if (entry.step) {
    selection = (
      <MachCompare
        slugs={have}
        all={all}
        steps={steps?.values ?? {}}
        fallback={entry.step.fallback}
        name={name}
        color={color}
        label={label}
        entry={entry}
        system={system}
      />
    );
  } else if (isEnvelope) {
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
  } else if (have.some((s) => isXY(all[s]))) {
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
      <div className="panel" style={{ marginBottom: 20 }}>
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

      <AllRecordsTable {...props} all={all} loading={!values} />
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
  name,
  color,
  label,
  entry,
  system,
}: {
  slugs: string[];
  all: Record<string, unknown>;
  /** Each record's step (catalog `step.field`), else `fallback`. */
  steps: Record<string, unknown>;
  fallback: number;
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
      .map((v) => conv(entry, v, system));
    return {
      id: slug,
      label: name(slug),
      color: color(slug) ?? "var(--ink-3)",
      x: machAxis(values.length, step),
      values,
    };
  });
  return (
    <SeriesCompare series={series} title={label} xLabel="Mach" yUnit={displayUnit(entry, system)} />
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
  const tablePath = path.split("[].")[0] ?? "";
  const axisName = catalog.entries[tablePath]?.axis ?? entry.axis ?? "x";
  const axisEntry = catalog.entries[`${tablePath}[].${axisName}`];
  const convX = (v: number) => (axisEntry ? conv(axisEntry, v, system) : v);
  const xLabel =
    axisName === "mach" ? "Mach" : unitLabel(axisEntry?.label ?? axisName, axisEntry, system);
  const series = slugs.flatMap((slug): ChartSeries[] => {
    const v = all[slug];
    if (!isXY(v)) return [];
    const values = v.y.map((y) => conv(entry, y, system));
    return [
      {
        id: slug,
        label: name(slug),
        color: color(slug) ?? "var(--ink-3)",
        x: v.x.map(convX),
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
      <details className="exact" style={{ marginTop: 10 }}>
        <summary>Table</summary>
        <div className="exact-scroll" style={{ maxHeight: 360 }}>
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
  const tablePath = path.split("[].")[0] ?? "";
  const [rowField, colField] = (entry.axis ?? "grid:,").slice(5).split(",");
  const rowEntry = catalog.entries[`${tablePath}[].${rowField}`];
  const colEntry = catalog.entries[`${tablePath}[].${colField}`];
  const pool = slugs.length ? slugs : Object.keys(all);
  const rows = useMemo(() => {
    const set = new Set<number>();
    for (const s of pool)
      for (const surface of asSurfaces(all[s])) for (const r of surface.rows) set.add(r);
    return [...set].sort((a, b) => a - b);
  }, [pool, all]);
  const [row, setRow] = useState<number | null>(null);
  const chosen = row !== null && rows.includes(row) ? row : (rows[0] ?? null);
  const fmtAxis = (e: CatalogEntry | undefined, v: number) =>
    withUnit(formatNumber(e ? conv(e, v, system) : v), e ? displayUnit(e, system) : null);

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
        x: line.x.map((x) => (colEntry ? conv(colEntry, x, system) : x)),
        values: line.y.map((y) => conv(entry, y, system)),
      });
    }
  }
  return (
    <div>
      <div className="toolbar" style={{ marginBottom: 10 }}>
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
              {fmtAxis(rowEntry, r)}
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
            title={`${pathLabel(entry, path)} at ${chosen === null ? "" : fmtAxis(rowEntry, chosen)}`}
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
    .map((v) => conv(entry, v, vctx.system));
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
              typeof v === "number" && entry.kind === "number" ? conv(entry, v, vctx.system) : null;
            return (
              <tr key={s}>
                <td className="name-cell">
                  <span className="swatch" style={{ background: color(s), marginRight: 8 }} />
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
  catalog,
  all,
  loading,
  records,
  selected,
  toggle,
  system,
}: FieldProps & { all: Record<string, unknown>; loading: boolean }) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<{ key: "name" | "value" | "sub"; dir: 1 | -1 }>({
    key: "value",
    dir: -1,
  });
  const info = SERIES_BY_ID.get(series);
  const plural = info?.label.toLowerCase() ?? "records";
  const links = useRefLinks(entry, all);
  const vctx = useMemo<ValueContext>(
    () => (links ? { enums: catalog.enums, system, links } : { enums: catalog.enums, system }),
    [catalog, system, links],
  );
  const curve = entry.kind === "numbers" || entry.axis !== undefined;
  const valueLabel = entry.axis?.startsWith("grid:") ? "Largest value" : curve ? "Peak" : "Value";

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const list = Object.entries(all).map(([slug, value]) => {
      const r = records.get(slug);
      let sortValue = sortableValue(entry, value, vctx);
      if (entry.axis?.startsWith("grid:")) {
        const cells = asSurfaces(value).flatMap((s) => s.z.flat());
        sortValue = cells.length ? conv(entry, Math.max(...cells), system) : null;
      }
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
    visible.sort((a, b) => {
      if (sort.key === "name") return sort.dir * naturalCompare(a.name, b.name);
      if (sort.key === "sub") return sort.dir * a.sub.localeCompare(b.sub);
      const av = a.sort;
      const bv = b.sort;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === "number" && typeof bv === "number") return sort.dir * (av - bv);
      return sort.dir * naturalCompare(String(av), String(bv));
    });
    return visible;
  }, [all, filter, sort, entry, records, vctx, system, curve]);

  const header = (key: "name" | "value" | "sub", label: string, num = false) => (
    <th
      scope="col"
      className={num ? "num" : undefined}
      aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className="sort-btn"
        data-active={sort.key === key}
        onClick={() =>
          setSort((s) => ({
            key,
            dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "value" ? -1 : 1,
          }))
        }
      >
        {label}
        <span aria-hidden="true">{sort.key === key ? (sort.dir === 1 ? "▲" : "▼") : ""}</span>
      </button>
    </th>
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
      <div className="table-wrap" style={{ maxHeight: 560, overflow: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col" style={{ width: 44 }}>
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
                      style={{ accentColor: "var(--accent)", width: 16, height: 16 }}
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
  const docs = useLoaded<Array<RecordDoc | null>>(
    (key) =>
      Promise.all(
        key
          .split(",")
          .filter(Boolean)
          .map((s) => loadRecord(series, s).catch(() => null)),
      ),
    slugs.join(","),
  );
  const records = useMemo(() => (docs ?? []).filter((d): d is RecordDoc => Boolean(d)), [docs]);

  const valueMaps = useMemo(
    () =>
      records.map(
        (r) =>
          new Map(comparableValues(catalog, r.data, r.companion).map((v) => [v.path, v] as const)),
      ),
    [records, catalog],
  );

  const rows = useMemo(() => {
    const order = new Map(Object.keys(catalog.entries).map((k, i) => [k, i]));
    const paths = new Map<string, string>();
    for (const m of valueMaps)
      for (const v of m.values()) if (!paths.has(v.path)) paths.set(v.path, v.key);
    return [...paths.entries()]
      .map(([path, key]) => ({ path, key, entry: catalog.entries[key] }))
      .filter((r): r is { path: string; key: string; entry: CatalogEntry } =>
        Boolean(r.entry && r.entry.name !== "displayName"),
      )
      .map((r) => ({ ...r, section: sectionOf(catalog, r.key) }))
      .sort(
        (a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0) || a.path.localeCompare(b.path),
      );
  }, [catalog, valueMaps]);

  if (!docs) return <p className="muted">Loading…</p>;
  if (records.length === 0) return <p className="muted">Failed to load data. Reload the page.</p>;

  // Sections in the order their first field appears.
  const sectionOrder: string[] = [];
  for (const r of rows) if (!sectionOrder.includes(r.section)) sectionOrder.push(r.section);

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
      <div className="table-wrap" style={{ maxHeight: "70vh", overflow: "auto" }}>
        <table className="table matrix">
          <thead>
            <tr>
              <th scope="col">Field</th>
              {records.map((r) => (
                <th scope="col" key={r.slug}>
                  <span className="swatch" style={{ background: color(r.slug), marginRight: 6 }} />
                  <RefLink href={recordHref(series, r.slug)}>{r.name}</RefLink>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sectionOrder.map((section) => {
              const body = rows
                .filter((r) => r.section === section)
                .map(({ path, entry }) => {
                  const texts = records.map((rec, i) => {
                    const v = valueMaps[i]?.get(path);
                    return v === undefined
                      ? null
                      : plainValue(entry, v.value, {
                          enums: catalog.enums,
                          system,
                          links: rec.links,
                        });
                  });
                  const differs = new Set(texts).size > 1;
                  if (diffOnly && !differs) return null;
                  const label = pathLabel(entry, path);
                  return (
                    <tr key={path} className={differs && records.length > 1 ? "diff" : undefined}>
                      <th scope="row">
                        {entry.comparable ? (
                          <button
                            type="button"
                            className="sort-btn"
                            onClick={() => onPickField(path)}
                          >
                            {label}
                          </button>
                        ) : (
                          label
                        )}
                      </th>
                      {records.map((r, i) => (
                        <td
                          key={r.slug}
                          className="num"
                          tabIndex={texts[i] === null ? undefined : 0}
                          data-field={path}
                          data-field-label={label}
                          data-field-comparable={entry.comparable ? "true" : "false"}
                          data-field-text={texts[i] ?? ""}
                          data-series={series}
                          data-record={r.slug}
                          data-record-name={r.name}
                          style={{ textAlign: "left", maxWidth: 320 }}
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
                    {section}
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
