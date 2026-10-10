"use client";

import { Fragment, type ReactNode, useMemo, useState } from "react";
import { getPath } from "@/lib/catalog";
import {
  isAngleSectors,
  machAxis,
  plainValue,
  rangeText,
  sectorRanges,
  type ValueContext,
} from "@/lib/format-field";
import { isGeoField, LOCATION_ID } from "@/lib/geo";
import { isRecord } from "@/lib/json";
import { enumDisplay } from "@/lib/names";
import { complexFields, type RangeList as RangeListSpec, tableColumns } from "@/lib/record-tables";
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
  ScalarValue,
  tipIdFor,
} from "../field-view";
import { LazyLineChart as LineChart } from "../lazy-line-chart";
import { openLua, useLuaAvailable } from "../lua-button";

export type RenderCtx = {
  catalog: SeriesCatalog;
  vctx: ValueContext;
  fctx: FieldContext;
};

/** A Mach-indexed coefficient: small chart, exact values on demand. */
export function MachCard({
  entry,
  path,
  values,
  step,
  ctx,
}: {
  entry: CatalogEntry;
  path: string;
  values: number[];
  step: number;
  ctx: RenderCtx;
}) {
  const axis = machAxis(values.length, step);
  const tipId = tipIdFor(ctx.fctx, path);
  const shown = values.map((v) => convertNumber(v, entry, ctx.vctx.system));
  const axisLabel = entry.axis?.kind === "sampled" ? entry.axis.label : "x";
  return (
    <figure
      className="mach-card"
      tabIndex={0}
      aria-describedby={tipId}
      aria-keyshortcuts="Shift+F10 C"
      style={{ margin: 0 }}
      {...fieldDataAttrs(entry, path, values, ctx.fctx, ctx.vctx)}
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
        series={[
          {
            id: ctx.fctx.slug,
            label: ctx.fctx.recordName,
            color: "var(--s1)",
            values: shown,
            step,
          },
        ]}
      />
      <details className="exact">
        <summary>
          Table ({values.length} samples, Mach step {formatNumber(step)})
        </summary>
        <div className="exact-scroll">
          <table className="exact-table">
            <thead>
              <tr>
                <th scope="col">{axisLabel}</th>
                <th scope="col">{entry.dcsKey ?? entry.label}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((v, i) => (
                <tr key={axis[i]}>
                  <td>{formatNumber(axis[i] ?? 0)}</td>
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
  if (entry.role === "provenance") return <ProvenanceValue value={values} />;
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
  if (!available || !path.startsWith("_G/")) return null;
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
  rowLabel = "row",
  colLabel = "col",
  vctx,
  caption,
}: {
  entry: CatalogEntry;
  grid: number[][];
  rowAxis?: { entry: CatalogEntry; values: number[] } | undefined;
  colAxis?: { entry: CatalogEntry; values: number[] } | undefined;
  rowLabel?: string;
  colLabel?: string;
  vctx: ValueContext;
  caption?: string;
}) {
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
          {caption ?? entry.label}: rows by {rowLabel}, columns by {colLabel}
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
// Arrays of records

/** Short inline rendering of an array value inside a table cell or card. */
function InlineArray({
  entry,
  value,
  ctx,
  prefix,
}: {
  entry: CatalogEntry;
  value: unknown[];
  ctx: RenderCtx;
  prefix: string;
}) {
  if (entry.kind === "strings") return <StringList entry={entry} values={value} vctx={ctx.vctx} />;
  if (entry.kind === "numbers")
    return <NumberList entry={entry} values={value as number[]} vctx={ctx.vctx} />;
  if (entry.kind === "records" && entry.recordType) {
    const sub = `${prefix}[]`;
    const fieldsOf = ctx.catalog.types[entry.recordType]?.fields ?? [];
    const at = (f: string) => ctx.catalog.entries[`${sub}.${f}`];
    const link = entry.linkField;
    const linkEntry = link ? at(link) : undefined;
    // A list of records with a link (station accepts: clsid): the links, plus rule counts.
    if (link && linkEntry) {
      const labelOf = (f: string) => at(f)?.label.toLowerCase() ?? f;
      return (
        <LimitedList
          className="link-list"
          items={value.map((item, i) => {
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
    // One list field per item (gun belts): one numbered line of links per item.
    const single = fieldsOf.length === 1 ? at(fieldsOf[0] ?? "") : undefined;
    if (single?.kind === "strings" && fieldsOf[0]) {
      const field = fieldsOf[0];
      return (
        <ol className="inline-rows">
          {value.map((item, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: positional
            <li key={i}>
              <StringList
                entry={single}
                values={
                  isRecord(item) && Array.isArray(item[field]) ? (item[field] as unknown[]) : []
                }
                vctx={ctx.vctx}
              />
            </li>
          ))}
        </ol>
      );
    }
    return (
      <RecordsTable
        entry={entry}
        rows={value}
        ctx={ctx}
        prefix={prefix}
        concretePrefix={prefix}
        compact
      />
    );
  }
  if (isAngleSectors(entry, value))
    return <SectorTable entry={entry} path={prefix} sectors={value} ctx={ctx} />;
  return <JsonValue value={value} />;
}

/**
 * An array of records: a table when every field fits a cell, else one card per item.
 * Keyed arrays (motor stages) give each cell its concrete path for compare; tables with
 * an axis column (`mach`) get a chart of the other columns.
 */
export function RecordsTable({
  entry,
  rows,
  ctx,
  prefix,
  concretePrefix,
  compact,
}: {
  entry: CatalogEntry;
  rows: unknown[];
  ctx: RenderCtx;
  /** Catalog path of the array (`stations`, `flight.motorStages`). */
  prefix: string;
  concretePrefix: string;
  compact?: boolean;
}) {
  const typeName = entry.recordType ?? "";
  const itemPrefix = entry.keyField ? `${prefix}.*` : `${prefix}[]`;
  const columns = tableColumns(ctx.catalog, typeName, itemPrefix).filter((c) =>
    rows.some((r) => isRecord(r) && getPath(r, c.path) !== undefined),
  );
  const complex = complexFields(ctx.catalog, typeName, itemPrefix).filter((f) =>
    rows.some((r) => isRecord(r) && r[f.name] !== undefined && r[f.name] !== null),
  );
  const items = rows.filter(isRecord);
  // Cards when some item carries a long list or nested records; else complex fields fit cells.
  const heavy = complex.some((f) =>
    items.some((r) => {
      const v = r[f.name];
      return (
        Array.isArray(v) &&
        (v.length > 6 || f.entry.kind === "records" || f.entry.kind === "matrix")
      );
    }),
  );
  const inline = compact || !heavy;
  const [showAll, setShowAll] = useState(false);
  const cardLimit = 12;

  if (complex.length && !inline) {
    const shown = showAll ? items : items.slice(0, cardLimit);
    return (
      <div className="record-cards">
        {shown.map((row, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: positional
          <div className="record-card" key={i}>
            <dl className="record-card-head">
              {columns
                .filter((c) => getPath(row, c.path) !== undefined)
                .map((c) => (
                  <div key={c.path}>
                    <dt>{c.entry.label}</dt>
                    <dd>
                      <ScalarValue entry={c.entry} value={getPath(row, c.path)} vctx={ctx.vctx} />
                    </dd>
                  </div>
                ))}
            </dl>
            {complex.map(({ name, entry: e }) => {
              const v = row[name];
              if (v === undefined || v === null || (Array.isArray(v) && v.length === 0))
                return null;
              return (
                <div className="record-card-field" key={name}>
                  <span className="record-card-label">
                    {e.label}
                    {Array.isArray(v) ? <span className="muted"> ({v.length})</span> : null}
                  </span>
                  {Array.isArray(v) ? (
                    <InlineArray entry={e} value={v} ctx={ctx} prefix={`${itemPrefix}.${name}`} />
                  ) : (
                    <JsonValue value={v} />
                  )}
                </div>
              );
            })}
          </div>
        ))}
        {items.length > shown.length ? (
          <button type="button" className="btn btn-compact" onClick={() => setShowAll(true)}>
            Show all {items.length}
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="table-wrap"
      style={rows.length > 25 ? { maxHeight: 520, overflow: "auto" } : undefined}
    >
      <table className={compact ? "mini-table" : "table data-table"}>
        {/* A heading with the table's label sits right above: the caption is for screen readers. */}
        {compact ? null : <caption className="visually-hidden">{entry.label}</caption>}
        <thead>
          <tr>
            {entry.keyField ? <th scope="col">{entry.keyField}</th> : null}
            {columns
              .filter((c) => c.path !== entry.keyField)
              .map((c) => (
                <th
                  scope="col"
                  key={c.path}
                  className={c.entry.kind === "number" ? "num" : undefined}
                  title={c.entry.description}
                >
                  {unitLabel(c.entry.label, c.entry, ctx.vctx.system)}
                </th>
              ))}
            {inline
              ? complex.map((f) => (
                  <th scope="col" key={f.name}>
                    {f.entry.label}
                  </th>
                ))
              : null}
          </tr>
        </thead>
        <tbody>
          {items.map((row, i) => {
            const key = entry.keyField ? String(row[entry.keyField]) : null;
            return (
              <tr key={key ?? i}>
                {key !== null ? (
                  <th scope="row">
                    <span className="chip">{key}</span>
                  </th>
                ) : null}
                {columns
                  .filter((c) => c.path !== entry.keyField)
                  .map((c) => {
                    const v = getPath(row, c.path);
                    const concrete = key !== null ? `${concretePrefix}.${key}.${c.path}` : null;
                    const attrs =
                      concrete && v !== undefined
                        ? {
                            ...fieldDataAttrs(
                              c.entry,
                              concrete,
                              v,
                              ctx.fctx,
                              ctx.vctx,
                              `${c.entry.label} (${key})`,
                            ),
                            tabIndex: 0,
                          }
                        : {};
                    return (
                      <td
                        key={c.path}
                        className={c.entry.kind === "number" ? "num" : undefined}
                        {...attrs}
                      >
                        {v === undefined ? (
                          <span className="muted">—</span>
                        ) : c.entry.kind === "number" && typeof v === "number" ? (
                          ctx.fctx.hasLocation && isGeoField(c.entry.name) ? (
                            // Runway thresholds, stand positions: on the Location figure.
                            <a className="geo-link" href={`#${LOCATION_ID}`}>
                              {formatNumber(convertNumber(v, c.entry, ctx.vctx.system))}
                            </a>
                          ) : (
                            formatNumber(convertNumber(v, c.entry, ctx.vctx.system))
                          )
                        ) : c.entry.kind === "enum" ? (
                          enumDisplay(c.entry, v, ctx.vctx.enums).label
                        ) : c.entry.role === "provenance" && typeof v === "string" ? (
                          <ProvenanceValue value={v} inline />
                        ) : (
                          <ScalarValue entry={c.entry} value={v} vctx={ctx.vctx} />
                        )}
                      </td>
                    );
                  })}
                {inline
                  ? complex.map((f) => (
                      <td key={f.name}>
                        {Array.isArray(row[f.name]) ? (
                          <InlineArray
                            entry={f.entry}
                            value={row[f.name] as unknown[]}
                            ctx={ctx}
                            prefix={`${itemPrefix}.${f.name}`}
                          />
                        ) : null}
                      </td>
                    ))
                  : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** A table with a numeric axis column (`mach`): chart one or more columns over it. */
export function AxisTableChart({
  entry,
  rows,
  ctx,
  prefix,
}: {
  entry: CatalogEntry;
  rows: unknown[];
  ctx: RenderCtx;
  prefix: string;
}) {
  const axis = entry.axis?.kind === "column" ? entry.axis : null;
  const { catalog, vctx, fctx } = ctx;
  const columns = useMemo(
    () =>
      tableColumns(catalog, entry.recordType ?? "", `${prefix}[]`).filter(
        (c) => c.parts.length === 1 && c.path !== axis?.field && c.entry.kind === "number",
      ),
    [catalog, entry.recordType, prefix, axis],
  );
  const items = useMemo(() => rows.filter(isRecord), [rows]);
  const [picked, setPicked] = useState<string | null>(columns[0]?.path ?? null);
  const column = columns.find((c) => c.path === picked) ?? columns[0];
  const columnPath = column?.path;
  const series = useMemo(() => {
    const entryOf = columns.find((c) => c.path === columnPath)?.entry;
    if (!axis || !columnPath || !entryOf) return [];
    const pts = items
      .map((r) => [r[axis.field], r[columnPath]] as const)
      .filter(
        (p): p is readonly [number, number] => typeof p[0] === "number" && typeof p[1] === "number",
      );
    return [
      {
        id: fctx.slug,
        label: fctx.recordName,
        color: SERIES_COLORS[0] ?? "var(--s1)",
        x: pts.map((p) => p[0]),
        values: pts.map((p) => convertNumber(p[1], entryOf, vctx.system)),
      },
    ];
  }, [items, axis, columns, columnPath, fctx, vctx.system]);
  if (!column || !axis) return null;
  const path = `${prefix}[].${column.path}`;
  const xy = { x: series[0]?.x ?? [], y: items.map((r) => r[column.path]) };
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
          {...fieldDataAttrs(
            ctx.catalog.entries[path] ?? column.entry,
            path,
            xy,
            ctx.fctx,
            ctx.vctx,
            `${column.entry.label} by ${axis.field}`,
          )}
        >
          <MoreButton label={`${column.entry.label} by ${axis.field}`} />
        </span>
      </div>
      <LineChart
        title={`${column.entry.label} by ${axis.field}`}
        xLabel={axis.label}
        yUnit={displayUnit(column.entry, ctx.vctx.system)}
        series={series}
        height={260}
      />
    </div>
  );
}
