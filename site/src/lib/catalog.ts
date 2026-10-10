/**
 * The field catalog: every schema field a series' records can carry, keyed by path,
 * built from dcs-world-schema/types/entities/*.yaml. Shared by the data build (values
 * files, facets) and the client renderer (labels, units, descriptions, kinds).
 */
import { isRecord, type Json } from "./json";
import { findRangePair, isRangeList } from "./record-tables";
import { seriesForRef } from "./series";
import { capitalise } from "./text";
import {
  type CatalogEntry,
  type EnumInfo,
  type FieldKind,
  SCALAR_KINDS,
  type SeriesCatalog,
} from "./types";
import { resolveConversions, stripUnitSuffix, unitFor } from "./units";

/** The subset of a schema YAML file the catalog reads. */
export type SchemaField = { type: string; description?: string; ref?: string };
export type SchemaType = {
  kind: string;
  description?: string;
  fields?: Record<string, SchemaField>;
  values?: Record<string, string | number>;
  arrayOf?: string;
};
export type SchemaTypes = Record<string, SchemaType>;

/** The prefix companion-series fields take on the parent's page and in field paths. */
export const COMPANION_PREFIX = "flight";

/** What the companion's fields are called on the parent's page: `entries[COMPANION_PREFIX].label`. */
const COMPANION_LABEL = "Flight model";

/** Bookkeeping, not reference data: the per-field provenance map (read as data, for tooltips). */
const SKIP = new Set(["_source"]);

/**
 * The schema does not mark these; the names below are the only input to the catalog's
 * marks (`role`, `keyField`, `axis`, `layout`, `titleFields`, `countFields`), which renderers read.
 */

/** Root fields that name a record, the first present winning (catalog `titleFields`). */
const RECORD_TITLES = ["displayName", "name"];

/** Where the record was read from in the DCS Lua dump: the `provenance` role. */
const PROVENANCE = new Set(["sourcePaths", "sourcePath"]);

/** Arrays of records addressed by a key field (`flight.motorStages.march.impulseS`). */
const KEYED_ARRAYS: Record<string, string> = { motorStages: "stage" };

/** Numeric columns that index the other columns of a table (`table[].mach`). */
const AXIS_COLUMNS = ["mach"];

/** A Mach-sampled coefficient's step: its record's `machStep`, else DCS's default. */
const MACH_STEP = { field: "machStep", fallback: 0.2 };
const MACH_LABEL = "Mach";

/** Record types holding traverse sectors (`layout: "sectors"`). */
const SECTOR_TYPES = new Set(["Entity.AngleSector"]);

