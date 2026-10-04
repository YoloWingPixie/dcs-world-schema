"use client";

import { loadModel, loadOverlays } from "../client-data";
import { browserQuery } from "../db/browser";
import { searchReference } from "../db/reference";
import { constantLabel } from "../names";
import { recordHref } from "../series";
import { slugify } from "../series-display";
import type { SearchProvider, SourceHits } from "./types";

/** Series that matter most in a mixed result list rank a little higher. */
const WEIGHT: Record<string, number> = {
  aircraft: 1.4,
  weapons: 1.4,
  ground_vehicles: 1.2,
  ships: 1.2,
  sensors: 1.1,
  airbases: 1.1,
  stores: 0.8,
  liveries: 0.5,
  callsigns: 0.6,
  beacons: 0.7,
  navaids: 0.7,
};

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

/**
 * The reference database's `search` table (FTS5), one group per series, plus the
 * hand-written overlay aliases (AMRAAM), which live with the site, not the data.
 */
export const REFERENCE_PROVIDER: SearchProvider = {
  id: "reference",
  label: "Reference",
  warm: () => {
    loadModel().catch(() => {});
    loadOverlays().catch(() => {});
  },
  search: async (query, limit) => {
    const [model, overlays, hits] = await Promise.all([
      loadModel(),
      loadOverlays(),
      searchReference(browserQuery, query, 150),
    ]);
    const wanted = norm(query);
    // Overlay aliases: an exact or prefix alias match names a record directly.
    const aliasHits = [];
    if (wanted.length >= 2) {
      for (const [series, o] of Object.entries(overlays.series)) {
        const owner = model.byId.get(series)?.parent ?? series;
        for (const [stem, overlay] of Object.entries(o.records)) {
          if (!overlay.aliases?.some((a) => norm(a).startsWith(wanted))) continue;
          aliasHits.push({ series: owner, stem });
        }
      }
    }
    const groups = new Map<string, SourceHits>();
    const add = (series: string, id: string, name: string, subtitle: string, score: number) => {
      const s = model.byId.get(series);
      if (!s) return;
      let g = groups.get(series);
      if (!g) {
        g = { source: { id: series, label: s.label, weight: WEIGHT[series] ?? 1 }, results: [] };
        groups.set(series, g);
      }
      if (g.results.some((r) => r.key === id) || g.results.length >= limit) return;
      const exact = norm(name) === wanted || norm(id) === wanted;
      const meta = subtitle
        .split(" · ")
        .filter(Boolean)
        .map((part) => constantLabel(part))
        .join(" · ");
      g.results.push({
        key: id,
        title: name,
        ...(meta ? { subtitle: meta } : {}),
        ...(id !== name ? { detail: id } : {}),
        href: recordHref(series, id),
        score: score * (WEIGHT[series] ?? 1) * (exact ? 4 : 1),
      });
    };
    if (aliasHits.length) {
      // Resolve alias stems (ids or slugs) through the search table.
      for (const { series, stem } of aliasHits.slice(0, 40)) {
        const rows = await browserQuery(
          "SELECT id, name, subtitle FROM search WHERE series = ? AND id = ?",
          [series, stem],
        );
        const row =
          rows[0] ??
          (
            await browserQuery("SELECT id, name, subtitle FROM search WHERE series = ?", [series])
          ).find((r) => slugify(String(r.id)) === stem);
        if (row) add(series, String(row.id), String(row.name), String(row.subtitle ?? ""), 50);
      }
    }
    for (const h of hits) add(h.series, h.id, h.name, h.subtitle, h.score);
    for (const g of groups.values()) g.results.sort((a, b) => b.score - a.score);
    return [...groups.values()];
  },
};
