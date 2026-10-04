"use client";

import type { ReactNode } from "react";
import { isRecord } from "@/lib/catalog";
import type { CatalogEntry } from "@/lib/types";
import { FieldRow } from "../field-view";
import {
  AxisTableChart,
  HeatGrid,
  JsonValue,
  MachCard,
  NumberList,
  RecordsTable,
  type RenderCtx,
  SCALAR_KINDS,
  StringList,
} from "./blocks";
import { EnvelopeBlock, isEnvelope } from "./envelope";

type Json = Record<string, unknown>;

const present = (v: unknown) =>
  v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0);

/** Fields a record type lists, in schema order, that this value carries. */
export function presentFields(ctx: RenderCtx, typeName: string, prefix: string, value: Json) {
  return (ctx.catalog.types[typeName]?.fields ?? [])
    .map((name) => ({
      name,
      key: prefix ? `${prefix}.${name}` : name,
      value: value[name],
    }))
    .map((f) => ({ ...f, entry: ctx.catalog.entries[f.key] }))
    .filter((f): f is typeof f & { entry: CatalogEntry } => Boolean(f.entry) && present(f.value));
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
  if (isEnvelope(entry, ctx, prefix)) {
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
  return (
    <>
      {entry.axis && !entry.keyField ? (
        <AxisTableChart entry={entry} rows={rows} ctx={ctx} prefix={prefix} />
      ) : null}
      {entry.axis && !entry.keyField ? (
        <details className="exact">
          <summary>Exact rows ({rows.length})</summary>
          <RecordsTable
            entry={entry}
            rows={rows}
            ctx={ctx}
            prefix={prefix}
            concretePrefix={concretePrefix}
          />
        </details>
      ) : (
        <RecordsTable
          entry={entry}
          rows={rows}
          ctx={ctx}
          prefix={prefix}
          concretePrefix={concretePrefix}
        />
      )}
    </>
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
  skip,
}: {
  typeName: string;
  /** Catalog path of this value (`aero`, `flight.motorStages.*`), "" at the root. */
  prefix: string;
  /** Concrete path (`flight.motorStages.march`). */
  concretePrefix: string;
  value: Json;
  ctx: RenderCtx;
  depth: number;
  skip?: Set<string>;
}) {
  const fields = presentFields(ctx, typeName, prefix, value).filter((f) => !skip?.has(f.name));
  if (depth === 0 && !prefix) {
    // Friendly classifications first, raw codes and numbers after (stable otherwise).
    const rank = (e: CatalogEntry) =>
      e.kind === "enum" && typeof value[e.name] === "string" ? 0 : e.kind === "number" ? 2 : 1;
    fields.sort((a, b) => rank(a.entry) - rank(b.entry));
  }
  const concrete = (name: string) => (concretePrefix ? `${concretePrefix}.${name}` : name);
  const machStep = typeof value.machStep === "number" ? value.machStep : 0.2;

  const scalars: ReactNode[] = [];
  const wide: ReactNode[] = [];
  const charts: ReactNode[] = [];
  const nested: ReactNode[] = [];

  for (const { name, key, value: v, entry } of fields) {
    const path = concrete(name);
    if (/^sourcePaths?$/.test(name)) {
      wide.push(
        <FieldRow
          key={key}
          entry={entry}
          path={path}
          value={v}
          ctx={ctx.fctx}
          vctx={ctx.vctx}
          body={<StringList entry={entry} values={Array.isArray(v) ? v : [v]} vctx={ctx.vctx} />}
        />,
      );
    } else if (SCALAR_KINDS.has(entry.kind) || (entry.kind === "any" && typeof v !== "object")) {
      scalars.push(
        <FieldRow key={key} entry={entry} path={path} value={v} ctx={ctx.fctx} vctx={ctx.vctx} />,
      );
    } else if (entry.kind === "numbers" && entry.axis === "mach" && Array.isArray(v)) {
      charts.push(
        <MachCard
          key={key}
          entry={entry}
          path={path}
          values={v as number[]}
          step={machStep}
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
        <div
          className={`subgroup depth-${depth}`}
          key={key}
          id={depth === 0 ? undefined : undefined}
        >
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
