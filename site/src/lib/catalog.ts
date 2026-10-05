/**
 * The field catalog: every schema field a series' records can carry, keyed by path,
 * built from dcs-world-schema/types/entities/*.yaml. Shared by the data build (values
 * files, facets) and the client renderer (labels, units, descriptions, kinds).
 */
import { seriesForRef } from "./series";
import type { CatalogEntry, EnumInfo, FieldKind, SeriesCatalog } from "./types";
import { stripUnitSuffix, unitFor } from "./units";

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

/** Bookkeeping, not reference data. */
const SKIP = new Set(["_source"]);

/** Arrays of records addressed by a key field (`flight.motorStages.march.impulseS`). */
export const KEYED_ARRAYS: Record<string, string> = { motorStages: "stage" };

/** Numeric columns that index the other columns of a table (`table[].mach`). */
const AXIS_COLUMNS = ["mach"];

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
  const label = words.join(" ") || name;
  return label.charAt(0).toUpperCase() + label.slice(1);
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
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The DCS key a field reads: "... (`key`)." at the end, or "Optional `key`, ..." at the start. */
export function dcsKeyFromDescription(description: string): string | null {
  const text = description.trim();
  const tail = /\(`([^`/]+)`(?:,? else `[^`]+`)?\)[.;]?\s*(?:unit not stated\.?)?$/.exec(text);
  if (tail?.[1]) return tail[1];
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
      return lower;
    });
  const label = parts.join(" ") || constant;
  return label.charAt(0).toUpperCase() + label.slice(1);
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
 * For `xName` string fields beside a numeric or enum `x`: the enum type(s) of `x`
 * ("" when `x` is a plain number), else null.
 */
function constantSibling(types: SchemaTypes, owner: string, name: string): string | null {
  if (!name.endsWith("Name") || name === "displayName") return null;
  const sibling = types[owner]?.fields?.[name.slice(0, -4)];
  if (!sibling || sibling.ref || sibling.type.startsWith("country.id")) return null;
  const enums = enumTypesOf(types, sibling.type);
  if (enums.length) return enums.join(" | ");
  return sibling.type === "number" ? "" : null;
}

type Walk = {
  types: SchemaTypes;
  resolveRef: (ref: string) => string[];
  entries: Record<string, CatalogEntry>;
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
) {
  const { types } = w;
  const type = field.type.trim();
  const description = field.description ?? "";
  const base = type.replace(/(\[\])+$/, "");
  const depth = (type.match(/\[\]/g) ?? []).length;
  const unit = unitFor(name);
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
    const columns = Object.keys(types[base]?.fields ?? {});
    const axis = AXIS_COLUMNS.find((c) => columns.includes(c));
    if (axis) extra.axis = axis;
  } else if (types[base]?.kind === "array" || (depth >= 1 && isRecordType(types, base))) {
    kind = "matrix";
  } else if (enumTypesOf(types, type).length && depth === 0) {
    kind = "enum";
    extra.enumType = enumTypesOf(types, type).join(" | ");
    for (const e of enumTypesOf(types, type)) w.usedEnums.add(e);
  } else if (type === "number") kind = "number";
  else if (type === "string" && constantSibling(types, owner, name) !== null) {
    // `categoryName` beside a numeric `category`: a DCS constant name.
    kind = "enum";
    const sibling = constantSibling(types, owner, name);
    if (sibling) {
      extra.enumType = sibling;
      for (const e of sibling.split(" | ")) w.usedEnums.add(e);
    }
  } else if (type === "string") kind = "string";
  else if (type === "boolean") kind = "boolean";
  else if (type === "number[]") {
    kind = "numbers";
    if (/per Mach sample/i.test(description)) extra.axis = "mach";
  } else if (type === "string[]") kind = "strings";
  else if (type === "number[][]") kind = "grid";
  else kind = "any";

  const comparable =
    !insideArray &&
    !/^sourcePaths?$/.test(name) &&
    (kind === "number" ||
      kind === "string" ||
      kind === "boolean" ||
      kind === "enum" ||
      kind === "ref" ||
      kind === "numbers" ||
      (kind === "strings" && Boolean(extra.ref)));

  const label =
    kind === "numbers" && extra.axis === "mach"
      ? labelFromDescription(description)
      : (LABELS[name] ?? humanize(name));

  w.entries[path] = {
    path,
    name,
    label,
    type,
    kind,
    unit: kind === "number" || kind === "numbers" || kind === "grid" ? unit : null,
    unitNotStated,
    description,
    dcsKey: dcsKeyFromDescription(description),
    owner,
    comparable,
    ...extra,
  };

  if (kind === "record") walkType(w, base, path, insideArray);
  if (kind === "records") {
    if (extra.keyField) walkType(w, base, `${path}.*`, insideArray);
    else walkType(w, base, `${path}[]`, true);
    // Envelopes (two number[] axes and number[][] grids): each grid compares as a surface.
    const fields = Object.entries(types[base]?.fields ?? {});
    const axes = fields.filter(([, f]) => f.type === "number[]").map(([n]) => n);
    const grids = fields.filter(([, f]) => f.type === "number[][]").map(([n]) => n);
    if (!insideArray && !extra.keyField && axes.length >= 2 && grids.length) {
      for (const g of grids) {
        const entry = w.entries[`${path}[].${g}`];
        if (!entry) continue;
        entry.comparable = true;
        entry.axis = `grid:${axes[0]},${axes[1]}`;
      }
    }
    // Axis tables: each numeric column compares as a curve over the axis.
    if (extra.axis && !insideArray && !extra.keyField) {
      for (const [col, f] of Object.entries(types[base]?.fields ?? {})) {
        const entry = w.entries[`${path}[].${col}`];
        if (entry && col !== extra.axis && f.type === "number") {
          entry.comparable = true;
          entry.axis = extra.axis;
        }
      }
    }
  }
}

