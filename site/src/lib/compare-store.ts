"use client";

import { useMemo, useSyncExternalStore } from "react";
import { showToast } from "@/components/toast";
import { getUnitSystem } from "./unit-system";

/**
 * What is being compared: one series at a time, an optional field path and record slugs.
 * Each series keeps its own selection, so switching series and back restores it.
 */
export type CompareState = { series: string; field: string | null; records: string[] };
type Stored = {
  active: string;
  bySeries: Record<string, { field: string | null; records: string[] }>;
};

const KEY = "dcs-ref:compare:v2";
const DEFAULT_SERIES = "weapons";
const EMPTY: CompareState = { series: DEFAULT_SERIES, field: null, records: [] };
const listeners = new Set<() => void>();
let stored: Stored | null = null;
let snapshot: CompareState | null = null;
/** The compare page address last read into the store. */
let readSearch: string | null = null;

function load(): Stored {
  if (!stored) {
    try {
      const raw = window.localStorage.getItem(KEY);
      const parsed = raw ? (JSON.parse(raw) as Partial<Stored>) : null;
      stored = {
        active: typeof parsed?.active === "string" ? parsed.active : DEFAULT_SERIES,
        bySeries: typeof parsed?.bySeries === "object" && parsed.bySeries ? parsed.bySeries : {},
      };
    } catch {
      stored = { active: DEFAULT_SERIES, bySeries: {} };
    }
  }
  readUrl(stored);
  return stored;
}

/**
 * On the compare page, a comparison its address names (a shared link, a link elsewhere on
 * the site) replaces the stored one: once per address, before anything renders it, so no
 * other series loads first. Afterwards the page writes the store's state to the address.
 */
function readUrl(s: Stored) {
  const { pathname, search } = window.location;
  if (search === readSearch || !/\/compare\/?$/.test(pathname)) return;
  readSearch = search;
  const next = parseCompareParams(new URLSearchParams(search));
  if (!next) return;
  const same = s.active === next.series && compareQuery(next) === compareQuery(stateOf(s));
  if (!same) save(withState(s, next));
}

function withState(s: Stored, next: CompareState): Stored {
  return {
    active: next.series,
    bySeries: {
      ...s.bySeries,
      [next.series]: { field: next.field, records: [...new Set(next.records)] },
    },
  };
}

function save(next: Stored) {
  stored = next;
  snapshot = null;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(stored));
  } catch {
    // Storage blocked: the selection still lives in memory and the URL.
  }
}

function stateOf(s: Stored, series = s.active): CompareState {
  const entry = s.bySeries[series];
  return {
    series,
    field: typeof entry?.field === "string" ? entry.field : null,
    records: Array.isArray(entry?.records)
      ? entry.records.filter((r): r is string => typeof r === "string")
      : [],
  };
}

export function getCompare(series?: string): CompareState {
  if (typeof window === "undefined") return EMPTY;
  if (!series || series === load().active) {
    snapshot ??= stateOf(load());
    return snapshot;
  }
  return stateOf(load(), series);
}

/** Replaces the selection of `next.series` and makes it the active comparison. */
export function setCompare(next: CompareState) {
  save(withState(load(), next));
  for (const listener of listeners) listener();
}

export function addRecords(series: string, ...slugs: string[]) {
  const state = getCompare(series);
  setCompare({ ...state, records: [...state.records, ...slugs] });
}

export function removeRecord(series: string, slug: string) {
  const state = getCompare(series);
  setCompare({ ...state, records: state.records.filter((r) => r !== slug) });
}

/**
 * Adds a record to its series' selection, or removes it when it is there, and says so in a
 * toast; "Open compare" opens the selection with its field kept.
 */
export function toggleInCompare(series: string, slug: string, name: string) {
  if (getCompare(series).records.includes(slug)) {
    removeRecord(series, slug);
    showToast(`Removed ${name} from compare.`);
  } else {
    addRecords(series, slug);
    showToast(`Added ${name} to compare.`, compareHref(getCompare(series)), "Open compare");
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== KEY) return;
    stored = null;
    snapshot = null;
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The active comparison (any series). */
export function useCompare(): CompareState {
  return useSyncExternalStore(
    subscribe,
    () => getCompare(),
    () => EMPTY,
  );
}

/**
 * The active comparison, or null while the page hydrates (the server has no store): the
 * compare page renders nothing for a comparison its address may replace.
 */
export function useCompareOnClient(): CompareState | null {
  return useSyncExternalStore(
    subscribe,
    () => getCompare(),
    () => null,
  );
}

/**
 * A series' selected records. The store is read as one string (the slugs, one per line), so
 * the snapshot is stable and a change elsewhere in the store does not re-render.
 */
export function useCompareRecords(series: string): string[] {
  const joined = useSyncExternalStore(
    subscribe,
    () => getCompare(series).records.join("\n"),
    () => "",
  );
  return useMemo(() => (joined ? joined.split("\n") : []), [joined]);
}

/** `s=<series>&f=<path>&r=a,b` (commas kept readable), with the unit system when imperial. */
export function compareQuery(state: CompareState): string {
  const params = new URLSearchParams();
  params.set("s", state.series);
  if (state.field) params.set("f", state.field);
  if (state.records.length) params.set("r", state.records.join(","));
  if (typeof window !== "undefined" && getUnitSystem() === "imperial") {
    params.set("units", "imperial");
  }
  return params.toString().replace(/%2C/g, ",");
}

/** `/compare/?s=<series>&f=<path>&r=a,b` — the shareable form of a selection. */
export function compareHref(state: CompareState): string {
  return `/compare/?${compareQuery(state)}`;
}

export function parseCompareParams(params: URLSearchParams): CompareState | null {
  if (!params.has("s") && !params.has("f") && !params.has("r")) return null;
  return {
    series: params.get("s") || DEFAULT_SERIES,
    field: params.get("f") || null,
    records: (params.get("r") ?? "").split(",").filter(Boolean),
  };
}
