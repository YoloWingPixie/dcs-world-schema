/**
 * Where the reference data and the Lua API meet: per series, the class a mission script
 * gets for its records, the member whose value names a record, and the enum pages that
 * list the records (each such page's `valuesSeries` is the series: tests/api checks it).
 *
 * The SQLite package builds each record's Scripting rows from these (tools/package/
 * site_views.py) and keeps only what the API data confirms: an enum row only when the enum
 * lists the record, a member only when it exists. Record pages render the rows with the
 * record; API pages read the same table backwards to link a class or an enum to the data.
 */
import spec from "./scripting.json";

/** A numeric field whose value is a member of a small API enum. */
export type EnumField = {
  /** The record field holding the number (`category`). */
  path: string;
  /** What the value is, as the scripting section's row reads ("Category"). */
  label: string;
  /** The field holding DCS's constant name for it (`categoryName`): it must name the key. */
  name: string;
  /** Candidate enums; a value maps to the one whose key matches the constant name. */
  enums: string[];
  /** Browse facet listing the records with each value (`?f.<facet>=<name>`), if any. */
  facet?: string;
};

export type Scripting = {
  /** The Lua class the scripting engine hands back for these records' objects. */
  class?: string;
  /** The member (`Page.member`) whose value is the record's enum value. */
  member?: string;
  /** What the member does with the value: returns it, or takes it as its argument. */
  memberRole?: "returns" | "takes";
  /** Enum pages listing the series' records; `{theatre}` is the record's `theatre`. */
  enums: string[];
  /** `Object:hasAttribute` checks the record's `attributes`. */
  attributes?: boolean;
  /** Record fields an API member returns as they are (the schema's descriptions say so). */
  fields?: Array<{ path: string; member: string }>;
  values?: EnumField[];
};

/**
 * The entries, in scripting.json: tools/package/sqlite.py reads the same file to build each
 * record's Scripting rows into its record view.
 */
export const SCRIPTING = spec as Record<string, Scripting>;

/** Whether a DCS constant name (`SENSOR_OPTICAL`, `RADAR_AS`) names an enum key (`OPTIC`, `AS`). */
export function namesKey(constant: string, key: string): boolean {
  const last = constant.split("_").pop() ?? "";
  return last.length > 0 && last.startsWith(key);
}

/** Series whose records a class's objects are, in table order. */
export function seriesOfClass(name: string): string[] {
  return Object.entries(SCRIPTING)
    .filter(([, s]) => s.class === name)
    .map(([id]) => id);
}

/** A field of a series whose values are this enum's (fixed enums, not `valuesSeries`). */
export function enumField(page: string): { series: string; field: EnumField } | null {
  for (const [series, s] of Object.entries(SCRIPTING)) {
    const field = s.values?.find((v) => v.enums.includes(page));
    if (field) return { series, field };
  }
  return null;
}

/** An enum value's row id on its page (components/api/enum-table.tsx). */
export const enumValueId = (key: string) => `v-${encodeURIComponent(key)}`;

/** `Enum.KEY`, or `Enum["Key with spaces"]` when the key is no Lua name. */
export function enumMemberText(page: string, key: string): string {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(key)
    ? `${page}.${key}`
    : `${page}[${JSON.stringify(key)}]`;
}