function walkType(w: Walk, typeName: string, prefix: string, insideArray: boolean) {
  const type = w.types[typeName];
  if (!type?.fields) return;
  if (w.usedTypes.has(`${typeName}@${prefix}`)) return;
  w.usedTypes.add(`${typeName}@${prefix}`);
  for (const [name, field] of Object.entries(type.fields)) {
    if (SKIP.has(name)) continue;
    const path = prefix ? `${prefix}.${name}` : name;
    addField(w, typeName, name, field, path, insideArray);
  }
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
  const w: Walk = { types, resolveRef, entries: {}, usedTypes: new Set(), usedEnums: new Set() };
  if (!types[rootType]) throw new Error(`Schema has no type ${rootType} (series ${series})`);
  walkType(w, rootType, "", false);
  if (companion) {
    if (!types[companion.type]) throw new Error(`Schema has no type ${companion.type}`);
    w.entries[COMPANION_PREFIX] = {
      path: COMPANION_PREFIX,
      name: COMPANION_PREFIX,
      label: "Flight model",
      type: companion.type,
      kind: "record",
      unit: null,
      unitNotStated: false,
      description: types[companion.type]?.description ?? "",
      dcsKey: null,
      owner: rootType,
      comparable: false,
      recordType: companion.type,
    };
    walkType(w, companion.type, COMPANION_PREFIX, false);
  }
  const typeNames = new Set([...w.usedTypes].map((t) => t.split("@")[0] ?? t));
  const outTypes: SeriesCatalog["types"] = {};
  for (const t of typeNames) {
    outTypes[t] = {
      description: types[t]?.description ?? "",
      fields: Object.keys(types[t]?.fields ?? {}).filter((f) => !SKIP.has(f)),
    };
  }
  const enums: Record<string, EnumInfo> = {};
  for (const e of w.usedEnums) {
    enums[e] = { description: types[e]?.description ?? "", values: types[e]?.values ?? {} };
  }
  return { series, rootType, entries: w.entries, types: outTypes, enums, fieldPaths: [] };
}

// ---------------------------------------------------------------------------
// Paths and values

type Json = Record<string, unknown>;

export function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

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
function rootFor(path: string, data: Json, companion: Json | undefined) {
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
  if (entry.axis?.startsWith("grid:") && entry.path.includes("[].")) {
    const [tablePath, column] = entry.path.split("[].") as [string, string];
    const [rowField, colField] = entry.axis.slice(5).split(",") as [string, string];
    const items = getPath(root, tablePath.slice(prefix.length));
    if (!Array.isArray(items)) return [];
    const surfaces = items
      .filter(isRecord)
      .filter((it) => Array.isArray(it[column]))
      .map((it) => ({ rows: it[rowField], cols: it[colField], z: it[column] }));
    return surfaces.length ? [{ path: entry.path, value: surfaces }] : [];
  }
  if (entry.axis && entry.path.includes("[].")) {
    const [tablePath, column] = entry.path.split("[].") as [string, string];
    const tableEntry = catalog.entries[tablePath];
    const rows = getPath(root, tablePath.slice(prefix.length));
    if (!Array.isArray(rows) || !tableEntry?.axis) return [];
    const x: number[] = [];
    const y: number[] = [];
    for (const row of rows) {
      if (!isRecord(row)) continue;
      const xv = row[tableEntry.axis];
      const yv = row[column];
      if (typeof xv === "number" && typeof yv === "number") {
        x.push(xv);
        y.push(yv);
      }
    }
    return x.length ? [{ path: entry.path, value: { x, y } }] : [];
  }
  const out: Array<{ path: string; value: unknown }> = [];
  const walk = (node: unknown, segments: string[], concrete: string[], parent: string) => {
    if (segments.length === 0) {
      if (node === undefined || node === null) return;
      if (Array.isArray(node) && node.length === 0) return;
      out.push({ path: concrete.join("."), value: node });
      return;
    }
    const [head, ...tail] = segments as [string, ...string[]];
    if (head === "*") {
      if (!Array.isArray(node)) return;
      const keyField = KEYED_ARRAYS[parent] ?? "key";
      for (const item of node) {
        if (!isRecord(item)) continue;
        walk(item, tail, [...concrete, String(item[keyField])], head);
      }
      return;
    }
    if (!isRecord(node)) return;
    walk(node[head], tail, [...concrete, head], head);
  };
  const start = prefix ? [prefix.replace(/\.$/, "")] : [];
  walk(root, rest.split("."), start, "");
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

/** Value of a concrete path (`flight.motorStages.march.impulseS`, `aero.massKg`). */
export function valueAtConcrete(
  path: string,
  catalog: Pick<SeriesCatalog, "entries">,
  data: Json,
  companion?: Json,
): unknown {
  const key = catalogKeyFor(path, catalog);
  const entry = key ? catalog.entries[key] : undefined;
  if (!entry) return undefined;
  return valuesAt(entry, catalog, data, companion).find((v) => v.path === path)?.value;
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
