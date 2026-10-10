/**
 * How an array of records reads, from the catalog alone: its table columns, the fields too
 * rich for a cell, and its list of ranges (radio segments). Shared by the catalog build
 * (lib/catalog.ts marks `ranges` lists from the columns), the record renderers
 * (components/record) and the placement pass (lib/placement.ts). Each answer is computed
 * once per catalog.
 */
import { isRecord, type Json } from "./json";
import { perObject } from "./once";
import { type CatalogEntry, SCALAR_KINDS, type SeriesCatalog } from "./types";

export type Column = { path: string; key: string; entry: CatalogEntry };

type Shapes = Pick<SeriesCatalog, "types" | "entries">;

/** Answers computed once per catalog and key. */
const cache = perObject<Shapes>();

/** The entries of a record type's fields at catalog path `prefix` ("" at the root), in schema order. */
export function recordFields(catalog: Shapes, typeName: string, prefix: string): CatalogEntry[] {
  return (catalog.types[typeName]?.fields ?? [])
    .map((name) => catalog.entries[prefix ? `${prefix}.${name}` : name])
    .filter((e): e is CatalogEntry => e !== undefined);
}

/**
 * `items` without each code whose constant name is among them too (`modulation` beside
 * `modulationName`): the name stands in its place. `field` gives an item's path (relative to
 * the same record) and entry.
 */
export function withoutNamedCodes<T>(
  items: readonly T[],
  field: (item: T) => { path: string; entry: CatalogEntry },
): T[] {
  const named = new Set(
    items.flatMap((item) => {
      const { path, entry } = field(item);
      if (!entry.codeField) return [];
      const dot = path.lastIndexOf(".");
      return [dot < 0 ? entry.codeField : `${path.slice(0, dot)}.${entry.codeField}`];
    }),
  );
  return items.filter((item) => !named.has(field(item).path));
}

/** Scalar columns of a record type, one level of nested records flattened. */
export function tableColumns(catalog: Shapes, typeName: string, prefix: string): Column[] {
  return cache.cachedBy(catalog, `columns\n${typeName}\n${prefix}`, () => {
    const out: Column[] = [];
    for (const entry of recordFields(catalog, typeName, prefix)) {
      if (SCALAR_KINDS.has(entry.kind)) out.push({ path: entry.name, key: entry.path, entry });
      else if (entry.kind === "record" && entry.recordType) {
        for (const sub of recordFields(catalog, entry.recordType, entry.path)) {
          if (SCALAR_KINDS.has(sub.kind)) {
            out.push({ path: `${entry.name}.${sub.name}`, key: sub.path, entry: sub });
          }
        }
      }
    }
    return withoutNamedCodes(out, (c) => c);
  });
}

/** Complex (non-column) fields of a record type: lists, nested tables. */
export function complexFields(
  catalog: Shapes,
  typeName: string,
  prefix: string,
): Array<{ name: string; entry: CatalogEntry }> {
  return cache.cachedBy(catalog, `complex\n${typeName}\n${prefix}`, () => {
    const fields = recordFields(catalog, typeName, prefix).map((entry) => ({
      name: entry.name,
      entry,
    }));
    return withoutNamedCodes(fields, (f) => ({ path: f.name, entry: f.entry })).filter(
      (f) => !SCALAR_KINDS.has(f.entry.kind) && f.entry.kind !== "record",
    );
  });
}

export type RangeList = {
  pair: { min: CatalogEntry; max: CatalogEntry };
  others: Column[];
};

/** The range pair and other columns of a `ranges` list (catalog `layout`), else null. */
export function rangeListOf(catalog: Shapes, entry: CatalogEntry): RangeList | null {
  if (entry.layout !== "ranges" || !entry.rangePair || !entry.recordType) return null;
  const { rangePair, recordType, path, itemPath } = entry;
  if (!itemPath) return null;
  return cache.cachedBy(catalog, `ranges\n${path}`, () => {
    const min = catalog.entries[rangePair.min];
    const max = catalog.entries[rangePair.max];
    if (!min || !max) return null;
    const others = tableColumns(catalog, recordType, itemPath).filter(
      (c) => c.entry !== min && c.entry !== max,
    );
    return { pair: { min, max }, others };
  });
}

