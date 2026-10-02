// Reference helpers: pure functions of the published data (map projection,
// threat rings, unit classification, loadout fit and mass, radio tuning, weapons
// and detection, TACAN channels, runways and stands, countries, liveries and
// datalinks) and pure geo maths (distances, coordinate formats, MGRS). The
// Python package is the reference implementation; the shared vectors in
// tools/package/tests/vectors/ hold this one to its results. Unknown ids and
// impossible inputs throw. Copied into src/ by tools/package/build.py.
import type { SeriesName } from './index.js';
import { loadSeries } from './index.js';
import { aircraftCarrying, loadIndexMeta, nameKey, threatsForUnit } from './lookup.js';
import type { Aircraft, Datalink, MapProjection, Station, StationForbidden, StationRequired, StationStore, Store, Theatre, UnitDetection, UnitModel, Warhead, Weapon, WeaponSystem } from './types.js';

function own<T>(table: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

async function record<S extends SeriesName>(series: S, id: string) {
  const found = own(await loadSeries(series), id);
  if (found === undefined) throw new Error(`no ${series} record ${JSON.stringify(id)}`);
  return found;
}

// Theatre projection ---------------------------------------------------------

export interface LatLon {
  readonly lat: number;
  readonly lon: number;
}

export interface MapXZ {
  readonly x: number;
  readonly z: number;
}

// WGS84 and the Krueger series to order n^6 (Karney 2011), as
// tools/datamine/tmerc.py fitted the projections with.
const F = 1 / 298.257223563;
const N = F / (2 - F);
const E = Math.sqrt(F * (2 - F));
const A_RECT = (6378137.0 / (1 + N)) * (1 + N ** 2 / 4 + N ** 4 / 64 + N ** 6 / 256);
const ALPHA = [
  N / 2 - (2 / 3) * N ** 2 + (5 / 16) * N ** 3 + (41 / 180) * N ** 4 - (127 / 288) * N ** 5 + (7891 / 37800) * N ** 6,
  (13 / 48) * N ** 2 - (3 / 5) * N ** 3 + (557 / 1440) * N ** 4 + (281 / 630) * N ** 5 - (1983433 / 1935360) * N ** 6,
  (61 / 240) * N ** 3 - (103 / 140) * N ** 4 + (15061 / 26880) * N ** 5 + (167603 / 181440) * N ** 6,
  (49561 / 161280) * N ** 4 - (179 / 168) * N ** 5 + (6601661 / 7257600) * N ** 6,
  (34729 / 80640) * N ** 5 - (3418889 / 1995840) * N ** 6,
  (212378941 / 319334400) * N ** 6,
];
const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;

function tm(lat: number, dlon: number): [number, number] {
  const phi = lat * RAD;
  const lam = dlon * RAD;
  const s = Math.sin(phi);
  const t = Math.sinh(Math.atanh(s) - E * Math.atanh(E * s));
  const xiP = Math.atan2(t, Math.cos(lam));
  const etaP = Math.atanh(Math.sin(lam) / Math.sqrt(1 + t * t));
  let xi = xiP;
  let eta = etaP;
  ALPHA.forEach((a, i) => {
    const j = i + 1;
    xi += a * Math.sin(2 * j * xiP) * Math.cosh(2 * j * etaP);
    eta += a * Math.cos(2 * j * xiP) * Math.sinh(2 * j * etaP);
  });
  return [A_RECT * eta, A_RECT * xi];
}

/** The Transverse Mercator parameters `toMap` needs. */
type Tm = Pick<MapProjection, 'centralMeridian' | 'scaleFactor' | 'falseEasting' | 'falseNorthing'>;

function toMap(p: Tm, lat: number, lon: number): [number, number] {
  const [e, n] = tm(lat, lon - p.centralMeridian);
  const k = p.scaleFactor;
  return [p.falseNorthing + k * n, p.falseEasting + k * e];
}

async function projection(theatre: string): Promise<MapProjection> {
  const found = await theatreByName(theatre);
  if (found === undefined) throw new Error(`no theatre ${JSON.stringify(theatre)}`);
  if (found.projection === undefined) throw new Error(`theatre ${found.id} has no map projection`);
  return found.projection;
}

/** The theatre whose id, displayName, directory or one of its `aliases` is `name` (trimmed, ASCII case-insensitive). */
export async function theatreByName(name: string): Promise<Theatre | undefined> {
  const key = nameKey(name);
  for (const t of Object.values(await loadSeries('theatres'))) {
    const names = [t.id, t.displayName, t.directory, ...(t.aliases ?? [])];
    if (names.some((n) => n !== undefined && nameKey(n) === key)) return t;
  }
  return undefined;
}

/** DCS map metres (`x` north, `z` east) of a WGS84 latitude/longitude on `theatre` (anything `theatreByName` accepts). */
export async function toMapXZ(theatre: string, lat: number, lon: number): Promise<MapXZ> {
  const [x, z] = toMap(await projection(theatre), lat, lon);
  return { x, z };
}

/** WGS84 latitude/longitude of map metres (`x`, `z`) on `theatre`: Newton iteration on `toMapXZ` until both residuals are under a micrometre. */
export async function toLatLon(theatre: string, x: number, z: number): Promise<LatLon> {
  return inverse(await projection(theatre), x, z);
}

function inverse(p: Tm, x: number, z: number): LatLon {
  let lat = 0;
  let lon = p.centralMeridian;
  const h = 1e-6;
  for (let i = 0; i < 50; i++) {
    const [px, pz] = toMap(p, lat, lon);
    const dx = x - px;
    const dz = z - pz;
    if (Math.abs(dx) < 1e-6 && Math.abs(dz) < 1e-6) return { lat, lon };
    const [x1, z1] = toMap(p, lat + h, lon);
    const [x2, z2] = toMap(p, lat, lon + h);
    const a = (x1 - px) / h;
    const b = (x2 - px) / h;
    const c = (z1 - pz) / h;
    const d = (z2 - pz) / h;
    const det = a * d - b * c;
    lat += (d * dx - b * dz) / det;
    lon += (a * dz - c * dx) / det;
  }
  throw new Error(`toLatLon did not converge for (${x}, ${z})`);
}

// Threats ----------------------------------------------------------------------

/** The union of a threat's engagement envelopes and its sensors' reach; a limit is present only when every envelope gives it. */
export interface ThreatRange {
  readonly rMinKm?: number;
  readonly rMaxKm?: number;
  readonly hMinM?: number;
  readonly hMaxM?: number;
  readonly detectionKm?: number;
}

type EnvelopeKey = 'rMinKm' | 'rMaxKm' | 'hMinM' | 'hMaxM';

/**
 * Over every component `envelope` and `gunEnvelope` of threat `threatId`: `rMaxKm`/`hMaxM` the largest,
 * `rMinKm`/`hMinM` the smallest, each only when every envelope gives it. `detectionKm` is the largest
 * `detectionRangeKm` of its `sensors`.
 */
export async function threatRange(threatId: string): Promise<ThreatRange> {
  const threat = await record('threats', threatId);
  const envelopes = (threat.components ?? []).flatMap((c) =>
    [c.envelope, c.gunEnvelope].filter((e) => e !== undefined),
  );
  const out: { -readonly [K in keyof ThreatRange]?: number } = {};
  const picks: [EnvelopeKey, (...v: number[]) => number][] = [
    ['rMinKm', Math.min],
    ['rMaxKm', Math.max],
    ['hMinM', Math.min],
    ['hMaxM', Math.max],
  ];
  for (const [key, pick] of picks) {
    const values = envelopes.flatMap((e) => (e[key] === undefined ? [] : [e[key]]));
    if (envelopes.length > 0 && values.length === envelopes.length) out[key] = pick(...values);
  }
  const sensors = await loadSeries('sensors');
  const reach = (threat.sensors ?? []).flatMap((s) => {
    const km = own(sensors, s)?.detectionRangeKm;
    return km === undefined ? [] : [km];
  });
  if (reach.length > 0) out.detectionKm = Math.max(...reach);
  return out;
}

async function unitSeries(unitId: string): Promise<SeriesName | undefined> {
  for (const s of (await loadIndexMeta()).unitSeries) {
    if (own(await loadSeries(s), unitId) !== undefined) return s;
  }
  return undefined;
}

/** Threat systems (`threats` ids) unit type `unitType` is a component or the emitter of; throws for an id no unit series holds. */
export async function threatForUnitType(unitType: string): Promise<readonly string[]> {
  if ((await unitSeries(unitType)) === undefined) throw new Error(`no unit type ${JSON.stringify(unitType)}`);
  return threatsForUnit(unitType);
}

/** Mean Earth radius (IUGG) of the spherical ring geometry, metres. */
export const EARTH_RADIUS_M = 6371008.8;

function destinationLonLat(lat: number, lon: number, bearing: number, distM: number): [number, number] {
  const phi = lat * RAD;
  const lam = lon * RAD;
  const theta = bearing * RAD;
  const delta = distM / EARTH_RADIUS_M;
  const phi2 = Math.asin(Math.sin(phi) * Math.cos(delta) + Math.cos(phi) * Math.sin(delta) * Math.cos(theta));
  const lam2 =
    lam +
    Math.atan2(Math.sin(theta) * Math.sin(delta) * Math.cos(phi), Math.cos(delta) - Math.sin(phi) * Math.sin(phi2));
  const lon2 = lam2 * DEG;
  return [((((lon2 + 180) % 360) + 360) % 360) - 180, phi2 * DEG];
}

function ring(lat: number, lon: number, km: number, segments: number, clockwise: boolean): [number, number][] {
  const points: [number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const step = i % segments;
    const bearing = clockwise ? (360 * step) / segments : ((360 * (segments - step)) / segments) % 360;
    points.push(destinationLonLat(lat, lon, bearing, km * 1000));
  }
  return points;
}

/** GeoJSON of `threatRingGeoJSON`: one Polygon feature. */
export interface ThreatRingCollection {
  readonly type: 'FeatureCollection';
  readonly features: readonly [
    {
      readonly type: 'Feature';
      readonly properties: ThreatRange & { readonly threat: string };
      readonly geometry: { readonly type: 'Polygon'; readonly coordinates: [number, number][][] };
    },
  ];
}

/**
 * The threat's `rMaxKm` ring around (`lat`, `lon`) (counterclockwise, as RFC 7946 wants an exterior ring)
 * with its `rMinKm` ring as a clockwise hole when `rMinKm > 0`; `segments` points per ring plus the closing
 * one. Throws for a threat without `rMaxKm` or `segments < 3`.
 */
export async function threatRingGeoJSON(
  threatId: string,
  lat: number,
  lon: number,
  options: { readonly segments?: number } = {},
): Promise<ThreatRingCollection> {
  const segments = options.segments ?? 64;
  if (segments < 3) throw new Error(`segments must be at least 3, got ${segments}`);
  const range = await threatRange(threatId);
  if (range.rMaxKm === undefined) throw new Error(`threat ${threatId} has no engagement range`);
  const rings = [ring(lat, lon, range.rMaxKm, segments, false)];
  if ((range.rMinKm ?? 0) > 0) rings.push(ring(lat, lon, range.rMinKm!, segments, true));
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { threat: threatId, ...range },
        geometry: { type: 'Polygon', coordinates: rings },
      },
    ],
  };
}

