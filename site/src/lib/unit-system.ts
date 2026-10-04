"use client";

/**
 * The site-wide Metric / Imperial choice: localStorage, `?units=` and <html data-units>
 * (applied before paint by UNITS_BOOTSTRAP in units.ts).
 */
import { useSyncExternalStore } from "react";
import type { UnitSystem } from "./units";

const KEY = "dcs-ref:units";
const listeners = new Set<() => void>();
let current: UnitSystem | null = null;

const isSystem = (v: unknown): v is UnitSystem => v === "metric" || v === "imperial";

export function getUnitSystem(): UnitSystem {
  if (typeof window === "undefined") return "metric";
  if (current) return current;
  const fromDom = document.documentElement.dataset.units;
  current = isSystem(fromDom) ? fromDom : "metric";
  return current;
}

export function setUnitSystem(system: UnitSystem) {
  current = system;
  if (system === "imperial") document.documentElement.dataset.units = system;
  else delete document.documentElement.dataset.units;
  try {
    window.localStorage.setItem(KEY, system);
  } catch {
    // Storage blocked: the choice holds for this page view.
  }
  // A shared link's `?units=` should not override the toggle on reload.
  const url = new URL(window.location.href);
  if (url.searchParams.has("units")) {
    if (system === "imperial") url.searchParams.set("units", system);
    else url.searchParams.delete("units");
    window.history.replaceState(window.history.state, "", url);
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== KEY || !isSystem(event.newValue)) return;
    setUnitSystem(event.newValue);
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Client components: the current system (metric on the server and before hydration). */
export function useUnitSystem(): UnitSystem {
  return useSyncExternalStore(subscribe, getUnitSystem, () => "metric");
}
