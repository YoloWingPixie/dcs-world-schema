/**
 * The reference data, read from the released SQLite database (tools/package/sqlite.py).
 * Everything is derived from what the database says about itself — `series`,
 * `schema_types`, `ref_paths`, `search` — so a new series, field or enum value renders
 * without a site change. Functions take a `Query` (the browser's HTTP-range worker, or
 * node:sqlite in tests) and return the shapes the UI renders (lib/types.ts).
 */

import type { SchemaTypes } from "../catalog";
import {
  buildSeriesCatalog,
  COMPANION_PREFIX,
  entryFor,
  humanize,
  rootFields,
  rootFor,
} from "../catalog";
import { pathLabel } from "../format-field";
import { isRecord, present } from "../json";
import { collidingIds, LINK_DETAILS, withDetail } from "../link-details";
import { perObject } from "../once";
import { samplesOf, withoutNamedCodes } from "../record-tables";
import { SERIES_BY_ID, SERIES_GROUPS, type SeriesGroupId } from "../series";
import { displayFor, offersFacet } from "../series-display";
import { naturalCompare } from "../text";
import {
  type CatalogEntry,
  type Facet,
  type FieldPath,
  type LinkTarget,
  type PathValues,
  type RecordDoc,
  SCALAR_KINDS,
  type ScriptingRow,
  type SeriesCatalog,
  type SeriesIndex,
} from "../types";
import { schemaTypesFromRows } from "./schema";

export type Row = Record<string, unknown>;
/** Runs one statement; rows as objects. */
export type Query = (sql: string, params?: unknown[]) => Promise<Row[]>;

export type SeriesModel = {
  id: string;
  typeName: string;
  keyColumn: string;
  count: number;
  /** Set on a companion series (weapon_flight): the series whose records it extends. */
  parent?: string;
  /** Set on a parent series: its companion. */
  companion?: string;
  /** A unit type series (target of `units` references). */
  unit: boolean;
  label: string;
  singular: string;
  blurb: string;
  group: SeriesGroupId | "other";
};

export type RefPath = {
  table: string;
  series: string;
  path: string;
  target: string;
  source: string;
  targetColumn: string;
};

export type Model = {
  meta: Record<string, string>;
  series: SeriesModel[];
  byId: Map<string, SeriesModel>;
  types: SchemaTypes;
  refPaths: RefPath[];
};

export const UNITS = "units";

export const qi = (name: string) => `"${name.replace(/"/g, '""')}"`;