// Classification ----------------------------------------------------------------

type Facts = Readonly<Record<string, readonly string[]>>;
type When = Readonly<Record<string, { readonly any?: readonly string[]; readonly all?: readonly string[]; readonly none?: readonly string[] }>>;
interface Classification {
  readonly unitClasses: readonly { readonly class: string; readonly when: When }[];
  readonly aircraftRoles: readonly { readonly role: string; readonly when: When }[];
}

let classification: Promise<Classification> | undefined;

function loadClassification(): Promise<Classification> {
  classification ??= import('../data/_index/classification.json', { with: { type: 'json' } }).then(
    (mod: { default: unknown }) => mod.default as Classification,
  );
  return classification;
}

function matches(when: When, facts: Facts): boolean {
  for (const [fact, tests] of Object.entries(when)) {
    const have = new Set(own(facts, fact) ?? []);
    if (tests.any !== undefined && !tests.any.some((v) => have.has(v))) return false;
    if (tests.all !== undefined && !tests.all.every((v) => have.has(v))) return false;
    if (tests.none !== undefined && tests.none.some((v) => have.has(v))) return false;
  }
  return true;
}

/** Sorted roles of aircraft `aircraftId`: those of every matching `aircraft/roles` rule of the `classification` index. */
export async function aircraftRoles(aircraftId: string): Promise<readonly string[]> {
  const a: Aircraft = await record('aircraft', aircraftId);
  const tanker = a.refuelling?.isTanker;
  const facts: Facts = {
    attributes: a.attributes ?? [],
    kind: [a.kind],
    tasks: (a.tasks ?? []).map((t) => t.name),
    defaultTask: a.defaultTask ? [a.defaultTask.name] : [],
    isTanker: tanker !== undefined && tanker !== false && tanker !== 0 ? ['true'] : [],
  };
  const rules = (await loadClassification()).aircraftRoles;
  return [...new Set(rules.filter((r) => matches(r.when, facts)).map((r) => r.role))].sort();
}

/** Class of unit `unitId` (any unit series): that of the first matching `units/classes` rule, else `other`. */
export async function unitClass(unitId: string): Promise<string> {
  const series = await unitSeries(unitId);
  if (series === undefined) throw new Error(`no unit type ${JSON.stringify(unitId)}`);
  const u = (await loadSeries(series))[unitId] as { readonly attributes?: readonly string[]; readonly kind?: string };
  const facts: Facts = {
    series: [series],
    attributes: u.attributes ?? [],
    kind: series === 'aircraft' && u.kind !== undefined ? [u.kind] : [],
  };
  for (const r of (await loadClassification()).unitClasses) {
    if (matches(r.when, facts)) return r.class;
  }
  return 'other';
}

// Loadouts ------------------------------------------------------------------------

export interface FitConflict {
  /** Position in the requested list. */
  readonly index: number;
  readonly clsid: string;
  /**
   * `unsupported`: no station accepts the store; `noFreeStation`: its stations are all needed by the stores
   * before it; `loadoutRules`: every placement with them breaks a station's `forbidden`/`required` rule.
   */
  readonly reason: 'unsupported' | 'noFreeStation' | 'loadoutRules';
}

export type FitResult =
  | { readonly assignment: Readonly<Record<number, string>>; readonly conflicts?: undefined }
  | { readonly conflicts: readonly FitConflict[]; readonly assignment?: undefined };

export interface LoadoutMass {
  readonly totalKg: number;
  readonly emptyKg: number;
  readonly storesKg: number;
  readonly fuelKg: number;
  readonly maxTakeoffKg?: number;
  readonly overMtow?: boolean;
}

async function stations(aircraftId: string): Promise<Station[]> {
  const a = await record('aircraft', aircraftId);
  return [...(a.stations ?? [])].sort((p, q) => p.station - q.station);
}

async function store(clsid: string): Promise<Store> {
  return record('stores', clsid);
}

function accepted(station: Station, clsid: string): StationStore | undefined {
  return station.accepts.find((a) => a.clsid === clsid);
}

/** Station numbers (ascending) of aircraft `aircraftId` accepting store `clsid`. */
export async function stationsAccepting(aircraftId: string, clsid: string): Promise<readonly number[]> {
  await store(clsid);
  return (await stations(aircraftId)).filter((s) => accepted(s, clsid)).map((s) => s.station);
}

/** Whether station `station` of aircraft `aircraftId` accepts store `clsid`; throws for a station the aircraft lacks. */
export async function canMount(aircraftId: string, station: number, clsid: string): Promise<boolean> {
  await store(clsid);
  const found = (await stations(aircraftId)).find((s) => s.station === station);
  if (found === undefined) throw new Error(`aircraft ${aircraftId} has no station ${station}`);
  return accepted(found, clsid) !== undefined;
}

