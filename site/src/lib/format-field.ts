import { enumDisplay } from "./names";
import type { CatalogEntry, EnumInfo, LinkTarget, RecordDoc, SeriesCatalog } from "./types";
import {
  convertValue,
  displayUnit,
  formatNumber,
  formatPlain,
  formatStored,
  type UnitSystem,
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
  for (const series of Object.keys(links)) {
    const hit = links[series]?.[key];
    if (hit === undefined) continue;
    const [slug, name] = typeof hit === "string" ? [key, hit] : (hit as LinkTarget);
    if (entry.ref.includes(series) || entry.ref.some((r) => r.startsWith(series))) {
      return { series, slug, name };
    }
  }
  // Companion targets resolve to their parent series.
  for (const series of Object.keys(links)) {
    const hit = links[series]?.[key];
    if (hit === undefined) continue;
    const [slug, name] = typeof hit === "string" ? [key, hit] : (hit as LinkTarget);
    return { series, slug, name };
  }
  return null;
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
 * Traverse sectors (`Entity.AngleSector[]`, DCS `WS[i].angles`): per sector
 * `[azimuth from, azimuth to, elevation min, elevation max]`, or azimuth only.
 */
export function isAngleSectors(entry: CatalogEntry, value: unknown): value is number[][] {
  return (
    entry.type.replace(/\[\]$/, "") === "Entity.AngleSector" &&
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
  const unit = displayUnit(entry.unit, system, entry.name);
  const angle = (v: number) =>
    withUnit(formatNumber(convertValue(v, entry.unit, system, entry.name).value), unit);
  const range = (a: number | undefined, b: number | undefined) =>
    a === undefined || b === undefined ? null : `${angle(a)} to ${angle(b)}`;
  return sectors.map(([az0, az1, el0, el1]) => ({
    azimuth: range(az0, az1) ?? "",
    elevation: range(el0, el1),
  }));
}

/** The `minX` / `maxX` number pair of a record type (`minMHz`, `maxMHz`), if it has one. */
export function rangePair(
  catalog: Pick<SeriesCatalog, "types" | "entries">,
  typeName: string,
  prefix: string,
): { min: CatalogEntry; max: CatalogEntry } | null {
  const fields = catalog.types[typeName]?.fields ?? [];
  for (const name of fields) {
    const rest = /^min([A-Z].*)$/.exec(name)?.[1];
    if (!rest || !fields.includes(`max${rest}`)) continue;
    const min = catalog.entries[`${prefix}.${name}`];
    const max = catalog.entries[`${prefix}.max${rest}`];
    if (min?.kind === "number" && max?.kind === "number" && min.unit === max.unit) {
      return { min, max };
    }
  }
  return null;
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
  const fmt = (e: CatalogEntry, v: number) =>
    formatNumber(convertValue(v, e.unit, system, e.name).value);
  const text = `${fmt(pair.min, a)}–${fmt(pair.max, b)}`;
  return unit ? withUnit(text, displayUnit(pair.min.unit, system, pair.min.name)) : text;
}

/** Several ranges with one unit: "100–150, 220–390 MHz". */
export function coverageText(
  pair: { min: CatalogEntry; max: CatalogEntry },
  rows: Record<string, unknown>[],
  system: UnitSystem,
): string | null {
  const parts = rows.map((r) => rangeText(pair, r, system, false)).filter((t) => t !== null);
  if (!parts.length) return null;
  return withUnit(parts.join(", "), displayUnit(pair.min.unit, system, pair.min.name));
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
  if (typeof value === "number") return formatPlain(value, entry.unit, ctx.system, entry.name);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  if (isXY(value)) {
    const ys = value.y.map((v) => convertValue(v, entry.unit, ctx.system, entry.name).value);
    return `${ys.length} points, ${formatNumber(Math.min(...ys))} to ${formatNumber(Math.max(...ys))}`;
  }
  if (entry.kind === "numbers") {
    const nums = numbers(value).map(
      (v) => convertValue(v, entry.unit, ctx.system, entry.name).value,
    );
    if (entry.axis === "mach" || nums.length > 8) {
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
  return formatStored(value, entry.unit, system, entry.name);
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
    return convertValue(value, entry.unit, ctx.system, entry.name).value;
  }
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "string") {
    if (entry.kind === "enum") return enumDisplay(entry, value, ctx.enums).label;
    if (entry.kind === "ref") return resolveLink(entry, value, ctx.links)?.name ?? value;
    return value;
  }
  if (isXY(value))
    return Math.max(
      ...value.y.map((v) => convertValue(v, entry.unit, ctx.system, entry.name).value),
    );
  if (entry.kind === "numbers") {
    const nums = numbers(value);
    return nums.length
      ? Math.max(...nums.map((v) => convertValue(v, entry.unit, ctx.system, entry.name).value))
      : null;
  }
  if (Array.isArray(value)) return value.length;
  return null;
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
