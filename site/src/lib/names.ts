/** Friendly names for DCS constants. Presentation only: the raw constant is always shown beside it. */
import { enumConstantLabel } from "./catalog";
import type { CatalogEntry, EnumInfo } from "./types";

const CATEGORY: Record<string, string> = {
  wsType_Missile: "Missile",
  wsType_Bomb: "Bomb",
  wsType_NURS: "Rocket",
  wsType_Torpedo: "Torpedo",
  wsType_Shell: "Shell",
};

const KIND: Record<string, string> = {
  wsType_AA_Missile: "Air-to-air missile",
  wsType_AS_Missile: "Air-to-surface missile",
  wsType_SA_Missile: "Surface-to-air missile",
  wsType_SS_Missile: "Surface-to-surface missile",
  wsType_AA_TRAIN_Missile: "Air-to-air training missile",
  wsType_AS_TRAIN_Missile: "Air-to-surface training missile",
  wsType_Bomb_A: "General-purpose bomb",
  wsType_Bomb_Guided: "Guided bomb",
  wsType_Bomb_Cluster: "Cluster bomb",
  wsType_Bomb_Lighter: "Illumination bomb",
  wsType_Bomb_BetAB: "Penetration bomb",
  wsType_Rocket: "Unguided rocket",
  wsType_S_Torpedo: "Ship torpedo",
  wsType_A_Torpedo: "Air-dropped torpedo",
};

const GUIDANCE: Record<string, string> = {
  ActiveRadar: "Active radar",
  SemiActiveRadar: "Semi-active radar",
  InfraredSeeker: "Infrared",
  AntiRadar: "Anti-radiation",
  LaserHoming: "Laser",
  Autopilot: "Autopilot / INS",
  SemiAutoAT: "Command (SACLOS)",
};

const CONSTANTS: Record<string, string> = {
  ...CATEGORY,
  ...KIND,
  CAT_FUEL_TANKS: "Fuel tank",
  CAT_PODS: "Pod",
  CAT_BOMBS: "Bombs",
  CAT_MISSILES: "Missiles",
  CAT_ROCKETS: "Rockets",
  CAT_AIR_TO_AIR: "Air-to-air",
  CAT_SHELLS: "Shells",
  CAT_GUN_MOUNT: "Gun mount",
  CAT_CLUSTER_DESC: "Cluster",
  CAT_SERVICE: "Service",
  CAT_TORPEDOES: "Torpedoes",
  SENSOR_IRST: "IRST",
  SENSOR_RWR: "RWR",
  OPTIC_SENSOR_TV: "TV",
  OPTIC_SENSOR_LLTV: "Low-light TV",
  OPTIC_SENSOR_IR: "Infrared",
  RADAR_AS: "Air search radar",
  RADAR_SS: "Surface search radar",
  RADAR_MULTIROLE: "Multirole radar",
  BEACON_TYPE_TACAN: "TACAN",
  BEACON_TYPE_VOR: "VOR",
  BEACON_TYPE_DME: "DME",
  BEACON_TYPE_VOR_DME: "VOR/DME",
  BEACON_TYPE_VORTAC: "VORTAC",
  BEACON_TYPE_HOMER: "NDB (homer)",
  BEACON_TYPE_AIRPORT_HOMER: "Airport NDB",
  BEACON_TYPE_ILS_LOCALIZER: "ILS localizer",
  BEACON_TYPE_ILS_GLIDESLOPE: "ILS glideslope",
  BEACON_TYPE_ICLS_LOCALIZER: "ICLS localizer",
  BEACON_TYPE_ICLS_GLIDESLOPE: "ICLS glideslope",
  MODULATION_AM: "AM",
  MODULATION_FM: "FM",
  MODULATION_AM_AND_FM: "AM and FM",
};

export function categoryLabel(constant: string | null | undefined): string | null {
  return constant ? (CATEGORY[constant] ?? constantLabel(constant)) : null;
}

export function kindLabel(constant: string | null | undefined): string | null {
  return constant ? (KIND[constant] ?? constantLabel(constant)) : null;
}

export function guidanceLabel(constant: string | null | undefined): string | null {
  return constant ? (GUIDANCE[constant] ?? constant.replace(/([a-z])([A-Z])/g, "$1 $2")) : null;
}

/** Friendly label of any DCS constant name. */
export function constantLabel(constant: string): string {
  return CONSTANTS[constant] ?? GUIDANCE[constant] ?? enumConstantLabel(constant);
}

/** The constant name of an enum value (numeric values looked up in the enum). */
export function enumConstant(
  entry: Pick<CatalogEntry, "enumType">,
  value: unknown,
  enums: Record<string, EnumInfo>,
): string | null {
  if (typeof value === "string") return value;
  if (typeof value !== "number" || !entry.enumType) return null;
  // A union (`OpticSensorType | RadarType`) is ambiguous when several members share the number.
  const hits = entry.enumType
    .split(" | ")
    .flatMap((t) => Object.entries(enums[t]?.values ?? {}).filter(([, v]) => v === value))
    .map(([k]) => k);
  return hits.length === 1 ? (hits[0] ?? null) : null;
}

/**
 * Friendly label and raw form of an enum value: `{ label: "Radar", raw: "SENSOR_RADAR = 1" }`.
 * String enums whose values are words (`fixedwing`) get a capitalised label.
 */
export function enumDisplay(
  entry: Pick<CatalogEntry, "enumType" | "name">,
  value: unknown,
  enums: Record<string, EnumInfo>,
): { label: string; raw: string } {
  if (entry.name === "seekerTypeName" && typeof value === "string") {
    return { label: guidanceLabel(value) ?? value, raw: value };
  }
  const constant = enumConstant(entry, value, enums);
  if (typeof value === "number") {
    return constant
      ? { label: constantLabel(constant), raw: `${constant} = ${value}` }
      : { label: String(value), raw: String(value) };
  }
  const text = String(value);
  // Value side of a string enum (`ROTARY: "rotary"`): label the value itself.
  if (/^[a-z][a-z0-9 -]*$/.test(text)) {
    return { label: text.charAt(0).toUpperCase() + text.slice(1).replace(/-/g, " "), raw: text };
  }
  return { label: constantLabel(text), raw: text };
}
