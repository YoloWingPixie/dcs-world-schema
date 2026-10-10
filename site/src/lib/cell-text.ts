import { plainValue, refName, type ValueContext } from "./format-field";
import { enumDisplay } from "./names";
import type { CatalogEntry } from "./types";
import { convertNumber, formatNumber } from "./units";

/**
 * Display text of a table cell (browse rows, compare subtitles): lib/format-field
 * `plainValue`, except that numbers leave their unit to the column head and enums show
 * their label alone. Without an entry (the catalog still loading), the raw value.
 */
export function cellText(
  entry: CatalogEntry | undefined,
  value: unknown,
  ctx: ValueContext,
): string {
  if (value === undefined || value === null) return "";
  if (!entry) {
    if (typeof value === "number") return formatNumber(value);
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (Array.isArray(value)) return value.map(String).join(", ");
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  }
  if (entry.kind === "enum") return enumDisplay(entry, value, ctx.enums).label;
  if (typeof value === "number") return formatNumber(convertNumber(value, entry, ctx.system));
  return plainValue(entry, value, ctx);
}

/**
 * The values a browse facet sees in one cell, as text: none for an empty cell, each item of
 * a list, a ref by its raw id (so same-named records stay apart and a shared filter outlives
 * a rename; `facetLabel` names it).
 */
export function facetValues(value: unknown): string[] {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value.map(String) : [String(value)];
}

/**
 * How a facet value (`facetValues`) reads: "Yes"/"No", an enum's label, a ref's record
 * name (from `ctx.links`, as `cellText`); without an entry, as written.
 */
export function facetLabel(
  entry: CatalogEntry | undefined,
  value: string,
  ctx: ValueContext,
): string {
  if (!entry) return value;
  if (entry.kind === "boolean") return value === "true" ? "Yes" : "No";
  if (entry.kind === "enum") {
    const raw = /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
    return enumDisplay(entry, raw, ctx.enums).label;
  }
  if (entry.ref) return refName(entry, value, ctx.links);
  return value;
}
