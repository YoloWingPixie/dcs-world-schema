"use client";

import { searchQuery, transientQuery } from "../db/browser";
import { once } from "../once";
import type { SearchProvider, SourceHits } from "../search/types";
import { squash } from "../text";
import { loadApiOverlays } from "./client";
import { resolveSymbols, searchApi } from "./db";

/** Each overlay symbol's text, lowercased once the overlays load. */
const loadOverlayTexts = () =>
  once("api-overlay-texts", async () =>
    Object.entries((await loadApiOverlays()).symbols).map(([symbol, o]) => ({
      symbol,
      text: `${o.text ?? ""} ${o.summary ?? ""} ${o.description ?? ""}`.toLowerCase(),
    })),
  );

/**
 * The Lua API in the palette: the `search` rows of series `api` (FTS5, the same index as
 * the reference records), plus symbols whose hand-written overlay text matches.
 */
export const API_PROVIDER: SearchProvider = {
  id: "api",
  label: "Lua API",
  warm: () => {
    loadOverlayTexts().catch(() => {});
  },
  search: async (query, limit) => {
    const [hits, texts] = await Promise.all([
      searchApi(searchQuery, query, Math.max(limit * 2, 20)),
      loadOverlayTexts(),
    ]);
    const group: SourceHits = { source: { id: "api", label: "Lua API", weight: 1.2 }, results: [] };
    const seen = new Set<string>();
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const overlayHits = words.length
      ? texts.filter(({ text }) => words.every((w) => text.includes(w))).map((t) => t.symbol)
      : [];
    const top = hits[0]?.score ?? 1;
    if (overlayHits.length) {
      const hrefs = await resolveSymbols(transientQuery, overlayHits);
      for (const [path, href] of hrefs) {
        if (hits.some((h) => h.href === href)) continue;
        hits.push({ href, path, subtitle: "Note", score: top * 0.5 });
      }
    }
    const wanted = squash(query);
    for (const h of hits.sort((a, b) => b.score - a.score)) {
      if (seen.has(h.href) || group.results.length >= limit) continue;
      seen.add(h.href);
      const summary = h.subtitle.replace(/`/g, "");
      group.results.push({
        key: h.href,
        title: h.path,
        subtitle: summary,
        href: h.href,
        score: h.score * (squash(h.path) === wanted ? 2 : 1),
      });
    }
    return group.results.length ? [group] : [];
  },
};
