"use client";

import type MiniSearch from "minisearch";
import { useEffect, useMemo, useState } from "react";
import type * as Engine from "./engine";
import { mergeHits } from "./merge";
import { SEARCH_PROVIDERS, SEARCH_SOURCES } from "./sources";
import type { SearchGroup, SearchSource, SourceHits, StoredDoc } from "./types";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const indexes = new Map<string, MiniSearch<StoredDoc>>();
const pending = new Map<string, Promise<MiniSearch<StoredDoc>>>();
const listeners = new Set<() => void>();
const failed = new Set<string>();

// MiniSearch loads with the first index, not with the page.
let engine: typeof Engine | null = null;
const loadEngine = () =>
  import("./engine").then((m) => {
    engine = m;
    return m;
  });

/** Fetch and deserialise one source's prebuilt index (once per page view). */
export function loadSource(source: SearchSource): Promise<MiniSearch<StoredDoc>> {
  const ready = indexes.get(source.id);
  if (ready) return Promise.resolve(ready);
  let promise = pending.get(source.id);
  if (!promise) {
    promise = Promise.all([
      fetch(`${BASE_PATH}${source.indexUrl}`).then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      }),
      loadEngine(),
    ])
      .then(([json, e]) => {
        const index = e.deserializeIndex(json, source.options);
        indexes.set(source.id, index);
        failed.delete(source.id);
        return index;
      })
      .catch((error: unknown) => {
        pending.delete(source.id);
        failed.add(source.id);
        throw error;
      })
      .finally(() => {
        for (const l of listeners) l();
      });
    pending.set(source.id, promise);
  }
  return promise;
}

/** Start loading every source, most important first (idempotent). */
export function warmSearch(sources: SearchSource[] = SEARCH_SOURCES) {
  const ordered = [...sources].sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));
  for (const s of ordered) loadSource(s).catch(() => {});
  for (const p of SEARCH_PROVIDERS) p.warm?.();
}

/** Provider results of the latest query (older answers are dropped). */
function useProviderResults(query: string, enabled: boolean, limit: number) {
  const [state, setState] = useState<{ query: string; groups: SourceHits[]; pending: boolean }>({
    query: "",
    groups: [],
    pending: false,
  });
  useEffect(() => {
    const q = query.trim();
    if (!enabled || q.length < 2) {
      setState({ query: q, groups: [], pending: false });
      return;
    }
    let live = true;
    setState((s) => ({ ...s, pending: true }));
    const timer = window.setTimeout(() => {
      Promise.all(SEARCH_PROVIDERS.map((p) => p.search(q, limit).catch(() => [])))
        .then((lists) => {
          if (live) setState({ query: q, groups: lists.flat(), pending: false });
        })
        .catch(() => live && setState({ query: q, groups: [], pending: false }));
    }, 60);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query, enabled, limit]);
  return state;
}

export type GlobalResults = {
  groups: SourceHits[];
  /** Sources still loading. */
  loading: SearchGroup[];
  failed: SearchGroup[];
  ready: boolean;
};

/**
 * Results of `query` across every loaded source, re-run as more indexes arrive.
 * `only` restricts to some source ids. Loading starts when `enabled` turns true.
 */
export function useGlobalSearch(
  query: string,
  { enabled = true, only, limit = 8 }: { enabled?: boolean; only?: string[]; limit?: number } = {},
): GlobalResults {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const listener = () => setVersion((v) => v + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  useEffect(() => {
    if (enabled) warmSearch();
  }, [enabled]);

  const provided = useProviderResults(query, enabled, limit);
  const onlyKey = only?.join(",") ?? "";
  // biome-ignore lint/correctness/useExhaustiveDependencies: version re-runs as indexes load
  return useMemo(() => {
    const wanted = onlyKey ? new Set(onlyKey.split(",")) : null;
    const sources = SEARCH_SOURCES.filter((s) => !wanted || wanted.has(s.id));
    const groups: SourceHits[] = [];
    for (const source of sources) {
      const index = indexes.get(source.id);
      if (!index || !engine || !query.trim()) continue;
      groups.push({ source, results: engine.searchIndex(index, source, query, limit) });
    }
    const fromProviders = provided.groups.filter((g) => !wanted || wanted.has(g.source.id));
    const loading = sources.filter((s) => !indexes.has(s.id) && !failed.has(s.id));
    return {
      groups: mergeHits([...groups, ...fromProviders]),
      loading: provided.pending ? [...loading, { id: "reference", label: "Reference" }] : loading,
      failed: sources.filter((s) => failed.has(s.id)),
      ready:
        sources.some((s) => indexes.has(s.id)) || provided.groups.length > 0 || !provided.pending,
    };
  }, [query, onlyKey, limit, version, provided]);
}