function firstSentence(text: string): string {
  const clean = text.replace(/`/g, "");
  const first = clean.split(/(?<=\.)\s/)[0] ?? clean;
  return first.length > 140 ? `${first.slice(0, 137)}…` : first;
}

// ---------------------------------------------------------------------------
// Model

/**
 * The rows the model is built from, one statement per table. scripts/split-sqlite.ts writes
 * the same statements' rows to a static file (`model` in reference.json), which the browser
 * reads instead of the database (lib/client-data.ts `loadModel`).
 */
export type ModelTables = {
  /** The database's `meta` table: its DCS revision (`dcsVersion`), when it was extracted. */
  meta: Row[];
  series: Row[];
  schema_types: Row[];
  ref_paths: Row[];
};

export const MODEL_SQL: Record<keyof ModelTables, string> = {
  meta: "SELECT key, value FROM meta",
  series: "SELECT name, type_name, key_column, records FROM series ORDER BY rowid",
  schema_types: "SELECT name, definition FROM schema_types",
  ref_paths: "SELECT table_name, series, path, target, source_column, target_column FROM ref_paths",
};

export async function readModelTables(q: Query): Promise<ModelTables> {
  const [meta, series, schema_types, ref_paths] = await Promise.all([
    q(MODEL_SQL.meta),
    q(MODEL_SQL.series),
    q(MODEL_SQL.schema_types),
    q(MODEL_SQL.ref_paths),
  ]);
  return { meta, series, schema_types, ref_paths };
}

export async function loadModel(q: Query): Promise<Model> {
  return modelFrom(await readModelTables(q));
}

export function modelFrom(tables: ModelTables): Model {
  const meta = Object.fromEntries(tables.meta.map((r) => [String(r.key), String(r.value)]));
  const types = schemaTypesFromRows(
    tables.schema_types.map((r) => ({ name: String(r.name), definition: String(r.definition) })),
  );
  const refPaths: RefPath[] = tables.ref_paths.map((r) => ({
    table: String(r.table_name),
    series: String(r.series),
    path: String(r.path),
    target: String(r.target),
    source: String(r.source_column),
    targetColumn: String(r.target_column),
  }));
  // Unit series: the types a multi-type reference (`Entity.Aircraft | ...`) names.
  const unitTypes = new Set<string>();
  for (const t of Object.values(types)) {
    for (const f of Object.values(t.fields ?? {})) {
      const parts = f.ref?.split("|").map((x) => x.trim()) ?? [];
      if (parts.length > 1) for (const p of parts) unitTypes.add(p);
    }
  }
  const series: SeriesModel[] = tables.series.map((r) => {
    const id = String(r.name);
    const typeName = String(r.type_name);
    const hint = SERIES_BY_ID.get(id);
    const keyColumn = String(r.key_column);
    // A series keyed by a reference to another series' record extends that record.
    const parent = refPaths.find(
      (p) => p.series === id && p.table === id && p.path === keyColumn && p.target !== UNITS,
    )?.target;
    const label = hint?.label ?? humanize(id);
    const model: SeriesModel = {
      id,
      typeName,
      keyColumn,
      count: Number(r.records ?? 0),
      unit: unitTypes.has(typeName),
      label,
      singular: hint?.singular ?? label.toLowerCase().replace(/s$/, ""),
      blurb: hint?.blurb ?? firstSentence(types[typeName]?.description ?? ""),
      group: hint?.group ?? "other",
    };
    if (parent) model.parent = parent;
    return model;
  });
  for (const s of series) {
    if (!s.parent) continue;
    const parent = series.find((p) => p.id === s.parent);
    if (parent) parent.companion = s.id;
  }
  return { meta, series, byId: new Map(series.map((s) => [s.id, s])), types, refPaths };
}

/**
 * Series a schema `ref` names (a union of unit types names every unit series); a companion's
 * records live on their parent's pages, so it names the parent.
 */
export function refResolver(model: Model) {
  return (ref: string): string[] => {
    const names = ref.split("|").map((t) => t.trim());
    const ids = names.flatMap((t) =>
      model.series.filter((s) => s.typeName === t).map((s) => s.parent ?? s.id),
    );
    return [...new Set(ids)];
  };
}

export const seriesGroups = (model: Model) => {
  const groups: Array<{ id: string; label: string; series: SeriesModel[] }> = SERIES_GROUPS.map(
    (g) => ({ id: g.id, label: g.label, series: [] }),
  );
  const other = { id: "other", label: "Other", series: [] as SeriesModel[] };
  for (const s of model.series) {
    if (s.parent) continue;
    (groups.find((g) => g.id === s.group) ?? other).series.push(s);
  }
  return [...groups, other].filter((g) => g.series.length);
};

const catalogs = perObject<Model, SeriesCatalog>();

/** The field catalog of a browsable series (its companion's fields under `flight.`). */
export function catalogFor(model: Model, series: string): SeriesCatalog {
  return catalogs.cachedBy(model, series, () => buildCatalog(model, series));
}

function buildCatalog(model: Model, series: string): SeriesCatalog {
  const s = model.byId.get(series);
  if (!s) throw new Error(`Unknown series: ${series}`);
  const companion = s.companion ? model.byId.get(s.companion) : undefined;
  try {
    return buildSeriesCatalog(
      model.types,
      series,
      { type: s.typeName, keyColumn: s.keyColumn },
      companion ? { type: companion.typeName, keyColumn: companion.keyColumn } : undefined,
      refResolver(model),
    );
  } catch {
    // A type the database does not describe: an empty catalog renders raw JSON.
    return { series, rootType: s.typeName, entries: {}, types: {}, enums: {}, titleFields: [] };
  }
}

// ---------------------------------------------------------------------------
// Rows

/** A stored value as the record holds it: booleans restored, JSON text of non-scalars parsed. */
function decodeValue(entry: CatalogEntry | undefined, raw: unknown): unknown {
  if (entry?.kind === "boolean") return raw === 1 || raw === true || raw === "1";
  if ((entry && SCALAR_KINDS.has(entry.kind)) || typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

/** Names of records by series: `series -> id -> name`, from the search table. */
export async function namesOf(
  q: Query,
  model: Model,
  wanted: Map<string, Set<string>>,
): Promise<Map<string, Map<string, string>>> {
  const out = new Map<string, Map<string, string>>();
  for (const [series, ids] of wanted) {
    const list = [...ids];
    const s = model.byId.get(series);
    const owner = s?.parent ?? series;
    const map = new Map<string, string>();
    if (list.length > 40) {
      // Many ids: one range scan of the series in the (series, id, name) index beats
      // a b-tree descent per id over HTTP.
      const rows = await q("SELECT id, name FROM search WHERE series = ?", [owner]);
      for (const r of rows) if (ids.has(String(r.id))) map.set(String(r.id), String(r.name));
    } else if (list.length) {
      const rows = await q(
        `SELECT id, name FROM search WHERE series = ? AND id IN (${list.map(() => "?").join(",")})`,
        [owner, ...list],
      );
      for (const r of rows) map.set(String(r.id), String(r.name));
    }
    out.set(series, map);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Records

/** A `record_views` row (tools/package/sqlite.py): a record page in one read. */
type RecordView = {
  name: string;
  subtitle: string;
  record: Record<string, unknown>;
  companion?: Record<string, unknown>;
  links: Record<string, Record<string, string>>;
  referencedBy: Array<{
    series: string;
    path: string;
    via?: string;
    total: number;
    records: [string, string][];
  }>;
  /** The record's Scripting rows, checked against the Lua API when the database was built. */
  scripting?: ScriptingRow[];
};

/**
 * A view's JSON from its stored `view` BLOB: raw-deflated UTF-8 (tools/package/site_views.py),
 * inflated by the browser's own `DecompressionStream`.
 */
async function inflateView<T>(table: string, blob: unknown): Promise<T> {
  if (!(blob instanceof Uint8Array)) {
    throw new Error(
      `The database's ${table} are not compressed: rebuild it with \`task package:sqlite\`.`,
    );
  }
  const stream = new Blob([blob as Uint8Array<ArrayBuffer>])
    .stream()
    .pipeThrough(new DecompressionStream("deflate-raw"));
  return JSON.parse(await new Response(stream).text()) as T;
}

