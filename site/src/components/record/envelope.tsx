"use client";

import { useState } from "react";
import { surfaceAxes } from "@/lib/format-field";
import { surfaceLine, surfacesOf } from "@/lib/record-tables";
import type { CatalogEntry } from "@/lib/types";
import { convertNumber, displayUnit, formatPlain, unitLabel } from "@/lib/units";
import { SERIES_COLORS } from "../chart-colors";
import { fieldDataAttrs, MoreButton } from "../field-view";
import { LazyLineChart as LineChart } from "../lazy-line-chart";
import { HeatGrid, type RenderCtx } from "./blocks";

/**
 * One launch envelope (an `Entity.WeaponLaunchEnvelope`-shaped record: two number[] axes
 * and number[][] grids): heatmap of the chosen grid, and the grid by column axis with one
 * line per picked row (altitude). Its compare value is the grid's in every item, as
 * the record's value of the grid (lib/catalog.ts `valuesAt`).
 */
export function EnvelopeBlock({
  entry,
  items,
  item,
  index,
  ctx,
}: {
  entry: CatalogEntry;
  /** Every item of the envelope list. */
  items: unknown[];
  item: Record<string, unknown>;
  index: number;
  ctx: RenderCtx;
}) {
  const total = items.length;
  const { catalog, vctx } = ctx;
  const surface = entry.axis?.kind === "surface" ? entry.axis : null;
  // The grids this item holds, and its two axes labelled for one value ("Altitude").
  const grids = (surface?.columns ?? []).flatMap((path) => {
    const e = catalog.entries[path];
    return e && Array.isArray(item[e.name]) ? [e] : [];
  });
  const axes = surfaceAxes(catalog, surface ?? undefined);
  const rowEntry = axes?.rows;
  const colEntry = axes?.cols;
  const [gridPath, setGridPath] = useState(grids[0]?.path ?? "");
  const gridEntry = grids.find((g) => g.path === gridPath);
  // The chosen grid over the item's axes, as compare reads it (lib/record-tables `surfacesOf`).
  const grid = surface && gridEntry ? surfacesOf([item], surface, gridEntry.name)[0] : undefined;
  const rows = grid?.rows ?? [];
  const cols = grid?.cols ?? [];
  const [picked, setPicked] = useState<number[]>(() =>
    [0, Math.floor(rows.length / 2), rows.length - 1].filter(
      (v, i, a) => v >= 0 && a.indexOf(v) === i,
    ),
  );

  const zUnit = gridEntry ? displayUnit(gridEntry, vctx.system) : null;

  const series = picked
    .flatMap((r) => {
      const line = grid ? surfaceLine(grid, r) : null;
      return line ? [{ r, line }] : [];
    })
    .map(({ r, line }, i) => ({
      id: `row-${r}`,
      label: formatPlain(rows[r] ?? 0, rowEntry, vctx.system),
      color: SERIES_COLORS[i % SERIES_COLORS.length] ?? "var(--s1)",
      x: line.x.map((c) => convertNumber(c, colEntry, vctx.system)),
      values: line.y.map((v) => convertNumber(v, gridEntry, vctx.system)),
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
            surface ? surfacesOf(items, surface, gridEntry.name) : [],
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
            grid={grid?.z ?? []}
            rowAxis={{ entry: rowEntry, values: rows }}
            colAxis={{ entry: colEntry, values: cols }}
            vctx={vctx}
          />
        </details>
      </div>
    </div>
  );
}
