import { plainValue, type ValueContext } from "./format-field";
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