/**
 * The one view a statement selects from the per-page views tools/package/sqlite.py writes
 * (`record_views`, `series_views`, `field_values`), or null when there is none: a database without them
 * is too old for this site.
 */
async function readView<T>(
  q: Query,
  table: string,
  sql: string,
  params: unknown[],
): Promise<T | null> {
  const [row] = await rowsOf(q, table, sql, params);
  return row ? inflateView<T>(table, row.view) : null;
}

/** A statement's rows from a table the package writes for the site; a database without it is too old. */
async function rowsOf(q: Query, table: string, sql: string, params: unknown[]): Promise<Row[]> {
  try {
    return await q(sql, params);
  } catch (error) {
    if (/no such table/i.test(String(error))) {
      throw new Error(
        `The database has no ${table} table: rebuild it with \`task package:sqlite\`.`,
      );
    }
    throw error;
  }
}

const byName = (a: LinkTarget, b: LinkTarget) => naturalCompare(a[1], b[1]);

function referencedLabel(model: Model, series: string, path: string, via?: string): string {
  if (via) return `via ${model.byId.get(via)?.label.toLowerCase() ?? via}`;
  return catalogFor(model, series).entries[path]?.label ?? humanize(path.split(".").pop() ?? path);
}

/** A record page: one `record_views` row. */
export async function getRecord(
  q: Query,
  model: Model,
  series: string,
  id: string,
): Promise<RecordDoc | null> {
  const s = model.byId.get(series);
  if (!s) return null;
  const view = await readView<RecordView>(
    q,
    "record_views",
    "SELECT view FROM record_views WHERE series = ? AND id = ?",
    [series, id],
  );
  if (!view) return null;
  const key = view.record[s.keyColumn];
  return distinguishLinks(q, model, {
    series,
    id: String(key ?? id),
    slug: String(key ?? id),
    name: view.name,
    meta: view.subtitle,
    data: view.record,
    ...(view.companion ? { companion: view.companion } : {}),
    links: view.links,
    referencedBy: view.referencedBy.map((g) => ({
      series: g.series,
      path: g.path,
      label: referencedLabel(model, g.series, g.path, g.via),
      records: [...g.records].sort(byName),
      ...(g.via ? { via: g.via } : {}),
      ...(g.total > g.records.length ? { total: g.total } : {}),
    })),
    ...(view.scripting?.length ? { scripting: view.scripting } : {}),
  });
}