/** A table's curve over its axis column, or a Mach-sampled list's over Mach (catalog `axis`). */
export type Curve = { x: number[]; y: number[] };

/** One envelope item's grid over its two axes (catalog `axis.kind: "surface"`). */
export type Surface = { rows: number[]; cols: number[]; z: number[][] };

/**
 * The curve of `column` over the `axis` column of a table's rows: the rows holding a number
 * in both, in order; null when none does. A record's value of the column (lib/catalog.ts
 * `valuesAt`) and its chart (components/record/blocks.tsx `AxisTableChart`).
 */
export function curveOf(rows: unknown, axis: string, column: string): Curve | null {
  if (!Array.isArray(rows)) return null;
  const x: number[] = [];
  const y: number[] = [];
  for (const row of rows) {
    if (!isRecord(row)) continue;
    const xv = row[axis];
    const yv = row[column];
    if (typeof xv === "number" && typeof yv === "number") {
      x.push(xv);
      y.push(yv);
    }
  }
  return x.length ? { x, y } : null;
}

/** `length` samples from 0 at `step`, as DCS samples a Mach-indexed list (rounded to 4 places). */
function machAxis(length: number, step: number): number[] {
  return Array.from({ length }, (_, i) => Number((i * step).toFixed(4)));
}

/**
 * The curve of a Mach-sampled list (catalog `axis.kind: "sampled"`) in the record holding it:
 * its numbers over `machAxis` at the holder's step field, else the axis' fallback step; null
 * for any other entry, or when the holder has no numbers there. A record's value of the list
 * (lib/catalog.ts `valuesAt`) and its chart (components/record/blocks.tsx `MachCard`).
 */
export function samplesOf(holder: Json, entry: CatalogEntry): Curve | null {
  const axis = entry.axis;
  const list = holder[entry.name];
  if (axis?.kind !== "sampled" || !Array.isArray(list)) return null;
  const y = list.filter((v): v is number => typeof v === "number");
  if (!y.length) return null;
  const step = holder[axis.step.field];
  return { x: machAxis(y.length, typeof step === "number" ? step : axis.step.fallback), y };
}

/**
 * The surfaces of the grid `column` in a list of envelope items: one per item holding it,
 * with the item's `rows` and `cols` axes. A record's value of the grid (lib/catalog.ts
 * `valuesAt`) and of its envelope blocks (components/record/envelope.tsx).
 */
export function surfacesOf(
  items: unknown,
  axis: { rows: string; cols: string },
  column: string,
): Surface[] {
  if (!Array.isArray(items)) return [];
  return items
    .filter(isRecord)
    .filter((it) => Array.isArray(it[column]))
    .map((it) => ({
      rows: it[axis.rows] as number[],
      cols: it[axis.cols] as number[],
      z: it[column] as number[][],
    }));
}

/** The surfaces of a compare value (`flight.launchEnvelopes[].maxRangeM`). */
export function asSurfaces(value: unknown): Surface[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (s): s is Surface =>
      isRecord(s) && Array.isArray(s.rows) && Array.isArray(s.cols) && Array.isArray(s.z),
  );
}

/**
 * Row `i` of a surface over its column axis (as many points as both hold); null when the
 * surface has no row `i`. A record's envelope lines (components/record/envelope.tsx) and
 * compare's (`surfaceRow`).
 */
export function surfaceLine(surface: Surface, i: number): Curve | null {
  const z = surface.z[i];
  if (!z) return null;
  const n = Math.min(z.length, surface.cols.length);
  return { x: surface.cols.slice(0, n), y: z.slice(0, n) };
}

/** The line of the first surface with a row nearest to `row` (an altitude, within 1%), else null. */
export function surfaceRow(surfaces: Surface[], row: number): Curve | null {
  for (const s of surfaces) {
    const i = s.rows.findIndex((r) => Math.abs(r - row) <= Math.max(1, Math.abs(row) * 0.01));
    if (i >= 0) return surfaceLine(s, i) ?? { x: [], y: [] };
  }
  return null;
}