/** Descriptions of string fields holding a game asset's path (`role: "asset"`). */
const ASSET =
  /\b(?:image|texture|model) (?:file|path)\b|^(?:Optional\s+)?(?:script path|path of\b.*`[^`]+\.\w+`)/i;

/** Item fields that name a list item (`ammoName`), and counts shown beside it (`ammoCapacity`). */
const TITLE_FIELD = /Name$/;
const COUNT_FIELD = /capacity$/i;

/** Labels the field name alone does not make readable. */
const LABELS: Record<string, string> = {
  categoryName: "Category",
  subcategoryName: "Kind",
  seekerTypeName: "Guidance",
  launcherCategoryName: "Launcher category",
  category: "Category code",
  subcategory: "Kind code",
  seekerType: "Seeker head code",
  launcherCategory: "Launcher category code",
  className: "Simulation class",
  rangeKm: "Max range",
  rangeMinKm: "Min range",
  rangeField: "Max range source",
  rangeMinField: "Min range source",
  launchRangeMaxKm: "Max launch distance",
  rangeMaxM: "Max range (AI)",
  machMax: "Max Mach",
  fovRad: "Field of view",
  cxCoeff: "Drag coefficients",
  warhead2: "Second warhead",
  gLoadLimit: "Load limit",
  ix: "Roll inertia (Ix)",
  iy: "Yaw inertia (Iy)",
  iz: "Pitch inertia (Iz)",
  sourcePaths: "Source",
  sourcePath: "Source block",
  displayName: "Display name",
  rcsM2: "Radar cross-section",
  v0Ms: "Muzzle velocity",
  hMaxM: "Service ceiling",
  nyMax: "Max load factor",
  cx0: "Zero-lift drag",
  cya: "Normal force slope",
  natoName: "NATO name",
  rwrSymbol: "RWR symbol",
  clsid: "CLSID",
  typeName: "Type",
  idName: "Constant",
};

const ACRONYMS: Record<string, string> = {
  ir: "IR",
  pn: "PN",
  rwr: "RWR",
  alic: "ALIC",
  nato: "NATO",
  aoa: "AoA",
  g: "G",
  rcs: "RCS",
  ecm: "ECM",
  ils: "ILS",
  tacan: "TACAN",
  vor: "VOR",
  ndb: "NDB",
  icls: "ICLS",
  id: "ID",
  ai: "AI",
  sfm: "SFM",
  rpm: "RPM",
  ws: "WS",
  irst: "IRST",
  cas: "CAS",
  tv: "TV",
  dcs: "DCS",
  clsid: "CLSID",
  eplrs: "EPLRS",
  cmds: "CMDS",
  hf: "HF",
  vhf: "VHF",
  uhf: "UHF",
  fm: "FM",
  am: "AM",
};

export function humanize(name: string): string {
  const words = stripUnitSuffix(name.replace(/^_+/, ""))
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/_/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.toLowerCase());
  return capitalise(words.join(" ") || name);
}

/** A schema description as shown: `Optional x` reads `X` (optional is the norm). */
export function cleanDescription(description: string): string {
  return description.replace(/^Optional\s+(\w)/, (_, c: string) => c.toUpperCase());
}

/** `Optional zero-lift drag coefficient per Mach sample (`Cx0`).` -> `Zero-lift drag coefficient`. */
export function labelFromDescription(description: string): string {
  const text = description
    .replace(/;?\s*unit not stated\.?\s*$/, "")
    .replace(/^Optional\s+/, "")
    .replace(/\s*\([^)]*\)\.?\s*$/, "")
    .replace(/\s+per Mach sample/, "")
    .replace(/;.*$/, "")
    .trim();
  return capitalise(text);
}

/** The DCS key a field reads: "... (`key`)." at the end, or "Optional `key`, ..." at the start. */
export function dcsKeyFromDescription(description: string): string | null {
  const text = description.trim();
  const tail = /\(`([^`/]+)`(?:,? else `[^`]+`)?\)[.;]?\s*(?:unit not stated\.?)?$/.exec(text);
  // `_source.band: hand-authored` is provenance, not a DCS key.
  if (tail?.[1]) return tail[1].startsWith("_source") ? null : tail[1];
  const head = /^(?:Optional\s+)?(?:DCS\s+)?`([^`/\s]+)`[,:]/.exec(text);
  return head?.[1] ?? null;
}

/** Enum display: `SENSOR_RADAR` -> `Radar`, `wsType_AA_Missile` -> `AA missile`. */
export function enumConstantLabel(constant: string): string {
  const parts = constant
    .replace(/^wsType_/, "")
    .replace(
      /^(SENSOR|OPTIC_SENSOR|RADAR|MODULATIONTYPE|MODULATION|BEACON_TYPE|CAT|SystemName)_/,
      "",
    )
    .split(/_+/)
    .filter(Boolean)
    .map((w) => {
      const lower = w.toLowerCase();
      if (ACRONYMS[lower]) return ACRONYMS[lower];
      if (/^[A-Z0-9]{2,4}$/.test(w) && w.length <= 3) return w;
      // Slashed acronyms keep their case: `V/UHF`, `VOR/DME`.
      if (/^[A-Z0-9]{1,4}(\/[A-Z0-9]{1,4})+$/.test(w)) return w;
      return lower;
    });
  return capitalise(parts.join(" ") || constant);
}

const isRecordType = (types: SchemaTypes, t: string) => types[t]?.kind === "record";
const isEnumType = (types: SchemaTypes, t: string) => types[t]?.kind === "enum";

function enumTypesOf(types: SchemaTypes, type: string): string[] {
  return type
    .split("|")
    .map((t) => t.trim())
    .filter((t) => isEnumType(types, t));
}

/**
 * For `xName` string fields beside a numeric or enum `x` (and `string[]` beside `x[]`):
 * the enum type(s) of `x` ("" when `x` is a plain number), else null.
 */
function constantSibling(types: SchemaTypes, owner: string, name: string): string | null {
  if (!name.endsWith("Name") || RECORD_TITLES.includes(name)) return null;
  const own = types[owner]?.fields?.[name]?.type.trim();
  const sibling = types[owner]?.fields?.[name.slice(0, -4)];
  if (!sibling || sibling.ref || sibling.type.startsWith("country.id")) return null;
  const list = own === "string[]";
  const type = sibling.type.trim();
  if (list !== type.endsWith("[]")) return null;
  const base = list ? type.slice(0, -2) : type;
  const enums = enumTypesOf(types, base);
  if (enums.length) return enums.join(" | ");
  return base === "number" ? "" : null;
}

type Walk = {
  types: SchemaTypes;
  resolveRef: (ref: string) => string[];
  entries: Record<string, CatalogEntry>;
  /** The catalog's `types`, filled as the walk reaches each type. */
  outTypes: SeriesCatalog["types"];
  /** The catalog so far, for lib/record-tables (a subtree is complete once walked). */
  shapes: Pick<SeriesCatalog, "types" | "entries">;
  usedTypes: Set<string>;
  usedEnums: Set<string>;
};

function addField(
  w: Walk,
  owner: string,
  name: string,
  field: SchemaField,
  path: string,
  insideArray: boolean,
  parentUnit: string | null = null,
) {
  const { types } = w;
  const type = field.type.trim();
  const description = field.description ?? "";
  const base = type.replace(/(\[\])+$/, "");
  const depth = (type.match(/\[\]/g) ?? []).length;
  // A unit on a record field (`slewRateRadS: {yaw, pitch}`) holds for its unsuffixed members.
  const unit = unitFor(name) ?? parentUnit;
  const unitNotStated = /unit not stated/.test(description);
  let kind: FieldKind;
  const extra: Partial<CatalogEntry> = {};

  const refSeries = field.ref
    ? w.resolveRef(field.ref)
    : base === "country.id"
      ? ["countries"]
      : null;

  if (refSeries?.length) {
    kind = depth === 0 ? "ref" : "strings";
    extra.ref = refSeries;
  } else if (isRecordType(types, base) && depth === 0) {
    kind = "record";
    extra.recordType = base;
  } else if (isRecordType(types, base) && depth === 1) {
    kind = "records";
    extra.recordType = base;
    const keyField = KEYED_ARRAYS[name];
    if (keyField) extra.keyField = keyField;
    const fields = Object.entries(types[base]?.fields ?? {});
    const column = AXIS_COLUMNS.find((c) => fields.some(([n]) => n === c));
    // Envelopes: two number[] axes and number[][] grids per item.
    const axes = fields.filter(([, f]) => f.type === "number[]").map(([n]) => n);
    const grids = fields.filter(([, f]) => f.type === "number[][]");
    if (axes.length >= 2 && grids.length) {
      extra.layout = "envelope";
      extra.axis = { kind: "surface", rows: axes[0] as string, cols: axes[1] as string };
    } else if (column) {
      extra.axis = { kind: "column", field: column, label: LABELS[column] ?? humanize(column) };
      if (!keyField) extra.layout = "axis-table";
    }
  } else if (types[base]?.kind === "array" || (depth >= 1 && isRecordType(types, base))) {
    kind = "matrix";
  } else if (enumTypesOf(types, type).length && depth === 0) {
    kind = "enum";
    extra.enumType = enumTypesOf(types, type).join(" | ");
    for (const e of enumTypesOf(types, type)) w.usedEnums.add(e);
  } else if (type === "number") kind = "number";
  else if (
    (type === "string" || type === "string[]") &&
    constantSibling(types, owner, name) !== null
  ) {
    // `categoryName` beside a numeric `category`: a DCS constant name, shown in its place.
    kind = type === "string" ? "enum" : "strings";
    extra.codeField = name.slice(0, -4);
    const sibling = constantSibling(types, owner, name);
    if (sibling) {
      extra.enumType = sibling;
      for (const e of sibling.split(" | ")) w.usedEnums.add(e);
    }
  } else if (type === "string") kind = "string";
  else if (type === "boolean") kind = "boolean";
  else if (type === "number[]") {
    kind = "numbers";
    if (/per Mach sample/i.test(description)) {
      extra.axis = { kind: "sampled", step: { ...MACH_STEP }, label: MACH_LABEL };
    }
  } else if (type === "string[]") kind = "strings";
  else if (type === "number[][]") kind = "grid";
  else kind = "any";

  if (SECTOR_TYPES.has(type.replace(/\[\]$/, ""))) extra.layout = "sectors";
  if (PROVENANCE.has(name)) extra.role = "provenance";
  else if ((kind === "string" || kind === "strings") && ASSET.test(description)) {
    extra.role = "asset";
  }
  const comparable =
    !insideArray &&
    extra.role !== "provenance" &&
    (SCALAR_KINDS.has(kind) || kind === "numbers" || (kind === "strings" && Boolean(extra.ref)));

  const withUnit = kind === "number" || kind === "numbers" || kind === "grid" || kind === "matrix";
  const label =
    kind === "numbers" && extra.axis?.kind === "sampled"
      ? labelFromDescription(description)
      : (LABELS[name] ?? humanize(extra.codeField ?? name));

  w.entries[path] = {
    path,
    name,
    label,
    type,
    kind,
    unit: withUnit ? unit : null,
    ...(withUnit && unit ? { conversions: resolveConversions(unit, name) } : {}),
    unitNotStated,
    description: cleanDescription(description),
    dcsKey: dcsKeyFromDescription(description),
    owner,
    comparable,
    ...extra,
  };

  if (kind === "record") walkType(w, base, path, insideArray, unit);
  if (kind === "records") {
    const item = extra.keyField ? `${path}.*` : `${path}[]`;
    walkType(w, base, item, insideArray || !extra.keyField);
    const names = w.outTypes[base]?.fields ?? [];
    const entry = w.entries[path] as CatalogEntry;
    const itemEntry = (n: string) => w.entries[`${item}.${n}`];
    const titles = names.filter((n) => TITLE_FIELD.test(n) && itemEntry(n)?.kind === "string");
    const counts = names.filter((n) => COUNT_FIELD.test(n) && itemEntry(n)?.kind === "number");
    if (titles.length) entry.titleFields = titles;
    if (counts.length) entry.countFields = counts;
    // Lists of links (station accepts: `clsid`), read item by item.
    const link = extra.keyField ? undefined : names.find((n) => itemEntry(n)?.kind === "ref");
    if (link) {
      entry.linkField = link;
      const lists = names.filter((n) => itemEntry(n)?.kind === "strings" && itemEntry(n)?.ref);
      if (lists.length) entry.linkListFields = lists;
    }
    const pair = findRangePair(w.shapes, base, item);
    if (pair && isRangeList(w.shapes, entry, path)) {
      entry.layout = "ranges";
      entry.rangePair = { min: pair.min.path, max: pair.max.path };
    }
    // Envelopes compare each grid as a surface; axis tables each numeric column as a curve.
    if (extra.axis && extra.axis.kind !== "sampled" && !insideArray && !extra.keyField) {
      const fields = types[base]?.fields ?? {};
      for (const [n, f] of Object.entries(fields)) {
        const column = itemEntry(n);
        if (!column) continue;
        const compares =
          extra.axis.kind === "surface"
            ? f.type === "number[][]"
            : n !== extra.axis.field && f.type === "number";
        if (compares) {
          column.comparable = true;
          column.axis = extra.axis;
        }
      }
    }
  }
}

/** A min/max record beside a `ranges` list only bounds it (a radio's `range`): `bounds`. */
function markBounds(w: Walk, typeName: string, prefix: string) {
  const at = (name: string) => w.entries[prefix ? `${prefix}.${name}` : name];
  const fields = w.outTypes[typeName]?.fields ?? [];
  const list = fields.map(at).find((e) => e?.layout === "ranges");
  if (!list) return;
  for (const name of fields) {
    const e = at(name);
    if (e?.kind !== "record" || !e.recordType) continue;
    if (w.outTypes[e.recordType]?.fields.length !== 2) continue;
    if (findRangePair(w.shapes, e.recordType, e.path)) e.bounds = list.path;
  }
}

function walkType(
  w: Walk,
  typeName: string,
  prefix: string,
  insideArray: boolean,
  parentUnit: string | null = null,
) {
  const type = w.types[typeName];
  if (!type?.fields) return;
  if (w.usedTypes.has(`${typeName}@${prefix}`)) return;
  w.usedTypes.add(`${typeName}@${prefix}`);
  w.outTypes[typeName] ??= {
    description: type.description ?? "",
    fields: Object.keys(type.fields).filter((f) => !SKIP.has(f)),
  };
  for (const [name, field] of Object.entries(type.fields)) {
    if (SKIP.has(name)) continue;
    const path = prefix ? `${prefix}.${name}` : name;
    addField(w, typeName, name, field, path, insideArray, parentUnit);
  }
  markBounds(w, typeName, prefix);
}

/** The catalog of a series, with its companion's fields under `flight.` when it has one. */
export function buildSeriesCatalog(
  types: SchemaTypes,
  series: string,
  rootType: string,
  companion?: { type: string },
  /** Series a schema `ref` names; by default the site's known series. */
  resolveRef: (ref: string) => string[] = seriesForRef,
): SeriesCatalog {
  const entries: Record<string, CatalogEntry> = {};
  const outTypes: SeriesCatalog["types"] = {};
  const w: Walk = {
    types,
    resolveRef,
    entries,
    outTypes,
    shapes: { types: outTypes, entries },
    usedTypes: new Set(),
    usedEnums: new Set(),
  };
  if (!types[rootType]) throw new Error(`Schema has no type ${rootType} (series ${series})`);
  walkType(w, rootType, "", false);
  if (companion) {
    if (!types[companion.type]) throw new Error(`Schema has no type ${companion.type}`);
    w.entries[COMPANION_PREFIX] = {
      path: COMPANION_PREFIX,
      name: COMPANION_PREFIX,
      label: COMPANION_LABEL,
      type: companion.type,
      kind: "record",
      unit: null,
      unitNotStated: false,
      description: cleanDescription(types[companion.type]?.description ?? ""),
      dcsKey: null,
      owner: rootType,
      comparable: false,
      recordType: companion.type,
    };
    walkType(w, companion.type, COMPANION_PREFIX, false);
  }
  const enums: Record<string, EnumInfo> = {};
  for (const e of w.usedEnums) {
    enums[e] = { description: types[e]?.description ?? "", values: types[e]?.values ?? {} };
  }
  const titleFields = RECORD_TITLES.filter((n) => entries[n]);
  return { series, rootType, entries, types: outTypes, enums, titleFields };
}

// ---------------------------------------------------------------------------
// Paths and values

/**
 * `flight.motorStages.march.impulseS` -> `flight.motorStages.*.impulseS` (the catalog key),
 * or the path itself when it is a key.
 */
export function catalogKeyFor(
  path: string,
  catalog: Pick<SeriesCatalog, "entries">,
): string | null {
  if (catalog.entries[path]) return path;
  const parts = path.split(".");
  for (let i = 0; i < parts.length; i++) {
    const candidate = [...parts.slice(0, i), "*", ...parts.slice(i + 1)].join(".");
    if (catalog.entries[candidate]) return candidate;
  }
  return null;
}

/** The root a path reads from: the record, or its companion for `flight.` paths. */
export function rootFor<T>(path: string, data: T, companion: T | undefined) {
  if (path === COMPANION_PREFIX || path.startsWith(`${COMPANION_PREFIX}.`)) {
    return { root: companion, rest: path.slice(COMPANION_PREFIX.length + 1) };
  }
  return { root: data, rest: path };
}

/**
 * Every concrete value of a catalog key: plain paths give one, keyed paths one per key,
 * axis columns (`table[].cx0`) one `{ x, y }` curve.
 */
export function valuesAt(
  entry: CatalogEntry,
  catalog: Pick<SeriesCatalog, "entries">,
  data: Json,
  companion?: Json,
): Array<{ path: string; value: unknown }> {
  const { root, rest } = rootFor(entry.path, data, companion);
  if (!root) return [];
  const prefix = entry.path.slice(0, entry.path.length - rest.length);
  const axis = entry.path.includes("[].") ? entry.axis : undefined;
  if (axis?.kind === "surface") {
    const [tablePath, column] = entry.path.split("[].") as [string, string];
    const items = getPath(root, tablePath.slice(prefix.length));
    if (!Array.isArray(items)) return [];
    const surfaces = items
      .filter(isRecord)
      .filter((it) => Array.isArray(it[column]))
      .map((it) => ({ rows: it[axis.rows], cols: it[axis.cols], z: it[column] }));
    return surfaces.length ? [{ path: entry.path, value: surfaces }] : [];
  }
  if (axis?.kind === "column") {
    const [tablePath, column] = entry.path.split("[].") as [string, string];
    const rows = getPath(root, tablePath.slice(prefix.length));
    if (!Array.isArray(rows)) return [];
    const x: number[] = [];
    const y: number[] = [];
    for (const row of rows) {
      if (!isRecord(row)) continue;
      const xv = row[axis.field];
      const yv = row[column];
      if (typeof xv === "number" && typeof yv === "number") {
        x.push(xv);
        y.push(yv);
      }
    }
    return x.length ? [{ path: entry.path, value: { x, y } }] : [];
  }
  const out: Array<{ path: string; value: unknown }> = [];
  // `keyed` is the catalog path walked so far: a `*` reads its array's `keyField`.
  const walk = (node: unknown, segments: string[], concrete: string[], keyed: string) => {
    if (segments.length === 0) {
      if (node === undefined || node === null) return;
      if (Array.isArray(node) && node.length === 0) return;
      out.push({ path: concrete.join("."), value: node });
      return;
    }
    const [head, ...tail] = segments as [string, ...string[]];
    const here = keyed ? `${keyed}.${head}` : head;
    if (head === "*") {
      if (!Array.isArray(node)) return;
      const keyField = catalog.entries[keyed]?.keyField ?? "key";
      for (const item of node) {
        if (!isRecord(item)) continue;
        walk(item, tail, [...concrete, String(item[keyField])], here);
      }
      return;
    }
    if (!isRecord(node)) return;
    walk(node[head], tail, [...concrete, head], here);
  };
  const start = prefix ? [prefix.replace(/\.$/, "")] : [];
  walk(root, rest.split("."), start, start.join("."));
  return out;
}

/** Plain dotted path lookup (no arrays). */
export function getPath(node: unknown, path: string): unknown {
  if (!path) return node;
  let cur: unknown = node;
  for (const seg of path.split(".")) {
    if (!isRecord(cur)) return undefined;
    cur = cur[seg];
  }
  return cur;
}

/** Comparable values of a record, by concrete path. */
export function comparableValues(
  catalog: SeriesCatalog,
  data: Json,
  companion?: Json,
): Array<{ path: string; key: string; value: unknown }> {
  const out: Array<{ path: string; key: string; value: unknown }> = [];
  for (const entry of Object.values(catalog.entries)) {
    if (!entry.comparable) continue;
    for (const v of valuesAt(entry, catalog, data, companion)) {
      out.push({ path: v.path, key: entry.path, value: v.value });
    }
  }
  return out;
}
