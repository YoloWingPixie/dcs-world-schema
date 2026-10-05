"use client";

import { browserQuery } from "../db/browser";
import type { SearchProvider, SourceHits } from "../search/types";
import { loadApiOverlays } from "./client";
import { resolveSymbols, searchApi } from "./db";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

/**
 * The Lua API in the palette: the `search` rows of series `api` (FTS5, the same index as
 * the reference records), plus symbols whose hand-written overlay text matches.
 */
export const API_PROVIDER: SearchProvider = {
  id: "api",
  label: "Lua API",
  warm: () => {
    loadApiOverlays().catch(() => {});
  },
  search: async (query, limit) => {
    const [hits, overlays] = await Promise.all([
      searchApi(browserQuery, query, Math.max(limit * 2, 20)),
      loadApiOverlays(),
    ]);
    const group: SourceHits = { source: { id: "api", label: "Lua API", weight: 1.2 }, results: [] };
    const seen = new Set<string>();
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const overlayHits = Object.entries(overlays.symbols)
      .filter(([, o]) => {
        const text = `${o.text ?? ""} ${o.summary ?? ""} ${o.description ?? ""}`.toLowerCase();
        return words.length > 0 && words.every((w) => text.includes(w));
      })
      .map(([symbol]) => symbol);
    const top = hits[0]?.score ?? 1;
    if (overlayHits.length) {
      const hrefs = await resolveSymbols(browserQuery, overlayHits);
      for (const [path, href] of hrefs) {
        if (hits.some((h) => h.href === href)) continue;
        hits.push({ href, path, subtitle: "Note", score: top * 0.5 });
      }
    }
    const wanted = norm(query);
    for (const h of hits.sort((a, b) => b.score - a.score)) {
      if (seen.has(h.href) || group.results.length >= limit) continue;
      seen.add(h.href);
      const summary = h.subtitle.replace(/`/g, "");
      group.results.push({
        key: h.href,
        title: h.path,
        subtitle: summary,
        href: h.href,
        score: h.score * (norm(h.path) === wanted ? 2 : 1),
      });
    }
    return group.results.length ? [group] : [];
  },
};
