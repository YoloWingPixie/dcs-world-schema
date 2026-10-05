/**
 * Presentation hints for the reference series: nicer labels, blurbs and home-page
 * groups. Optional: the series themselves come from the database (`series` table, see
 * lib/db/reference.ts), and a series missing here renders with a label derived from
 * its name and a blurb from its schema type.
 */

export type SeriesGroupId = "units" | "weapons" | "systems" | "world" | "mission";

export type SeriesInfo = {
  id: string;
  /** Plural label ("Ground vehicles"). */
  label: string;
  /** Singular noun for one record ("ground vehicle"). */
  singular: string;
  group: SeriesGroupId;
  /** Root schema record type. */
  type: string;
  blurb: string;
  /**
   * A series whose records extend this one's, keyed by the same id
   * (weapon_flight for weapons). Its fields render on the parent page under `flight.`.
   */
  companion?: string;
  /** This series is rendered inside its parent's page (`companion` of `parent`). */
  parent?: string;
  /** Series that are unit types (targets of `Entity.Aircraft | ...` unit refs). */
  unit?: boolean;
};

export const SERIES_GROUPS: Array<{ id: SeriesGroupId; label: string }> = [
  { id: "units", label: "Units" },
  { id: "weapons", label: "Weapons and stores" },
  { id: "systems", label: "Sensors and comms" },
  { id: "world", label: "Theatres and navigation" },
  { id: "mission", label: "Mission editor" },
];

export const SERIES: SeriesInfo[] = [
  {
    id: "aircraft",
    label: "Aircraft",
    singular: "aircraft",
    group: "units",
    type: "Entity.Aircraft",
    blurb: "Fixed-wing and rotary aircraft: stations, sensors, radios, performance.",
    companion: "aircraft_flight",
    unit: true,
  },
  {
    id: "ground_vehicles",
    label: "Ground vehicles",
    singular: "ground vehicle",
    group: "units",
    type: "Entity.GroundVehicle",
    blurb: "Armour, air defence, artillery and soft-skinned vehicles.",
    unit: true,
  },
  {
    id: "ships",
    label: "Ships",
    singular: "ship",
    group: "units",
    type: "Entity.Ship",
    blurb: "Surface ships, carriers and submarines.",
    unit: true,
  },
  {
    id: "personnel",
    label: "Personnel",
    singular: "personnel unit",
    group: "units",
    type: "Entity.Personnel",
    blurb: "Infantry and deck crew.",
    unit: true,
  },
  {
    id: "structures",
    label: "Structures",
    singular: "structure",
    group: "units",
    type: "Entity.Structure",
    blurb: "Static objects: buildings, fortifications, cargo, FARP equipment.",
    unit: true,
  },
  {
    id: "aircraft_flight",
    label: "Aircraft flight models",
    singular: "aircraft flight model",
    group: "units",
    type: "Entity.AircraftFlight",
    blurb: "Simple flight model tables and engine data, one per aircraft.",
    parent: "aircraft",
  },
  {
    id: "weapons",
    label: "Weapons",
    singular: "weapon",
    group: "weapons",
    type: "Entity.Weapon",
    blurb: "Missiles, bombs, rockets and torpedoes.",
    companion: "weapon_flight",
  },
  {
    id: "weapon_flight",
    label: "Weapon flight models",
    singular: "weapon flight model",
    group: "weapons",
    type: "Entity.WeaponFlight",
    blurb: "Aerodynamics, motors, autopilot and seeker blocks of each weapon.",
    parent: "weapons",
  },
  {
    id: "stores",
    label: "Stores",
    singular: "store",
    group: "weapons",
    type: "Entity.Store",
    blurb: "Pylon loads by CLSID: payload, rack, mass, drag.",
  },
  {
    id: "racks",
    label: "Racks",
    singular: "rack",
    group: "weapons",
    type: "Entity.Rack",
    blurb: "Multiple-ejector racks and launchers.",
  },
  {
    id: "warheads",
    label: "Warheads",
    singular: "warhead",
    group: "weapons",
    type: "Entity.Warhead",
    blurb: "Explosive mass and fragmentation of weapon warheads.",
  },
  {
    id: "gun_ammo",
    label: "Gun ammunition",
    singular: "gun ammunition",
    group: "weapons",
    type: "Entity.GunAmmo",
    blurb: "Shells: calibre, muzzle velocity, mass and ballistics.",
  },
  {
    id: "fuzes",
    label: "Fuzes",
    singular: "fuze",
    group: "weapons",
    type: "Entity.FuzeType",
    blurb: "Fuze types.",
  },
  {
    id: "sensors",
    label: "Sensors",
    singular: "sensor",
    group: "systems",
    type: "Entity.Sensor",
    blurb: "Radars, optics, IRST and RWR: detection ranges and scan volumes.",
  },
  {
    id: "radios",
    label: "Radios",
    singular: "radio",
    group: "systems",
    type: "Entity.Radio",
    blurb: "Aircraft radios: bands, presets and guard channels.",
  },
  {
    id: "datalink",
    label: "Datalink",
    singular: "datalink",
    group: "systems",
    type: "Entity.Datalink",
    blurb: "Aircraft datalink capabilities.",
  },
  {
    id: "threats",
    label: "Threat systems",
    singular: "threat system",
    group: "systems",
    type: "Entity.ThreatSystem",
    blurb: "Air-defence systems and their RWR symbols.",
  },
  {
    id: "theatres",
    label: "Theatres",
    singular: "theatre",
    group: "world",
    type: "Entity.Theatre",
    blurb: "Maps and their projections.",
  },
  {
    id: "airbases",
    label: "Airbases",
    singular: "airbase",
    group: "world",
    type: "Entity.Airbase",
    blurb: "Airfields, FARPs and helipads per theatre: runways, stands, beacons.",
  },
  {
    id: "beacons",
    label: "Beacons",
    singular: "beacon",
    group: "world",
    type: "Entity.Beacon",
    blurb: "TACAN, VOR, NDB and ILS beacons per theatre.",
  },
  {
    id: "navaids",
    label: "Navaids",
    singular: "navaid",
    group: "world",
    type: "Entity.Navaid",
    blurb: "Grouped landing aids (ILS, PRMG, RSBN) per runway.",
  },
  {
    id: "countries",
    label: "Countries",
    singular: "country",
    group: "mission",
    type: "Entity.Country",
    blurb: "Country ids, names, ranks and awards.",
  },
  {
    id: "callsigns",
    label: "Callsigns",
    singular: "callsign set",
    group: "mission",
    type: "Entity.CountryCallsigns",
    blurb: "Flight callsigns per country and category.",
  },
  {
    id: "attributes",
    label: "Attributes",
    singular: "attribute",
    group: "mission",
    type: "Entity.Attribute",
    blurb: "Unit attributes.",
  },
  {
    id: "tasks",
    label: "Tasks",
    singular: "task",
    group: "mission",
    type: "Entity.Task",
    blurb: "Mission-editor group tasks.",
  },
  {
    id: "actions",
    label: "Actions",
    singular: "action",
    group: "mission",
    type: "Entity.Action",
    blurb: "Mission-editor actions.",
  },
  {
    id: "options",
    label: "Options",
    singular: "option",
    group: "mission",
    type: "Entity.ActionOption",
    blurb: "AI options: ROE, reaction to threat, formation.",
  },
  {
    id: "formations",
    label: "Formations",
    singular: "formation",
    group: "mission",
    type: "Entity.Formation",
    blurb: "Flight formations.",
  },
  {
    id: "skills",
    label: "Skills",
    singular: "skill",
    group: "mission",
    type: "Entity.Skill",
    blurb: "AI skill levels.",
  },
  {
    id: "liveries",
    label: "Liveries",
    singular: "livery",
    group: "mission",
    type: "Entity.Livery",
    blurb: "Paint schemes per unit type.",
  },
];

