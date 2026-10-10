"use client";

import { type ReactNode, useState } from "react";
import { getPath } from "@/lib/catalog";
import { isAngleSectors } from "@/lib/format-field";
import { isGeoField, LOCATION_ID } from "@/lib/geo";
import { isRecord, type Json } from "@/lib/json";
import { enumDisplay } from "@/lib/names";
import { complexFields, rangeListOf, tableColumns, withoutNamedCodes } from "@/lib/record-tables";
import { type CatalogEntry, SCALAR_KINDS } from "@/lib/types";
import { convertNumber, formatNumber, unitLabel } from "@/lib/units";
import { FieldRow, fieldDataAttrs, ScalarValue } from "../field-view";
import {
  AxisTableChart,
  HeatGrid,
  JsonValue,
  LinkedItems,
  ListPerItem,
  MachCard,
  NumberList,
  ProvenanceValue,
  RangeList,
  type RenderCtx,
  SectorTable,
  StringList,
} from "./blocks";
import { EnvelopeBlock } from "./envelope";

/** A number list this long or shorter reads on its label's line, like any other value. */
const INLINE_NUMBERS = 12;

const present = (v: unknown) =>
  v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0);

/**
 * Fields a record type lists, in schema order, that this value carries. A code with its
 * constant name beside it (`modulation`, `modulationName`) shows once, as the name.
 */
export function presentFields(ctx: RenderCtx, typeName: string, prefix: string, value: Json) {
  const fields = (ctx.catalog.types[typeName]?.fields ?? [])
    .map((name) => ({
      name,
      key: prefix ? `${prefix}.${name}` : name,
      value: value[name],
    }))
    .map((f) => ({ ...f, entry: ctx.catalog.entries[f.key] }))
    .filter((f): f is typeof f & { entry: CatalogEntry } => Boolean(f.entry) && present(f.value));
  return withoutNamedCodes(fields, (f) => ({ path: f.name, entry: f.entry }));
}

/** Tooltip lines of a field: the code its constant name stands for, its provenance. */
export function fieldNotes(entry: CatalogEntry, value: Json): string[] | undefined {
  const notes: string[] = [];
  const code = entry.codeField ? value[entry.codeField] : undefined;
  if (code !== undefined && code !== null) {
    notes.push(`Code ${Array.isArray(code) ? code.join(", ") : String(code)}`);
  }
  const source = isRecord(value._source) ? value._source[entry.name] : undefined;
  if (typeof source === "string") notes.push(`Source: ${source}`);
  return notes.length ? notes : undefined;
}