/**
 * Same-named records in one list of links ("KERMAN" three times) get a short detail
 * each (lib/link-details.ts). Mutates `links` and `groups`: one query per series with a
 * detail rule, for the colliding ids of every list together.
 */
async function addLinkDetails(
  q: Query,
  model: Model,
  links: RecordDoc["links"],
  groups: Array<{ series: string; records: LinkTarget[] }>,
): Promise<void> {
  const nameOf = (v: LinkTarget | string) => (typeof v === "string" ? v : v[1]);
  // Each list's colliding ids and how to rename them, by series.
  const lists: Array<{
    series: string;
    ids: Set<string>;
    apply: (found: Map<string, string>) => void;
  }> = [];
  for (const [series, map] of Object.entries(links)) {
    const ids = new Set(collidingIds(Object.entries(map).map(([id, v]) => [id, nameOf(v)])));
    lists.push({
      series,
      ids,
      apply: (found) => {
        for (const id of ids) {
          const v = map[id];
          const detail = found.get(id);
          if (v === undefined || !detail) continue;
          map[id] =
            typeof v === "string" ? withDetail(v, detail) : [v[0], withDetail(v[1], detail)];
        }
      },
    });
  }
  for (const group of groups) {
    const ids = new Set(collidingIds(group.records));
    lists.push({
      series: group.series,
      ids,
      apply: (found) => {
        group.records = group.records.map(([id, name]) => [
          id,
          withDetail(name, ids.has(id) ? (found.get(id) ?? null) : null),
        ]);
      },
    });
  }
  const wanted = new Map<string, Set<string>>();
  for (const list of lists) {
    if (!list.ids.size || !LINK_DETAILS[list.series]) continue;
    const set = wanted.get(list.series) ?? new Set<string>();
    for (const id of list.ids) set.add(id);
    wanted.set(list.series, set);
  }
  const found = new Map(
    await Promise.all(
      [...wanted].map(
        async ([series, ids]) => [series, await linkDetails(q, model, series, [...ids])] as const,
      ),
    ),
  );
  for (const list of lists) {
    const details = found.get(list.series);
    if (details?.size) list.apply(details);
  }
}

/** The detail (lib/link-details.ts) of each of `ids` in `series`, by id. */
async function linkDetails(
  q: Query,
  model: Model,
  series: string,
  ids: string[],
): Promise<Map<string, string>> {
  const rule = LINK_DETAILS[series];
  const s = model.byId.get(series);
  const out = new Map<string, string>();
  if (!rule || !s || !ids.length) return out;
  const columns = [s.keyColumn, ...rule.columns.filter((c) => c !== s.keyColumn)];
  const rows = await q(
    `SELECT ${columns.map(qi).join(", ")} FROM ${qi(series)} WHERE ${qi(s.keyColumn)} IN (${ids.map(() => "?").join(",")})`,
    ids,
  );
  for (const row of rows) {
    const detail = rule.detail(row);
    if (detail) out.set(String(row[s.keyColumn]), detail);
  }
  return out;
}

async function distinguishLinks(q: Query, model: Model, doc: RecordDoc): Promise<RecordDoc> {
  await addLinkDetails(q, model, doc.links, doc.referencedBy);
  return doc;
}

/**
 * Beacon rows by id, with the columns a map point reads (lib/geo `beaconPoint`): the
 * positions of an airbase's beacons or a navaid's transmitters in one statement.
 */
export async function getBeaconRows(q: Query, ids: string[]): Promise<Map<string, Row>> {
  const out = new Map<string, Row>();
  for (let i = 0; i < ids.length; i += 300) {
    const chunk = ids.slice(i, i + 300);
    const rows = await q(
      `SELECT id, latitude, longitude, typeName, callsign FROM beacons WHERE id IN (${chunk.map(() => "?").join(",")})`,
      chunk,
    );
    for (const r of rows) out.set(String(r.id), r);
  }
  return out;
}

/** Records of one series pointing at a record, under one path (`via` for a second hop). */
type RefGroup = { series: string; path: string; via?: string; ids: Set<string> };

/**
 * Who points at record `id` directly: one indexed lookup per reference path that targets
 * it, grouped by referring series and path. `keep` limits the paths read.
 */
