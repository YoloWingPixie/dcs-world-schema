"use client";

import { useSyncExternalStore } from "react";
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

function load(): Stored {
  if (stored) return stored;
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
  return stored;
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
  const s = load();
  stored = {
    active: next.series,
    bySeries: {
      ...s.bySeries,
      [next.series]: { field: next.field, records: [...new Set(next.records)] },
    },
  };
  snapshot = null;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(stored));
  } catch {
    // Storage blocked: the selection still lives in memory and the URL.
  }
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

/** Whether a record is in its series' selection. */
export function useInCompare(series: string, slug: string): boolean {
  return useSyncExternalStore(
    subscribe,
    () => getCompare(series).records.includes(slug),
    () => false,
  );
}

/** `/compare/?s=<series>&f=<path>&r=a,b` — the shareable form of a selection. */
export function compareHref(state: CompareState): string {
  const params = new URLSearchParams();
  params.set("s", state.series);
  if (state.field) params.set("f", state.field);
  if (state.records.length) params.set("r", state.records.join(","));
  if (typeof window !== "undefined" && getUnitSystem() === "imperial") {
    params.set("units", "imperial");
  }
  return `/compare/?${params.toString().replace(/%2C/g, ",")}`;
}

export function parseCompareParams(params: URLSearchParams): CompareState | null {
  if (!params.has("s") && !params.has("f") && !params.has("r") && !params.has("w")) return null;
  return {
    series: params.get("s") || DEFAULT_SERIES,
    field: params.get("f") || null,
    // `w` is the weapons-only prototype's parameter.
    records: (params.get("r") ?? params.get("w") ?? "").split(",").filter(Boolean),
  };
}
