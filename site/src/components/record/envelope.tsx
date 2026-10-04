"use client";

import { useState } from "react";
import { isRecord } from "@/lib/catalog";
import type { CatalogEntry } from "@/lib/types";
import { convertValue, displayUnit, formatNumber } from "@/lib/units";
import { fieldDataAttrs, MoreButton } from "../field-view";
import { LineChart, SERIES_COLORS } from "../line-chart";
import { HeatGrid, type RenderCtx } from "./blocks";

export type Surface = { rows: number[]; cols: number[]; z: number[][] };

/** The envelope surfaces of a compare value (`flight.launchEnvelopes[].maxRangeM`). */
export function asSurfaces(value: unknown): Surface[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (s): s is Surface =>
      isRecord(s) && Array.isArray(s.rows) && Array.isArray(s.cols) && Array.isArray(s.z),
  );
}

/** Rows of a surface nearest to `row` (an altitude), or null when none is within 1%. */
export function surfaceRow(surfaces: Surface[], row: number): { x: number[]; y: number[] } | null {
  for (const s of surfaces) {
    const i = s.rows.findIndex((r) => Math.abs(r - row) <= Math.max(1, Math.abs(row) * 0.01));
    if (i >= 0) {
      const z = s.z[i] ?? [];
      const n = Math.min(z.length, s.cols.length);
      return { x: s.cols.slice(0, n), y: z.slice(0, n) };
    }
  }
  return null;
}

/**
 * One launch envelope (an `Entity.WeaponLaunchEnvelope`-shaped record: two number[] axes
 * and number[][] grids): heatmap of the chosen grid, and the grid by column axis with one
 * line per picked row (altitude).
 */
