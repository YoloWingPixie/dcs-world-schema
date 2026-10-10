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
  blurb: string;
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
    blurb: "Fixed-wing and rotary aircraft: stations, sensors, radios, performance.",
  },
  {
    id: "ground_vehicles",
    label: "Ground vehicles",
    singular: "ground vehicle",
    group: "units",
    blurb: "Armour, air defence, artillery and soft-skinned vehicles.",
  },
  {
    id: "ships",
    label: "Ships",
    singular: "ship",
    group: "units",
    blurb: "Surface ships, carriers and submarines.",
  },
  {
    id: "personnel",
    label: "Personnel",
    singular: "personnel unit",
    group: "units",
    blurb: "Infantry and deck crew.",
  },
  {
    id: "structures",
    label: "Structures",
    singular: "structure",
    group: "units",
    blurb: "Static objects: buildings, fortifications, cargo, FARP equipment.",
  },
  {
    id: "aircraft_flight",
    label: "Aircraft flight models",
    singular: "aircraft flight model",
    group: "units",
    blurb: "Simple flight model tables and engine data, one per aircraft.",
  },
  {
    id: "weapons",
    label: "Weapons",
    singular: "weapon",
    group: "weapons",
    blurb: "Missiles, bombs, rockets and torpedoes.",
  },
  {
    id: "weapon_flight",
    label: "Weapon flight models",
    singular: "weapon flight model",
    group: "weapons",
    blurb: "Aerodynamics, motors, autopilot and seeker blocks of each weapon.",
  },
  {
    id: "stores",
    label: "Stores",
    singular: "store",
    group: "weapons",
    blurb: "Pylon loads by CLSID: payload, rack, mass, drag.",
  },
  {
    id: "racks",
    label: "Racks",
    singular: "rack",
    group: "weapons",
    blurb: "Multiple-ejector racks and launchers.",
  },
  {
    id: "warheads",
    label: "Warheads",
    singular: "warhead",
    group: "weapons",
    blurb: "Explosive mass and fragmentation of weapon warheads.",
  },
  {
    id: "gun_ammo",
    label: "Gun ammunition",
    singular: "gun ammunition",
    group: "weapons",
    blurb: "Shells: calibre, muzzle velocity, mass and ballistics.",
  },
  {
    id: "fuzes",
    label: "Fuzes",
    singular: "fuze",
    group: "weapons",
    blurb: "Fuze types.",
  },
  {
    id: "sensors",
    label: "Sensors",
    singular: "sensor",
    group: "systems",
    blurb: "Radars, optics, IRST and RWR: detection ranges and scan volumes.",
  },
  {
    id: "radios",
    label: "Radios",
    singular: "radio",
    group: "systems",
    blurb: "Aircraft radios: bands, presets and guard channels.",
  },
  {
    id: "datalink",
    label: "Datalink",
    singular: "datalink",
    group: "systems",
    blurb: "Aircraft datalink capabilities.",
  },
  {
    id: "threats",
    label: "Threat systems",
    singular: "threat system",
    group: "systems",
    blurb: "Air-defence systems and their RWR symbols.",
  },
  {
    id: "theatres",
    label: "Theatres",
    singular: "theatre",
    group: "world",
    blurb: "Maps and their projections.",
  },
  {
    id: "airbases",
    label: "Airbases",
    singular: "airbase",
    group: "world",
    blurb: "Airfields, FARPs and helipads per theatre: runways, stands, beacons.",
  },
  {
    id: "beacons",
    label: "Beacons",
    singular: "beacon",
    group: "world",
    blurb: "TACAN, VOR, NDB and ILS beacons per theatre.",
  },
  {
    id: "navaids",
    label: "Navaids",
    singular: "navaid",
    group: "world",
    blurb: "Grouped landing aids (ILS, PRMG, RSBN) per runway.",
  },
  {
    id: "countries",
    label: "Countries",
    singular: "country",
    group: "mission",
    blurb: "Country ids, names, ranks and awards.",
  },
  {
    id: "callsigns",
    label: "Callsigns",
    singular: "callsign set",
    group: "mission",
    blurb: "Flight callsigns per country and category.",
  },
  {
    id: "attributes",
    label: "Attributes",
    singular: "attribute",
    group: "mission",
    blurb: "Unit attributes.",
  },
  {
    id: "tasks",
    label: "Tasks",
    singular: "task",
    group: "mission",
    blurb: "Mission-editor group tasks.",
  },
  {
    id: "actions",
    label: "Actions",
    singular: "action",
    group: "mission",
    blurb: "Mission-editor actions.",
  },
  {
    id: "options",
    label: "Options",
    singular: "option",
    group: "mission",
    blurb: "AI options: ROE, reaction to threat, formation.",
  },
  {
    id: "formations",
    label: "Formations",
    singular: "formation",
    group: "mission",
    blurb: "Flight formations.",
  },
  {
    id: "skills",
    label: "Skills",
    singular: "skill",
    group: "mission",
    blurb: "AI skill levels.",
  },
  {
    id: "liveries",
    label: "Liveries",
    singular: "livery",
    group: "mission",
    blurb: "Paint schemes per unit type.",
  },
];

export const SERIES_BY_ID: ReadonlyMap<string, SeriesInfo> = new Map(SERIES.map((s) => [s.id, s]));

/**
 * The page a record lives on: `/<series>/<id>/`, served by the client-side reference shell
 * (app/not-found.tsx). `series` is a page's series: a companion's records (weapon_flight)
 * live on their parent's pages, and the references to them name the parent already
 * (lib/db/reference `refResolver`).
 */
export function recordHref(series: string, id: string): string {
  return `/${series}/${encodeURIComponent(id)}/`;
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

/** A series' browse page (a page's series, as for `recordHref`). */
export function seriesHref(series: string): string {
  return `/${series}/`;
}

/** The browse page's query parameter of a facet (`?f.<path>=<value>`). */
export const facetParam = (path: string) => `f.${path}`;