async function directReferences(
  q: Query,
  model: Model,
  series: string,
  id: string,
  keep: (owner: string, path: string) => boolean = () => true,
): Promise<RefGroup[]> {
  const s = model.byId.get(series);
  if (!s) return [];
  const targets = new Set([series, ...(s.unit ? [UNITS] : [])]);
  const groups = new Map<string, RefGroup>();
  for (const rp of model.refPaths) {
    if (!targets.has(rp.target)) continue;
    const from = model.byId.get(rp.series);
    if (!from || from.parent === series) continue; // a record's own companion
    const owner = from.parent ?? from.id;
    const path = from.parent ? `${COMPANION_PREFIX}.${rp.path}` : rp.path;
    if (!keep(owner, path)) continue;
    const rows = await q(
      `SELECT DISTINCT ${qi(rp.source)} AS src FROM ${qi(rp.table)} WHERE ${qi(rp.targetColumn)} = ?`,
      [id],
    );
    if (!rows.length) continue;
    const key = `${owner}|${path}`;
    const g = groups.get(key) ?? { series: owner, path, ids: new Set<string>() };
    for (const r of rows) g.ids.add(String(r.src));
    groups.set(key, g);
  }
  return [...groups.values()];
}

/**
 * Second hop: units that reach the record through a non-unit record of `direct` (a
 * weapon through stores), as groups with `via` set to the series they go through. `only`
 * limits it to one unit series.
 */
async function hopReferences(
  q: Query,
  model: Model,
  direct: RefGroup[],
  only?: string,
): Promise<RefGroup[]> {
  const hops = new Map<string, RefGroup>();
  for (const g of direct) {
    const gs = model.byId.get(g.series);
    if (!gs || gs.unit || g.ids.size > 400) continue;
    for (const rp of model.refPaths) {
      if (rp.target !== g.series || (only && rp.series !== only)) continue;
      const from = model.byId.get(rp.series);
      if (!from?.unit) continue;
      const ids = [...g.ids];
      const found = new Set<string>();
      for (let i = 0; i < ids.length; i += 300) {
        const chunk = ids.slice(i, i + 300);
        const rows = await q(
          `SELECT DISTINCT ${qi(rp.source)} AS src FROM ${qi(rp.table)} WHERE ${qi(rp.targetColumn)} IN (${chunk.map(() => "?").join(",")})`,
          chunk,
        );
        for (const r of rows) found.add(String(r.src));
      }
      if (!found.size) continue;
      const key = `${rp.series}|via ${g.series}`;
      const h = hops.get(key) ?? {
        series: rp.series,
        path: rp.path,
        via: g.series,
        ids: new Set(),
      };
      for (const f of found) h.ids.add(f);
      hops.set(key, h);
    }
  }
  return [...hops.values()];
}

/**
 * Every record of one "referenced by" group (`from`, `path`), uncapped and with link
 * details: only that group's reference path is read (for a `via` group, the paths into
 * the series it goes through, and the one hop from there).
 */
export async function referencedByGroup(
  q: Query,
  model: Model,
  series: string,
  id: string,
  from: string,
  path: string,
  /** A derived group's series it goes through (`ReferencedBy.via`). */
  via?: string,
): Promise<LinkTarget[]> {
  const direct = await directReferences(q, model, series, id, (owner, p) =>
    via ? owner === via : owner === from && p === path,
  );
  const groups = via ? await hopReferences(q, model, direct, from) : direct;
  // Every group is of series `from` (and under `path`, or through `via`).
  const ids = new Set(groups.flatMap((g) => [...g.ids]));
  if (!ids.size) return [];
  const names = (await namesOf(q, model, new Map([[from, ids]]))).get(from);
  const records = [...ids].map((i): LinkTarget => [i, names?.get(i) ?? i]).sort(byName);
  await addLinkDetails(q, model, {}, [{ series: from, records }]);
  return records;
}

// ---------------------------------------------------------------------------
// Browse

const topLevelScalars = (catalog: SeriesCatalog) =>
  rootFields(catalog).filter((e) => SCALAR_KINDS.has(e.kind) && e.role !== "key");

/**
 * The catalog entry a browse column or facet path names, by the column picker's rule: one
 * value per record (`compareAs` `value`) of a scalar kind. A facet may also be a list
 * (`attributes`), each item one of its values. Null for any other path. Columns outside
 * the browse index load lazily (lib/client-data `loadLinkedField`).
 */
export function browseEntry(
  catalog: SeriesCatalog,
  path: string,
  use: "column" | "facet",
): CatalogEntry | null {
  const entry = entryFor(catalog, path);
  if (entry?.compareAs !== "value") return null;
  if (SCALAR_KINDS.has(entry.kind)) return entry;
  return use === "facet" && entry.kind === "strings" ? entry : null;
}