/** Size of a maximum matching of stores (each a list of candidate stations) to distinct stations. */
function matching(options: readonly (readonly number[])[]): number {
  const owner = new Map<number, number>();
  const augment = (i: number, seen: Set<number>): boolean => {
    for (const s of options[i]!) {
      if (seen.has(s)) continue;
      seen.add(s);
      const held = owner.get(s);
      if (held === undefined || augment(held, seen)) {
        owner.set(s, i);
        return true;
      }
    }
    return false;
  };
  let size = 0;
  for (let i = 0; i < options.length; i++) if (augment(i, new Set())) size++;
  return size;
}

type Rules = ReadonlyMap<string, StationStore>;

const ruleKey = (station: number, clsid: string): string => `${station} ${clsid}`;

/**
 * Whether `occupant` (undefined: empty) of the rule's station breaks it: a `required` rule wants one of
 * `clsids` (or nothing with `allowEmpty`), a `forbidden` rule none of `clsids` (no store with `anyStore`).
 */
function breaks(rule: StationForbidden | StationRequired, occupant: string | undefined): boolean {
  if ('allowEmpty' in rule) return occupant === undefined ? !rule.allowEmpty : !rule.clsids.includes(occupant);
  return occupant !== undefined && (rule.anyStore === true || (rule.clsids ?? []).includes(occupant));
}

/**
 * Whether store `c` can join `a` (station -> CLSID) on station `s` without breaking a rule of either side;
 * a `required` rule on a station still empty is left to the complete assignment.
 */
function allowed(a: ReadonlyMap<number, string>, rules: Rules, s: number, c: string): boolean {
  for (const kind of ['forbidden', 'required'] as const) {
    for (const r of rules.get(ruleKey(s, c))![kind] ?? []) {
      const occupant = r.station === s ? c : a.get(r.station);
      if (occupant !== undefined && breaks(r, occupant)) return false;
    }
    for (const [t, o] of a) {
      for (const r of rules.get(ruleKey(t, o))![kind] ?? []) {
        if (r.station === s && breaks(r, c)) return false;
      }
    }
  }
  return true;
}

/**
 * Whether stores of `pool` (each used once) can fill every station a `required` rule of `a` needs, keeping
 * every rule; `a` is restored.
 */
function complete(
  a: Map<number, string>,
  rules: Rules,
  clsids: readonly string[],
  options: readonly (readonly number[])[],
  pool: readonly number[],
): boolean {
  let need: StationRequired | undefined;
  for (const [t, o] of a) {
    need = (rules.get(ruleKey(t, o))!.required ?? []).find((r) => breaks(r, a.get(r.station)));
    if (need !== undefined) break;
  }
  if (need === undefined) return true;
  const s = need.station;
  if (a.has(s)) return false;
  const tried = new Set<string>();
  for (const j of pool) {
    const c = clsids[j]!;
    if (tried.has(c) || !need.clsids.includes(c) || !options[j]!.includes(s)) continue;
    tried.add(c);
    if (!allowed(a, rules, s, c)) continue;
    a.set(s, c);
    const done = complete(a, rules, clsids, options, pool.filter((k) => k !== j));
    a.delete(s);
    if (done) return true;
  }
  return false;
}

/**
 * The first assignment of stores `idx` (in order, each on its lowest station that leaves the rest
 * placeable) keeping every rule, stations `required` rules need left empty only where stores of `pool` can
 * fill them; undefined if none.
 */
function place(
  clsids: readonly string[],
  options: readonly (readonly number[])[],
  idx: readonly number[],
  rules: Rules,
  pool: readonly number[] = [],
): Record<number, string> | undefined {
  const a = new Map<number, string>();
  const at = new Map<number, number>();
  const step = (k: number): boolean => {
    if (k === idx.length) return complete(a, rules, clsids, options, pool);
    const i = idx[k]!;
    // A store equal to an earlier one goes above it (same fits, fewer tries).
    let low: number | undefined;
    for (const j of idx.slice(0, k)) {
      if (clsids[j] === clsids[i]) low = Math.max(low ?? -Infinity, at.get(j)!);
    }
    for (const s of options[i]!) {
      if (a.has(s) || (low !== undefined && s <= low) || !allowed(a, rules, s, clsids[i]!)) continue;
      a.set(s, clsids[i]!);
      at.set(i, s);
      const rest = idx.slice(k + 1).map((j) => options[j]!.filter((t) => !a.has(t)));
      if (matching(rest) === rest.length && step(k + 1)) return true;
      a.delete(s);
      at.delete(i);
    }
    return false;
  };
  if (!step(0)) return undefined;
  const out: Record<number, string> = {};
  for (const s of [...a.keys()].sort((p, q) => p - q)) out[s] = a.get(s)!;
  return out;
}

/**
 * Put each store of `clsids` on its own station of `aircraftId`. A store no station accepts is
 * `unsupported`; the others are taken in list order, each kept while all kept stores still fit on distinct
 * stations (else `noFreeStation`) and some such placement, with stores later in the list filling the
 * stations its `required` rules need, keeps every station's `forbidden`/`required` rules (else
 * `loadoutRules`; a `required` station must hold a listed store, or be empty where it `allowEmpty`). Every
 * station accepting a store is a candidate, whatever its `type`, as in the mission editor. With no
 * conflicts, each store in list order gets the lowest-numbered station that leaves the rest placeable.
 */
export async function fitStores(aircraftId: string, clsids: readonly string[]): Promise<FitResult> {
  // Same lookup order, hence same error, as stationsAccepting per store.
  for (const c of clsids.slice(0, 1)) await store(c);
  const all = await stations(aircraftId);
  for (const c of clsids.slice(1)) await store(c);
  const rules = new Map<string, StationStore>();
  const accepting = new Map<string, number[]>(clsids.map((c) => [c, []]));
  for (const s of all) {
    const here = new Set<string>();
    for (const a of s.accepts) {
      const opts = accepting.get(a.clsid);
      if (opts === undefined) continue;
      rules.set(ruleKey(s.station, a.clsid), a);
      if (!here.has(a.clsid)) {
        here.add(a.clsid);
        opts.push(s.station);
      }
    }
  }
  const options: readonly (readonly number[])[] = clsids.map((c) => accepting.get(c)!);
  // Without rules every placement that fits keeps them.
  const ruled = clsids.some((c, i) =>
    options[i]!.some((s) => {
      const r = rules.get(ruleKey(s, c))!;
      return (r.forbidden?.length ?? 0) > 0 || (r.required?.length ?? 0) > 0;
    }),
  );
  const conflicts: FitConflict[] = [];
  const kept: number[] = [];
  let placed: Record<number, string> | undefined;
  const later = (i: number): number[] =>
    options.flatMap((opts, k) => (k > i && opts.length > 0 ? [k] : []));
  options.forEach((opts, i) => {
    let reason: FitConflict['reason'] | undefined;
    if (opts.length === 0) reason = 'unsupported';
    else if (matching([...kept, i].map((k) => options[k]!)) !== kept.length + 1) reason = 'noFreeStation';
    else if (ruled) {
      placed = place(clsids, options, [...kept, i], rules, later(i));
      if (placed === undefined) reason = 'loadoutRules';
    }
    if (reason === undefined) kept.push(i);
    else conflicts.push({ index: i, clsid: clsids[i]!, reason });
  });
  if (conflicts.length > 0) return { conflicts };
  // With no conflicts the last store's placement is that of every store.
  return { assignment: placed ?? place(clsids, options, kept, rules) ?? {} };
}

/**
 * Mass of aircraft `aircraftId` with `loadout` (station -> store CLSID) and `fuelKg` of internal fuel
 * (default `aero.internalFuelKg`, full): `emptyKg` + `storesKg` (each store's `aero.massKg`, DCS's launcher
 * `Weight`: rack and contents included) + `fuelKg`; with `aero.maxTakeoffKg`, `maxTakeoffKg` and `overMtow`.
 * Throws for a station that does not accept its store, a store without a mass, a missing empty mass, fuel not
 * given where the aircraft has no `internalFuelKg`, or fuel outside 0..`internalFuelKg`.
 */
