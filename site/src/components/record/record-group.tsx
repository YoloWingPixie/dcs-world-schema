"use client";

import { type ReactNode, useState } from "react";
import { isRecord, type Json } from "@/lib/json";
import { rangeListOf, withoutNamedCodes } from "@/lib/record-tables";
import { type CatalogEntry, SCALAR_KINDS } from "@/lib/types";
import { FieldRow } from "../field-view";
import {
  AxisTableChart,
  HeatGrid,
  JsonValue,
  MachCard,
  NumberList,
  ProvenanceValue,
  RangeList,
  RecordsTable,
  type RenderCtx,
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
  concretePrefix,
}: {
  entry: CatalogEntry;
  rows: unknown[];
  ctx: RenderCtx;
  prefix: string;
  concretePrefix: string;
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
            prefix={prefix}
          />
        ))}
      </div>
    );
  }
  const ranges = rangeListOf(ctx.catalog, entry);
  if (ranges) return <RangeList rows={rows} ctx={ctx} list={ranges} />;
  const table = (
    <RecordsTable
      entry={entry}
      rows={rows}
      ctx={ctx}
      prefix={prefix}
      concretePrefix={concretePrefix}
    />
  );
  if (entry.layout !== "axis-table") return table;
  return (
    <>
      <AxisTableChart entry={entry} rows={rows} ctx={ctx} prefix={prefix} />
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
 * The fields of one record value: scalars as rows, Mach tables as chart cards, lists and
 * grids full width, nested records as sub-groups and arrays of records as tables.
 */
export function RecordGroup({
  typeName,
  prefix,
  concretePrefix,
  value,
  ctx,
  depth,
  only,
}: {
  typeName: string;
  /** Catalog path of this value (`aero`, `flight.motorStages.*`), "" at the root. */
  prefix: string;
  /** Concrete path (`flight.motorStages.march`). */
  concretePrefix: string;
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
  const concrete = (name: string) => (concretePrefix ? `${concretePrefix}.${name}` : name);

  const scalars: ReactNode[] = [];
  const wide: ReactNode[] = [];
  const charts: ReactNode[] = [];
  const nested: ReactNode[] = [];

  for (const { name, key, value: v, entry } of fields) {
    const path = concrete(name);
    if (entry.role === "provenance") {
      wide.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          body={<ProvenanceValue value={v} />}
        />,
      );
    } else if (
      SCALAR_KINDS.has(entry.kind) ||
      (entry.kind === "any" && typeof v !== "object") ||
      (entry.kind === "strings" && entry.codeField)
    ) {
      scalars.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          notes={fieldNotes(entry, value)}
        />,
      );
    } else if (entry.kind === "numbers" && entry.axis?.kind === "sampled" && Array.isArray(v)) {
      const step = value[entry.axis.step.field];
      charts.push(
        <MachCard
          key={key}
          entry={entry}
          path={path}
          values={v as number[]}
          step={typeof step === "number" ? step : entry.axis.step.fallback}
          ctx={ctx}
        />,
      );
    } else if (entry.kind === "numbers" && Array.isArray(v)) {
      wide.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          wide={v.length > INLINE_NUMBERS}
          body={<NumberList entry={entry} values={v as number[]} vctx={ctx.vctx} />}
        />,
      );
    } else if (entry.kind === "strings" && Array.isArray(v)) {
      wide.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          label={`${entry.label} (${v.length})`}
          body={<StringList entry={entry} values={v} vctx={ctx.vctx} />}
        />,
      );
    } else if (entry.kind === "grid" && Array.isArray(v)) {
      wide.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          body={<HeatGrid entry={entry} grid={v as number[][]} vctx={ctx.vctx} />}
        />,
      );
    } else if (entry.kind === "record" && isRecord(v) && entry.recordType) {
      const Heading = depth === 0 ? "h3" : "h4";
      nested.push(
        <div className={`subgroup depth-${depth}`} key={key}>
          <Heading
            className="subgroup-title"
            title={ctx.catalog.types[entry.recordType]?.description}
          >
            {entry.label}
          </Heading>
          <RecordGroup
            typeName={entry.recordType}
            prefix={key}
            concretePrefix={path}
            value={v}
            ctx={ctx}
            depth={depth + 1}
          />
        </div>,
      );
    } else if (entry.kind === "records" && Array.isArray(v)) {
      const Heading = depth === 0 ? "h3" : "h4";
      nested.push(
        <div className={`subgroup depth-${depth}`} key={key}>
          <Heading className="subgroup-title" title={entry.description}>
            {entry.label} <span className="muted">({v.length})</span>
          </Heading>
          <RecordsBlock entry={entry} rows={v} ctx={ctx} prefix={key} concretePrefix={path} />
        </div>,
      );
    } else {
      wide.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          body={<JsonValue value={v} />}
        />,
      );
    }
  }

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