/** One array of records under its own heading: envelopes, axis tables, tables or cards. */
export function RecordsBlock({
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
  if (entry.layout === "envelope") {
    return (
      <div className="envelopes">
        {rows.filter(isRecord).map((item, i) => (
          <EnvelopeBlock
            // biome-ignore lint/suspicious/noArrayIndexKey: envelopes are positional
            key={i}
            entry={entry}
            item={item}
            index={i}
            total={rows.length}
            ctx={ctx}
          />
        ))}
      </div>
    );
  }
  const ranges = rangeListOf(ctx.catalog, entry);
  if (ranges) return <RangeList rows={rows} ctx={ctx} list={ranges} />;
  if (entry.layout === "list-per-item") {
    return <ListPerItem entry={entry} items={rows} ctx={ctx} path={prefix} />;
  }
  const table = <RecordsTable entry={entry} rows={rows} ctx={ctx} prefix={prefix} />;
  if (entry.layout !== "axis-table") return table;
  return (
    <>
      <AxisTableChart entry={entry} rows={rows} ctx={ctx} />
      <ExactTable rows={rows.length}>{table}</ExactTable>
    </>
  );
}

/** A table under a collapsed "Table (n rows)": rendered once first opened. */
function ExactTable({ rows, children }: { rows: number; children: ReactNode }) {
  const [opened, setOpened] = useState(false);
  return (
    <details className="exact" onToggle={(e) => e.currentTarget.open && setOpened(true)}>
      <summary>Table ({rows} rows)</summary>
      {opened ? children : null}
    </details>
  );
}

/**
 * Where a field's block goes in a record group: its line (`row`), full width (`wide`), the
 * chart cards (`chart`) or a sub-group under its own heading (`nested`).
 */
export type Block = { slot: "row" | "wide" | "chart" | "nested"; node: ReactNode };

/** Where a block renders: a record group's field, or an array in a table cell or record card. */
export type BlockPlace =
  | {
      in: "group";
      /** Catalog path of the field (`aero.massKg`); also the block's React key. */
      path: string;
      /** The record holding the field: a Mach list's step, a constant name's code. */
      holder: Json;
      depth: number;
    }
  | { in: "cell"; path: string };

/**
 * The one block dispatcher of record pages, by the catalog's kind, layout and role: a
 * group's fields as rows, chart cards, full-width lists and sub-groups; a cell's arrays as
 * short lists and compact tables. Arrays of records read by their link, or one line per
 * item, in a cell; under their own heading in a group (RecordsBlock).
 */
export function blockFor(
  entry: CatalogEntry,
  value: unknown,
  ctx: RenderCtx,
  at: BlockPlace,
): Block {
  const { path } = at;
  const group = at.in === "group" ? at : null;
  const list = Array.isArray(value) ? value : null;
  /** A group's row (or full-width row, with a body); a cell's bare body. */
  const field = (body: ReactNode, slot: "row" | "wide" = "wide", props: object = {}): Block =>
    group
      ? {
          slot,
          node: (
            <FieldRow
              key={path}
              entry={entry}
              path={path}
              value={value}
              ctx={ctx.fctx}
              vctx={ctx.vctx}
              {...(body === null ? {} : { body })}
              {...props}
            />
          ),
        }
      : { slot, node: body ?? <ScalarValue entry={entry} value={value} vctx={ctx.vctx} /> };

  if (entry.role === "provenance") return field(<ProvenanceValue value={value} />);
  if (
    SCALAR_KINDS.has(entry.kind) ||
    (entry.kind === "any" && typeof value !== "object") ||
    (entry.kind === "strings" && entry.codeField)
  ) {
    if (!group && list) return field(<StringList entry={entry} values={list} vctx={ctx.vctx} />);
    return field(null, "row", group ? { notes: fieldNotes(entry, group.holder) } : {});
  }
  if (entry.kind === "numbers" && list) {
    const numbers = list as number[];
    if (entry.axis?.kind === "sampled") {
      const step = group?.holder[entry.axis.step.field];
      return {
        slot: "chart",
        node: (
          <MachCard
            key={path}
            entry={entry}
            path={path}
            values={numbers}
            step={typeof step === "number" ? step : entry.axis.step.fallback}
            ctx={ctx}
          />
        ),
      };
    }
    return field(<NumberList entry={entry} values={numbers} vctx={ctx.vctx} />, "wide", {
      wide: list.length > INLINE_NUMBERS,
    });
  }
  if (entry.kind === "strings" && list) {
    return field(<StringList entry={entry} values={list} vctx={ctx.vctx} />, "wide", {
      label: `${entry.label} (${list.length})`,
    });
  }
  if (entry.kind === "grid" && list) {
    return field(<HeatGrid entry={entry} grid={list as number[][]} vctx={ctx.vctx} />);
  }
  if (isAngleSectors(entry, value)) {
    return field(<SectorTable entry={entry} path={path} sectors={value} ctx={ctx} />);
  }
  if (group && entry.kind === "record" && isRecord(value) && entry.recordType) {
    const Heading = group.depth === 0 ? "h3" : "h4";
    return {
      slot: "nested",
      node: (
        <div className={`subgroup depth-${group.depth}`} key={path}>
          <Heading
            className="subgroup-title"
            title={ctx.catalog.types[entry.recordType]?.description}
          >
            {entry.label}
          </Heading>
          <RecordGroup
            typeName={entry.recordType}
            prefix={path}
            value={value}
            ctx={ctx}
            depth={group.depth + 1}
          />
        </div>
      ),
    };
  }
  if (entry.kind === "records" && list) {
    if (group) {
      const Heading = group.depth === 0 ? "h3" : "h4";
      return {
        slot: "nested",
        node: (
          <div className={`subgroup depth-${group.depth}`} key={path}>
            <Heading className="subgroup-title" title={entry.description}>
              {entry.label} <span className="muted">({list.length})</span>
            </Heading>
            <RecordsBlock entry={entry} rows={list} ctx={ctx} prefix={path} />
          </div>
        ),
      };
    }
    if (entry.linkField) {
      return field(<LinkedItems entry={entry} items={list} ctx={ctx} path={path} />);
    }
    if (entry.layout === "list-per-item") {
      return field(<ListPerItem entry={entry} items={list} ctx={ctx} path={path} />);
    }
    if (entry.recordType) {
      return field(<RecordsTable entry={entry} rows={list} ctx={ctx} prefix={path} compact />);
    }
  }
  return field(<JsonValue value={value} />);
}

/** The fields of one record value, each where `blockFor` puts it. */
export function RecordGroup({
  typeName,
  prefix,
  value,
  ctx,
  depth,
  only,
}: {
  typeName: string;
  /** Catalog path of this value (`aero`, `flight.motorStages.*`), "" at the root. */
  prefix: string;
  value: Json;
  ctx: RenderCtx;
  depth: number;
  /** The fields to show, in this order (a record page's Overview: lib/placement.ts); all by default. */
  only?: readonly string[];
}) {
  let fields = presentFields(ctx, typeName, prefix, value);
  if (only) {
    const order = new Map(only.map((name, i) => [name, i]));
    fields = fields
      .filter((f) => order.has(f.name))
      .sort((a, b) => (order.get(a.name) ?? 0) - (order.get(b.name) ?? 0));
  }

  const slots: Record<Block["slot"], ReactNode[]> = { row: [], wide: [], chart: [], nested: [] };
  for (const { key, value: v, entry } of fields) {
    const block = blockFor(entry, v, ctx, { in: "group", path: key, holder: value, depth });
    slots[block.slot].push(block.node);
  }
  const { row: scalars, wide, chart: charts, nested } = slots;

  return (
    <>
      {scalars.length || wide.length ? (
        <div className="fields">
          {scalars}
          {wide}
        </div>
      ) : null}
      {charts.length ? <div className="mach-grid">{charts}</div> : null}
      {nested}
    </>
  );
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
  compact,
}: {
  entry: CatalogEntry;
  rows: unknown[];
  ctx: RenderCtx;
  /** Catalog path of the array (`stations`, `flight.motorStages`). */
  prefix: string;
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
                    blockFor(e, v, ctx, { in: "cell", path: `${itemPrefix}.${name}` }).node
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
                    const concrete = key !== null ? `${prefix}.${key}.${c.path}` : null;
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
                        {Array.isArray(row[f.name])
                          ? blockFor(f.entry, row[f.name], ctx, {
                              in: "cell",
                              path: `${itemPrefix}.${f.name}`,
                            }).node
                          : null}
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
