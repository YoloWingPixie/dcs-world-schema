import { isRecord } from "./json";
import { enumDisplay } from "./names";
import { asSurfaces, type Curve } from "./record-tables";
import type { CatalogEntry, EnumInfo, LinkTarget, RecordDoc } from "./types";
import {
  convertNumber,
  displayUnit,
  formatNumber,
  formatPlain,
  formatStored,
  type UnitSystem,
  unitLabel,
  withUnit,
} from "./units";

export type ValueContext = {
  enums: Record<string, EnumInfo>;
  system: UnitSystem;
  links?: RecordDoc["links"];
};

export type ResolvedLink = { series: string; slug: string; name: string };

/** The record a ref value names, from the record's link table. */
export function resolveLink(
  entry: Pick<CatalogEntry, "ref">,
  raw: unknown,
  links: RecordDoc["links"] | undefined,
): ResolvedLink | null {
  if (!links || !entry.ref || (typeof raw !== "string" && typeof raw !== "number")) return null;
  const key = String(raw);
  // A companion target is its parent's (the catalog resolves refs so).
  for (const series of Object.keys(links)) {
    if (!entry.ref.includes(series)) continue;
    const hit = links[series]?.[key];
    if (hit === undefined) continue;
    const [slug, name] = typeof hit === "string" ? [key, hit] : (hit as LinkTarget);
    return { series, slug, name };
  }
  return null;
}

/**
 * An axis table column's curve as a chart draws it, in the display system: x through the
 * axis column's entry, y through the column's own, and the x label with its unit. Shared by
 * the record page's table chart and compare.
 */
export function axisCurve(
  curve: Curve,
  entry: CatalogEntry,
  axisEntry: CatalogEntry | undefined,
  system: UnitSystem,
): { x: number[]; y: number[]; xLabel: string } {
  const label = entry.axis?.kind === "column" ? entry.axis.label : "x";
  return {
    x: curve.x.map((v) => convertNumber(v, axisEntry, system)),
    y: curve.y.map((v) => convertNumber(v, entry, system)),
    xLabel: unitLabel(label, axisEntry, system),
  };
}

export function isXY(value: unknown): value is { x: number[]; y: number[] } {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { x?: unknown }).x) &&
    Array.isArray((value as { y?: unknown }).y)
  );
}

const numbers = (v: unknown): number[] =>
  Array.isArray(v) ? v.filter((x): x is number => typeof x === "number") : [];

/**
 * The cells of an envelope grid's compared value (catalog `compareAs: "surfaces"`, lib/
 * record-tables.ts `surfacesOf`), in the display system; null for any other value (one
 * item's grid on a record page).
 */
function surfaceCells(entry: CatalogEntry, value: unknown, system: UnitSystem) {
  const surfaces = entry.compareAs === "surfaces" ? asSurfaces(value) : [];
  if (!surfaces.length) return null;
  const cells = surfaces.flatMap((s) => numbers(s.z.flat()));
  return { count: surfaces.length, cells: cells.map((v) => convertNumber(v, entry, system)) };
}

/**
 * Traverse sectors (catalog `layout: "sectors"`, DCS `WS[i].angles`): per sector
 * `[azimuth from, azimuth to, elevation min, elevation max]`, or azimuth only.
 */
export function isAngleSectors(entry: CatalogEntry, value: unknown): value is number[][] {
  return (
    entry.layout === "sectors" &&
    Array.isArray(value) &&
    value.every(
      (s) =>
        Array.isArray(s) &&
        (s.length === 2 || s.length === 4) &&
        s.every((x) => typeof x === "number"),
    )
  );
}

export type SectorRange = { azimuth: string; elevation: string | null };