export async function loadoutMass(
  aircraftId: string,
  loadout: Readonly<Record<number, string>>,
  fuelKg?: number,
): Promise<LoadoutMass> {
  const aero = (await record('aircraft', aircraftId)).aero ?? {};
  if (aero.emptyMassKg === undefined) throw new Error(`aircraft ${aircraftId} has no aero.emptyMassKg`);
  const capacity = aero.internalFuelKg;
  let fuel = fuelKg;
  if (fuel === undefined) {
    if (capacity === undefined) throw new Error(`aircraft ${aircraftId} has no aero.internalFuelKg; pass fuelKg`);
    fuel = capacity;
  }
  if (fuel < 0 || (capacity !== undefined && fuel > capacity)) {
    throw new Error(`fuel ${fuel} kg outside 0..${capacity} kg for ${aircraftId}`);
  }
  let storesKg = 0;
  const entries = Object.entries(loadout)
    .map(([k, v]) => [Number(k), v] as const)
    .sort((p, q) => p[0] - q[0]);
  for (const [station, clsid] of entries) {
    if (!(await canMount(aircraftId, station, clsid))) {
      throw new Error(`station ${station} of ${aircraftId} does not accept ${clsid}`);
    }
    const mass = (await store(clsid)).aero?.massKg;
    if (mass === undefined) throw new Error(`store ${clsid} has no aero.massKg`);
    storesKg += mass;
  }
  const emptyKg = aero.emptyMassKg;
  const totalKg = emptyKg + storesKg + fuel;
  const out: LoadoutMass = { totalKg, emptyKg, storesKg, fuelKg: fuel };
  if (aero.maxTakeoffKg === undefined) return out;
  return { ...out, maxTakeoffKg: aero.maxTakeoffKg, overMtow: totalKg > aero.maxTakeoffKg };
}

// Radios --------------------------------------------------------------------------

export interface FrequencyRange {
  readonly minMHz: number;
  readonly maxMHz: number;
  /** DCS `MODULATION_*` names. */
  readonly modulations: readonly string[];
}

export interface RadioBands {
  /** `<index>` of the radio id `<aircraft>__radio<index>` (DCS `panelRadio` order, from 0). */
  readonly index: number;
  readonly id: string;
  readonly band: string;
  readonly ranges: readonly FrequencyRange[];
  readonly presets: number;
  readonly guard: boolean;
  readonly stepKHz?: number;
}

export interface FrequencyCheck {
  readonly ok: boolean;
  readonly reason?: 'outOfRange' | 'offStep';
}

const RADIO_SEP = '__radio';

/** The radios of aircraft `aircraftId` by index: band, tunable ranges (the DCS range segments) with their modulations, presets, guard and `stepKHz` where given. */
export async function radioBands(aircraftId: string): Promise<readonly RadioBands[]> {
  const radios = await loadSeries('radios');
  const out: RadioBands[] = [];
  for (const rid of (await record('aircraft', aircraftId)).radios ?? []) {
    const r = own(radios, rid);
    if (r === undefined) throw new Error(`no radios record ${JSON.stringify(rid)}`);
    const at = rid.lastIndexOf(RADIO_SEP);
    const index = rid.slice(at + RADIO_SEP.length);
    if (at < 0 || rid.slice(0, at) !== aircraftId || !/^[0-9]+$/.test(index)) {
      throw new Error(`radio id ${JSON.stringify(rid)} is not ${aircraftId}${RADIO_SEP}<index>`);
    }
    out.push({
      index: Number(index),
      id: rid,
      band: r.band,
      ranges: r.segments.map((s) => ({ minMHz: s.minMHz, maxMHz: s.maxMHz, modulations: [s.modulationName] })),
      presets: r.presets,
      guard: r.guard,
      ...(r.stepKHz === undefined ? {} : { stepKHz: r.stepKHz }),
    });
  }
  return out.sort((p, q) => p.index - q.index);
}

/** Largest distance from a tuning step, in steps, still on the step grid. */
export const STEP_TOLERANCE = 1e-6;

/**
 * Whether radio `radioIndex` of `aircraftId` tunes `mhz`: within a range (else `outOfRange`) and, with
 * `stepKHz`, on the step grid counted from 0 Hz (else `offStep`). Throws for a radio the aircraft lacks.
 */
export async function isValidFrequency(aircraftId: string, radioIndex: number, mhz: number): Promise<FrequencyCheck> {
  const r = (await radioBands(aircraftId)).find((b) => b.index === radioIndex);
  if (r === undefined) throw new Error(`aircraft ${aircraftId} has no radio ${radioIndex}`);
  if (!r.ranges.some((g) => g.minMHz <= mhz && mhz <= g.maxMHz)) return { ok: false, reason: 'outOfRange' };
  if (r.stepKHz !== undefined) {
    const steps = (mhz * 1000) / r.stepKHz;
    if (Math.abs(steps - Math.round(steps)) > STEP_TOLERANCE) return { ok: false, reason: 'offStep' };
  }
  return { ok: true };
}

// Weapons -------------------------------------------------------------------------

/** A warhead record, as the data gives it. */
export type WarheadInfo = Readonly<Warhead>;

/** A weapon record's fields as the data gives them (no `_source`), its `warhead` resolved to the warhead record. */
export type WeaponInfo = Readonly<Omit<Weapon, '_source' | 'warhead'>> & { readonly warhead?: WarheadInfo };

export interface LaunchPlatforms {
  readonly aircraft: readonly string[];
  readonly groundVehicles: readonly string[];
  readonly ships: readonly string[];
}

async function weaponIdOf(idOrClsid: string): Promise<string> {
  if (own(await loadSeries('weapons'), idOrClsid) !== undefined) return idOrClsid;
  const found = own(await loadSeries('stores'), idOrClsid);
  if (found === undefined) throw new Error(`no weapon or store ${JSON.stringify(idOrClsid)}`);
  const delivered = [...new Set((found.delivers ?? []).map((d) => String(d.weapon)))].sort();
  if (delivered.length !== 1) {
    throw new Error(`store ${idOrClsid} delivers ${delivered.length} weapon types, not one`);
  }
  return delivered[0]!;
}

/**
 * The weapon `idOrClsid` names: a weapon id, else the CLSID of a store delivering exactly one weapon type
 * (throws for a store delivering several or none). Fields are the weapon record's (`_source` dropped), with
 * `warhead` the warhead record; a field the data lacks is absent.
 */
export async function weaponInfo(idOrClsid: string): Promise<WeaponInfo> {
  const { _source, warhead, ...rest } = await record('weapons', await weaponIdOf(idOrClsid));
  if (warhead === undefined) return rest;
  return { ...rest, warhead: { ...(await record('warheads', warhead)) } };
}

async function surfaceLaunchers(series: 'ground_vehicles' | 'ships', weaponId: string): Promise<string[]> {
  const units = await loadSeries(series);
  return Object.keys(units)
    .filter((uid) =>
      (units[uid]!.weaponSystems ?? []).some((ws: WeaponSystem) => (ws.weapons ?? []).includes(weaponId)),
    )
    .sort();
}

/**
 * Unit types launching weapon `weaponId`, sorted: `aircraft` with a station accepting a store that delivers it
 * (the `carriers` index), `groundVehicles` and `ships` with a launcher (`weaponSystems[]`) whose `weapons` hold it.
 */
export async function launchPlatforms(weaponId: string): Promise<LaunchPlatforms> {
  await record('weapons', weaponId);
  return {
    aircraft: await aircraftCarrying(weaponId),
    groundVehicles: await surfaceLaunchers('ground_vehicles', weaponId),
    ships: await surfaceLaunchers('ships', weaponId),
  };
}

/**
 * Unit ids of every unit series whose `model.shape` is `shape`, sorted. Names compare as `nameKey` does
 * (trimmed, ASCII case-insensitive): DCS finds models by file name, and Windows file names ignore case.
 */
export async function modelToUnits(shape: string): Promise<readonly string[]> {
  const key = nameKey(shape);
  const out: string[] = [];
  for (const s of (await loadIndexMeta()).unitSeries) {
    const units = (await loadSeries(s)) as Readonly<Record<string, { readonly model?: UnitModel }>>;
    for (const [uid, u] of Object.entries(units)) {
      const found = u.model?.shape;
      if (typeof found === 'string' && nameKey(found) === key) out.push(uid);
    }
  }
  return out.sort();
}

export interface SensorSummary {
  readonly id: string;
  readonly kind: string;
  readonly detectionRangeKm?: number;
}

