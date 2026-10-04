import { enumDisplay } from "./names";
import type { CatalogEntry, EnumInfo, LinkTarget, RecordDoc } from "./types";
import { convertValue, formatNumber, formatPlain, type UnitSystem } from "./units";

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

/** Short plain-text rendering, for copying, compare tables and tooltips. */
export function plainValue(entry: CatalogEntry, value: unknown, ctx: ValueContext): string {
  if (value === undefined || value === null) return "";
  if (entry.kind === "enum") {
    const d = enumDisplay(entry, value, ctx.enums);
    return d.label === d.raw ? d.label : `${d.label} (${d.raw})`;
  }
  if (entry.kind === "ref") return resolveLink(entry, value, ctx.links)?.name ?? String(value);
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

/** The stored (metric) form, when the display converts: "161.48 kg". */
export function storedValue(entry: CatalogEntry, value: unknown): string | null {
  if (typeof value !== "number" || !entry.unit) return null;
  return formatPlain(value, entry.unit, "metric");
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
