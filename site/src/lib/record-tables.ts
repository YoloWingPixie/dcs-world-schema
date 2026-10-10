/**
 * How an array of records reads, from the catalog alone: its table columns, the fields too
 * rich for a cell, and its list of ranges (radio segments). Shared by the catalog build
 * (lib/catalog.ts marks `ranges` lists from the columns), the record renderers
 * (components/record) and the placement pass (lib/placement.ts). Each answer is computed
 * once per catalog.
 */
import { perObject } from "./once";
import { type CatalogEntry, SCALAR_KINDS, type SeriesCatalog } from "./types";

export type Column = { path: string; key: string; entry: CatalogEntry; parts: string[] };

type Shapes = Pick<SeriesCatalog, "types" | "entries">;

/** Answers computed once per catalog and key. */
const cache = perObject<Shapes>();

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
    const fields = (catalog.types[typeName]?.fields ?? [])
      .map((name) => ({ name, entry: catalog.entries[`${prefix}.${name}`] }))
      .filter((f): f is { name: string; entry: CatalogEntry } => Boolean(f.entry));
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
  const { rangePair, recordType, path } = entry;
  return cache.cachedBy(catalog, `ranges\n${path}`, () => {
    const min = catalog.entries[rangePair.min];
    const max = catalog.entries[rangePair.max];
    if (!min || !max) return null;
    const others = tableColumns(catalog, recordType, `${path}[]`).filter(
      (c) => c.entry !== min && c.entry !== max,
    );
    return { pair: { min, max }, others };
  });
}
