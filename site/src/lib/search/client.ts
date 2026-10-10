"use client";

import { useEffect, useMemo, useState } from "react";
import { loadApiOverlays } from "../api/client";
import { loadModel, loadOverlays } from "../client-data";
import { nameIndexFile } from "../db/browser";
import { once, settled } from "../once";
import type * as Engine from "./engine";
import type { SourceHits } from "./types";

export { MIN_QUERY } from "./types";

type Loaded = { engine: typeof Engine; index: Engine.NameIndex };

const INDEX = "search-index";

/**
 * The search index: the name index file, MiniSearch (its own chunk) and the overlays'
 * aliases and API notes, indexed once per page.
 */
export const loadSearch = () =>
  once(INDEX, async (): Promise<Loaded> => {
    const [file, engine, model, overlays, api] = await Promise.all([
      nameIndexFile(),
      import("./engine"),
      loadModel(),
      loadOverlays(),
      loadApiOverlays(),
    ]);
    const aliases = new Map<string, string[]>();
    for (const [series, o] of Object.entries(overlays.series)) {
      // A companion's overlay (weapon_flight) names its parent's record.
      const owner = model.byId.get(series)?.parent ?? series;
      for (const [id, overlay] of Object.entries(o.records)) {
        if (!overlay.aliases?.length) continue;
        const key = engine.recordKey(owner, id);
        aliases.set(key, [...(aliases.get(key) ?? []), ...overlay.aliases]);
      }
    }
    const notes = new Map<string, string>();
    for (const [symbol, o] of Object.entries(api.symbols)) {
      notes.set(symbol, `${o.text ?? ""} ${o.summary ?? ""} ${o.description ?? ""}`);
    }
    return { engine, index: await engine.buildNameIndex(file, model, { aliases, notes }) };
  });

/** Start loading the index (idempotent): the palette opening, the search box in focus. */
export function warmSearch() {
  loadSearch().catch(() => {});
}

export type GlobalResults = {
  groups: SourceHits[];
  /** The index is still loading. */
  loading: boolean;
  /** The index failed to load. */
  failed: boolean;
};

/**
 * Results of `query`, `limit` per group, from the in-memory index; loading starts when
 * `enabled` turns true. Each keystroke searches at once: no round trip, no debounce.
 */
export function useGlobalSearch(
  query: string,
  { enabled = true, limit = 8 }: { enabled?: boolean; limit?: number } = {},
): GlobalResults {
  const [loaded, setLoaded] = useState<Loaded | null>(() => settled<Loaded>(INDEX) ?? null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!enabled || loaded) return;
    let live = true;
    setFailed(false);
    loadSearch().then(
      (l) => live && setLoaded(l),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [enabled, loaded]);

  return useMemo(
    () => ({
      groups: loaded ? loaded.engine.searchNames(loaded.index, query, limit) : [],
      loading: enabled && !loaded && !failed,
      failed,
    }),
    [loaded, failed, enabled, query, limit],
  );
}
