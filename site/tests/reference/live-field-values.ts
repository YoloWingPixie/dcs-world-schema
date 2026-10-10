/**
 * The live reads the site made before the package precomputed `field_values` and
 * `field_paths` (tools/package/sqlite.py): one field across a series straight from the
 * series tables (a column, its JSON, or the column walked as lib/catalog `valuesAt` walks
 * a record), the keyed paths from a `json_each` scan, and the names of the records a ref
 * field names from `search`. Kept as the oracle the precomputed views are checked against
 * (field-values.test.ts).
 */
import { entryFor, tableAxis, valuesAt } from "../../src/lib/catalog";
import {
  catalogFor,
  type Model,
  namesOf,
  type Query,
  qi,
  storageOf,
} from "../../src/lib/db/reference";
import { present } from "../../src/lib/json";
import {
  type CatalogEntry,
  type FieldPath,
  type PathValues,
  SCALAR_KINDS,
} from "../../src/lib/types";

function decodeValue(entry: CatalogEntry | undefined, raw: unknown): unknown {
  if (entry?.kind === "boolean") return raw === 1 || raw === true || raw === "1";
  if ((entry && SCALAR_KINDS.has(entry.kind)) || typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

/** One field across every record of a series, by record id, read from the series tables. */
export async function liveFieldValues(
  q: Query,
  model: Model,
  series: string,
  path: string,
): Promise<Record<string, unknown>> {
  if (!model.byId.has(series)) return {};
  const catalog = catalogFor(model, series);
  const entry = entryFor(catalog, path);
  if (!entry) return {};
  const at = storageOf(model, series, tableAxis(entry)?.table ?? path);
  if (!at) return {};
  const values: Record<string, unknown> = {};
  const keep = (k: unknown, v: unknown) => {
    if (present(v)) values[String(k)] = v;
  };
  const simple = entry.compareAs === "value" && path === entry.path;
  if (simple && at.ref && at.ref.table !== at.table) {
    const rows = await q(
      `SELECT ${qi(at.ref.source)} AS k, ${qi(at.ref.targetColumn)} AS v, ordinal AS o FROM ${qi(at.ref.table)}`,
    );
    const lists = new Map<string, Array<[number, unknown]>>();
    for (const r of rows) {
      const k = String(r.k);
      const list = lists.get(k) ?? [];
      list.push([Number(r.o), r.v]);
      lists.set(k, list);
    }
    for (const [k, list] of lists)
      keep(
        k,
        list.sort((x, y) => x[0] - y[0]).map(([, v]) => v),
      );
    return values;
  }
  const read = (v: string, params: unknown[] = []) =>
    q(`SELECT ${qi(at.key)} AS k, ${v} AS v FROM ${qi(at.table)} WHERE v IS NOT NULL`, params);
  if (simple) {
    const rows = at.json
      ? await read(`json_extract(${qi(at.column)}, ?)`, [at.json])
      : await read(qi(at.column));
    for (const r of rows) keep(r.k, decodeValue(entry, r.v));
    return values;
  }
  const columnEntry = catalog.entries[at.field];
  const inCompanion = at.field !== at.column;
  for (const r of await read(qi(at.column))) {
    const root = { [at.column]: decodeValue(columnEntry, r.v) };
    const found = valuesAt(
      entry,
      catalog,
      inCompanion ? {} : root,
      inCompanion ? root : undefined,
    ).find((v) => v.path === path);
    if (found) keep(r.k, found.value);
  }
  return values;
}

/**
 * One field's values and the names of the records its ids name (lib/client-data
 * `loadLinkedField` before `field_values`).
 */
export async function liveField(
  q: Query,
  model: Model,
  series: string,
  path: string,
): Promise<PathValues> {
  const values = await liveFieldValues(q, model, series, path);
  const targets = entryFor(catalogFor(model, series), path)?.ref ?? [];
  const ids = new Set<string>();
  for (const v of Object.values(values)) {
    for (const x of Array.isArray(v) ? v : [v]) {
      if (typeof x === "string" || typeof x === "number") ids.add(String(x));
    }
  }
  const links: PathValues["links"] = {};
  if (!targets.length || !ids.size) return { values, links };
  const names = await namesOf(q, model, new Map(targets.map((t) => [t, ids])));
  for (const [t, byId] of names) {
    links[t] = Object.fromEntries([...byId].map(([id, name]) => [id, [id, name]]));
  }
  return { values, links };
}

/**
 * Concrete paths of keyed-array fields, keys most common first: a `json_each` scan of the
 * column per keyed array. (The scan grouped by `key` before, which SQLite 3.51 resolves to
 * `json_each`'s own `key` column, the item's position, not the alias; `stage` here.)
 */
export async function liveKeyedFieldPaths(
  q: Query,
  model: Model,
  series: string,
): Promise<FieldPath[]> {
  if (!model.byId.has(series)) return [];
  const catalog = catalogFor(model, series);
  const out: FieldPath[] = [];
  for (const arr of Object.values(catalog.entries).filter((e) => e.keyField)) {
    const at = storageOf(model, series, arr.path);
    if (!at || at.json) continue;
    const rows = await q(
      `SELECT json_extract(j.value, ?) AS stage, count(*) AS n FROM ${qi(at.table)}, json_each(${qi(at.table)}.${qi(at.column)}) AS j GROUP BY stage ORDER BY n DESC`,
      [`$.${arr.keyField}`],
    );
    for (const r of rows) {
      if (r.stage === null) continue;
      for (const e of Object.values(catalog.entries)) {
        if (e.compareAs === undefined || !e.path.startsWith(`${arr.path}.*.`)) continue;
        out.push({
          path: e.path.replace(`${arr.path}.*.`, `${arr.path}.${String(r.stage)}.`),
          key: e.path,
        });
      }
    }
  }
  return out;
}
