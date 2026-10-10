"use client";

import { loadModel, loadOverlays } from "../client-data";
import { prefetchSearchParts, searchQuery, transientQuery } from "../db/browser";
import { searchReference } from "../db/reference";
import { constantLabel } from "../names";
import { once } from "../once";
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

/** An overlay record's aliases, squashed once (`series` is the record's owner series). */
type AliasEntry = { series: string; stem: string; keys: string[] };

/** Every overlay alias, built once the model and overlays load. */
const loadAliases = () =>
  once("reference-aliases", async (): Promise<AliasEntry[]> => {
    const [model, overlays] = await Promise.all([loadModel(), loadOverlays()]);
    const out: AliasEntry[] = [];
    for (const [series, o] of Object.entries(overlays.series)) {
      const owner = model.byId.get(series)?.parent ?? series;
      for (const [stem, overlay] of Object.entries(o.records)) {
        if (overlay.aliases?.length) {
          out.push({ series: owner, stem, keys: overlay.aliases.map(squash) });
        }
      }
    }
    return out;
  });

const aliasKey = (series: string, stem: string) => `${series}\u0000${stem}`;

/**
 * Search rows of every overlay alias stem (an id or a slug), resolved once on the first alias
 * hit: one statement for the ids, then, for series with stems no id matched, one read of the
 * series' ids to match slugs.
 */
const loadAliasRows = (entries: AliasEntry[]) =>
  once("reference-alias-rows", async (): Promise<Map<string, AliasRow>> => {
    const out = new Map<string, AliasRow>();
    if (!entries.length) return out;
    const row = (r: Record<string, unknown>, series: string): AliasRow => ({
      series,
      id: String(r.id),
      name: String(r.name),
      subtitle: String(r.subtitle ?? ""),
    });
    const rows = await transientQuery(
      `SELECT series, id, name, subtitle FROM search
        WHERE (series, id) IN (VALUES ${entries.map(() => "(?, ?)").join(", ")})`,
      entries.flatMap((e) => [e.series, e.stem]),
    );
    for (const r of rows)
      out.set(aliasKey(String(r.series), String(r.id)), row(r, String(r.series)));
    const missing = new Map<string, string[]>();
    for (const { series, stem } of entries) {
      if (out.has(aliasKey(series, stem))) continue;
      missing.set(series, [...(missing.get(series) ?? []), stem]);
    }
    for (const [series, stems] of missing) {
      const all = await transientQuery("SELECT id, name, subtitle FROM search WHERE series = ?", [
        series,
      ]);
      const bySlug = new Map(all.map((r) => [slugify(String(r.id)), r]));
      for (const stem of stems) {
        const hit = bySlug.get(stem);
        if (hit) out.set(aliasKey(series, stem), row(hit, series));
      }
    }
    return out;
  });

/** Records whose overlay alias starts with `wanted` (squashed), at most `max` of them. */
async function aliasRows(wanted: string, max: number): Promise<AliasRow[]> {
  if (wanted.length < 2) return [];
  const entries = await loadAliases();
  const matched = entries.filter((e) => e.keys.some((k) => k.startsWith(wanted))).slice(0, max);
  if (!matched.length) return [];
  const rows = await loadAliasRows(entries);
  return matched.flatMap((e) => rows.get(aliasKey(e.series, e.stem)) ?? []);
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
    loadAliases().catch(() => {});
  },
  search: async (query, limit) => {
    const wanted = squash(query);
    const [model, aliases, hits] = await Promise.all([
      loadModel(),
      aliasRows(wanted, 40),
      searchReference(searchQuery, query, 150),
    ]);
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
    for (const row of aliases) {
      add(row.series, row.id, row.name, row.subtitle, 50);
    }
    for (const h of hits) add(h.series, h.id, h.name, h.subtitle, h.score);
    for (const g of groups.values()) g.results.sort((a, b) => b.score - a.score);
    return [...groups.values()];
  },
};
