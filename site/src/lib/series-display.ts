/**
 * Per-series presentation choices the schema cannot express: how a record is named
 * and slugged, the one-line meta under its name, the headline readouts on its page,
 * and the default browse columns. Every series works without an entry here (the
 * defaults pick from the catalog); entries only refine.
 */

type Json = Record<string, unknown>;

export type SeriesDisplay = {
  /** Display name of a record (default: displayName, name, then the id). */
  name?: (r: Json, id: string) => string;
  /** Slug source before slugify (default: the id). */
  slug?: (r: Json, id: string) => string;
  /** Paths whose values make the meta line, in order. */
  meta?: string[];
  /** Headline values on the record page (up to four). */
  readouts?: string[];
  /** Default browse columns (paths). */
  columns?: string[];
  /** Facet paths (default: enum, boolean and low-cardinality string fields). */
  facets?: string[];
};

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);

export const SERIES_DISPLAY: Record<string, SeriesDisplay> = {
  aircraft: {
    meta: ["kind", "defaultTask.name", "countryOfOrigin"],
    readouts: [
      "aero.maxTakeoffKg",
      "performance.machMax",
      "performance.hMaxM",
      "performance.rangeKm",
    ],
    columns: ["kind", "defaultTask.name", "aero.maxTakeoffKg", "performance.machMax", "flyable"],
    facets: ["kind", "flyable", "defaultTask.name", "countryOfOrigin", "attributes"],
  },
  ground_vehicles: {
    meta: ["operators.0.countryName"],
    readouts: ["mobility.maxSpeedKmh", "detection.detectionRangeMax", "detection.threatRange"],
    facets: ["attributes"],
  },
  ships: { readouts: ["mobility.maxSpeedKmh", "detection.rcsM2"], facets: ["attributes"] },
  structures: { facets: ["attributes"] },
  personnel: { facets: ["attributes"] },
  weapons: {
    meta: ["subcategoryName", "seekerTypeName"],
    readouts: ["massKg", "rangeKm", "flight.machMax", "flight.autopilot.gLoadLimit"],
    columns: ["subcategoryName", "seekerTypeName", "massKg", "rangeKm", "flight.machMax"],
    facets: ["categoryName", "subcategoryName", "seekerTypeName"],
  },
  stores: {
    meta: ["kind", "categoryName"],
    readouts: ["aero.massKg", "aero.dragIndex"],
    columns: ["kind", "categoryName", "aero.massKg", "aero.dragIndex", "rack"],
    facets: ["kind", "categoryName"],
  },
  sensors: {
    meta: ["kind", "categoryName"],
    readouts: ["detectionRangeKm"],
    facets: ["kind", "categoryName"],
  },
  gun_ammo: {
    meta: ["caliberMm", "type"],
    readouts: ["caliberMm", "v0Ms", "massKg", "explosiveKg"],
    columns: ["caliberMm", "type", "v0Ms", "massKg", "explosiveKg"],
  },
  warheads: { meta: ["type"], readouts: ["massKg", "explosiveMassKg"] },
  radios: { meta: ["band"], name: (r, id) => str(r.name) ?? id },
  airbases: {
    name: (r, id) => str(r.name) ?? id,
    meta: ["theatre", "categoryName"],
    readouts: ["longestRunwayM"],
    columns: ["theatre", "categoryName", "longestRunwayM"],
    facets: ["theatre", "categoryName"],
  },
  beacons: {
    name: (r, id) =>
      `${str(r.displayName) ?? str(r.callsign) ?? id}${str(r.callsign) && str(r.displayName) ? ` (${r.callsign})` : ""}`,
    meta: ["typeName", "theatre"],
    columns: ["typeName", "theatre", "callsign", "frequencyHz", "channel"],
    facets: ["typeName", "theatre"],
  },
  navaids: {
    name: (r, id) => `${str(r.type) ?? "Navaid"} ${str(r.callsign) ?? id}`,
    meta: ["type", "theatre"],
    facets: ["type", "theatre"],
  },
  liveries: {
    name: (r, id) => `${str(r.entryPoint) ?? ""}: ${str(r.name) ?? id}`,
    slug: (_r, id) => id.replace(/^Bazar\/Liveries\//, "").replace(/\/description\.lua$/, ""),
    meta: ["entryPoint"],
    columns: ["entryPoint", "name"],
  },
  callsigns: { name: (r, id) => `${str(r.countryName) ?? id} callsigns`, facets: ["numeric"] },
  countries: {
    name: (r, id) => str(r.name) ?? id,
    meta: ["shortName", "idName"],
    columns: ["shortName", "idName", "internationalName"],
  },
  actions: { meta: ["kind"], facets: ["kind"] },
  threats: {
    name: (r, id) => (str(r.natoDesignation) ? `${r.natoDesignation} (${id})` : id),
    meta: ["kind", "rwrSymbol"],
    facets: ["kind"],
  },
  formations: { name: (r, id) => (str(r.name) ? `${r.name} (${r.group})` : id) },
  theatres: { name: (r, id) => str(r.displayName) ?? id },
};

export function displayFor(series: string): SeriesDisplay {
  return SERIES_DISPLAY[series] ?? {};
}

export function recordName(series: string, record: Json, id: string): string {
  const custom = displayFor(series).name;
  if (custom) return custom(record, id);
  return str(record.displayName) ?? str(record.name) ?? id;
}

/** URL-safe slug for an id; ids carry spaces, slashes, braces and parentheses. */
export function slugify(id: string): string {
  return id
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .replace(/-{2,}/g, "-");
}
