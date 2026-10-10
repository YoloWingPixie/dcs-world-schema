"use client";

import { Fragment, type ReactNode, useMemo, useState } from "react";
import { getPath } from "@/lib/catalog";
import {
  axisCurve,
  plainValue,
  rangeText,
  sectorRanges,
  type ValueContext,
} from "@/lib/format-field";
import { isRecord } from "@/lib/json";
import { isDumpPath } from "@/lib/lua/source";
import { type Curve, curveOf, type RangeList as RangeListSpec } from "@/lib/record-tables";
import type { CatalogEntry, SeriesCatalog } from "@/lib/types";
import { convertNumber, displayUnit, formatNumber, unitLabel, withUnit } from "@/lib/units";
import { SERIES_COLORS } from "../chart-colors";
import {
  Description,
  type FieldContext,
  FieldRow,
  fieldDataAttrs,
  MoreButton,
  RecordLink,
  tipIdFor,
} from "../field-view";
import { LazyLineChart as LineChart } from "../lazy-line-chart";
import { openLua, useLuaAvailable } from "../lua-button";

export type RenderCtx = {
  catalog: SeriesCatalog;
  vctx: ValueContext;
  fctx: FieldContext;
};

/** A Mach-sampled coefficient (lib/record-tables `samplesOf`): small chart, exact values on demand. */
export function MachCard({
  entry,
  path,
  samples,
  ctx,
}: {
  entry: CatalogEntry;
  path: string;
  samples: Curve;
  ctx: RenderCtx;
}) {
  const tipId = tipIdFor(ctx.fctx, path);
  // Mach has no unit: the x axis stays as sampled.
  const { y: shown, xLabel } = axisCurve(samples, entry, undefined, ctx.vctx.system);
  // The samples start at 0, so the second is the step.
  const step = samples.x[1] === undefined ? "" : `, ${xLabel} step ${formatNumber(samples.x[1])}`;
  return (
    <figure
      className="mach-card"
      tabIndex={0}
      aria-describedby={tipId}
      aria-keyshortcuts="Shift+F10 C"
      {...fieldDataAttrs(entry, path, samples, ctx.fctx, ctx.vctx)}
    >
      <figcaption className="mach-card-head">
        <span className="mach-card-title">
          {entry.label} {entry.dcsKey ? <span className="field-key">{entry.dcsKey}</span> : null}
        </span>
        <MoreButton label={entry.label} />
      </figcaption>
      <LineChart
        compact
        title={entry.label}
        xLabel={xLabel}
        series={[
          {
            id: ctx.fctx.slug,
            label: ctx.fctx.recordName,
            color: SERIES_COLORS[0],
            values: shown,
            x: samples.x,
          },
        ]}
      />
      <details className="exact">
        <summary>{`Table (${shown.length} samples${step})`}</summary>
        <div className="exact-scroll">
          <table className="exact-table">
            <thead>
              <tr>
                <th scope="col">{xLabel}</th>
                <th scope="col">{entry.dcsKey ?? entry.label}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((v, i) => (
                <tr key={samples.x[i]}>
                  <td>{formatNumber(samples.x[i] ?? 0)}</td>
                  <td>{formatNumber(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <Description entry={entry} id={tipId} />
    </figure>
  );
}

const LIST_LIMIT = 30;

/** A wrapping list that shows the first LIST_LIMIT items until asked for all. */
function LimitedList({ className, items }: { className: string; items: ReactNode[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, LIST_LIMIT);
  return (
    <ul className={className}>
      {shown}
      {items.length > shown.length ? (
        <li className="list-more">
          <button type="button" className="btn btn-compact btn-quiet" onClick={() => setAll(true)}>
            Show all {items.length}
          </button>
        </li>
      ) : null}
    </ul>
  );
}

/** number[] without an axis: the values in order. */
export function NumberList({
  entry,
  values,
  vctx,
}: {
  entry: CatalogEntry;
  values: number[];
  vctx: ValueContext;
}) {
  const unit = displayUnit(entry, vctx.system);
  return (
    <div className="field-value value-list">
      {values.map((v, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: positional values
        <span key={i}>{formatNumber(convertNumber(v, entry, vctx.system))}</span>
      ))}
      {unit ? <span className="unit">{unit}</span> : null}
    </div>
  );
}

/** One ruled row per range: "100–150 MHz . . . . AM". */
export function RangeList({
  rows,
  ctx,
  list,
}: {
  rows: unknown[];
  ctx: RenderCtx;
  list: RangeListSpec;
}) {
  return (
    <div className="fields range-list">
      {rows.filter(isRecord).map((row, i) => {
        const label = rangeText(list.pair, row, ctx.vctx.system) ?? "—";
        const [first, ...rest] = list.others.filter((c) => getPath(row, c.path) !== undefined);
        const entry = first?.entry ?? list.pair.min;
        return (
          <FieldRow
            // biome-ignore lint/suspicious/noArrayIndexKey: ranges are positional
            key={i}
            entry={entry}
            path={first?.key ?? entry.path}
            value={first ? getPath(row, first.path) : undefined}
            ctx={ctx.fctx}
            vctx={ctx.vctx}
            label={label}
            after={rest.map((c) => (
              <span className="secondary" key={c.path}>
                {c.entry.label}: {plainValue(c.entry, getPath(row, c.path), ctx.vctx)}
              </span>
            ))}
          />
        );
      })}
    </div>
  );
}

/** Traverse sectors in degrees, one row each; the stored radians are in the field menu. */
export function SectorTable({
  entry,
  path,
  sectors,
  ctx,
}: {
  entry: CatalogEntry;
  path: string;
  sectors: number[][];
  ctx: RenderCtx;
}) {
  const ranges = sectorRanges(entry, sectors, ctx.vctx.system);
  const elevation = ranges.some((r) => r.elevation);
  const raw = sectors.map((s) => withUnit(s.map((v) => formatNumber(v)).join(", "), entry.unit));
  return (
    <div tabIndex={0} {...fieldDataAttrs(entry, path, sectors, ctx.fctx, ctx.vctx)}>
      <table className="mini-table">
        <thead>
          <tr>
            <th scope="col">Sector</th>
            <th scope="col">Azimuth</th>
            {elevation ? <th scope="col">Elevation</th> : null}
          </tr>
        </thead>
        <tbody>
          {ranges.map((r, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: positional sectors
            <tr key={i} title={raw[i]}>
              <td>{i + 1}</td>
              <td>{r.azimuth}</td>
              {elevation ? <td>{r.elevation ?? "—"}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StringList({
  entry,
  values,
  vctx,
}: {
  entry: CatalogEntry;
  values: unknown[];
  vctx: ValueContext;
}) {
  if (entry.ref) {
    return (
      <LimitedList
        className="link-list"
        items={values.map((v, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: lists may repeat (gun belts)
          <li key={`${String(v)}-${i}`}>
            <RecordLink entry={entry} raw={v} vctx={vctx} />
          </li>
        ))}
      />
    );
  }
  if (entry.codeField) return <>{plainValue(entry, values, vctx)}</>;
  return (
    <ul className="tag-list">
      {values.map((v, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: lists may repeat
        <li key={i}>{String(v)}</li>
      ))}
    </ul>
  );
}

/**
 * A `provenance` field's dump paths (`sourcePaths`, a block's `sourcePath`), each with its
 * "View Lua" link: a list, or `inline` for one path in a table cell.
 */
export function ProvenanceValue({ value, inline = false }: { value: unknown; inline?: boolean }) {
  const paths = (Array.isArray(value) ? value : [value]).map(String);
  if (inline) {
    return (
      <>
        {paths.map((p) => (
          <Fragment key={p}>
            {p}
            <LuaLink path={p} />
          </Fragment>
        ))}
      </>
    );
  }
  return (
    <ul className="path-list">
      {paths.map((p) => (
        <li key={p}>
          {p}
          <LuaLink path={p} />
        </li>
      ))}
    </ul>
  );
}

/** "View Lua" beside a `_G` dump path or block `sourcePath`: the record's Lua drawer, there. */
export function LuaLink({ path }: { path: string }) {
  const available = useLuaAvailable();
  if (!available || !isDumpPath(path)) return null;
  return (
    <button
      type="button"
      className="lua-link"
      onClick={() => openLua(path)}
      aria-label={`View Lua: ${path}`}
    >
      View Lua
    </button>
  );
}

/** number[][]: a shaded table. */
export function HeatGrid({
  entry,
  grid,
  rowAxis,
  colAxis,
  vctx,
}: {
  entry: CatalogEntry;
  grid: number[][];
  /** The row axis: its entry (labelled for one value: "Altitude") and values. */
  rowAxis?: { entry: CatalogEntry; values: number[] } | undefined;
  colAxis?: { entry: CatalogEntry; values: number[] } | undefined;
  vctx: ValueContext;
}) {
  const rowLabel = rowAxis?.entry.label ?? "row";
  const colLabel = colAxis?.entry.label ?? "col";
  const cells = grid.flat().filter((v) => typeof v === "number");
  const max = Math.max(...cells);
  const min = Math.min(...cells);
  const shade = (v: number) => {
    const t = max === min ? 0.5 : (v - min) / (max - min);
    return `rgb(var(--heat) / ${(0.06 + t * 0.42).toFixed(3)})`;
  };
  const unit = displayUnit(entry, vctx.system);
  const axisText = (axis: { entry: CatalogEntry; values: number[] } | undefined, i: number) =>
    axis?.values[i] !== undefined
      ? formatNumber(convertNumber(axis.values[i] as number, axis.entry, vctx.system))
      : String(i + 1);
  const rowUnit = rowAxis ? displayUnit(rowAxis.entry, vctx.system) : null;
  const colUnit = colAxis ? displayUnit(colAxis.entry, vctx.system) : null;
  const columns = Math.max(...grid.map((r) => r.length));
  return (
    <div className="table-wrap">
      <table className="launch-grid">
        <caption className="visually-hidden">
          {entry.label}: rows by {rowLabel}, columns by {colLabel}
          {unit ? `, values in ${unit}` : ""}.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="corner">
              {unitLabel(rowLabel, rowAxis?.entry, vctx.system)} \{" "}
              {unitLabel(colLabel, colAxis?.entry, vctx.system)}
            </th>
            {Array.from({ length: columns }, (_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: positional headers
              <th scope="col" key={i}>
                {axisText(colAxis, i)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.map((row, r) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows are positional
            <tr key={r}>
              <th scope="row">{axisText(rowAxis, r)}</th>
              {row.map((c, i) => {
                const v = convertNumber(c, entry, vctx.system);
                const label = `${rowLabel} ${withUnit(axisText(rowAxis, r), rowUnit)}, ${colLabel} ${withUnit(axisText(colAxis, i), colUnit)}: ${withUnit(formatNumber(v), unit)}`;
                return (
                  // biome-ignore lint/suspicious/noArrayIndexKey: cells are positional
                  <td key={i} style={{ background: shade(c) }} title={label} aria-label={label}>
                    {formatNumber(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** `any` or nested arrays: compact JSON. */
export function JsonValue({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 1);
  if (text.length < 120) return <code className="json">{JSON.stringify(value)}</code>;
  return (
    <details className="exact">
      <summary>Raw value ({text.length.toLocaleString("en-US")} characters)</summary>
      <pre className="json-block">{text}</pre>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Arrays of records read as lists (record-group `blockFor` picks them)

/**
 * Items read by their link (station accepts: `clsid`, catalog `linkField`), each with the
 * sizes of its other lists and its counts (`countFields`).
 */
export function LinkedItems({
  entry,
  items,
  ctx,
}: {
  entry: CatalogEntry;
  items: unknown[];
  ctx: RenderCtx;
}) {
  const link = entry.linkField ?? "";
  const fieldsOf = ctx.catalog.types[entry.recordType ?? ""]?.fields ?? [];
  const at = (f: string) => ctx.catalog.entries[`${entry.itemPath}.${f}`];
  const linkEntry = at(link);
  if (!linkEntry) return null;
  const labelOf = (f: string) => at(f)?.label.toLowerCase() ?? f;
  return (
    <LimitedList
      className="link-list"
      items={items.map((item, i) => {
        const rec = isRecord(item) ? item : {};
        const filled = (f: string) => Array.isArray(rec[f]) && rec[f].length > 0;
        // Without its link (a payload firing gun ammo, no weapon): the item's lists of
        // links, else its own name, else its position.
        const missing = rec[link] === undefined || rec[link] === null;
        const links = missing ? entry.linkListFields?.find(filled) : undefined;
        const linksEntry = links ? at(links) : undefined;
        const named = missing
          ? entry.titleFields?.find((f) => typeof rec[f] === "string" && rec[f])
          : undefined;
        const extras = [
          ...fieldsOf
            .filter((f) => f !== link && f !== links && filled(f))
            .map((f) => `${(rec[f] as unknown[]).length} ${labelOf(f)}`),
          ...(entry.countFields ?? [])
            .filter((k) => typeof rec[k] === "number")
            .map((k) => `${labelOf(k)} ${rec[k]}`),
        ];
        const lead = !missing ? (
          <RecordLink entry={linkEntry} raw={rec[link]} vctx={ctx.vctx} />
        ) : links && linksEntry ? (
          (rec[links] as unknown[]).map((v, j) => (
            <span key={String(v)}>
              {j ? ", " : ""}
              <RecordLink entry={linksEntry} raw={v} vctx={ctx.vctx} />
            </span>
          ))
        ) : named ? (
          String(rec[named])
        ) : (
          `${entry.label} ${i + 1}`
        );
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: positional
          <li key={i}>
            {lead}
            {extras.length ? <span className="muted"> ({extras.join(", ")})</span> : null}
          </li>
        );
      })}
    />
  );
}

/** Items holding one list each (gun belts, catalog `layout: "list-per-item"`): one numbered line per item. */
export function ListPerItem({
  entry,
  items,
  ctx,
}: {
  entry: CatalogEntry;
  items: unknown[];
  ctx: RenderCtx;
}) {
  const field = ctx.catalog.types[entry.recordType ?? ""]?.fields[0] ?? "";
  const list = ctx.catalog.entries[`${entry.itemPath}.${field}`];
  if (!list) return null;
  return (
    <ol className="inline-rows">
      {items.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: positional
        <li key={i}>
          <StringList
            entry={list}
            values={isRecord(item) && Array.isArray(item[field]) ? (item[field] as unknown[]) : []}
            vctx={ctx.vctx}
          />
        </li>
      ))}
    </ol>
  );
}

const NO_CURVE: Curve = { x: [], y: [] };

/** A table with a numeric axis column (`mach`): chart one of its curves (catalog `axis.columns`) over it. */
export function AxisTableChart({
  entry,
  rows,
  ctx,
}: {
  entry: CatalogEntry;
  rows: unknown[];
  ctx: RenderCtx;
}) {
  const axis = entry.axis?.kind === "column" ? entry.axis : null;
  const { catalog, vctx, fctx } = ctx;
  const columns = useMemo(
    () =>
      (axis?.columns ?? []).flatMap((path) => {
        const e = catalog.entries[path];
        return e ? [{ path, entry: e }] : [];
      }),
    [catalog, axis],
  );
  const [picked, setPicked] = useState<string | null>(columns[0]?.path ?? null);
  const column = columns.find((c) => c.path === picked) ?? columns[0];
  // The column's curve, as the record's compare value of it (lib/catalog.ts `valuesAt`).
  const xy = useMemo(
    () => (axis && column ? curveOf(rows, axis.field, column.entry.name) : null) ?? NO_CURVE,
    [rows, axis, column],
  );
  const chart = useMemo(
    () =>
      column && axis ? axisCurve(xy, column.entry, catalog.entries[axis.path], vctx.system) : null,
    [xy, column, axis, catalog, vctx.system],
  );
  const series = useMemo(
    () =>
      chart
        ? [
            {
              id: fctx.slug,
              label: fctx.recordName,
              color: SERIES_COLORS[0] ?? "var(--s1)",
              x: chart.x,
              values: chart.y,
            },
          ]
        : [],
    [chart, fctx],
  );
  if (!column || !axis || !chart) return null;
  const title = `${column.entry.label} by ${axis.label}`;
  return (
    <div className="axis-chart">
      <div className="axis-chart-head">
        {/* biome-ignore lint/a11y/useSemanticElements: a toolbar of toggle buttons */}
        <div className="seg" role="group" aria-label="Column to chart">
          {columns.map((c) => (
            <button
              type="button"
              key={c.path}
              className="seg-btn"
              aria-pressed={c.path === column.path}
              onClick={() => setPicked(c.path)}
            >
              {c.entry.label}
            </button>
          ))}
        </div>
        <span
          className="axis-chart-compare"
          tabIndex={0}
          {...fieldDataAttrs(column.entry, column.path, xy, ctx.fctx, ctx.vctx, title)}
        >
          <MoreButton label={title} />
        </span>
      </div>
      <LineChart
        title={title}
        xLabel={chart.xLabel}
        yUnit={displayUnit(column.entry, ctx.vctx.system)}
        series={series}
        height={260}
      />
    </div>
  );
}
