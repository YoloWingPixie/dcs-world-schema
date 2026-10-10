/**
 * The field catalog: every schema field a series' records can carry, keyed by path,
 * built from dcs-world-schema/types/entities/*.yaml. Shared by the data build (values
 * files, facets) and the client renderer (labels, units, descriptions, kinds).
 */
import { isRecord, type Json, present } from "./json";
import {
  complexFields,
  curveOf,
  recordFields,
  samplesOf,
  surfacesOf,
  tableColumns,
} from "./record-tables";
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

/** What a catalog calls its companion's fields ("Flight model"). */
export const companionLabel = (catalog: Pick<SeriesCatalog, "entries">) =>
  catalog.entries[COMPANION_PREFIX]?.label ?? COMPANION_PREFIX;

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

/** Words shown in capitals (or their own case), by their lower-case form. */
export const ACRONYMS: Readonly<Record<string, string>> = {
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

// ---------------------------------------------------------------------------
// The walk: one bare entry per schema field, nothing that depends on other fields

/** A field too rich for a table cell: a nested table (`records`, `matrix`). */
export const holdsTable = (entry: CatalogEntry) =>
  entry.kind === "records" || entry.kind === "matrix";

/** What the walk knew of an entry that the catalog does not keep, for the mark passes. */
type Found = {
  /** Schema type as written (`number[]`, `Entity.Station[]`). */
  type: string;
  /** Inside an array of records: one value per item, so not one comparable value. */
  insideArray: boolean;
};

type Walk = {
  types: SchemaTypes;
  resolveRef: (ref: string) => string[];
  entries: Record<string, CatalogEntry>;
  found: Map<string, Found>;
  /** The catalog's `types`, filled as the walk reaches each type. */
  outTypes: SeriesCatalog["types"];
  /** Each record value walked: its type and catalog path ("" at the root). */
  records: Array<{ typeName: string; prefix: string }>;
  usedTypes: Set<string>;
  usedEnums: Set<string>;
};

/** The entry of one field and the walk of its record type, if it has one. */
function addField(
  w: Walk,
  owner: string,
  name: string,
  field: SchemaField,
  path: string,
  insideArray: boolean,
  parentUnit: string | null,
) {
  const { types } = w;
  const type = field.type.trim();
  const description = field.description ?? "";
  const base = type.replace(/(\[\])+$/, "");
  const depth = (type.match(/\[\]/g) ?? []).length;
  // A unit on a record field (`slewRateRadS: {yaw, pitch}`) holds for its unsuffixed members.
  const unit = unitFor(name) ?? parentUnit;
  let kind: FieldKind;
  const extra: Partial<CatalogEntry> = {};

  const refSeries = field.ref
    ? w.resolveRef(field.ref)
    : base === "country.id"
      ? ["countries"]
      : null;
  const enums = enumTypesOf(types, type);
  const constant =
    type === "string" || type === "string[]" ? constantSibling(types, owner, name) : null;

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
    extra.itemPath = keyField ? `${path}.*` : `${path}[]`;
  } else if (types[base]?.kind === "array" || (depth >= 1 && isRecordType(types, base))) {
    kind = "matrix";
  } else if (enums.length && depth === 0) {
    kind = "enum";
    extra.enumType = enums.join(" | ");
  } else if (type === "number") kind = "number";
  else if (constant !== null) {
    // `categoryName` beside a numeric `category`: a DCS constant name, shown in its place.
    kind = type === "string" ? "enum" : "strings";
    extra.codeField = name.slice(0, -4);
    if (constant) extra.enumType = constant;
  } else if (type === "string") kind = "string";
  else if (type === "boolean") kind = "boolean";
  else if (type === "number[]") kind = "numbers";
  else if (type === "string[]") kind = "strings";
  else if (type === "number[][]") kind = "grid";
  else kind = "any";
  for (const e of extra.enumType?.split(" | ") ?? []) w.usedEnums.add(e);

  const withUnit = kind === "number" || kind === "numbers" || kind === "grid" || kind === "matrix";
  w.entries[path] = {
    path,
    name,
    label: LABELS[name] ?? humanize(extra.codeField ?? name),
    kind,
    unit: withUnit ? unit : null,
    ...(withUnit && unit ? { conversions: resolveConversions(unit, name) } : {}),
    unitNotStated: /unit not stated/.test(description),
    description: cleanDescription(description),
    dcsKey: dcsKeyFromDescription(description),
    ...extra,
  };
  w.found.set(path, { type, insideArray });

  if (kind === "record") walkType(w, base, path, insideArray, unit);
  if (kind === "records" && extra.itemPath) {
    walkType(w, base, extra.itemPath, insideArray || !extra.keyField, null);
  }
}

