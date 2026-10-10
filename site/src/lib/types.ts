/** Shapes of the reference data the pages read (lib/db/reference.ts builds them from SQLite). */
import type { UnitConversions } from "./units";

export type FieldKind =
  /** Scalars. */
  | "number"
  | "string"
  | "boolean"
  | "enum"
  /** A string (or number, for `country.id`) naming another record. */
  | "ref"
  /** number[]: a chart when `axis` says how it is indexed, else a value list. */
  | "numbers"
  /** string[] (`ref` set: links). */
  | "strings"
  /** number[][] */
  | "grid"
  /** Arrays of number arrays (`Entity.AngleSector[]`) and other nested arrays. */
  | "matrix"
  /** A nested record: a group of fields. */
  | "record"
  /** An array of records: a table. */
  | "records"
  /** Untyped (`any`): shown as JSON. */
  | "any";

/** The kinds holding one value (a table cell, a browse column). */
export const SCALAR_KINDS: ReadonlySet<FieldKind> = new Set([
  "number",
  "string",
  "boolean",
  "enum",
  "ref",
]);

/** One schema field at a path of a series' records. */
export type CatalogEntry = {
  /**
   * `aero.massKg`; `stations[].accepts[].clsid` inside arrays of records;
   * `flight.motorStages.*.impulseS` inside keyed arrays (one value per key);
   * `flight.` prefixes the companion series' fields (weapon_flight on a weapon).
   */
  path: string;
  name: string;
  label: string;
  /** Schema type as written (`number`, `Entity.Seeker`, `string[]`). */
  type: string;
  kind: FieldKind;
  unit: string | null;
  /** How `unit` displays in each system (lib/units.ts `resolveConversions`); set with a unit. */
  conversions?: UnitConversions;
  unitNotStated: boolean;
  description: string;
  /** The DCS key the description names (`Cx0`), when it names one. */
  dcsKey: string | null;
  /** Declaring schema type. */
  owner: string;
  /** Target series of a `ref` (several for unit-type unions). */
  ref?: string[];
  /** Enum type name, for `enum` fields. */
  enumType?: string;
  /** Record type of `record` / `records` fields. */
  recordType?: string;
  /**
   * How a `numbers` field is indexed: `mach` (sampled from Mach 0 by the sibling `machStep`)
   * or the path of a sibling array holding the axis values. `records` tables with a numeric
   * axis column name it here (`mach`).
   */
  axis?: string;
  /**
   * On an `xName` constant-name field: `x`, the code it names. A record shows the name in
   * the code's place (one row), the code staying in the raw line.
   */
  codeField?: string;
  /** Keyed arrays (`*` in paths): the field naming each element. */
  keyField?: string;
  /** What the field is for, when it is not reference data: `provenance` (`sourcePaths`, `sourcePath`). */
  role?: "provenance";
  /**
   * How a `records` array lays out: `envelope` (two number[] axes and number[][] grids per
   * item), `axis-table` (rows indexed by the `axis` column).
   */
  layout?: "envelope" | "axis-table";
  /** On a Mach-indexed `numbers` field: the sibling field holding the step, and the step without it. */
  step?: { field: string; fallback: number };
  /** On a `records` field: item fields that name an item without a link, in order. */
  titleFields?: string[];
  /** On a `records` field: item counts shown beside each item in a list (`ammoCapacity`). */
  countFields?: string[];
  /** Can be compared across records (its values read with getFieldValues, lib/db/reference.ts). */
  comparable: boolean;
  /** Hand-written field note (content/reference/<series>/_fields/<path>.md), as HTML. */
  note?: string;
};

export type EnumInfo = { description: string; values: Record<string, string | number> };

export type SeriesCatalog = {
  series: string;
  rootType: string;
  entries: Record<string, CatalogEntry>;
  /** Field order of each record type the series uses (schema order). */
  types: Record<string, { description: string; fields: string[] }>;
  enums: Record<string, EnumInfo>;
  /** Comparable concrete paths (keyed `*` filled in) and how many records carry each. */
  fieldPaths: Array<{ path: string; key: string; count: number }>;
};

/** `[slug, display name]` of a linked record. */
export type LinkTarget = [slug: string, name: string];

export type ReferencedBy = {
  series: string;
  /** Path in the referring series (`delivers[].weapon`), or a derived relation name. */
  path: string;
  label: string;
  records: LinkTarget[];
  /** A derived group: units reaching the record through this series (aircraft via stores). */
  via?: string;
  /** Set when `records` is capped: how many records the group has. */
  total?: number;
};

export type Overlay = {
  /** Rendered Markdown. */
  html: string;
  aliases?: string[];
  seeAlso?: Array<{ label: string; href: string }>;
};

export type RecordDoc = {
  series: string;
  id: string;
  slug: string;
  name: string;
  /** One-line classification shown under the title. */
  meta: string;
  data: Record<string, unknown>;
  /** The companion series' record (weapon_flight for a weapon), keyed `flight` in paths. */
  companion?: Record<string, unknown>;
  /** Every ref in the record: series -> raw id -> [slug, name], or the name when slug = id. */
  links: Record<string, Record<string, LinkTarget | string>>;
  referencedBy: ReferencedBy[];
  overlay?: Overlay;
};

/** One browse-table row: slug, name, meta, then the series' column values in order. */
export type BrowseRow = [slug: string, name: string, id: string, ...values: unknown[]];

export type Facet = {
  path: string;
  label: string;
  kind: "enum" | "boolean" | "string" | "strings";
  /** Index into `SeriesIndex.columns` (row position `3 + column`). */
  column: number;
};

export type SeriesIndex = {
  series: string;
  count: number;
  /** Column paths after the fixed slug, name, id (visible ones and facet-only ones). */
  columns: string[];
  /** Columns shown by default. */
  visible: string[];
  facets: Facet[];
  rows: BrowseRow[];
  intro?: Overlay;
};

/** One comparable field across every record of a series (getFieldValues, lib/db/reference.ts). */
export type FieldValues = { path: string; values: Record<string, unknown> };
