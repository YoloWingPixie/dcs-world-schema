import MiniSearch, { type Options, type SearchResult } from "minisearch";
import type { SearchResultItem, SearchSource, SourceHits, StoredDoc } from "./types";

/** Build time: the JSON a source's `indexUrl` serves. */
export function serializeIndex<T extends Record<string, unknown>>(
  options: Options<T>,
  docs: T[],
): string {
  const index = new MiniSearch<T>(options);
  index.addAll(docs);
  return JSON.stringify(index);
}

export function deserializeIndex(json: string, options: Options<StoredDoc>): MiniSearch<StoredDoc> {
  return MiniSearch.loadJSON<StoredDoc>(json, options);
}

/** Squash punctuation so "aim120", "aim 120" and "AIM-120C" all meet the same tokens. */
export function nameVariants(...names: string[]): string[] {
  const out = new Set<string>();
  for (const name of names) {
    const lower = name.toLowerCase();
    out.add(lower.replace(/[^a-z0-9]+/g, ""));
    out.add(lower.replace(/[^a-z0-9]+/g, " ").trim());
    // "aim120c" -> "aim 120 c" so "120" alone also hits.
    out.add(lower.replace(/([a-z])(\d)/g, "$1 $2").replace(/(\d)([a-z])/g, "$1 $2"));
  }
  return [...out].filter(Boolean);
}

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

/** AND first, OR as a fallback, then exact-title hits float to the top. */
export function searchIndex(
  index: MiniSearch<StoredDoc>,
  source: SearchSource,
  query: string,
  limit = 50,
): SourceHits["results"] {
  const q = query.trim();
  if (!q) return [];
  let raw: SearchResult[] = index.search(q);
  if (raw.length === 0) raw = index.search(q, { combineWith: "OR" });
  const wanted = norm(q);
  const weight = source.weight ?? 1;
  return raw
    .slice(0, limit * 2)
    .map((r) => {
      const item: SearchResultItem = source.docToResult(r as unknown as StoredDoc);
      const exact = norm(item.title) === wanted || norm(item.detail ?? "") === wanted;
      return { ...item, score: r.score * weight * (exact ? 4 : 1) };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

/** Groups ordered by their best hit; empty groups dropped. */
export function mergeHits(groups: SourceHits[]): SourceHits[] {
  return groups
    .filter((g) => g.results.length > 0)
    .sort(
      (a, b) =>
        (b.results[0]?.score ?? 0) - (a.results[0]?.score ?? 0) ||
        (a.source.priority ?? 100) - (b.source.priority ?? 100),
    );
}