function walkType(
  w: Walk,
  typeName: string,
  prefix: string,
  insideArray: boolean,
  parentUnit: string | null,
) {
  const type = w.types[typeName];
  if (!type?.fields) return;
  if (w.usedTypes.has(`${typeName}@${prefix}`)) return;
  w.usedTypes.add(`${typeName}@${prefix}`);
  w.outTypes[typeName] ??= {
    description: type.description ?? "",
    fields: Object.keys(type.fields).filter((f) => !SKIP.has(f)),
  };
  w.records.push({ typeName, prefix });
  for (const [name, field] of Object.entries(type.fields)) {
    if (SKIP.has(name)) continue;
    const path = prefix ? `${prefix}.${name}` : name;
    addField(w, typeName, name, field, path, insideArray, parentUnit);
  }
}

// ---------------------------------------------------------------------------
// Mark passes: each reads the whole walked catalog and the marks of the passes before it

type Build = Walk & {
  /** The catalog being marked, for lib/record-tables. */
  shapes: Pick<SeriesCatalog, "types" | "entries">;
  keys: string[];
};

/** The fields of a `records` entry's items: name, schema type and entry. */
function itemFields(b: Build, entry: CatalogEntry) {
  const item = entry.itemPath ?? "";
  const schema = b.types[entry.recordType ?? ""]?.fields ?? {};
  return (b.outTypes[entry.recordType ?? ""]?.fields ?? []).map((name) => ({
    name,
    type: schema[name]?.type.trim() ?? "",
    entry: b.entries[`${item}.${name}`],
  }));
}

/** The `minX` / `maxX` number pair of a record type's fields at `prefix`, if it has one. */
function findRangePair(b: Build, typeName: string, prefix: string) {
  const fields = b.outTypes[typeName]?.fields ?? [];
  for (const name of fields) {
    const rest = /^min([A-Z].*)$/.exec(name)?.[1];
    if (!rest || !fields.includes(`max${rest}`)) continue;
    const min = b.entries[`${prefix}.${name}`];
    const max = b.entries[`${prefix}.max${rest}`];
    if (min?.kind === "number" && max?.kind === "number" && min.unit === max.unit) {
      return { min, max };
    }
  }
  return null;
}

/** Most columns besides its range a list of ranges shows (more read better as a table). */
const RANGE_LIST_OTHERS = 2;

/**
 * Whether an array of records with a range pair reads as a list of ranges (radio segments):
 * no complex fields, and at most two other columns.
 */
function isRangeList(
  b: Build,
  entry: CatalogEntry,
  item: string,
  pair: { min: CatalogEntry; max: CatalogEntry },
): boolean {
  if (!entry.recordType || entry.keyField || entry.axis) return false;
  if (complexFields(b.shapes, entry.recordType, item).length) return false;
  const others = tableColumns(b.shapes, entry.recordType, item).filter(
    (c) => c.entry !== pair.min && c.entry !== pair.max,
  );
  return others.length <= RANGE_LIST_OTHERS;
}

/** A singular label for one value of a list axis ("Altitudes" -> "Altitude"). */
const singular = (label: string) => label.replace(/s$/, "");

