/**
 * Per-series presentation choices the schema cannot express: the headline readouts on a
 * record page, the default browse columns and facets, and the browse grouping. Every
 * series works without an entry here (the defaults pick from the catalog); entries only
 * refine. Record names and the meta line under them come from the database's `search` table.
 */

export type SeriesDisplay = {
  /**
   * Headline values on the record page (up to four): paths, `#path` for an array's count;
   * a list of ranges reads as its coverage.
   */
  readouts?: string[];
  /** Default browse columns (paths). */
  columns?: string[];
  /** Facet paths (default: enum, boolean and low-cardinality string fields). */
  facets?: string[];
  /** Browse grouped under headings by default (lib/browse-groups); `?group=flat` lists flat. */
  groupBy?: GroupBy;
};

export type GroupBy = {
  /** A ref field (the group is its first target, linked from the heading) or a column. */
  path: string;
  /** Column whose value groups a row the ref leaves empty. */
  fallback?: string;
  /** What a group is, for the toggle and headings: "airframe". */
  label: string;
  /** Default columns while grouped (the heading already names the group). */
  columns?: string[];
};

export const SERIES_DISPLAY: Record<string, SeriesDisplay> = {
  aircraft: {
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
    readouts: ["mobility.maxSpeedKmh", "detection.detectionRangeMax", "detection.threatRange"],
    facets: ["attributes"],
  },
  ships: { readouts: ["mobility.maxSpeedKmh", "detection.rcsM2"], facets: ["attributes"] },
  structures: { facets: ["attributes"] },
  personnel: { facets: ["attributes"] },
  weapons: {
    readouts: ["massKg", "rangeKm", "flight.machMax", "flight.autopilot.gLoadLimit"],
    columns: ["subcategoryName", "seekerTypeName", "massKg", "rangeKm", "flight.machMax"],
    facets: ["categoryName", "subcategoryName", "seekerTypeName"],
  },
  stores: {
    readouts: ["aero.massKg", "aero.dragIndex"],
    columns: ["kind", "categoryName", "aero.massKg", "aero.dragIndex", "rack"],
    facets: ["kind", "categoryName"],
  },
  sensors: {
    readouts: ["detectionRangeKm"],
    facets: ["kind", "categoryName"],
  },
  gun_ammo: {
    readouts: ["caliberMm", "v0Ms", "massKg", "explosiveKg"],
    columns: ["caliberMm", "type", "v0Ms", "massKg", "explosiveKg"],
  },
  warheads: { readouts: ["massKg", "explosiveMassKg"] },
  radios: {
    readouts: ["segments", "stepKHz", "presets", "guard"],
  },
  airbases: {
    readouts: ["longestRunwayM", "referencePoint.elevationM", "#runways", "#stands"],
    columns: ["theatre", "categoryName", "longestRunwayM"],
    facets: ["theatre", "categoryName"],
  },
  beacons: {
    columns: ["typeName", "theatre", "callsign", "frequencyHz", "channel"],
    facets: ["typeName", "theatre"],
  },
  navaids: {
    facets: ["type", "theatre"],
  },
  liveries: {
    columns: ["entryPoint", "module"],
    // The unit type a livery's folder is the entry point of; folders no unit uses
    // (asset-pack props, weapon models) group by the folder name.
    groupBy: {
      path: "unitTypes",
      fallback: "entryPoint",
      label: "airframe",
      columns: ["module"],
    },
  },
  callsigns: { facets: ["numeric"] },
  countries: {
    columns: ["shortName", "idName", "internationalName"],
  },
  actions: { facets: ["kind"] },
  threats: {
    facets: ["kind"],
  },
};

export function displayFor(series: string): SeriesDisplay {
  return SERIES_DISPLAY[series] ?? {};
}

/** URL-safe slug for an id; ids carry spaces, slashes, braces and parentheses. */
export function slugify(id: string): string {
  return id
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .replace(/-{2,}/g, "-");
}
