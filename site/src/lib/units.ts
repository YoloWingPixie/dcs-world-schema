/**
 * Units come from the schema's field-name suffixes (`massKg`, `rangeMaxM`, `v0Ms`...),
 * stored metric. The Metric / Imperial switch converts for display only: the stored value
 * and unit stay available (tooltips, copy).
 */
/** Longest suffix first: `Kmh` before `M`, `Ms` before `S`. */
const SUFFIX_UNITS: Array<[RegExp, string]> = [
  [/Kmh$/, "km/h"],
  [/MHz$/, "MHz"],
  [/KHz$/, "kHz"],
  [/Hz$/, "Hz"],
  [/Ms$/, "m/s"],
  [/M2$/, "m²"],
  [/Mm$/, "mm"],
  [/Kg$/, "kg"],
  [/Km$/, "km"],
  [/Deg$/, "°"],
  [/RadS$/, "rad/s"],
  [/DegS$/, "°/s"],
  [/Rad$/, "rad"],
  [/Rpm$/, "rpm"],
  [/M$/, "m"],
  [/S$/, "s"],
];

/** Fields whose unit the schema states in prose rather than a suffix. */
const NAMED_UNITS: Record<string, string> = {
  machMax: "Mach",
  machStep: "Mach",
  gLoadLimit: "g",
};

export function unitFor(name: string): string | null {
  const named = NAMED_UNITS[name];
  if (named) return named;
  for (const [pattern, unit] of SUFFIX_UNITS) {
    if (pattern.test(name)) return unit;
  }
  return null;
}

export function stripUnitSuffix(name: string): string {
  return name.replace(/(Kmh|MHz|KHz|Hz|Ms|M2|Mm|Kg|Km|RadS|DegS|Deg|Rad|Rpm|M|S)$/, "");
}

// ---------------------------------------------------------------------------
// Unit systems

export type UnitSystem = "metric" | "imperial";

type Conversion = { to: string; factor: number };

/**
 * Radians read as degrees in both systems (the schema stores what DCS stores; nobody
 * reads a gimbal limit in radians). The stored radian value stays in tooltips and copy.
 */
const DEGREES = 180 / Math.PI;
export const ANGLES: Record<string, Conversion> = {
  rad: { to: "°", factor: DEGREES },
  "rad/s": { to: "°/s", factor: DEGREES },
};

/** Metric unit -> imperial unit. Anything not listed (°, s, Mach, g, Hz, mm…) never converts. */
export const IMPERIAL: Record<string, Conversion> = {
  m: { to: "ft", factor: 3.280839895 },
  km: { to: "nm", factor: 1 / 1.852 },
  "m/s": { to: "kt", factor: 3600 / 1852 },
  "km/h": { to: "kt", factor: 1000 / 1852 },
  kg: { to: "lb", factor: 2.2046226218 },
  "m²": { to: "ft²", factor: 10.7639104167 },
  N: { to: "lbf", factor: 0.2248089431 },
  kgf: { to: "lbf", factor: 2.2046226218 },
};

/** Ranges and distances in metres read better in nautical miles than in feet. */
const RANGE_M: Conversion = { to: "nm", factor: 1 / 1852 };
/** Vertical speeds in m/s read as ft/min. */
const VERTICAL_MS: Conversion = { to: "ft/min", factor: 196.8503937 };

/**
 * The conversion for a stored unit, if any. `name` (the field name) refines metres:
 * ranges and distances go to nm, other lengths (altitudes, dimensions) to ft.
 */
export function conversionFor(
  unit: string | null,
  system: UnitSystem,
  name?: string,
): Conversion | null {
  if (!unit) return null;
  const angle = ANGLES[unit];
  if (angle) return angle;
  if (system === "metric") return null;
  if (unit === "m" && name && /range|distance/i.test(name) && !/altitude/i.test(name)) {
    return RANGE_M;
  }
  if (unit === "m/s" && name && /climb|vertical|vy\b|sinkrate/i.test(name)) return VERTICAL_MS;
  return IMPERIAL[unit] ?? null;
}