const PASSES: Array<(b: Build, entry: CatalogEntry) => void> = [
  /** `role`: the record key, provenance, game assets. */
  function role(b, e) {
    if (b.keys.includes(e.path)) e.role = "key";
    else if (PROVENANCE.has(e.name)) e.role = "provenance";
    else if ((e.kind === "string" || e.kind === "strings") && ASSET.test(e.description)) {
      e.role = "asset";
    }
  },

  /**
   * `axis`: Mach-sampled lists; tables indexed by a column (`mach`); envelopes (two number[]
   * axes and number[][] grids per item). Outside other arrays, a table's curves and grids
   * carry its axis too: they compare as curves and surfaces.
   */
  function axis(b, e) {
    const found = b.found.get(e.path);
    if (
      e.kind === "numbers" &&
      found?.type === "number[]" &&
      /per Mach sample/i.test(e.description)
    ) {
      e.axis = { kind: "sampled", step: { ...MACH_STEP }, label: MACH_LABEL };
      return;
    }
    if (e.kind !== "records" || !e.itemPath || !found) return;
    const item = e.itemPath;
    const fields = itemFields(b, e).filter((f) => f.entry);
    const lists = fields.filter((f) => f.type === "number[]").map((f) => f.name);
    const grids = fields.filter((f) => f.type === "number[][]");
    const column = AXIS_COLUMNS.find((c) => fields.some((f) => f.name === c));
    const paths = (names: string[]) => names.map((n) => `${item}.${n}`);
    if (lists.length >= 2 && grids.length) {
      const [rows, cols] = lists as [string, string];
      const label = (n: string) => singular(b.entries[`${item}.${n}`]?.label ?? n);
      e.axis = {
        kind: "surface",
        table: e.path,
        rows,
        cols,
        paths: { rows: `${item}.${rows}`, cols: `${item}.${cols}` },
        labels: { rows: label(rows), cols: label(cols) },
        columns: paths(grids.map((f) => f.name)),
      };
    } else if (column) {
      e.axis = {
        kind: "column",
        table: e.path,
        field: column,
        label: LABELS[column] ?? humanize(column),
        path: `${item}.${column}`,
        columns: paths(
          fields.filter((f) => f.name !== column && f.type === "number").map((f) => f.name),
        ),
      };
    } else return;
    if (found.insideArray || e.keyField) return;
    const axis = e.axis;
    for (const path of axis.columns) {
      const curve = b.entries[path];
      if (curve) curve.axis = axis;
    }
  },

  /**
   * `layout`: envelopes, axis tables, traverse sectors, lists of ranges, one list per item,
   * cards for items holding nested tables.
   */
  function layout(b, e) {
    const found = b.found.get(e.path);
    if (SECTOR_TYPES.has(found?.type.replace(/\[\]$/, "") ?? "")) e.layout = "sectors";
    if (e.kind !== "records" || !e.recordType || !e.itemPath) return;
    if (e.axis?.kind === "surface") e.layout = "envelope";
    else if (e.axis?.kind === "column" && !e.keyField) e.layout = "axis-table";
    const pair = findRangePair(b, e.recordType, e.itemPath);
    if (pair && isRangeList(b, e, e.itemPath, pair)) {
      e.layout = "ranges";
      e.rangePair = { min: pair.min.path, max: pair.max.path };
    }
    const fields = itemFields(b, e);
    if (!e.layout && fields.length === 1 && fields[0]?.entry?.kind === "strings") {
      e.layout = "list-per-item";
    }
    if (!e.layout && fields.some((f) => f.entry && holdsTable(f.entry))) e.layout = "cards";
  },

  /** `titleFields`, `countFields`, `linkField`, `linkListFields`: how a list names its items. */
  function itemNames(b, e) {
    if (e.kind !== "records") return;
    const fields = itemFields(b, e);
    const names = (test: (f: (typeof fields)[number]) => boolean) =>
      fields.filter(test).map((f) => f.name);
    const titles = names((f) => TITLE_FIELD.test(f.name) && f.entry?.kind === "string");
    const counts = names((f) => COUNT_FIELD.test(f.name) && f.entry?.kind === "number");
    if (titles.length) e.titleFields = titles;
    if (counts.length) e.countFields = counts;
    // Lists of links (station accepts: `clsid`), read item by item.
    const link = e.keyField ? undefined : fields.find((f) => f.entry?.kind === "ref")?.name;
    if (link) {
      e.linkField = link;
      const lists = names((f) => f.entry?.kind === "strings" && Boolean(f.entry.ref));
      if (lists.length) e.linkListFields = lists;
    }
  },

  /**
   * `compareAs`: one value per record (`value`), a curve (a table's column over its axis
   * column, or a Mach-sampled list over Mach at its record's step), or a table's grids as
   * surfaces.
   */
  function compareShape(b, e) {
    const found = b.found.get(e.path);
    if (e.kind !== "records" && e.axis?.kind === "column") e.compareAs = "curve";
    else if (e.kind !== "records" && e.axis?.kind === "surface") e.compareAs = "surfaces";
    else if (
      !found?.insideArray &&
      e.role !== "provenance" &&
      (SCALAR_KINDS.has(e.kind) || e.kind === "numbers" || (e.kind === "strings" && e.ref))
    ) {
      e.compareAs = e.axis?.kind === "sampled" ? "curve" : "value";
    }
  },

  /**
   * A Mach-sampled list is named by its description ("Zero-lift drag coefficient"). A
   * nested record's title field (`RECORD_TITLES`) stands alone as that record:
   * `defaultTask.name` reads "Default task".
   */
  function label(b, e) {
    if (e.kind === "numbers" && e.axis?.kind === "sampled")
      e.label = labelFromDescription(e.description);
    const dot = e.path.lastIndexOf(".");
    const holder = dot < 0 ? undefined : b.entries[e.path.slice(0, dot)];
    if (holder?.kind === "record" && RECORD_TITLES.includes(e.name) && holder.label !== e.label) {
      e.standaloneLabel = holder.label;
    }
  },
];