/** A unit's `detection` fields as the data gives them, and its sensors. */
export type UnitDetectionInfo = Readonly<UnitDetection> & { readonly sensors: readonly SensorSummary[] };

/**
 * Detection values of unit `unitId` (any unit series): its `detection` fields, and `sensors`, its sensor ids in
 * record order with each sensor's `kind` and `detectionRangeKm` (when given).
 */
export async function unitDetection(unitId: string): Promise<UnitDetectionInfo> {
  const series = await unitSeries(unitId);
  if (series === undefined) throw new Error(`no unit type ${JSON.stringify(unitId)}`);
  const u = (await loadSeries(series))[unitId] as {
    readonly detection?: UnitDetection;
    readonly sensors?: readonly string[];
  };
  const sensors: SensorSummary[] = [];
  for (const sid of u.sensors ?? []) {
    const s = await record('sensors', sid);
    sensors.push({
      id: sid,
      kind: s.kind,
      ...(s.detectionRangeKm === undefined ? {} : { detectionRangeKm: s.detectionRangeKm }),
    });
  }
  return { ...(u.detection ?? {}), sensors };
}

// TACAN and navaids ------------------------------------------------------------------

export type TacanBand = 'X' | 'Y';

export interface TacanFrequency {
  /** Transmit frequency of the side `role` names. */
  readonly txMHz: number;
  /** Receive frequency of that side. */
  readonly rxMHz: number;
  /** The VOR/ILS frequency the channel pairs with, when it pairs. */
  readonly pairedVhfMHz?: number;
}

export interface TacanChannel {
  readonly channel: number;
  readonly band: TacanBand;
}

interface ChannelRange {
  readonly from: number;
  readonly to: number;
}

interface TacanPlan {
  readonly channels: { readonly first: number; readonly last: number };
  readonly bands: readonly string[];
  readonly interrogationMHz: { readonly base: number };
  readonly replyOffsetMHz: Readonly<Record<string, readonly (ChannelRange & { readonly offset: number })[]>>;
  readonly vhfPairing: {
    readonly ranges: readonly (ChannelRange & { readonly baseKHz: number })[];
    readonly stepKHz: number;
    readonly bandOffsetKHz: Readonly<Record<string, number>>;
  };
}

let tacanPlan: Promise<TacanPlan> | undefined;

function loadTacanPlan(): Promise<TacanPlan> {
  tacanPlan ??= import('../data/_index/tacan.json', { with: { type: 'json' } }).then(
    (mod: { default: unknown }) => mod.default as TacanPlan,
  );
  return tacanPlan;
}

function validTacan(plan: TacanPlan, channel: number, band: string): boolean {
  return (
    typeof channel === 'number' &&
    channel === Math.floor(channel) &&
    plan.channels.first <= channel &&
    channel <= plan.channels.last &&
    plan.bands.includes(band)
  );
}

/** Whether `channel` (an integer) and `band` name a channel of the `tacan` plan (1-126, X or Y). */
export async function isValidTacan(channel: number, band: string): Promise<boolean> {
  return validTacan(await loadTacanPlan(), channel, band);
}

/** [interrogation MHz, reply MHz, paired VHF MHz or undefined]. */
function tacan(plan: TacanPlan, channel: number, band: string): [number, number, number | undefined] {
  const air = plan.interrogationMHz.base + channel - plan.channels.first;
  const reply = plan.replyOffsetMHz[band]!.find((r) => r.from <= channel && channel <= r.to)!;
  const pairing = plan.vhfPairing;
  const hit = pairing.ranges.find((r) => r.from <= channel && channel <= r.to);
  let vhf: number | undefined;
  if (hit !== undefined) {
    const khz = hit.baseKHz + (channel - hit.from) * pairing.stepKHz;
    vhf = (khz + pairing.bandOffsetKHz[band]!) / 1000;
  }
  return [air, air + reply.offset, vhf];
}

/**
 * Frequencies of TACAN/DME channel `channel` `band` for the airborne interrogator (`role` `air`: transmits the
 * interrogation, receives the reply) or the ground beacon (`ground`: the other way round), from the `tacan`
 * index (ICAO Annex 10 Table A). Throws for a channel `isValidTacan` rejects.
 */
export async function tacanFrequency(
  channel: number,
  band: TacanBand,
  role: 'air' | 'ground',
): Promise<TacanFrequency> {
  const plan = await loadTacanPlan();
  if (!validTacan(plan, channel, band)) throw new Error(`no TACAN channel ${channel}${band}`);
  if (role !== 'air' && role !== 'ground') throw new Error(`role must be air or ground, got ${JSON.stringify(role)}`);
  const [air, reply, vhf] = tacan(plan, channel, band);
  const out = role === 'air' ? { txMHz: air, rxMHz: reply } : { txMHz: reply, rxMHz: air };
  return vhf === undefined ? out : { ...out, pairedVhfMHz: vhf };
}

/** Largest difference, MHz, at which `tacanChannel` counts a match. */
export const FREQUENCY_TOLERANCE_MHZ = 1e-6;

/**
 * Every channel (sorted by channel, then band) whose `role` side transmits on `mhz` (`air`: the interrogation,
 * which X and Y channels share; `ground`: the reply) or, for `vhf`, that pairs with VOR/ILS frequency `mhz`.
 */
export async function tacanChannel(mhz: number, role: 'air' | 'ground' | 'vhf'): Promise<readonly TacanChannel[]> {
  if (role !== 'air' && role !== 'ground' && role !== 'vhf') {
    throw new Error(`role must be air, ground or vhf, got ${JSON.stringify(role)}`);
  }
  const plan = await loadTacanPlan();
  const out: TacanChannel[] = [];
  for (let ch = plan.channels.first; ch <= plan.channels.last; ch++) {
    for (const band of plan.bands) {
      const [air, reply, vhf] = tacan(plan, ch, band);
      const value = role === 'air' ? air : role === 'ground' ? reply : vhf;
      if (value !== undefined && Math.abs(value - mhz) <= FREQUENCY_TOLERANCE_MHZ) {
        out.push({ channel: ch, band: band as TacanBand });
      }
    }
  }
  return out;
}

/**
 * `navaids` ids (ILS/PRMG) of airbase `airbaseId`, or of its runway end `runway` (a direction `designator`,
 * case-insensitive), sorted. Throws for an end the airbase lacks.
 */
export async function navaidsFor(airbaseId: string, runway?: string): Promise<readonly string[]> {
  const ab = await record('airbases', airbaseId);
  if (runway === undefined) return [...(ab.navaids ?? [])].sort();
  const key = nameKey(runway);
  for (const rwy of ab.runways ?? []) {
    for (const d of rwy.directions) {
      if (nameKey(d.designator) === key) return [...(d.navaids ?? [])].sort();
    }
  }
  throw new Error(`airbase ${airbaseId} has no runway end ${JSON.stringify(runway)}`);
}

// Runways and stands -----------------------------------------------------------------

export interface RunwayThreshold {
  readonly lat: number;
  readonly lon: number;
  readonly elevationM: number;
}

export interface RunwayEnd {
  /** Designator pair of the runway (`13/31`). */
  readonly runway: string;
  readonly designator: string;
  /** DCS's own name of the end. */
  readonly name: string;
  readonly trueDeg: number;
  readonly magDeg: number;
  readonly threshold: RunwayThreshold;
  readonly lengthM: number;
}

export interface BestRunway {
  readonly end: RunwayEnd;
  /** Negative for a tailwind. */
  readonly headwindKt: number;
  /** Magnitude, from either side. */
  readonly crosswindKt: number;
}

export interface NearbyAirbase {
  readonly id: string;
  readonly distNm: number;
  /** Initial true bearing from the given point to the reference point. */
  readonly bearingDeg: number;
}

/**
 * Every runway end (`runways[].directions[]`, in data order) of `airbaseId`: bearings from its threshold along
 * the runway, the threshold (the runway spawn point at that end) and the runway length. Empty for an airbase
 * without runway data.
 */