/** A `series_views` row (tools/package/sqlite.py): a browse table in one read. */
type SeriesView = {
  columns: string[];
  rows: unknown[][];
  labels: Record<string, Record<string, string>>;
  /**
   * The other paths lib/series-display.json shows by default: one value per row (null for
   * none) and the names of the records they reference, by series.
   */
  fields?: Record<string, { values: unknown[]; links: Record<string, Record<string, string>> }>;
  /** Per group-by ref path, each row's first target: `[series, id, name]` by row id. */
  groups?: Record<string, Record<string, GroupTarget>>;
};

// The index and the group targets of a browse page read the same view: one read and one
// inflate per series.
const seriesViews = perObject<Query, Promise<SeriesView | null>>();

function seriesView(q: Query, series: string): Promise<SeriesView | null> {
  return seriesViews.cachedBy(q, series, () => {
    const view = readView<SeriesView>(
      q,
      "series_views",
      "SELECT view FROM series_views WHERE series = ?",
      [series],
    );
    view.catch(() => seriesViews.drop(q, series));
    return view;
  });
}

/** Every record of a series with its top-level scalar columns (one `series_views` row). */
export async function getSeriesIndex(q: Query, model: Model, series: string): Promise<SeriesIndex> {
  const s = model.byId.get(series);
  if (!s) throw new Error(`Unknown series: ${series}`);
  const catalog = catalogFor(model, series);
  const columns = topLevelScalars(catalog);
  const view = await seriesView(q, series);
  if (!view) throw new Error(`No series_views row for ${series}.`);
  const at = new Map(view.columns.map((c, i) => [c, i + 2]));
  const rows: Row[] = view.rows.map((r) => {
    const out: Row = { __id: r[0] };
    for (const c of columns) {
      const i = at.get(c.name);
      out[c.name] = i === undefined ? null : (r[i] ?? null);
    }
    return out;
  });
  const names = new Map(view.rows.map((r) => [String(r[0]), String(r[1])]));
  // Ref columns keep their ids; the view's labels name the records they point at, as each
  // column's link table (lib/format-field `resolveLink`), the shape lazily loaded columns
  // carry (lib/client-data `loadLinkedField`). The labels do not say which of a ref's
  // series holds a record, so they go under its first: browse reads only the names.
  const links: SeriesIndex["links"] = {};
  for (const c of columns) {
    const labels = view.labels[c.name];
    const target = c.ref?.[0];
    if (c.kind === "ref" && labels && target) links[c.path] = { [target]: labels };
  }

  const count = rows.length;
  // A numeric code beside its constant name (`category` / `categoryName`) shows once; a
  // game asset's file path says little in a table.
  const kept = new Set(withoutNamedCodes(columns, (c) => ({ path: c.name, entry: c })));
  const redundant = (c: CatalogEntry) => !kept.has(c) || c.role === "asset";
  // Filled and distinct values per column, counted once.
  const stats = new Map<string, { filled: number; distinct: number }>();
  for (const c of columns) {
    const seen = new Set<unknown>();
    let filled = 0;
    for (const r of rows) {
      const v = r[c.name];
      if (v === null) continue;
      filled++;
      seen.add(v);
    }
    stats.set(c.name, { filled, distinct: seen.size });
  }
  const coverage = (c: CatalogEntry) => stats.get(c.name)?.filled ?? 0;
  const distinct = (c: CatalogEntry) => stats.get(c.name)?.distinct ?? 0;
  // The name and id head every row already (`columns` holds no key).
  const skipped = (c: CatalogEntry) => catalog.titleFields.includes(c.path);
  // Configured paths (lib/series-display) win over the heuristics below; they may name
  // fields outside the index (nested or list-valued), which browse loads lazily.
  const display = displayFor(series);
  const configured = (paths: string[] | undefined, use: "column" | "facet") => {
    const found = (paths ?? []).flatMap((p) => {
      const entry = browseEntry(catalog, p, use);
      return entry ? [{ path: p, entry }] : [];
    });
    return found.length ? found : undefined;
  };
  // Configured facets go as listed: browse offers each that holds two values
  // (lib/series-display `offersFacet`), once it has the values of those outside the index.
  const facets =
    configured(display.facets, "facet") ??
    columns
      .filter(
        (c) => (c.kind === "enum" || c.kind === "boolean" || c.kind === "string") && !skipped(c),
      )
      .filter((c) => {
        const d = distinct(c);
        return offersFacet(d) && d <= (c.kind === "string" ? 12 : 40) && coverage(c) >= count * 0.3;
      })
      .sort((a, b) => (a.kind === "boolean" ? 1 : 0) - (b.kind === "boolean" ? 1 : 0))
      .slice(0, 5)
      .map((c) => ({ path: c.path, entry: c }));
  const visible =
    configured(display.columns, "column")?.map((c) => c.path) ??
    columns
      .filter((c) => !skipped(c) && !redundant(c) && coverage(c) >= Math.max(1, count * 0.3))
      .filter((c) => !(c.kind === "string" && distinct(c) > count * 0.6))
      .sort((a, b) => coverage(b) - coverage(a))
      .slice(0, 4)
      .map((c) => c.path);

  const decoded = rows.map((r) => {
    const rid = String(r.__id);
    return [
      rid,
      names.get(rid) ?? rid,
      ...columns.map((c) => {
        const v = r[c.name];
        return v === null || v === undefined ? null : decodeValue(c, v);
      }),
    ] as SeriesIndex["rows"][number];
  });
  decoded.sort((a, b) => naturalCompare(a[1], b[1]));

  const facetList: Facet[] = facets.map(({ path, entry }) => ({
    path,
    label: pathLabel(entry, path),
  }));
  // The configured paths outside the columns, as `getFieldValues` reads them.
  const fields: SeriesIndex["fields"] = {};
  for (const [path, field] of Object.entries(view.fields ?? {})) {
    const entry = entryFor(catalog, path) ?? undefined;
    const values: Record<string, unknown> = {};
    field.values.forEach((v, i) => {
      const value = v === null ? null : decodeValue(entry, v);
      if (present(value)) values[String(view.rows[i]?.[0])] = value;
    });
    fields[path] = { values, links: field.links };
  }
  return {
    series,
    count,
    columns: columns.map((c) => c.path),
    visible,
    facets: facetList,
    rows: decoded,
    links,
    fields,
  };
}

