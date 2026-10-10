/**
 * Where the reference data and the Lua API meet: per series, the class a mission script
 * gets for its records, the member whose value names a record, and the enum pages that
 * list the records (each such page's `valuesSeries` is the series: tests/api checks it).
 *
 * Record pages render these lazily (record-scripting.ts) and keep only what the API data
 * confirms: an enum row only when the enum lists the record, a member only when it exists.
 * API pages read the same table backwards to link a class or an enum to the data.
 */

/** A numeric field whose value is a member of a small API enum. */
export type EnumField = {
  /** The record field holding the number (`category`). */
  path: string;
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

export const SCRIPTING: Record<string, Scripting> = {
  aircraft: {
    class: "Unit",
    member: "Unit.getTypeName",
    enums: ["DcsId.AircraftType", "DcsId.HelicopterType"],
    attributes: true,
  },
  ground_vehicles: {
    class: "Unit",
    member: "Unit.getTypeName",
    enums: ["DcsId.GroundUnitType"],
    attributes: true,
  },
  ships: {
    class: "Unit",
    member: "Unit.getTypeName",
    enums: ["DcsId.ShipType"],
    attributes: true,
  },
  structures: {
    class: "StaticObject",
    member: "Object.getTypeName",
    enums: ["DcsId.StructureType"],
    attributes: true,
  },
  personnel: {
    class: "StaticObject",
    member: "Object.getTypeName",
    enums: ["DcsId.PersonnelType"],
    attributes: true,
  },
  weapons: { class: "Weapon", member: "Weapon.getTypeName", enums: ["DcsId.WeaponType"] },
  airbases: {
    class: "Airbase",
    enums: ["DcsId.Theatre.{theatre}.AirbaseName", "DcsId.Theatre.{theatre}.AirdromeId"],
    fields: [
      { path: "name", member: "Airbase.getName" },
      { path: "airdromeId", member: "Airbase.getID" },
    ],
    values: [
      {
        path: "category",
        name: "categoryName",
        enums: ["Airbase.Category"],
        facet: "categoryName",
      },
    ],
  },
  attributes: { member: "Object.hasAttribute", memberRole: "takes", enums: ["DcsId.Attribute"] },
  sensors: {
    enums: ["DcsId.SensorName"],
    values: [
      { path: "category", name: "categoryName", enums: ["Unit.SensorType"], facet: "categoryName" },
      { path: "type", name: "typeName", enums: ["Unit.RadarType", "Unit.OpticType"] },
    ],
  },
  skills: { enums: ["DcsId.Skill"] },
  formations: { enums: ["DcsId.FormationId"] },
};

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

/** An enum value's anchor on its page (components/api/enum-table.tsx row ids), as a hash. */
export const enumValueHash = (key: string) =>
  `#${encodeURIComponent(`v-${encodeURIComponent(key)}`)}`;

/** `Enum.KEY`, or `Enum["Key with spaces"]` when the key is no Lua name. */
export function enumMemberText(page: string, key: string): string {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(key)
    ? `${page}.${key}`
    : `${page}[${JSON.stringify(key)}]`;
}