export async function runwayEnds(airbaseId: string): Promise<readonly RunwayEnd[]> {
  const out: RunwayEnd[] = [];
  for (const rwy of (await record('airbases', airbaseId)).runways ?? []) {
    for (const d of rwy.directions) {
      const t = d.threshold;
      if (t.elevationM === undefined) throw new Error(`runway end ${d.designator} of ${airbaseId} has no elevation`);
      out.push({
        runway: rwy.designator,
        designator: d.designator,
        name: d.name,
        trueDeg: d.trueBearingDeg,
        magDeg: d.magneticBearingDeg,
        threshold: { lat: t.latitude, lon: t.longitude, elevationM: t.elevationM },
        lengthM: rwy.lengthM,
      });
    }
  }
  return out;
}

/** Wind components closer than this compare equal in `bestRunway`. */
export const WIND_TOLERANCE_KT = 1e-9;

function better(a: BestRunway, b: BestRunway): boolean {
  if (Math.abs(a.headwindKt - b.headwindKt) > WIND_TOLERANCE_KT) return a.headwindKt > b.headwindKt;
  if (Math.abs(a.crosswindKt - b.crosswindKt) > WIND_TOLERANCE_KT) return a.crosswindKt < b.crosswindKt;
  if (a.end.lengthM !== b.end.lengthM) return a.end.lengthM > b.end.lengthM;
  return a.end.designator < b.end.designator;
}

/**
 * The runway end of `airbaseId` facing the wind (blowing from `windFromDegTrue` at `windKt`): headwind
 * `windKt * cos(from - trueDeg)`, crosswind `|windKt * sin(from - trueDeg)|`. Most headwind wins; ties (within
 * `WIND_TOLERANCE_KT`, as in calm air) go to the least crosswind, then the longer runway, then the lower
 * designator (string order). Throws for a negative wind or an airbase without runway data.
 */
export async function bestRunway(airbaseId: string, windFromDegTrue: number, windKt: number): Promise<BestRunway> {
  if (!(windKt >= 0)) throw new Error(`wind speed must be >= 0 kt, got ${windKt}`);
  let best: BestRunway | undefined;
  for (const end of await runwayEnds(airbaseId)) {
    const a = (windFromDegTrue - end.trueDeg) * RAD;
    const cand: BestRunway = { end, headwindKt: windKt * Math.cos(a), crosswindKt: Math.abs(windKt * Math.sin(a)) };
    if (best === undefined || better(cand, best)) best = cand;
  }
  if (best === undefined) throw new Error(`airbase ${airbaseId} has no runway data`);
  return best;
}

/** Metres per international nautical mile. */
export const NM_M = 1852;

/**
 * The `n` (default 5) airbases of `theatre` (anything `theatreByName` accepts) whose reference points lie
 * nearest (lat, lon) by `distanceBearing`, nearest first (ties by id). `minRunwayM` keeps airbases whose
 * `longestRunwayM` reaches it (those without runway data drop out); `category` keeps those of that
 * `categoryName` (case-insensitive, e.g. `AIRDROME`).
 */
export async function nearestAirbases(
  theatre: string,
  lat: number,
  lon: number,
  options: { readonly minRunwayM?: number; readonly n?: number; readonly category?: string } = {},
): Promise<readonly NearbyAirbase[]> {
  const n = options.n ?? 5;
  if (!Number.isInteger(n) || n < 1) throw new Error(`n must be an integer of at least 1, got ${n}`);
  const t = await theatreByName(theatre);
  if (t === undefined) throw new Error(`no theatre ${JSON.stringify(theatre)}`);
  const found: [number, string, number][] = [];
  for (const [aid, ab] of Object.entries(await loadSeries('airbases'))) {
    const p = ab.referencePoint;
    if (ab.theatre !== t.id || p === undefined) continue;
    if (options.minRunwayM !== undefined && !((ab.longestRunwayM ?? -1) >= options.minRunwayM)) continue;
    if (options.category !== undefined && nameKey(ab.categoryName ?? '') !== nameKey(options.category)) continue;
    const db = distanceBearing(lat, lon, p.latitude, p.longitude);
    found.push([db.distM, aid, db.bearingDeg]);
  }
  found.sort((p, q) => p[0] - q[0] || (p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : p[2] - q[2]));
  return found.slice(0, n).map(([d, id, b]) => ({ id, distNm: d / NM_M, bearingDeg: b }));
}

/**
 * `termIndex` of every stand of `airbaseId` taking `aircraftId`, ascending, by the mission editor's rule
 * (`StandLimits`): wing span (else rotor diameter) < `maxWidthM`, length < `maxLengthM`, height < `maxHeightM`
 * (1000 when absent), and `helicopters` (rotary) or `airplanes` (fixed wing) true. Stands without `limits` are
 * left out. Throws for an aircraft without those dimensions.
 */
export async function standsFor(airbaseId: string, aircraftId: string): Promise<readonly number[]> {
  const a = await record('aircraft', aircraftId);
  const dims = a.dimensions ?? {};
  const width = 'wingSpanM' in dims ? dims.wingSpanM : dims.rotorDiameterM;
  const { lengthM, heightM } = dims;
  if (width === undefined || lengthM === undefined || heightM === undefined) {
    throw new Error(`aircraft ${aircraftId} lacks the dimensions stands check`);
  }
  const rotary = a.kind === 'rotary';
  const stands = (await record('airbases', airbaseId)).stands ?? [];
  return stands
    .flatMap((s) => {
      const lim = s.limits;
      const fits =
        lim !== undefined &&
        width < lim.maxWidthM &&
        lengthM < lim.maxLengthM &&
        heightM < (lim.maxHeightM ?? 1000) &&
        (rotary ? lim.helicopters : lim.airplanes);
      return fits ? [s.termIndex] : [];
    })
    .sort((p, q) => p - q);
}

// Countries, liveries and datalinks --------------------------------------------------

let countryAliases: Promise<Readonly<Record<string, number>>> | undefined;

function loadCountryAliases(): Promise<Readonly<Record<string, number>>> {
  countryAliases ??= import('../data/_index/countryAliases.json', { with: { type: 'json' } }).then(
    (mod: { default: unknown }) => mod.default as Readonly<Record<string, number>>,
  );
  return countryAliases;
}

const COUNTRY_NAMES = ['name', 'shortName', 'internationalName', 'idName', 'oldId'] as const;

/**
 * The id of the country whose name, shortName, internationalName, idName or oldId is `nameOrAlias` (as
 * `nameKey`), else of the `countryAliases` index entry, else undefined.
 */
export async function countryId(nameOrAlias: string): Promise<number | undefined> {
  const key = nameKey(nameOrAlias);
  for (const c of Object.values(await loadSeries('countries'))) {
    if (
      COUNTRY_NAMES.some((f) => {
        const name = c[f];
        return typeof name === 'string' && nameKey(name) === key;
      })
    ) {
      return Number(c.id);
    }
  }
  const alias = own(await loadCountryAliases(), key);
  return alias === undefined ? undefined : Number(alias);
}

/** DCS `Name` of country `id`. */
export async function countryName(id: number): Promise<string> {
  return (await record('countries', String(id))).name;
}

let allLiveryCountries: Promise<Readonly<Record<string, string>>> | undefined;

function loadAllLiveryCountries(): Promise<Readonly<Record<string, string>>> {
  allLiveryCountries ??= import('../data/_index/allLiveryCountries.json', { with: { type: 'json' } }).then(
    (mod: { default: unknown }) => mod.default as Readonly<Record<string, string>>,
  );
  return allLiveryCountries;
}

/**
 * Ids of the liveries of unit type `unitType` (in their `unitTypes`), sorted; with `country`, those without
 * `countries` (offered to every country) or whose `countries` hold it. A country of the `allLiveryCountries`
 * index (the Combined Joint Task Forces, as the mission editor's loadLiveries.lua treats them) gets every livery
 * of the unit type.
 */
export async function liveriesFor(unitType: string, country?: number): Promise<readonly string[]> {
  if ((await unitSeries(unitType)) === undefined) throw new Error(`no unit type ${JSON.stringify(unitType)}`);
  if (country !== undefined) {
    await record('countries', String(country));
    if (own(await loadAllLiveryCountries(), String(country)) !== undefined) country = undefined;
  }
  const liveries = await loadSeries('liveries');
  return Object.keys(liveries)
    .filter((lid) => {
      const lv = liveries[lid]!;
      const countries: readonly number[] | undefined = lv.countries;
      return (
        lv.unitTypes.includes(unitType) &&
        (country === undefined || countries === undefined || countries.includes(country))
      );
    })
    .sort();
}