/** The record a row's group heading names: `[series, id, display name]`. */
export type GroupTarget = [series: string, id: string, name: string];

/**
 * The first record a ref field points at, per row id (`liveries.unitTypes` -> the
 * livery's airframe), with that record's series and display name: the series view's
 * precomputed groups for a configured `groupBy` path, else one statement over the field's
 * join table (or the series' own column for a scalar ref). Empty when the field is not a
 * ref of the series.
 */
export async function getGroupTargets(
  q: Query,
  model: Model,
  series: string,
  path: string,
): Promise<Record<string, GroupTarget>> {
  if (displayFor(series).groupBy?.path === path) {
    const groups = (await seriesView(q, series))?.groups?.[path];
    if (groups) return groups;
  }
  const ref = storageOf(model, series, path)?.ref;
  if (!ref) return {};
  const target = `j.${qi(ref.targetColumn)}`;
  // A `units` ref names a record of whichever unit series holds the id.
  const owner = ref.target === UNITS ? "json_extract(u.series, '$[0]')" : "?";
  const params = ref.target === UNITS ? [] : [model.byId.get(ref.target)?.parent ?? ref.target];
  const rows = await q(
    `SELECT j.${qi(ref.source)} AS k, ${target} AS id, ${owner} AS series, n.name AS name
     FROM ${qi(ref.table)} j
     ${ref.target === UNITS ? `LEFT JOIN ${qi(UNITS)} u ON u.id = ${target}` : ""}
     LEFT JOIN search n ON n.series = ${owner} AND n.id = ${target}
     WHERE ${ref.table === series ? `${target} IS NOT NULL` : "j.ordinal = 0"}`,
    [...params, ...params],
  );
  const out: Record<string, GroupTarget> = {};
  for (const r of rows) {
    if (r.series === null || r.series === undefined) continue;
    const id = String(r.id);
    out[String(r.k)] = [String(r.series), id, r.name ? String(r.name) : id];
  }
  return out;
}

// ---------------------------------------------------------------------------
// Compare

/** Where a field path is stored in the database (`storageOf`). */
export type Storage = {
  /** The table holding the path's root column: the series', or its companion's for `flight.` paths. */
  table: string;
  /** That table's record key column. */
  key: string;
  /** The root column. */
  column: string;
  /** The column's catalog path (`flight.aerodynamics`). */
  field: string;
  /** Where a nested path sits in the column's JSON (`$.a.b`); null for the whole column. */
  json: string | null;
  /**
   * The `ref_paths` row of a whole column of refs: a join table for a list of ids
   * (`unitTypes`), the series' own table for one id. Null for any other path.
   */
  ref: RefPath | null;
};

