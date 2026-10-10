"use client";

import { useState } from "react";
import { isRecord } from "@/lib/json";
import type { CatalogEntry } from "@/lib/types";
import { convertNumber, displayUnit, formatPlain, unitLabel } from "@/lib/units";
import { SERIES_COLORS } from "../chart-colors";
import { fieldDataAttrs, MoreButton } from "../field-view";
import { LazyLineChart as LineChart } from "../lazy-line-chart";
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
}: {
  entry: CatalogEntry;
  item: Record<string, unknown>;
  index: number;
  total?: number;
  ctx: RenderCtx;
}) {
  const { catalog, vctx } = ctx;
  const surface = entry.axis?.kind === "surface" ? entry.axis : null;
  // The grids this item holds, and its two axes labelled for one value ("Altitude").
  const grids = (surface?.columns ?? []).flatMap((path) => {
    const e = catalog.entries[path];
    return e && Array.isArray(item[e.name]) ? [e] : [];
  });
  const axisEntry = (path: string | undefined, label: string | undefined) => {
    const e = path ? catalog.entries[path] : undefined;
    return e && label ? { ...e, label } : undefined;
  };
  const rowEntry = axisEntry(surface?.paths.rows, surface?.labels.rows);
  const colEntry = axisEntry(surface?.paths.cols, surface?.labels.cols);
  const rows = (item[surface?.rows ?? ""] as number[] | undefined) ?? [];
  const cols = (item[surface?.cols ?? ""] as number[] | undefined) ?? [];
  const [gridPath, setGridPath] = useState(grids[0]?.path ?? "");
  const gridEntry = grids.find((g) => g.path === gridPath);
  const grid = (gridEntry ? (item[gridEntry.name] as number[][]) : undefined) ?? [];
  const [picked, setPicked] = useState<number[]>(() =>
    [0, Math.floor(rows.length / 2), rows.length - 1].filter(
      (v, i, a) => v >= 0 && a.indexOf(v) === i,
    ),
  );

  const zUnit = gridEntry ? displayUnit(gridEntry, vctx.system) : null;

  const series = picked
    .filter((r) => grid[r])
    .map((r, i) => ({
      id: `row-${r}`,
      label: formatPlain(rows[r] ?? 0, rowEntry, vctx.system),
      color: SERIES_COLORS[i % SERIES_COLORS.length] ?? "var(--s1)",
      x: cols.map((c) => convertNumber(c, colEntry, vctx.system)).slice(0, grid[r]?.length ?? 0),
      values: (grid[r] ?? []).map((v) => convertNumber(v, gridEntry, vctx.system)),
    }));

  if (!rowEntry || !colEntry || !gridEntry) return null;

  return (
    <div className="envelope">
      <div className="envelope-head">
        <h4>
          {grids.map((g) => g.label).join(", ")}{" "}
          <span className="muted">
            {total > 1 ? `${index + 1} of ${total} · ` : ""}
            {rows.length} × {cols.length}
          </span>
        </h4>
        {grids.length > 1 ? (
          // biome-ignore lint/a11y/useSemanticElements: a toolbar of toggle buttons
          <div className="seg" role="group" aria-label="Table">
            {grids.map((g) => (
              <button
                type="button"
                key={g.path}
                className="seg-btn"
                aria-pressed={g === gridEntry}
                onClick={() => setGridPath(g.path)}
              >
                {g.label}
              </button>
            ))}
          </div>
        ) : null}
        <span
          className="axis-chart-compare"
          tabIndex={0}
          {...fieldDataAttrs(
            gridEntry,
            gridEntry.path,
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
                {formatPlain(r, rowEntry, vctx.system)}
              </button>
            ))}
          </div>
          {series.length ? (
            <LineChart
              title={`${gridEntry.label} by ${colEntry.label}`}
              xLabel={unitLabel(colEntry.label, colEntry, vctx.system)}
              yUnit={zUnit}
              series={series}
              height={280}
            />
          ) : (
            <p className="muted">No {rowEntry.label.toLowerCase()} selected.</p>
          )}
        </div>
        <details className="exact" open>
          <summary>Table</summary>
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
