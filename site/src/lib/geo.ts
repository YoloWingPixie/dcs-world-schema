/**
 * Where a record sits on the Earth, for the location figure (components/location-map).
 * Only WGS84 latitude/longitude the data already carries is plotted; DCS map x/z metres are
 * never projected here.
 */

export type LatLon = { lat: number; lon: number };

export type GeoPoint = LatLon & {
  /** `record`: the record itself; `equipment`: a navaid's transmitter; others are context. */
  kind: "record" | "equipment" | "stand" | "beacon";
  label: string;
};

export type GeoLine = { from: LatLon; to: LatLon; label: string };

export type Location = {
  /** The record's own position(s): one marker each, listed under the figure. */
  points: GeoPoint[];
  /** Context drawn around them: stands (dots). */
  extras: GeoPoint[];
  /** Runways, threshold to threshold. */
  lines: GeoLine[];
  /** Beacon ids whose positions arrive later (an airbase's beacons, a navaid's equipment). */
  beaconIds: string[];
  /** Beacons named by `beaconIds` are the record's own points (navaids), not context. */
  beaconsArePoints: boolean;
};

/** The section id the figure carries; coordinate fields link here. */
export const LOCATION_ID = "location";

type Json = Record<string, unknown>;

const isObj = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);

/** `{latitude, longitude}` in degrees, else null (x/z alone is not a location). */
export function latLonOf(v: unknown): LatLon | null {
  if (!isObj(v)) return null;
  const { latitude: lat, longitude: lon } = v;
  if (typeof lat !== "number" || typeof lon !== "number") return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

const strings = (v: unknown) =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

/** A record's location, or null when it has none. Series: beacons, airbases, navaids. */
export function locationOf(series: string, data: Json, name: string): Location | null {
  const none: Location = {
    points: [],
    extras: [],
    lines: [],
    beaconIds: [],
    beaconsArePoints: false,
  };
  if (series === "beacons") {
    const p = latLonOf(data);
    return p ? { ...none, points: [{ ...p, kind: "record", label: name }] } : null;
  }
  if (series === "navaids") {
    const ids = strings(data.equipment);
    return ids.length ? { ...none, beaconIds: ids, beaconsArePoints: true } : null;
  }
  if (series === "airbases") {
    const ref = latLonOf(data.referencePoint);
    if (!ref) return null;
    const lines: GeoLine[] = [];
    for (const rw of Array.isArray(data.runways) ? data.runways : []) {
      if (!isObj(rw) || !Array.isArray(rw.directions)) continue;
      const ends = rw.directions
        .map((d) => (isObj(d) ? latLonOf(d.threshold) : null))
        .filter((p): p is LatLon => p !== null);
      const [from, to] = ends;
      if (from && to) {
        lines.push({ from, to, label: `Runway ${String(rw.designator ?? "")}`.trim() });
      }
    }
    const extras: GeoPoint[] = [];
    for (const st of Array.isArray(data.stands) ? data.stands : []) {
      if (!isObj(st)) continue;
      const p = latLonOf(st.position);
      if (p) extras.push({ ...p, kind: "stand", label: `Stand ${String(st.name ?? "")}`.trim() });
    }
    return {
      points: [{ ...ref, kind: "record", label: `${name} reference point` }],
      extras,
      lines,
      beaconIds: strings(data.beacons),
      beaconsArePoints: false,
    };
  }
  return null;
}

/** A beacon record's position as a point of a figure. */
export function beaconPoint(data: Json, kind: GeoPoint["kind"], fallback: string): GeoPoint | null {
  const p = latLonOf(data);
  if (!p) return null;
  const type = typeof data.typeName === "string" ? data.typeName.replace(/^BEACON_TYPE_/, "") : "";
  const call = typeof data.callsign === "string" ? data.callsign : "";
  const label = [call, type.replace(/_/g, " ")].filter(Boolean).join(" · ") || fallback;
  return { ...p, kind, label };
}

/** 34°12′28.46″N */
export function dms(value: number, axis: "lat" | "lon"): string {
  const hemi = axis === "lat" ? (value < 0 ? "S" : "N") : value < 0 ? "W" : "E";
  // Round once, in hundredths of a second, so 59.995″ carries into the minute.
  const total = Math.round(Math.abs(value) * 360000);
  const deg = Math.floor(total / 360000);
  const min = Math.floor((total % 360000) / 6000);
  const sec = (total % 6000) / 100;
  const pad = (n: number, w: number) => String(n).padStart(w, "0");
  const width = axis === "lat" ? 2 : 3;
  return `${pad(deg, width)}°${pad(min, 2)}′${sec.toFixed(2).padStart(5, "0")}″${hemi}`;
}

/** 34.207906, 62.227941 (six places: about 0.1 m). */
export const decimal = (p: LatLon) => `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`;

export const osmUrl = (p: LatLon, zoom = 15) =>
  `https://www.openstreetmap.org/?mlat=${p.lat.toFixed(6)}&mlon=${p.lon.toFixed(6)}#map=${zoom}/${p.lat.toFixed(6)}/${p.lon.toFixed(6)}`;

export const googleUrl = (p: LatLon) =>
  `https://www.google.com/maps/search/?api=1&query=${p.lat.toFixed(6)}%2C${p.lon.toFixed(6)}`;

/**
 * Whether a field's value is a latitude or longitude in degrees, and so links to the figure.
 * Field names are `latitude` / `longitude` throughout the schema (beacons, `Entity.MapPoint`,
 * `Entity.GeoPoint`).
 */
export const isGeoField = (name: string) => name === "latitude" || name === "longitude";

/** Series whose record pages can carry the figure (and so the `#location` anchor). */
export const LOCATED_SERIES = new Set(["beacons", "airbases", "navaids"]);
