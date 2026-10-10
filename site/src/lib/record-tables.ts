/**
 * How an array of records reads, from the catalog alone: its table columns, the fields too
 * rich for a cell, and whether it is a list of ranges (radio segments). Shared by the record
 * renderers (components/record) and the placement pass (lib/placement.ts).
 */
import { rangePair } from "./format-field";
import { type CatalogEntry, SCALAR_KINDS, type SeriesCatalog } from "./types";

export type Column = { path: string; key: string; entry: CatalogEntry; parts: string[] };

/** Scalar columns of a record type, one level of nested records flattened. */
export function tableColumns(catalog: SeriesCatalog, typeName: string, prefix: string): Column[] {
  const out: Column[] = [];
  for (const name of catalog.types[typeName]?.fields ?? []) {
    const key = `${prefix}.${name}`;
    const entry = catalog.entries[key];
    if (!entry) continue;
    if (SCALAR_KINDS.has(entry.kind)) out.push({ path: name, key, entry, parts: [name] });
    else if (entry.kind === "record" && entry.recordType) {
      for (const sub of catalog.types[entry.recordType]?.fields ?? []) {
        const subEntry = catalog.entries[`${key}.${sub}`];
        if (subEntry && SCALAR_KINDS.has(subEntry.kind)) {
          out.push({
            path: `${name}.${sub}`,
            key: `${key}.${sub}`,
            entry: subEntry,
            parts: [name, sub],
          });
        }
      }
    }
  }
  // A code beside its constant name (`modulation`, `modulationName`): one column, the name.
  const named = new Set(
    out.flatMap((c) =>
      c.entry.codeField ? [[...c.parts.slice(0, -1), c.entry.codeField].join(".")] : [],
    ),
  );
  return out.filter((c) => !named.has(c.path));
}

/** Complex (non-column) fields of a record type: lists, nested tables. */
export function complexFields(catalog: SeriesCatalog, typeName: string, prefix: string) {
  const fields = (catalog.types[typeName]?.fields ?? [])
    .map((name) => ({ name, entry: catalog.entries[`${prefix}.${name}`] }))
    .filter((f): f is { name: string; entry: CatalogEntry } => Boolean(f.entry));
  const named = new Set(fields.map((f) => f.entry.codeField));
  return fields.filter(
    (f) => !named.has(f.name) && !SCALAR_KINDS.has(f.entry.kind) && f.entry.kind !== "record",
  );
}

export type RangeList = {
  pair: { min: CatalogEntry; max: CatalogEntry };
  others: Column[];
};

/**
 * An array of ranges with at most two other scalar columns (radio segments): the columns
 * a range list shows, else null (a table fits better).
 */
export function rangeListOf(
  catalog: SeriesCatalog,
  entry: CatalogEntry,
  prefix: string,
): RangeList | null {
  if (!entry.recordType || entry.keyField || entry.axis) return null;
  const item = `${prefix}[]`;
  const pair = rangePair(catalog, entry.recordType, item);
  if (!pair || complexFields(catalog, entry.recordType, item).length) return null;
  const others = tableColumns(catalog, entry.recordType, item).filter(
    (c) => c.entry !== pair.min && c.entry !== pair.max,
  );
  return others.length <= 2 ? { pair, others } : null;
}