export const SERIES_BY_ID: ReadonlyMap<string, SeriesInfo> = new Map(SERIES.map((s) => [s.id, s]));

export const UNIT_SERIES = SERIES.filter((s) => s.unit).map((s) => s.id);

/** Series that get their own browse page (companions render inside their parent). */
export const BROWSABLE_SERIES = SERIES.filter((s) => !s.parent);

export function seriesInfo(id: string): SeriesInfo {
  const info = SERIES_BY_ID.get(id);
  if (!info) throw new Error(`Unknown series: ${id}`);
  return info;
}

/** Ids of the series a schema `ref` names (`Entity.Store`, or a `A | B` union of unit types). */
export function seriesForRef(ref: string): string[] {
  return ref
    .split("|")
    .map((t) => t.trim())
    .flatMap((t) => SERIES.filter((s) => s.type === t).map((s) => s.id));
}

/**
 * The page a record lives on: `/<series>/<id>/`. Companion records (weapon_flight)
 * open their parent. Served by the client-side reference shell (app/not-found.tsx).
 */
export function recordHref(series: string, id: string): string {
  const info = SERIES_BY_ID.get(series);
  const target = info?.parent ?? series;
  return `/${target}/${encodeURIComponent(id)}/`;
}

/** `/<series>/<id>/` (basePath removed) -> its parts, or null. */
export function parseReferencePath(pathname: string): { series: string; id: string | null } | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length < 1 || parts.length > 2) return null;
  const [series, id] = parts as [string, string | undefined];
  if (!/^[a-z][a-z0-9_]*$/.test(series)) return null;
  try {
    return { series, id: id === undefined ? null : decodeURIComponent(id) };
  } catch {
    return null;
  }
}

export function seriesHref(series: string): string {
  const info = SERIES_BY_ID.get(series);
  return `/${info?.parent ?? series}/`;
}
