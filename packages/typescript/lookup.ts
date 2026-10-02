// Reverse and name lookups over the indexes in data/_index/ (built by
// tools/package/indexes.py), each index loaded on first use. Copied into src/
// by tools/package/build.py.
import type { SeriesName } from './index.js';

/** A record referencing another: its series, id and the referencing field. */
export interface Reference {
  readonly series: SeriesName;
  readonly id: string;
  /** Field path from the record, arrays as `[]` (e.g. `stations[].accepts[]`). */
  readonly path: string;
}

/** A field holding ids of another series (`target` is `units` for any unit series). */
export interface Relation {
  readonly series: SeriesName;
  readonly path: string;
  readonly target: SeriesName | 'units';
}

/** What the indexes cover. */
export interface IndexMeta {
  readonly relations: readonly Relation[];
  readonly unitSeries: readonly SeriesName[];
  /** Series with a `references_<series>` index. */
  readonly references: readonly SeriesName[];
  /** Series with a `names_<series>` index. */
  readonly names: readonly SeriesName[];
  readonly derived: Readonly<Record<string, { target: SeriesName; via: readonly SeriesName[]; paths: readonly (string | null)[] }>>;
}

type IdLists = Readonly<Record<string, readonly string[]>>;
const none: readonly string[] = Object.freeze([]);
const cache = new Map<string, Promise<unknown>>();

function loadIndex<T>(name: string): Promise<T> {
  let hit = cache.get(name);
  if (hit === undefined) {
    hit = import(`../data/_index/${name}.json`, { with: { type: 'json' } }).then(
      (mod: { default: unknown }) => mod.default,
    );
    cache.set(name, hit);
  }
  return hit as Promise<T>;
}

function own<T>(table: Readonly<Record<string, T>>, key: string): T | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** What the indexes cover: the `x-ref` relations, unit series, indexed series. */
export function loadIndexMeta(): Promise<IndexMeta> {
  return loadIndex<IndexMeta>('meta');
}

/** The key the name indexes use: trimmed of ASCII whitespace, ASCII letters lowercased. */
export function nameKey(name: string): string {
  return name.replace(/^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g, '').replace(/[A-Z]/g, (c) => c.toLowerCase());
}

/** Every record referencing record `id` of `series`, by any `x-ref` field. */
export async function referencesTo(series: SeriesName, id: string): Promise<readonly Reference[]> {
  const meta = await loadIndexMeta();
  if (!meta.references.includes(series)) return [];
  const index = await loadIndex<Readonly<Record<string, readonly Reference[]>>>(`references_${series}`);
  return own(index, id) ?? [];
}

function idsOf(refs: readonly Reference[], series: SeriesName): string[] {
  return [...new Set(refs.filter((r) => r.series === series).map((r) => r.id))].sort();
}

/** CLSIDs of the stores delivering weapon `weaponId`. */
export async function storesDelivering(weaponId: string): Promise<readonly string[]> {
  return idsOf(await referencesTo('weapons', weaponId), 'stores');
}

/** Aircraft with a station accepting a store that delivers weapon `weaponId`. */
export async function aircraftCarrying(weaponId: string): Promise<readonly string[]> {
  return own(await loadIndex<IdLists>('carriers'), weaponId) ?? none;
}

/** Threat systems (`threats` ids) the unit `unitId` is or is a component of. */
export async function threatsForUnit(unitId: string): Promise<readonly string[]> {
  const meta = await loadIndexMeta();
  const refs = await Promise.all(meta.unitSeries.map((s) => referencesTo(s, unitId)));
  return idsOf(refs.flat(), 'threats');
}

/** Airbase ids named `name` (case-insensitive), in theatre `theatre` (its id, case-insensitive) or any. */
export async function airbaseByName(name: string, theatre?: string): Promise<readonly string[]> {
  const index = await loadIndex<Readonly<Record<string, IdLists>>>('airbases_by_name');
  const key = nameKey(name);
  const ids = Object.keys(index)
    .filter((t) => theatre === undefined || nameKey(t) === nameKey(theatre))
    .flatMap((t) => own(index[t]!, key) ?? none);
  return [...new Set(ids)].sort();
}

/** Ids of the `series` records whose displayName or name is `name` (case-insensitive). */
export async function findByName(series: SeriesName, name: string): Promise<readonly string[]> {
  const meta = await loadIndexMeta();
  if (!meta.names.includes(series)) return none;
  return own(await loadIndex<IdLists>(`names_${series}`), nameKey(name)) ?? none;
}