export function EnvelopeBlock({
  entry,
  item,
  index,
  total = 1,
  ctx,
  prefix,
}: {
  entry: CatalogEntry;
  item: Record<string, unknown>;
  index: number;
  total?: number;
  ctx: RenderCtx;
  /** Catalog path of the array (`flight.launchEnvelopes`). */
  prefix: string;
}) {
  const { catalog, vctx } = ctx;
  const fields = catalog.types[entry.recordType ?? ""]?.fields ?? [];
  const at = (name: string) => catalog.entries[`${prefix}[].${name}`];
  const axes = fields.filter((f) => at(f)?.kind === "numbers");
  const grids = fields.filter((f) => at(f)?.kind === "grid" && Array.isArray(item[f]));
  const [rowName, colName] = axes as [string, string];
  const rows = (item[rowName] as number[] | undefined) ?? [];
  const cols = (item[colName] as number[] | undefined) ?? [];
  const singular = (e: CatalogEntry | undefined) =>
    e ? { ...e, label: e.label.replace(/s$/, "") } : undefined;
  const rowEntry = singular(at(rowName));
  const colEntry = singular(at(colName));
  const [gridName, setGridName] = useState(grids[0] ?? "");
  const gridEntry = at(gridName);
  const grid = (item[gridName] as number[][] | undefined) ?? [];
  const [picked, setPicked] = useState<number[]>(() =>
    [0, Math.floor(rows.length / 2), rows.length - 1].filter(
      (v, i, a) => v >= 0 && a.indexOf(v) === i,
    ),
  );

  const conv = (e: CatalogEntry | undefined, v: number) =>
    e ? convertValue(v, e.unit, vctx.system, e.name).value : v;
  const rowUnit = rowEntry ? displayUnit(rowEntry.unit, vctx.system, rowEntry.name) : null;
  const colUnit = colEntry ? displayUnit(colEntry.unit, vctx.system, colEntry.name) : null;
  const zUnit = gridEntry ? displayUnit(gridEntry.unit, vctx.system, gridEntry.name) : null;

  const series = picked
    .filter((r) => grid[r])
    .map((r, i) => ({
      id: `row-${r}`,
      label: `${formatNumber(conv(rowEntry, rows[r] ?? 0))}${rowUnit ? ` ${rowUnit}` : ""}`,
      color: SERIES_COLORS[i % SERIES_COLORS.length] ?? "var(--s1)",
      x: cols.map((c) => conv(colEntry, c)).slice(0, grid[r]?.length ?? 0),
      values: (grid[r] ?? []).map((v) => conv(gridEntry, v)),
    }));

  if (!rowEntry || !colEntry || !gridEntry || grids.length === 0) return null;
  const comparePath = `${prefix}[].${gridName}`;
  const compareEntry = catalog.entries[comparePath] ?? gridEntry;

  return (
    <div className="envelope">
      <div className="envelope-head">
        <h4>
          {grids.map((g) => at(g)?.label ?? g).join(", ")}{" "}
          <span className="muted">
            {total > 1 ? `envelope ${index + 1} of ${total}, ` : ""}
            {rows.length} {rowEntry.label.toLowerCase()}s × {cols.length}{" "}
            {colEntry.label.toLowerCase()}s
          </span>
        </h4>
        {grids.length > 1 ? (
          // biome-ignore lint/a11y/useSemanticElements: a toolbar of toggle buttons
          <div className="seg" role="group" aria-label="Table">
            {grids.map((g) => (
              <button
                type="button"
                key={g}
                className="seg-btn"
                aria-pressed={g === gridName}
                onClick={() => setGridName(g)}
              >
                {at(g)?.label ?? g}
              </button>
            ))}
          </div>
        ) : null}
        <span
          className="axis-chart-compare"
          tabIndex={0}
          {...fieldDataAttrs(
            compareEntry,
            comparePath,
            [{ rows, cols, z: grid }],
            ctx.fctx,
            vctx,
            gridEntry.label,
          )}
        >
          <MoreButton label={gridEntry.label} />
        </span>
      </div>
      <div className="envelope-body">
        <div>
          <p className="chart-caption">
            {gridEntry.label} by {colEntry.label.toLowerCase()}
            {zUnit ? ` (${zUnit})` : ""}, one line per {rowEntry.label.toLowerCase()}
          </p>
          {/* biome-ignore lint/a11y/useSemanticElements: toggle chips */}
          <div className="seg seg-wrap" role="group" aria-label={`${rowEntry.label} lines`}>
            {rows.map((r, i) => (
              <button
                type="button"
                // biome-ignore lint/suspicious/noArrayIndexKey: rows are positional
                key={i}
                className="seg-btn"
                aria-pressed={picked.includes(i)}
                onClick={() =>
                  setPicked((p) =>
                    p.includes(i) ? p.filter((x) => x !== i) : [...p, i].sort((a, b) => a - b),
                  )
                }
              >
                {formatNumber(conv(rowEntry, r))}
                {rowUnit ? ` ${rowUnit}` : ""}
              </button>
            ))}
          </div>
          {series.length ? (
            <LineChart
              title={`${gridEntry.label} by ${colEntry.label}`}
              xLabel={`${colEntry.label}${colUnit ? ` (${colUnit})` : ""}`}
              yUnit={zUnit}
              series={series}
              height={280}
            />
          ) : (
            <p className="muted">Pick at least one {rowEntry.label.toLowerCase()}.</p>
          )}
        </div>
        <details className="exact" open>
          <summary>Heatmap and exact values</summary>
          <HeatGrid
            entry={gridEntry}
            grid={grid}
            rowAxis={{ entry: rowEntry, values: rows }}
            colAxis={{ entry: colEntry, values: cols }}
            rowLabel={rowEntry.label}
            colLabel={colEntry.label}
            vctx={vctx}
          />
        </details>
      </div>
    </div>
  );
}

/** Whether a records entry is envelope-shaped. */
export function isEnvelope(entry: CatalogEntry, ctx: RenderCtx, prefix: string): boolean {
  const fields = ctx.catalog.types[entry.recordType ?? ""]?.fields ?? [];
  const kinds = fields.map((f) => ctx.catalog.entries[`${prefix}[].${f}`]?.kind);
  return kinds.filter((k) => k === "numbers").length >= 2 && kinds.includes("grid");
}

export const envelopeItems = (rows: unknown[]) => rows.filter(isRecord);