/** Each sector as display ranges, in DCS's order: "145° to -145°". */
export function sectorRanges(
  entry: CatalogEntry,
  sectors: number[][],
  system: UnitSystem,
): SectorRange[] {
  const angle = (v: number) => formatPlain(v, entry, system);
  const range = (a: number | undefined, b: number | undefined) =>
    a === undefined || b === undefined ? null : `${angle(a)} to ${angle(b)}`;
  return sectors.map(([az0, az1, el0, el1]) => ({
    azimuth: range(az0, az1) ?? "",
    elevation: range(el0, el1),
  }));
}

/** "100–150" (with `unit`: "100–150 MHz") of a row holding a range pair; null when either end is missing. */
export function rangeText(
  pair: { min: CatalogEntry; max: CatalogEntry },
  row: Record<string, unknown>,
  system: UnitSystem,
  unit = true,
): string | null {
  const [a, b] = [row[pair.min.name], row[pair.max.name]];
  if (typeof a !== "number" || typeof b !== "number") return null;
  const fmt = (e: CatalogEntry, v: number) => formatNumber(convertNumber(v, e, system));
  const text = `${fmt(pair.min, a)}–${fmt(pair.max, b)}`;
  return unit ? withUnit(text, displayUnit(pair.min, system)) : text;
}

/** Several ranges with one unit: "100–150, 220–390 MHz". */
export function coverageText(
  pair: { min: CatalogEntry; max: CatalogEntry },
  rows: Record<string, unknown>[],
  system: UnitSystem,
): string | null {
  const parts = rows.map((r) => rangeText(pair, r, system, false)).filter((t) => t !== null);
  if (!parts.length) return null;
  return withUnit(parts.join(", "), displayUnit(pair.min, system));
}

/** Short plain-text rendering, for copying, compare tables and tooltips. */
export function plainValue(entry: CatalogEntry, value: unknown, ctx: ValueContext): string {
  if (value === undefined || value === null) return "";
  if (entry.kind === "enum") {
    const d = enumDisplay(entry, value, ctx.enums);
    return d.rewrite ? `${d.label} (${d.raw})` : d.label;
  }
  if (entry.kind === "ref") return resolveLink(entry, value, ctx.links)?.name ?? String(value);
  if (entry.codeField && Array.isArray(value)) {
    return value.map((v) => enumDisplay(entry, v, ctx.enums).label).join(", ");
  }
  if (isAngleSectors(entry, value)) {
    return sectorRanges(entry, value, ctx.system)
      .map((r) => (r.elevation ? `azimuth ${r.azimuth}, elevation ${r.elevation}` : r.azimuth))
      .join("; ");
  }
  if (typeof value === "number") return formatPlain(value, entry, ctx.system);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  // A table column's compared curve (one cell of it is a number, above).
  if (entry.compareAs === "curve" && isXY(value)) {
    const ys = value.y.map((v) => convertNumber(v, entry, ctx.system));
    return `${ys.length} points, ${formatNumber(Math.min(...ys))} to ${formatNumber(Math.max(...ys))}`;
  }
  const surfaces = surfaceCells(entry, value, ctx.system);
  if (surfaces) {
    const { count, cells } = surfaces;
    const tables = `${count} ${count === 1 ? "table" : "tables"}`;
    return cells.length
      ? `${tables}, ${formatNumber(Math.min(...cells))} to ${formatNumber(Math.max(...cells))}`
      : tables;
  }
  if (entry.kind === "numbers") {
    const nums = numbers(value).map((v) => convertNumber(v, entry, ctx.system));
    if (entry.compareAs === "samples" || nums.length > 8) {
      return `${nums.length} values, ${formatNumber(Math.min(...nums))} to ${formatNumber(Math.max(...nums))}`;
    }
    return nums.map((n) => formatNumber(n)).join(", ");
  }
  if (Array.isArray(value)) {
    if (entry.ref)
      return value.map((v) => resolveLink(entry, v, ctx.links)?.name ?? String(v)).join(", ");
    if (value.every((v) => typeof v !== "object" || v === null)) {
      return value.map((v) => (typeof v === "number" ? formatNumber(v) : String(v))).join(", ");
    }
    return `${value.length} entries`;
  }
  return JSON.stringify(value);
}

