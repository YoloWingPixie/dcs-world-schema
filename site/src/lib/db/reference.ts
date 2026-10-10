/**
 * The reference data, read from the released SQLite database (tools/package/sqlite.py).
 * Everything is derived from what the database says about itself — `series`,
 * `schema_types`, `ref_paths`, `search` — so a new series, field or enum value renders
 * without a site change. Functions take a `Query` (the browser's HTTP-range worker, or
 * node:sqlite in tests) and return the shapes the UI renders (lib/types.ts).
 */

import type { SchemaTypes } from "../catalog";
import { buildSeriesCatalog, COMPANION_PREFIX, humanize, isRecord, valuesAt } from "../catalog";
import { collidingIds, LINK_DETAILS, withDetail } from "../link-details";
import { SERIES_BY_ID, SERIES_GROUPS, type SeriesGroupId } from "../series";
import type {
  CatalogEntry,
  Facet,
  FieldValues,
  LinkTarget,
  RecordDoc,
  ReferencedBy,
  SeriesCatalog,
  SeriesIndex,
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
const SCALAR = new Set(["number", "string", "boolean", "enum", "ref"]);

export const qi = (name: string) => `"${name.replace(/"/g, '""')}"`;

function firstSentence(text: string): string {
  const clean = text.replace(/`/g, "");
  const first = clean.split(/(?<=\.)\s/)[0] ?? clean;
  return first.length > 140 ? `${first.slice(0, 137)}…` : first;
}

// ---------------------------------------------------------------------------
// Model

export async function loadModel(q: Query): Promise<Model> {
  const [metaRows, seriesRows, typeRows, refRows] = [
    await q("SELECT key, value FROM meta"),
    await q("SELECT name, type_name, key_column, records FROM series ORDER BY rowid"),
    await q("SELECT name, definition FROM schema_types"),
    await q("SELECT table_name, series, path, target, source_column, target_column FROM ref_paths"),
  ];
  const meta = Object.fromEntries(metaRows.map((r) => [String(r.key), String(r.value)]));
  const types = schemaTypesFromRows(
    typeRows.map((r) => ({ name: String(r.name), definition: String(r.definition) })),
  );
  const refPaths: RefPath[] = refRows.map((r) => ({
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
  const series: SeriesModel[] = seriesRows.map((r) => {
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

/** Series a schema `ref` names (a union of unit types names every unit series). */
export function refResolver(model: Model) {
  return (ref: string): string[] => {
    const names = ref.split("|").map((t) => t.trim());
    return names.flatMap((t) => model.series.filter((s) => s.typeName === t).map((s) => s.id));
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

const catalogs = new WeakMap<Model, Map<string, SeriesCatalog>>();

/** The field catalog of a browsable series (its companion's fields under `flight.`). */
export function catalogFor(model: Model, series: string): SeriesCatalog {
  let cache = catalogs.get(model);
  if (!cache) {
    cache = new Map();
    catalogs.set(model, cache);
  }
  const hit = cache.get(series);
  if (hit) return hit;
  const s = model.byId.get(series);
  if (!s) throw new Error(`Unknown series: ${series}`);
  const companion = s.companion ? model.byId.get(s.companion) : undefined;
  let catalog: SeriesCatalog;
  try {
    catalog = buildSeriesCatalog(
      model.types,
      series,
      s.typeName,
      companion ? { type: companion.typeName } : undefined,
      refResolver(model),
    );
  } catch {
    // A type the database does not describe: an empty catalog renders raw JSON.
    catalog = { series, rootType: s.typeName, entries: {}, types: {}, enums: {}, fieldPaths: [] };
  }
  catalog.fieldPaths = Object.values(catalog.entries)
    .filter((e) => e.comparable && !e.path.includes("*"))
    .map((e) => ({ path: e.path, key: e.path, count: 0 }));
  cache.set(series, catalog);
  return catalog;
}

// ---------------------------------------------------------------------------
// Rows

/** A database row as the record it was built from: JSON columns parsed, booleans restored. */
export function decodeRow(row: Row, catalog: SeriesCatalog, prefix = ""): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(row)) {
    if (raw === null || raw === undefined) continue;
    const entry = catalog.entries[prefix ? `${prefix}.${name}` : name];
    if (entry?.kind === "boolean") out[name] = raw === 1 || raw === true || raw === "1";
    else if (entry && SCALAR.has(entry.kind)) out[name] = raw;
    else if (typeof raw === "string") {
      try {
        out[name] = JSON.parse(raw);
      } catch {
        out[name] = raw;
      }
    } else out[name] = raw;
  }
  return out;
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

function collectAll(node: unknown, segments: string[]): unknown[] {
  if (segments.length === 0) {
    if (node === undefined || node === null) return [];
    return Array.isArray(node) ? node.flat(4) : [node];
  }
  const [head, ...rest] = segments as [string, ...string[]];
  if (head === "*") return Array.isArray(node) ? node.flatMap((n) => collectAll(n, rest)) : [];
  const m = /^(.*?)((?:\[\])*)$/.exec(head);
  const name = m?.[1] ?? head;
  const depth = (m?.[2]?.length ?? 0) / 2;
  let values: unknown[] = [isRecord(node) ? node[name] : undefined];
  for (let i = 0; i < depth; i++) values = values.flatMap((v) => (Array.isArray(v) ? v : []));
  return values.flatMap((v) => collectAll(v, rest));
}

/** Which of `series` (a ref's target list) holds each id: one query per series. */
async function resolveIds(
  q: Query,
  model: Model,
  series: string[],
  ids: Set<string>,
): Promise<Map<string, [string, string]>> {
  const found = new Map<string, [string, string]>();
  for (const s of series) {
    const rest = new Set([...ids].filter((id) => !found.has(id)));
    if (!rest.size) break;
    const names = (await namesOf(q, model, new Map([[s, rest]]))).get(s) ?? new Map();
    const owner = model.byId.get(s)?.parent ?? s;
    for (const [id, name] of names) found.set(id, [owner, name]);
  }
  return found;
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
};

const missingTable = (error: unknown) => /no such table/i.test(String(error));

const byName = (a: LinkTarget, b: LinkTarget) => a[1].localeCompare(b[1], "en", { numeric: true });

function referencedLabel(model: Model, series: string, path: string, via?: string): string {
  if (via) return `via ${model.byId.get(via)?.label.toLowerCase() ?? via}`;
  return catalogFor(model, series).entries[path]?.label ?? humanize(path.split(".").pop() ?? path);
}

/** A record page: one `record_views` row, else (an older database) the record's own queries. */
export async function getRecord(
  q: Query,
  model: Model,
  series: string,
  id: string,
): Promise<RecordDoc | null> {
  const s = model.byId.get(series);
  if (!s) return null;
  let rows: Row[];
  try {
    rows = await q("SELECT view FROM record_views WHERE series = ? AND id = ?", [series, id]);
  } catch (error) {
    if (!missingTable(error)) throw error;
    const doc = await getRecordByQueries(q, model, series, id);
    return doc && distinguishLinks(q, model, doc);
  }
  const [row] = rows;
  if (!row) return null;
  const view = JSON.parse(String(row.view)) as RecordView;
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
      ...(g.total > g.records.length ? { total: g.total } : {}),
    })),
  });
}

/**
 * Same-named records in one list of links ("KERMAN" three times) get a short detail
 * each (lib/link-details.ts): one query per series with collisions and a detail rule.
 */
async function distinguishLinks(q: Query, model: Model, doc: RecordDoc): Promise<RecordDoc> {
  const details = async (series: string, ids: string[]) => {
    const rule = LINK_DETAILS[series];
    const s = model.byId.get(series);
    const out = new Map<string, string>();
    if (!rule || !s || !ids.length) return out;
    const rows = await q(
      `SELECT * FROM ${qi(series)} WHERE ${qi(s.keyColumn)} IN (${ids.map(() => "?").join(",")})`,
      ids,
    );
    for (const row of rows) {
      const detail = rule(row);
      if (detail) out.set(String(row[s.keyColumn]), detail);
    }
    return out;
  };
  const nameOf = (v: LinkTarget | string) => (typeof v === "string" ? v : v[1]);
  for (const [series, map] of Object.entries(doc.links)) {
    const found = await details(
      series,
      collidingIds(Object.entries(map).map(([id, v]) => [id, nameOf(v)])),
    );
    for (const [id, detail] of found) {
      const v = map[id];
      if (v === undefined) continue;
      map[id] = typeof v === "string" ? withDetail(v, detail) : [v[0], withDetail(v[1], detail)];
    }
  }
  for (const group of doc.referencedBy) {
    const found = await details(group.series, collidingIds(group.records));
    if (!found.size) continue;
    group.records = group.records.map(([id, name]) => [
      id,
      withDetail(name, found.get(id) ?? null),
    ]);
  }
  return doc;
}

async function getRecordByQueries(
  q: Query,
  model: Model,
  series: string,
  id: string,
): Promise<RecordDoc | null> {
  const s = model.byId.get(series);
  if (!s) return null;
  const catalog = catalogFor(model, series);
  const [row] = await q(`SELECT * FROM ${qi(series)} WHERE ${qi(s.keyColumn)} = ?`, [id]);
  if (!row) return null;
  const data = decodeRow(row, catalog);
  let companion: Record<string, unknown> | undefined;
  const comp = s.companion ? model.byId.get(s.companion) : undefined;
  if (comp) {
    const [crow] = await q(`SELECT * FROM ${qi(comp.id)} WHERE ${qi(comp.keyColumn)} = ?`, [id]);
    if (crow) companion = decodeRow(crow, catalog, COMPANION_PREFIX);
  }

  const [self] = await q("SELECT name, subtitle FROM search WHERE series = ? AND id = ?", [
    series,
    id,
  ]);

  // Links: every ref value in the record, resolved to the series holding it.
  const links: RecordDoc["links"] = {};
  const byTargets = new Map<string, Set<string>>();
  for (const entry of Object.values(catalog.entries)) {
    if (!entry.ref?.length) continue;
    const root = entry.path.startsWith(`${COMPANION_PREFIX}.`) ? companion : data;
    const path = entry.path.startsWith(`${COMPANION_PREFIX}.`)
      ? entry.path.slice(COMPANION_PREFIX.length + 1)
      : entry.path;
    if (!root) continue;
    const key = entry.ref.join(",");
    const set = byTargets.get(key) ?? new Set<string>();
    for (const v of collectAll(root, path.split("."))) {
      if (typeof v === "string" || typeof v === "number") set.add(String(v));
    }
    byTargets.set(key, set);
  }
  for (const [key, ids] of byTargets) {
    if (!ids.size) continue;
    const found = await resolveIds(q, model, key.split(","), ids);
    for (const [rawId, [owner, name]] of found) {
      links[owner] ??= {};
      (links[owner] as Record<string, string>)[rawId] = name;
    }
  }

  return {
    series,
    id: String(row[s.keyColumn] ?? id),
    slug: String(row[s.keyColumn] ?? id),
    name: self ? String(self.name) : String(id),
    meta: self ? String(self.subtitle ?? "") : "",
    data,
    ...(companion ? { companion } : {}),
    links,
    referencedBy: await referencedBy(q, model, series, id),
  };
}

/** Who points at record `id`: one indexed lookup per reference path that targets it. */
export async function referencedBy(
  q: Query,
  model: Model,
  series: string,
  id: string,
): Promise<ReferencedBy[]> {
  const s = model.byId.get(series);
  if (!s) return [];
  const targets = new Set([series, ...(s.unit ? [UNITS] : [])]);
  const groups = new Map<string, { series: string; path: string; ids: Set<string> }>();
  for (const rp of model.refPaths) {
    if (!targets.has(rp.target)) continue;
    const from = model.byId.get(rp.series);
    if (!from || from.parent === series) continue; // a record's own companion
    const rows = await q(
      `SELECT DISTINCT ${qi(rp.source)} AS src FROM ${qi(rp.table)} WHERE ${qi(rp.targetColumn)} = ?`,
      [id],
    );
    if (!rows.length) continue;
    const owner = from.parent ?? from.id;
    const path = from.parent ? `${COMPANION_PREFIX}.${rp.path}` : rp.path;
    const key = `${owner}|${path}`;
    const g = groups.get(key) ?? { series: owner, path, ids: new Set<string>() };
    for (const r of rows) g.ids.add(String(r.src));
    groups.set(key, g);
  }

  // Second hop: units that reach it through a non-unit record (a weapon through stores).
  const hops = new Map<string, { series: string; path: string; via: string; ids: Set<string> }>();
  for (const g of groups.values()) {
    const gs = model.byId.get(g.series);
    if (!gs || gs.unit || g.ids.size > 400) continue;
    for (const rp of model.refPaths) {
      if (rp.target !== g.series) continue;
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

  const wanted = new Map<string, Set<string>>();
  for (const g of [...groups.values(), ...hops.values()]) {
    const set = wanted.get(g.series) ?? new Set();
    for (const i of g.ids) set.add(i);
    wanted.set(g.series, set);
  }
  const names = await namesOf(q, model, wanted);
  const toRecords = (series: string, ids: Set<string>) =>
    [...ids]
      .map((i) => [i, names.get(series)?.get(i) ?? i] as [string, string])
      .sort((a, b) => a[1].localeCompare(b[1], "en", { numeric: true }));
  const labelOf = (series: string, path: string) =>
    catalogFor(model, series).entries[path]?.label ?? humanize(path.split(".").pop() ?? path);

  return [
    ...[...groups.values()].map((g) => ({
      series: g.series,
      path: g.path,
      label: labelOf(g.series, g.path),
      records: toRecords(g.series, g.ids),
    })),
    ...[...hops.values()].map((h) => ({
      series: h.series,
      path: `via:${h.via}`,
      label: `via ${model.byId.get(h.via)?.label.toLowerCase() ?? h.via}`,
      records: toRecords(h.series, h.ids),
    })),
  ];
}

/** Every record of one "referenced by" group (`from`, `path`), uncapped. */
export async function referencedByGroup(
  q: Query,
  model: Model,
  series: string,
  id: string,
  from: string,
  path: string,
): Promise<LinkTarget[]> {
  const groups = await referencedBy(q, model, series, id);
  return groups.find((g) => g.series === from && g.path === path)?.records ?? [];
}

// ---------------------------------------------------------------------------
// Browse

const topLevelScalars = (catalog: SeriesCatalog, key: string) =>
  Object.values(catalog.entries).filter(
    (e) => !e.path.includes(".") && !e.path.includes("[") && SCALAR.has(e.kind) && e.name !== key,
  );

/** A `series_views` row (tools/package/sqlite.py): a browse table in one read. */
type SeriesView = {
  columns: string[];
  rows: unknown[][];
  labels: Record<string, Record<string, string>>;
};

async function seriesView(q: Query, series: string): Promise<SeriesView | null> {
  try {
    const [row] = await q("SELECT view FROM series_views WHERE series = ?", [series]);
    return row ? (JSON.parse(String(row.view)) as SeriesView) : null;
  } catch (error) {
    if (missingTable(error)) return null;
    throw error;
  }
}

/** Every record of a series with its top-level scalar columns (one `series_views` row). */
export async function getSeriesIndex(q: Query, model: Model, series: string): Promise<SeriesIndex> {
  const s = model.byId.get(series);
  if (!s) throw new Error(`Unknown series: ${series}`);
  const catalog = catalogFor(model, series);
  const columns = topLevelScalars(catalog, s.keyColumn);
  const view = await seriesView(q, series);
  let rows: Row[];
  let names: Map<string, string>;
  // Ref columns show the target's name.
  const refNames = new Map<string, Map<string, [string, string]>>();
  if (view) {
    const at = new Map(view.columns.map((c, i) => [c, i + 2]));
    rows = view.rows.map((r) => {
      const out: Row = { __id: r[0] };
      for (const c of columns) {
        const i = at.get(c.name);
        out[c.name] = i === undefined ? null : (r[i] ?? null);
      }
      return out;
    });
    names = new Map(view.rows.map((r) => [String(r[0]), String(r[1])]));
    for (const [c, labels] of Object.entries(view.labels)) {
      refNames.set(c, new Map(Object.entries(labels).map(([k, v]) => [k, [series, v]])));
    }
  } else {
    const cols = columns.map((c) => qi(c.name)).join(", ");
    rows = await q(
      `SELECT ${qi(s.keyColumn)} AS __id${cols ? `, ${cols}` : ""} FROM ${qi(series)}`,
    );
    names = new Map(
      (await q("SELECT id, name FROM search WHERE series = ?", [series])).map((r) => [
        String(r.id),
        String(r.name),
      ]),
    );
    for (const c of columns.filter((c) => c.kind === "ref" && c.ref?.length)) {
      const ids = new Set(
        rows
          .map((r) => r[c.name])
          .filter((v) => v !== null)
          .map(String),
      );
      refNames.set(c.name, await resolveIds(q, model, c.ref ?? [], ids));
    }
  }

  const count = rows.length;
  // A numeric code beside its constant name (`category` / `categoryName`) shows once.
  const names_ = new Set(columns.map((c) => c.name));
  const redundant = (c: CatalogEntry) =>
    names_.has(`${c.name}Name`) ||
    rows.some(
      (r) =>
        typeof r[c.name] === "string" && /\.(png|dds|lua|edm|jpg|tga)$/i.test(String(r[c.name])),
    );
  const coverage = (c: CatalogEntry) => rows.filter((r) => r[c.name] !== null).length;
  const distinct = (c: CatalogEntry) =>
    new Set(rows.map((r) => r[c.name]).filter((v) => v !== null)).size;
  const skipNames = /^(displayName|name|id)$/;
  const facets = columns
    .filter(
      (c) =>
        (c.kind === "enum" || c.kind === "boolean" || c.kind === "string") &&
        !skipNames.test(c.name),
    )
    .filter((c) => {
      const d = distinct(c);
      return d >= 2 && d <= (c.kind === "string" ? 12 : 40) && coverage(c) >= count * 0.3;
    })
    .sort((a, b) => (a.kind === "boolean" ? 1 : 0) - (b.kind === "boolean" ? 1 : 0))
    .slice(0, 5);
  const visible = columns
    .filter(
      (c) => !skipNames.test(c.name) && !redundant(c) && coverage(c) >= Math.max(1, count * 0.3),
    )
    .filter((c) => !(c.kind === "string" && distinct(c) > count * 0.6))
    .sort((a, b) => coverage(b) - coverage(a))
    .slice(0, 4);

  const decoded = rows.map((r) => {
    const rid = String(r.__id);
    return [
      rid,
      names.get(rid) ?? rid,
      rid,
      ...columns.map((c) => {
        const v = r[c.name];
        if (v === null || v === undefined) return null;
        if (c.kind === "boolean") return v === 1 || v === true;
        if (c.kind === "ref") return refNames.get(c.name)?.get(String(v))?.[1] ?? v;
        return v;
      }),
    ] as SeriesIndex["rows"][number];
  });
  decoded.sort((a, b) => a[1].localeCompare(b[1], "en", { numeric: true }));

  const facetList: Facet[] = facets.map((c) => ({
    path: c.path,
    label: c.label,
    kind: c.kind === "enum" ? "enum" : c.kind === "boolean" ? "boolean" : "string",
    column: columns.indexOf(c),
  }));
  return {
    series,
    count,
    columns: columns.map((c) => c.path),
    visible: visible.map((c) => c.path),
    facets: facetList,
    rows: decoded,
  };
}

// ---------------------------------------------------------------------------
// Compare

/** One field across every record of a series, keyed by id. */
export async function getFieldValues(
  q: Query,
  model: Model,
  series: string,
  path: string,
): Promise<FieldValues> {
  const s = model.byId.get(series);
  if (!s) return { path, values: {} };
  const catalog = catalogFor(model, series);
  const key = Object.keys(catalog.entries).find((k) => k === path) ?? starKey(catalog, path);
  const entry = key ? catalog.entries[key] : undefined;
  if (!entry) return { path, values: {} };
  const inCompanion = path.startsWith(`${COMPANION_PREFIX}.`);
  const table = inCompanion ? model.byId.get(s.companion ?? "") : s;
  if (!table) return { path, values: {} };
  const rest = inCompanion ? path.slice(COMPANION_PREFIX.length + 1) : path;
  const [column, ...inner] = rest.replace(/\[\].*$/, "").split(".") as [string, ...string[]];
  const values: Record<string, unknown> = {};
  const simple = !entry.path.includes("*") && !entry.path.includes("[]");

  if (simple && inner.length === 0) {
    const rows = await q(
      `SELECT ${qi(table.keyColumn)} AS k, ${qi(column)} AS v FROM ${qi(table.id)} WHERE ${qi(column)} IS NOT NULL`,
    );
    for (const r of rows) {
      const decoded = decodeRow(
        { v: r.v },
        { ...catalog, entries: { v: { ...entry, name: "v", path: "v" } } },
      );
      values[String(r.k)] = decoded.v;
    }
    return { path, values };
  }
  if (simple) {
    const rows = await q(
      `SELECT ${qi(table.keyColumn)} AS k, json_extract(${qi(column)}, ?) AS v FROM ${qi(table.id)} WHERE v IS NOT NULL`,
      [`$.${inner.join(".")}`],
    );
    for (const r of rows) {
      let v: unknown = r.v;
      if (entry.kind === "boolean") v = v === 1 || v === true;
      else if (!SCALAR.has(entry.kind) && typeof v === "string") {
        try {
          v = JSON.parse(v);
        } catch {
          // keep text
        }
      }
      if (Array.isArray(v) && v.length === 0) continue;
      values[String(r.k)] = v;
    }
    return { path, values };
  }
  // Keyed stages, axis tables, envelopes: read the column and walk it.
  const rows = await q(
    `SELECT ${qi(table.keyColumn)} AS k, ${qi(column)} AS v FROM ${qi(table.id)} WHERE ${qi(column)} IS NOT NULL`,
  );
  for (const r of rows) {
    let parsed: unknown;
    try {
      parsed = typeof r.v === "string" ? JSON.parse(r.v) : r.v;
    } catch {
      continue;
    }
    const root = { [column]: parsed };
    const found = valuesAt(
      entry,
      catalog,
      inCompanion ? {} : root,
      inCompanion ? root : undefined,
    ).find((v) => v.path === path);
    if (found) values[String(r.k)] = found.value;
  }
  return { path, values };
}

function starKey(catalog: SeriesCatalog, path: string): string | undefined {
  const parts = path.split(".");
  for (let i = 0; i < parts.length; i++) {
    const candidate = [...parts.slice(0, i), "*", ...parts.slice(i + 1)].join(".");
    if (catalog.entries[candidate]) return candidate;
  }
  return undefined;
}

/** Concrete paths of keyed-array fields (`flight.motorStages.march.impulseS`). */
export async function keyedFieldPaths(
  q: Query,
  model: Model,
  series: string,
): Promise<Array<{ path: string; key: string; count: number }>> {
  const s = model.byId.get(series);
  if (!s) return [];
  const catalog = catalogFor(model, series);
  const out: Array<{ path: string; key: string; count: number }> = [];
  for (const arr of Object.values(catalog.entries).filter((e) => e.keyField)) {
    const inCompanion = arr.path.startsWith(`${COMPANION_PREFIX}.`);
    const table = inCompanion ? model.byId.get(s.companion ?? "") : s;
    const column = (inCompanion ? arr.path.slice(COMPANION_PREFIX.length + 1) : arr.path).split(
      ".",
    )[0];
    if (!table || !column || arr.path.split(".").length > (inCompanion ? 2 : 1)) continue;
    const rows = await q(
      `SELECT json_extract(j.value, ?) AS key, count(*) AS n FROM ${qi(table.id)}, json_each(${qi(table.id)}.${qi(column)}) AS j GROUP BY key ORDER BY n DESC`,
      [`$.${arr.keyField}`],
    );
    for (const r of rows) {
      if (r.key === null) continue;
      for (const e of Object.values(catalog.entries)) {
        if (!e.comparable || !e.path.startsWith(`${arr.path}.*.`)) continue;
        out.push({
          path: e.path.replace(`${arr.path}.*.`, `${arr.path}.${String(r.key)}.`),
          key: e.path,
          count: Number(r.n ?? 0),
        });
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Search

export type SearchHit = {
  series: string;
  id: string;
  name: string;
  subtitle: string;
  score: number;
};

/** FTS5 match expression: every word as a prefix, or the squashed query as one. */
export function ftsQuery(query: string): string | null {
  const words = query
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .slice(0, 6);
  if (!words.length) return null;
  const all = words.map((w) => `"${w}"*`).join(" ");
  const squashed = words.join("");
  return words.length > 1 ? `(${all}) OR "${squashed}"*` : all;
}

export async function searchReference(q: Query, query: string, limit = 120): Promise<SearchHit[]> {
  const match = ftsQuery(query);
  if (!match) return [];
  const rows = await q(
    `SELECT s.series AS series, s.id AS id, s.name AS name, s.subtitle AS subtitle,
            bm25(search_fts, 8.0, 2.0, 1.0) AS score
       FROM search_fts JOIN search s ON s.rowid = search_fts.rowid
      WHERE search_fts MATCH ? AND s.series <> 'api' ORDER BY score LIMIT ?`,
    [match, limit],
  );
  return rows.map((r) => ({
    series: String(r.series),
    id: String(r.id),
    name: String(r.name),
    subtitle: String(r.subtitle ?? ""),
    score: -Number(r.score ?? 0),
  }));
}