/** The table, column, JSON path and ref join of a series' field path; null outside the series. */
export function storageOf(model: Model, series: string, path: string): Storage | null {
  const s = model.byId.get(series);
  if (!s) return null;
  const { root: table, rest } = rootFor(
    path,
    s,
    s.companion ? model.byId.get(s.companion) : undefined,
  );
  if (!table || !rest) return null;
  const [column, ...inner] = rest.split(".") as [string, ...string[]];
  const ref = inner.length
    ? undefined
    : model.refPaths.find(
        (p) =>
          p.series === table.id &&
          (p.table === table.id ? p.path === column : p.path === `${column}[]`),
      );
  return {
    table: table.id,
    key: table.keyColumn,
    column,
    field: path.slice(0, path.length - rest.length) + column,
    json: inner.length ? `$.${inner.join(".")}` : null,
    ref: ref ?? null,
  };
}

/**
 * A `field_values` row (tools/package/sqlite.py): one comparable field across a series,
 * `{id: value}` of the records holding one (a Mach-sampled list as stored: the list and its
 * step), and for a ref field the names of the records its ids name, by series.
 */
type FieldView = {
  values: Record<string, unknown>;
  links?: Record<string, Record<string, string>>;
};

const NO_FIELD: PathValues = { values: {}, links: {} };

/**
 * One comparable field (`compareAs` set) across every record of a series, by record id (a
 * record without a value is left out), with the link table its refs read from (lib/
 * format-field `resolveLink`): one `field_values` row, precomputed for every comparable
 * path the site offers (its keyed paths: `keyedFieldPaths`). Empty for any other path.
 */
export async function getField(
  q: Query,
  model: Model,
  series: string,
  path: string,
): Promise<PathValues> {
  if (!model.byId.has(series)) return NO_FIELD;
  const entry = entryFor(catalogFor(model, series), path);
  if (entry?.compareAs === undefined) return NO_FIELD;
  const view = await readView<FieldView>(
    q,
    "field_values",
    "SELECT view FROM field_values WHERE series = ? AND path = ?",
    [series, path],
  );
  if (!view) return NO_FIELD;
  let values = view.values;
  if (entry.axis?.kind === "sampled") {
    // A curve over Mach at the record's own step, as a record page draws it.
    values = {};
    for (const [id, holder] of Object.entries(view.values)) {
      const curve = isRecord(holder) ? samplesOf(holder, entry) : null;
      if (curve) values[id] = curve;
    }
  }
  const links: PathValues["links"] = {};
  for (const [target, names] of Object.entries(view.links ?? {})) {
    // Browse slugs are record ids.
    links[target] = Object.fromEntries(Object.entries(names).map(([id, n]) => [id, [id, n]]));
  }
  return { values, links };
}

/** One comparable field across every record of a series, by record id (`getField`). */
export async function getFieldValues(
  q: Query,
  model: Model,
  series: string,
  path: string,
): Promise<Record<string, unknown>> {
  return (await getField(q, model, series, path)).values;
}

/** Comparable concrete paths of a catalog's plain fields (keyed ones: `keyedFieldPaths`). */
export function fieldPaths(catalog: SeriesCatalog): FieldPath[] {
  return Object.values(catalog.entries)
    .filter((e) => e.compareAs !== undefined && !e.path.includes("*"))
    .map((e) => ({ path: e.path, key: e.path }));
}

/**
 * Concrete paths of keyed-array fields (`flight.motorStages.march.impulseS`), keys most
 * common first: the series' `field_paths` row, for a series with keyed arrays.
 */
export async function keyedFieldPaths(
  q: Query,
  model: Model,
  series: string,
): Promise<FieldPath[]> {
  if (!model.byId.has(series)) return [];
  const catalog = catalogFor(model, series);
  if (!Object.values(catalog.entries).some((e) => e.keyField)) return [];
  const [row] = await rowsOf(q, "field_paths", "SELECT paths FROM field_paths WHERE series = ?", [
    series,
  ]);
  if (!row) return [];
  return (JSON.parse(String(row.paths)) as Array<[string, string]>).map(([path, key]) => ({
    path,
    key,
  }));
}