/** A datalink record without `id` and `_source`. */
export type DatalinkCapability = Readonly<Omit<Datalink, 'id'>>;

/** The datalink record of aircraft `aircraftId` (without `id`), or undefined when it has none. */
export async function datalinkCapability(aircraftId: string): Promise<DatalinkCapability | undefined> {
  const dl = (await record('aircraft', aircraftId)).datalink;
  if (dl === undefined) return undefined;
  const { id: _id, ...rest } = await record('datalink', dl);
  return rest;
}

// Geo ----------------------------------------------------------------------------------

export interface DistanceBearing {
  readonly distM: number;
  /** Initial true bearing, [0, 360). */
  readonly bearingDeg: number;
}

function checkLatLon(lat: number, lon: number): void {
  if (!(-90 <= lat && lat <= 90 && -180 <= lon && lon <= 180)) {
    throw new Error(`latitude ${lat} / longitude ${lon} out of range`);
  }
}

function bearing(deg: number): number {
  let out = deg;
  if (out < 0) out += 360;
  if (out >= 360) out -= 360;
  return out;
}

/**
 * Great-circle distance (haversine) and initial bearing from point 1 to point 2 on a sphere of radius
 * `EARTH_RADIUS_M` (within about 0.5 % of the WGS84 geodesic); bearing 0 for coincident points.
 */
export function distanceBearing(lat1: number, lon1: number, lat2: number, lon2: number): DistanceBearing {
  checkLatLon(lat1, lon1);
  checkLatLon(lat2, lon2);
  const p1 = lat1 * RAD;
  const p2 = lat2 * RAD;
  const dp = p2 - p1;
  const dl = (lon2 - lon1) * RAD;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  const distM = 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(Math.min(1, a)));
  const theta = Math.atan2(
    Math.sin(dl) * Math.cos(p2),
    Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl),
  );
  return { distM, bearingDeg: bearing(theta * DEG) };
}

/**
 * The point `distM` from (lat, lon) along initial true bearing `bearingDeg` on the sphere of
 * `distanceBearing`; longitude in [-180, 180).
 */
export function destination(lat: number, lon: number, bearingDeg: number, distM: number): LatLon {
  checkLatLon(lat, lon);
  const [lon2, lat2] = destinationLonLat(lat, lon, bearingDeg, distM);
  return { lat: lat2, lon: lon2 };
}

export type CoordFormat = 'DD' | 'DMS' | 'DDM' | 'MGRS';

/** Format -> [default, largest] precision: decimals of the degrees, seconds or minutes; MGRS digits. */
const PRECISION: Readonly<Record<CoordFormat, readonly [number, number]>> = {
  DD: [6, 8],
  DMS: [0, 4],
  DDM: [3, 6],
  MGRS: [5, 5],
};

function pad(n: number, width: number): string {
  return String(n).padStart(width, '0');
}

function angle(value: number, fmt: 'DD' | 'DMS' | 'DDM', precision: number, hemis: string): string {
  const unit = 10 ** precision;
  const scale = { DD: 1, DDM: 60, DMS: 3600 }[fmt] * unit;
  const total = Math.floor(Math.abs(value) * scale + 0.5);
  const hemi = value < 0 && total > 0 ? hemis[1] : hemis[0];
  const whole = Math.floor(total / unit);
  const tail = precision > 0 ? `.${pad(total - whole * unit, precision)}` : '';
  if (fmt === 'DD') return `${hemi} ${whole}${tail}°`;
  if (fmt === 'DDM') return `${hemi} ${Math.floor(whole / 60)}°${pad(whole % 60, 2)}${tail}'`;
  return `${hemi} ${Math.floor(whole / 3600)}°${pad(Math.floor(whole / 60) % 60, 2)}'${pad(whole % 60, 2)}${tail}"`;
}

// UTM/MGRS (WGS84): the Transverse Mercator above with k0 0.9996, false easting 500 km and false northing
// 10000 km south of the equator.
const BANDS = 'CDEFGHJKLMNPQRSTUVWX';
const COLUMNS = ['ABCDEFGH', 'JKLMNPQR', 'STUVWXYZ'] as const;
const ROWS = 'ABCDEFGHJKLMNPQRSTUV';

function utm(zone: number, south: boolean): Tm {
  return {
    centralMeridian: zone * 6 - 183,
    scaleFactor: 0.9996,
    falseEasting: 500000,
    falseNorthing: south ? 10000000 : 0,
  };
}

function bandLat(band: string): [number, number] {
  const south = -80 + 8 * BANDS.indexOf(band);
  return [south, band === 'X' ? 84 : south + 8];
}

function mgrs(lat: number, lon: number, precision: number): string {
  if (!(-80 <= lat && lat <= 84)) throw new Error(`MGRS covers latitudes -80 to 84 (UTM), got ${lat}`);
  let zone = Math.min(Math.floor((lon + 180) / 6) + 1, 60);
  const band = BANDS[Math.min(Math.floor((lat + 80) / 8), 19)]!;
  if (band === 'V' && zone === 31 && lon >= 3) zone = 32;
  else if (band === 'X' && lon >= 0 && lon < 42) zone = lon < 9 ? 31 : lon < 21 ? 33 : lon < 33 ? 35 : 37;
  const [n, e] = toMap(utm(zone, lat < 0), lat, lon);
  const col = Math.floor(e / 100000);
  const row = (Math.floor(n / 100000) + (zone % 2 === 0 ? 5 : 0)) % 20;
  const letters = `${zone} ${band} ${COLUMNS[(zone - 1) % 3]![col - 1]}${ROWS[row]}`;
  if (precision === 0) return letters;
  const div = 10 ** (5 - precision);
  const de = Math.floor((Math.floor(e) % 100000) / div);
  const dn = Math.floor((Math.floor(n) % 100000) / div);
  return `${letters} ${pad(de, precision)} ${pad(dn, precision)}`;
}

/**
 * (lat, lon) as the DCS mission editor writes it, without the `Label:` prefix it copies: `DMS`
 * `N 29°32'03"   E 52°35'55"` (`precision` decimals of the seconds, default 0; 2 is its "Lat Long Precise"),
 * `DDM` `N 29°32.296'   E 52°35.179'` (minutes' decimals, default 3), `DD` `N 29.534312°   E 52.598839°`
 * (degrees' decimals, default 6; not an editor format) and `MGRS` `39 R XN 54929 68251` (digits per
 * easting/northing, 0-5, default 5, truncated as MGRS is). Values round half up; degrees are not padded.
 */
export function formatCoord(lat: number, lon: number, fmt: CoordFormat, precision?: number): string {
  if (!Object.hasOwn(PRECISION, fmt)) {
    throw new Error(`format must be one of ${Object.keys(PRECISION).join(', ')}, got ${JSON.stringify(fmt)}`);
  }
  const [def, most] = PRECISION[fmt];
  const p = precision ?? def;
  if (!Number.isInteger(p) || p < 0 || p > most) {
    throw new Error(`${fmt} precision must be an integer 0-${most}, got ${p}`);
  }
  checkLatLon(lat, lon);
  if (fmt === 'MGRS') return mgrs(lat, lon, p);
  return `${angle(lat, fmt, p, 'NS')}   ${angle(lon, fmt, p, 'EW')}`;
}

export interface ParsedCoord {
  readonly format: 'DD' | 'DMS' | 'DDM' | 'MGRS' | 'METRIC';
  readonly lat?: number;
  readonly lon?: number;
  /** `METRIC`: DCS map metres north. */
  readonly x?: number;
  /** `METRIC`: DCS map metres east. */
  readonly z?: number;
}

type Token = readonly ['num' | 'word' | 'mark', string];

function isDigit(c: string | undefined): boolean {
  return c !== undefined && c >= '0' && c <= '9';
}

