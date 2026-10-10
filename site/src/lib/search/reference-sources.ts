"use client";

import { loadModel, loadOverlays } from "../client-data";
import { browserQuery, prefetchSearchParts, searchQuery, transientQuery } from "../db/browser";
import { searchReference } from "../db/reference";
import { constantLabel } from "../names";
import { recordHref } from "../series";
import { slugify } from "../series-display";
import { squash } from "../text";
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

type AliasRow = { series: string; id: string; name: string; subtitle: string };

/**
 * Search rows of overlay alias stems (ids or slugs): one statement for the ids, then, for
 * stems no id matched, one read of each series' names to match slugs.
 */
async function resolveAliases(stems: Array<{ series: string; stem: string }>): Promise<AliasRow[]> {
  if (!stems.length) return [];
  const rows = await transientQuery(
    `SELECT series, id, name, subtitle FROM search
      WHERE (series, id) IN (VALUES ${stems.map(() => "(?, ?)").join(", ")})`,
    stems.flatMap((s) => [s.series, s.stem]),
  );
  const row = (r: Record<string, unknown>, series: string): AliasRow => ({
    series,
    id: String(r.id),
    name: String(r.name),
    subtitle: String(r.subtitle ?? ""),
  });
  const byKey = new Map(rows.map((r) => [`${r.series}\u0000${r.id}`, row(r, String(r.series))]));
  const bySlug = new Map<string, Map<string, AliasRow>>();
  const out: AliasRow[] = [];
  for (const { series, stem } of stems) {
    const hit = byKey.get(`${series}\u0000${stem}`);
    if (hit) {
      out.push(hit);
      continue;
    }
    let slugs = bySlug.get(series);
    if (!slugs) {
      // Stable per series: kept for the page's lifetime.
      const all = await browserQuery("SELECT id, name, subtitle FROM search WHERE series = ?", [
        series,
      ]);
      slugs = new Map(all.map((r) => [slugify(String(r.id)), row(r, series)]));
      bySlug.set(series, slugs);
    }
    const found = slugs.get(stem);
    if (found) out.push(found);
  }
  return out;
}

/**
 * The reference database's `search` table (FTS5), one group per series, plus the
 * hand-written overlay aliases (AMRAAM), which live with the site, not the data.
 */
export const REFERENCE_PROVIDER: SearchProvider = {
  id: "reference",
  label: "Reference",
  warm: () => {
    prefetchSearchParts().catch(() => {});
    loadModel().catch(() => {});
    loadOverlays().catch(() => {});
  },
  search: async (query, limit) => {
    const [model, overlays, hits] = await Promise.all([
      loadModel(),
      loadOverlays(),
      searchReference(searchQuery, query, 150),
    ]);
    const wanted = squash(query);
    // Overlay aliases: an exact or prefix alias match names a record directly.
    const aliasHits = [];
    if (wanted.length >= 2) {
      for (const [series, o] of Object.entries(overlays.series)) {
        const owner = model.byId.get(series)?.parent ?? series;
        for (const [stem, overlay] of Object.entries(o.records)) {
          if (!overlay.aliases?.some((a) => squash(a).startsWith(wanted))) continue;
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
      const exact = squash(name) === wanted || squash(id) === wanted;
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
    for (const row of await resolveAliases(aliasHits.slice(0, 40))) {
      add(row.series, row.id, row.name, row.subtitle, 50);
    }
    for (const h of hits) add(h.series, h.id, h.name, h.subtitle, h.score);
    for (const g of groups.values()) g.results.sort((a, b) => b.score - a.score);
    return [...groups.values()];
  },
};