/** `bounds`: a min/max record beside a `ranges` list only bounds it (a radio's `range`). */
function markBounds(b: Build) {
  for (const { typeName, prefix } of b.records) {
    const at = (name: string) => b.entries[prefix ? `${prefix}.${name}` : name];
    const fields = b.outTypes[typeName]?.fields ?? [];
    const list = fields.map(at).find((e) => e?.layout === "ranges");
    if (!list) continue;
    for (const name of fields) {
      const e = at(name);
      if (e?.kind !== "record" || !e.recordType) continue;
      if (b.outTypes[e.recordType]?.fields.length !== 2) continue;
      if (findRangePair(b, e.recordType, e.path)) e.bounds = list.path;
    }
  }
}

/** A series' root record type and the column its records are keyed by (`id`, `clsid`). */
export type CatalogRoot = { type: string; keyColumn?: string };

/** The catalog of a series, with its companion's fields under `flight.` when it has one. */
export function buildSeriesCatalog(
  types: SchemaTypes,
  series: string,
  root: CatalogRoot,
  companion: CatalogRoot | undefined,
  /** Series a schema `ref` names (lib/db/reference `refResolver`). */
  resolveRef: (ref: string) => string[],
): SeriesCatalog {
  const entries: Record<string, CatalogEntry> = {};
  const outTypes: SeriesCatalog["types"] = {};
  const rootType = root.type;
  if (!types[rootType]) throw new Error(`Schema has no type ${rootType} (series ${series})`);
  if (companion && !types[companion.type]) throw new Error(`Schema has no type ${companion.type}`);
  const b: Build = {
    types,
    resolveRef,
    entries,
    found: new Map(),
    outTypes,
    records: [],
    usedTypes: new Set(),
    usedEnums: new Set(),
    shapes: { types: outTypes, entries },
    // The record key heads the page (the root's) or links back to the parent (the companion's).
    keys: [
      ...(root.keyColumn ? [root.keyColumn] : []),
      ...(companion?.keyColumn ? [`${COMPANION_PREFIX}.${companion.keyColumn}`] : []),
    ],
  };
  walkType(b, rootType, "", false, null);
  if (companion) {
    entries[COMPANION_PREFIX] = {
      path: COMPANION_PREFIX,
      name: COMPANION_PREFIX,
      label: COMPANION_LABEL,
      kind: "record",
      unit: null,
      unitNotStated: false,
      description: cleanDescription(types[companion.type]?.description ?? ""),
      dcsKey: null,
      recordType: companion.type,
    };
    walkType(b, companion.type, COMPANION_PREFIX, false, null);
  }
  const marked = Object.values(entries).filter((e) => b.found.has(e.path));
  for (const pass of PASSES) for (const e of marked) pass(b, e);
  markBounds(b);

  const enums: Record<string, EnumInfo> = {};
  for (const e of b.usedEnums) enums[e] = { values: types[e]?.values ?? {} };
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

/** The catalog entry a concrete path reads (`catalogKeyFor`); null for a path outside the catalog. */
export function entryFor(
  catalog: Pick<SeriesCatalog, "entries">,
  path: string,
): CatalogEntry | null {
  const key = catalogKeyFor(path, catalog);
  return key ? (catalog.entries[key] ?? null) : null;
}

/** The entries of a series' top-level fields (its root type's; the companion's apart), in schema order. */
export const rootFields = (catalog: Pick<SeriesCatalog, "rootType" | "types" | "entries">) =>
  recordFields(catalog, catalog.rootType, "");

/** A companion path's path in the companion (`flight.aerodynamics` -> `aerodynamics`, `flight` -> ""); null for the record's own. */
export function companionRest(path: string): string | null {
  if (path === COMPANION_PREFIX) return "";
  return path.startsWith(`${COMPANION_PREFIX}.`) ? path.slice(COMPANION_PREFIX.length + 1) : null;
}

/** The root a path reads from: the record, or its companion for `flight.` paths. */
export function rootFor<T>(path: string, data: T, companion: T | undefined) {
  const rest = companionRest(path);
  return rest === null ? { root: data, rest: path } : { root: companion, rest };
}

/**
 * The axis of a table a curve or surfaces is read from (`axis.table`), for a comparable
 * table column or grid (`compareAs` `curve` or `surfaces`); null for any other entry (a
 * Mach-sampled list's curve reads its own path).
 */
export function tableAxis(entry: CatalogEntry) {
  const { axis, compareAs } = entry;
  if (compareAs !== "curve" && compareAs !== "surfaces") return null;
  return axis?.kind === "column" || axis?.kind === "surface" ? axis : null;
}

/**
 * Every concrete value of a catalog key: plain paths give one, keyed paths one per key,
 * axis columns (`table[].cx0`) one `{ x, y }` curve (lib/record-tables.ts `curveOf`), as
 * do Mach-sampled lists (`samplesOf`: over Mach at their record's step), an envelope's
 * grids one list of every item's surface (`surfacesOf`).
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
  const axis = tableAxis(entry);
  if (axis) {
    const rows = getPath(root, axis.table.slice(prefix.length));
    if (axis.kind === "surface") {
      const surfaces = surfacesOf(rows, axis, entry.name);
      return surfaces.length ? [{ path: entry.path, value: surfaces }] : [];
    }
    const curve = curveOf(rows, axis.field, entry.name);
    return curve ? [{ path: entry.path, value: curve }] : [];
  }
  const found = walkPath(catalog, entry.path, data, companion);
  if (entry.axis?.kind === "sampled") {
    return found.flatMap((v) => {
      const curve = samplesOf(v.parent, entry);
      return curve ? [{ path: v.concretePath, value: curve }] : [];
    });
  }
  return found.map((v) => ({ path: v.concretePath, value: v.value }));
}

/** One value a catalog path reaches in a record. */
export type PathValue = {
  /**
   * Where the record holds it, for people: the holding record's path with array positions
   * (`stations[2]`, `flight.motorStages[0]`; "" for the root).
   */
  holder: string;
  /** The value's concrete path: keyed items by key (`flight.motorStages.march.impulseS`), list items by position (`stations[2].sourcePath`). */
  concretePath: string;
  value: unknown;
  /** The record holding it (a Mach-sampled list's step sits beside the list). */
  parent: Json;
};

/**
 * Every value at a catalog path (`aero.massKg`, `stations[].sourcePath`,
 * `flight.motorStages.*.impulseS`): `x[]` steps into each item of the list `x`, `*` into
 * each item of a keyed array (its `keyField` naming it). Absent, null and empty values are
 * skipped.
 */
export function walkPath(
  catalog: Pick<SeriesCatalog, "entries">,
  path: string,
  data: Json | undefined,
  companion?: Json,
): PathValue[] {
  const { root, rest } = rootFor(path, data, companion);
  if (!root) return [];
  const segments = rest.split(".");
  const join = (a: string, b: string) => (a ? `${a}.${b}` : b);
  const out: PathValue[] = [];
  // `keyed`: the catalog path so far; `concrete`: the concrete one; `holder`: with positions.
  const walk = (node: unknown, i: number, keyed: string, concrete: string, holder: string) => {
    const segment = segments[i] ?? "";
    if (segment === "*") {
      if (!Array.isArray(node)) return;
      const keyField = catalog.entries[keyed]?.keyField ?? "key";
      node.forEach((item, j) => {
        if (!isRecord(item)) return;
        const key = String(item[keyField]);
        walk(item, i + 1, join(keyed, "*"), join(concrete, key), `${holder}[${j}]`);
      });
      return;
    }
    if (!isRecord(node)) return;
    const field = segment.replace(/\[\]$/, "");
    const next = node[field];
    if (i === segments.length - 1) {
      if (!present(next)) return;
      out.push({ holder, concretePath: join(concrete, field), value: next, parent: node });
    } else if (field === segment) {
      walk(next, i + 1, join(keyed, segment), join(concrete, field), join(holder, field));
    } else if (Array.isArray(next)) {
      next.forEach((item, j) => {
        const at = `${join(concrete, field)}[${j}]`;
        walk(item, i + 1, join(keyed, segment), at, `${join(holder, field)}[${j}]`);
      });
    }
  };
  const start = path === rest ? "" : COMPANION_PREFIX;
  walk(root, 0, start, start, start);
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
    if (entry.compareAs === undefined) continue;
    for (const v of valuesAt(entry, catalog, data, companion)) {
      out.push({ path: v.path, key: entry.path, value: v.value });
    }
  }
  return out;
}