/**
 * [kind, text] tokens: `num` (sign, digits, optional decimals), `word` (letters), `mark` (`*` for the degree
 * sign, `'`, `"`); blanks and commas separate. Upper-cased, after the first colon.
 */
function tokens(text: string): Token[] {
  const colon = text.indexOf(':');
  const ascii = (colon >= 0 ? text.slice(colon + 1) : text).replaceAll('°', '*');
  if (!/^[\x00-\x7f]*$/.test(ascii)) throw new Error(`non-ASCII character in ${JSON.stringify(text)}`);
  const s = ascii.toUpperCase();
  const out: Token[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i]!;
    if (c === ' ' || c === '\t' || c === ',') {
      i += 1;
    } else if (c === '*' || c === "'" || c === '"') {
      out.push(['mark', c]);
      i += 1;
    } else if (c >= 'A' && c <= 'Z') {
      let j = i;
      while (j < s.length && s[j]! >= 'A' && s[j]! <= 'Z') j += 1;
      out.push(['word', s.slice(i, j)]);
      i = j;
    } else if (c === '+' || c === '-' || isDigit(c)) {
      const j = c === '+' || c === '-' ? i + 1 : i;
      let k = j;
      while (isDigit(s[k])) k += 1;
      if (k === j) throw new Error(`bad number in ${JSON.stringify(text)}`);
      if (s[k] === '.') {
        let m = k + 1;
        while (isDigit(s[m])) m += 1;
        if (m === k + 1) throw new Error(`bad number in ${JSON.stringify(text)}`);
        k = m;
      }
      out.push(['num', s.slice(i, k)]);
      i = k;
    } else {
      throw new Error(`unexpected ${JSON.stringify(c)} in ${JSON.stringify(text)}`);
    }
  }
  return out;
}

function unsigned(t: Token): boolean {
  return t[0] === 'num' && [...t[1]].every((c) => isDigit(c));
}

function parseMgrs(toks: readonly Token[], text: string): ParsedCoord {
  const zone = Number(toks[0]![1]);
  let i = 1;
  let letters = '';
  while (i < toks.length && toks[i]![0] === 'word') {
    letters += toks[i]![1];
    i += 1;
  }
  const rest = toks.slice(i);
  if (letters.length !== 3 || rest.length > 2 || !rest.every(unsigned)) {
    throw new Error(`not an MGRS reference: ${JSON.stringify(text)}`);
  }
  let es = '';
  let ns = '';
  if (rest.length === 2) {
    es = rest[0]![1];
    ns = rest[1]![1];
  } else if (rest.length === 1) {
    const half = Math.floor(rest[0]![1].length / 2);
    es = rest[0]![1].slice(0, half);
    ns = rest[0]![1].slice(half);
  }
  if (es.length !== ns.length || es.length > 5) {
    throw new Error(`MGRS easting and northing need 0-5 digits each: ${JSON.stringify(text)}`);
  }
  const band = letters[0]!;
  const col = letters[1]!;
  const row = letters[2]!;
  const columns = COLUMNS[(zone - 1) % 3]!;
  if (!BANDS.includes(band) || !columns.includes(col) || !ROWS.includes(row)) {
    throw new Error(`bad MGRS letters ${letters} for zone ${zone}: ${JSON.stringify(text)}`);
  }
  const size = 10 ** (5 - es.length);
  const e = (columns.indexOf(col) + 1) * 100000 + (Number(es || '0') + 0.5) * size;
  const rowIndex = (((ROWS.indexOf(row) - (zone % 2 === 0 ? 5 : 0)) % 20) + 20) % 20;
  let n = rowIndex * 100000 + (Number(ns || '0') + 0.5) * size;
  const [lo, hi] = bandLat(band);
  const p = utm(zone, lo < 0);
  const [mid] = toMap(p, (lo + hi) / 2, p.centralMeridian);
  n += Math.floor((mid - n) / 2000000 + 0.5) * 2000000;
  const ll = inverse(p, n, e);
  if (!(lo - 0.5 <= ll.lat && ll.lat <= hi + 0.5)) {
    throw new Error(`MGRS square ${col}${row} is not in band ${band}: ${JSON.stringify(text)}`);
  }
  return { format: 'MGRS', lat: ll.lat, lon: ll.lon };
}

/** [signed degrees, component count, next index] of `H d [m [s]]`. */
function parseHalf(toks: readonly Token[], start: number, hemis: string, text: string): [number, number, number] {
  let i = start;
  const t = toks[i];
  if (t === undefined || t[0] !== 'word' || (t[1] !== hemis[0] && t[1] !== hemis[1])) {
    throw new Error(`expected ${hemis[0]} or ${hemis[1]} in ${JSON.stringify(text)}`);
  }
  const sign = t[1] === hemis[1] ? -1 : 1;
  i += 1;
  const parts: string[] = [];
  while (i < toks.length && toks[i]![0] === 'num' && parts.length < 3) {
    if (![...toks[i]![1]].every((c) => c === '.' || isDigit(c))) {
      throw new Error(`signed angle component in ${JSON.stringify(text)}`);
    }
    parts.push(toks[i]![1]);
    i += 1;
    if (i < toks.length && toks[i]![0] === 'mark') {
      if (toks[i]![1] !== `*'"`[parts.length - 1]) {
        throw new Error(`misplaced ${toks[i]![1]} in ${JSON.stringify(text)}`);
      }
      i += 1;
    }
  }
  if (parts.length === 0) throw new Error(`no angle after ${hemis[0]}/${hemis[1]} in ${JSON.stringify(text)}`);
  if (parts.slice(0, -1).some((p) => p.includes('.'))) {
    throw new Error(`only the last component may have decimals: ${JSON.stringify(text)}`);
  }
  const values = parts.map(Number);
  if (values.slice(1).some((v) => v >= 60)) {
    throw new Error(`minutes and seconds must be below 60: ${JSON.stringify(text)}`);
  }
  let deg = values[0]!;
  if (values.length > 1) deg += values[1]! / 60;
  if (values.length > 2) deg += values[2]! / 3600;
  return [sign * deg, parts.length, i];
}

/**
 * A coordinate in any DCS mission editor copy format, with or without its `Label:` prefix (the text up to the
 * first colon is dropped): `Metric: X+00380826 Z-00352108` (`METRIC`, map metres `x`/`z`),
 * `N 29°32'03"   E 52°35'55"` and `N 29°32'03.53"   E 52°35'55.82"` (`DMS`), `N 29°32.296'   E 52°35.179'`
 * (`DDM`), `39 R XN 54929 68251` (`MGRS`: the centre of the square, so formatting it again at the same precision
 * gives the same text), and `N 29.5343°   E 52.5988°` or a signed `29.5343, 52.5988` (`DD`). Case, spacing and
 * the `°` `'` `"` marks are loose; anything else throws.
 */
export function parseCoord(text: string): ParsedCoord {
  const toks = tokens(text);
  const kinds = toks.map((t) => t[0]).join(' ');
  if (kinds === 'word num word num' && toks[0]![1] === 'X' && toks[2]![1] === 'Z') {
    return { format: 'METRIC', x: Number(toks[1]![1]), z: Number(toks[3]![1]) };
  }
  const first = toks[0];
  if (
    first !== undefined &&
    toks[1]?.[0] === 'word' &&
    unsigned(first) &&
    first[1].length <= 2 &&
    Number(first[1]) >= 1 &&
    Number(first[1]) <= 60
  ) {
    return parseMgrs(toks, text);
  }
  let lat: number;
  let lon: number;
  let format: 'DD' | 'DMS' | 'DDM';
  if (kinds === 'num num') {
    lat = Number(toks[0]![1]);
    lon = Number(toks[1]![1]);
    format = 'DD';
  } else {
    const [la, nLat, i] = parseHalf(toks, 0, 'NS', text);
    const [lo, nLon, j] = parseHalf(toks, i, 'EW', text);
    if (j !== toks.length || nLat !== nLon) {
      throw new Error(`latitude and longitude need the same form: ${JSON.stringify(text)}`);
    }
    lat = la;
    lon = lo;
    format = nLat === 1 ? 'DD' : nLat === 2 ? 'DDM' : 'DMS';
  }
  checkLatLon(lat, lon);
  return { format, lat, lon };
}