/** Keeps `sig` significant digits (no 12-decimal tails after converting). */
export function roundSignificant(value: number, sig = 4): number {
  if (value === 0 || !Number.isFinite(value)) return value;
  const digits = sig - Math.ceil(Math.log10(Math.abs(value)));
  if (digits <= 0) return Math.round(value);
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

export type Converted = { value: number; unit: string | null; converted: boolean };

/**
 * A "radians" value no angle can have (beyond a full turn): a DCS sentinel such as the
 * MANPADS' `reloadAngleY = -100` ("no reload pose"). It shows raw, never as degrees.
 */
export function isSentinelAngle(value: number, unit: string | null): boolean {
  return unit === "rad" && Math.abs(value) > 2 * Math.PI + 1e-9;
}

/** Display value in the chosen system (radians become degrees in both); `unitNotStated` fields never convert. */
export function convertValue(
  value: number,
  unit: string | null,
  system: UnitSystem,
  name?: string,
): Converted {
  if (isSentinelAngle(value, unit)) return { value, unit, converted: false };
  const c = conversionFor(unit, system, name);
  if (!c) return { value, unit, converted: false };
  return { value: roundSignificant(value * c.factor, 4), unit: c.to, converted: true };
}

/** The unit a field displays in under `system`. */
export function displayUnit(unit: string | null, system: UnitSystem, name?: string) {
  return conversionFor(unit, system, name)?.to ?? unit;
}

const groupFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Compact, honest number formatting: keeps up to `digits` significant decimals, no trailing zeros. */
export function formatNumber(value: number, digits = 4): string {
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) {
    return Math.abs(value) >= 10_000 ? groupFormat.format(value) : String(value);
  }
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 0.001 || abs >= 1e7)) return value.toExponential(2);
  const decimals = abs >= 100 ? 2 : abs >= 1 ? 3 : digits;
  const fixed = value.toFixed(decimals).replace(/\.?0+$/, "");
  return fixed === "-0" ? "0" : fixed;
}

export type FormattedValue = {
  text: string;
  unit: string | null;
  /** The stored value with its unit, when the display converted it ("161.48 kg"). */
  stored: string | null;
};

/** The space between a number and its unit: none before a degree sign ("60°", "12°/s"). */
export function unitGap(unit: string | null): string {
  return unit?.startsWith("°") ? "" : " ";
}

/** "9.45 m", "60°". */
export function withUnit(text: string, unit: string | null): string {
  return unit ? `${text}${unitGap(unit)}${unit}` : text;
}

export function formatWithUnit(
  value: number,
  unit: string | null,
  system: UnitSystem = "metric",
  name?: string,
): FormattedValue {
  if (unit === "Mach") {
    return { text: `Mach ${formatNumber(value)}`, unit: null, stored: null };
  }
  const c = convertValue(value, unit, system, name);
  return {
    text: formatNumber(c.value),
    unit: c.unit,
    stored: c.converted ? withUnit(formatNumber(value), unit) : null,
  };
}

/** The stored value with its unit ("0.3491 rad"), when the display converts it; else null. */
export function formatStored(
  value: number,
  unit: string | null,
  system: UnitSystem = "metric",
  name?: string,
): string | null {
  if (isSentinelAngle(value, unit)) return null;
  return conversionFor(unit, system, name) ? withUnit(formatNumber(value), unit) : null;
}

export function formatPlain(
  value: number,
  unit: string | null,
  system: UnitSystem = "metric",
  name?: string,
): string {
  const f = formatWithUnit(value, unit, system, name);
  return withUnit(f.text, f.unit);
}

// ---------------------------------------------------------------------------
// The site-wide choice lives in unit-system.ts (client); this script applies it before paint.

const KEY = "dcs-ref:units";

/**
 * Inline script for <head>: applies `?units=` (and remembers it) or the stored choice
 * before first paint, so the toggle renders in its final state.
 */
export const UNITS_BOOTSTRAP = `try{var u=new URLSearchParams(location.search).get("units");if(u==="metric"||u==="imperial")localStorage.setItem("${KEY}",u);else u=localStorage.getItem("${KEY}");if(u==="imperial")document.documentElement.dataset.units=u}catch(e){}`;