/**
 * The stored form, when the display converts or relabels it: "161.48 kg", "0.3491 rad",
 * "[2.5307, …] rad", `MODULATION_AM` (with `enums`, for enum labels).
 */
export function storedValue(
  entry: CatalogEntry,
  value: unknown,
  system: UnitSystem,
  enums?: Record<string, EnumInfo>,
): string | null {
  if (enums && entry.kind === "enum" && (typeof value === "string" || typeof value === "number")) {
    const d = enumDisplay(entry, value, enums);
    return d.raw !== d.label ? d.raw : null;
  }
  if (isAngleSectors(entry, value)) {
    const rows = value.map((s) => `[${s.map((v) => formatNumber(v)).join(", ")}]`);
    return withUnit(rows.join(", "), entry.unit);
  }
  if (typeof value !== "number") return null;
  return formatStored(value, entry, system);
}

/** A value that sorts (and charts), in the display system. */
export function sortableValue(
  entry: CatalogEntry,
  value: unknown,
  ctx: ValueContext,
): number | string | null {
  if (value === undefined || value === null) return null;
  if (typeof value === "number") {
    if (entry.kind === "enum") return enumDisplay(entry, value, ctx.enums).label;
    return convertNumber(value, entry, ctx.system);
  }
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "string") {
    if (entry.kind === "enum") return enumDisplay(entry, value, ctx.enums).label;
    if (entry.kind === "ref") return resolveLink(entry, value, ctx.links)?.name ?? value;
    return value;
  }
  if (entry.compareAs === "curve" && isXY(value))
    return Math.max(...value.y.map((v) => convertNumber(v, entry, ctx.system)));
  // An envelope grid sorts by its largest cell.
  const surfaces = surfaceCells(entry, value, ctx.system);
  if (surfaces) return surfaces.cells.length ? Math.max(...surfaces.cells) : null;
  if (entry.kind === "numbers") {
    const nums = numbers(value);
    return nums.length ? Math.max(...nums.map((v) => convertNumber(v, entry, ctx.system))) : null;
  }
  if (Array.isArray(value)) return value.length;
  return null;
}

/** How a number reads in a compare key: as a value of `entry` displays (`formatPlain`). */
export const displayedNumber = (entry: CatalogEntry, system: UnitSystem) => (n: number) =>
  formatPlain(n, entry, system);

/**
 * A key two compared values share exactly when they hold the same data: deep (curves,
 * samples, lists, surfaces), object keys in order, and each number as `number` writes it
 * (`displayedNumber`: rounded and converted as the display shows it). Unlike `plainValue`,
 * which summarises a curve as its count and range, it tells apart any two values that differ.
 */
export function compareKey(value: unknown, number: (n: number) => string = formatNumber): string {
  return JSON.stringify(value ?? null, (_key, v: unknown) => {
    if (typeof v === "number") return `\u0000${number(v)}`;
    if (isRecord(v)) {
      return Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)));
    }
    return v;
  });
}

/** Whether compared values differ (a missing one, `undefined`, differs from any present one). */
export function valuesDiffer(values: readonly unknown[], number?: (n: number) => string): boolean {
  const keys = values.map((v) => (v === undefined ? undefined : compareKey(v, number)));
  return new Set(keys).size > 1;
}

export function machAxis(length: number, step: number): number[] {
  return Array.from({ length }, (_, i) => Number((i * step).toFixed(4)));
}

/** "Max range (flight model, boost stage)". */
export function pathLabel(entry: CatalogEntry, path: string): string {
  const stars = entry.path.split(".");
  const parts = path.split(".");
  const keys = stars.flatMap((seg, i) => (seg === "*" ? [parts[i]] : [])).filter(Boolean);
  return keys.length ? `${entry.label} (${keys.join(", ")})` : entry.label;
}
