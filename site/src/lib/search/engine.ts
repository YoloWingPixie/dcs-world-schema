/**
 * The in-memory search behind the palette and /search: every row of the database's `search`
 * table (reference records and Lua API symbols), from the static name index
 * scripts/split-sqlite.ts writes (`names` in reference.json), indexed with MiniSearch when
 * the palette first opens. Hand-written record aliases (AMRAAM) and API notes join their
 * rows here, so the overlays stay out of the index file.
 */
import MiniSearch, { type SearchOptions } from "minisearch";
import { API_SERIES } from "../api/db";
import type { Model } from "../db/reference";
import { constantLabel } from "../names";
import { recordHref } from "../series";
import { squash } from "../text";
import { MIN_QUERY, type SourceHits } from "./types";

/** scripts/split-sqlite.ts `nameIndex`: `[series index, id ("" = the name), name, subtitle, keywords]`. */
export type NameIndexFile = {
  series: string[];
  rows: [series: number, id: string, name: string, subtitle: string, keywords: string][];
};

type Doc = {
  /** Row number (MiniSearch's id). */
  n: number;
  series: string;
  id: string;
  name: string;
  subtitle: string;
  keywords: string;
  aliases: string[];
  notes: string;
};

export type NameIndex = { search: MiniSearch<Doc>; docs: Doc[]; model: Model };

/** Words: runs of letters and digits, lowercased (scripts/split-sqlite.ts `words`). */
export const words = (text: string) =>
  text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);

/** A word's letter and digit runs: "aim120c" -> "aim", "120", "c". */
const runs = (w: string) => w.match(/\p{L}+|\p{N}+/gu) ?? [];

/**
 * The terms a name is found by: its words, letters and digits apart ("aim120c" -> "aim",
 * "120", "c") and squashed ("aim120c"), so "aim 120", "aim120" and "AIM-120C" all meet it.
 * The index file leaves out keywords these terms already cover.
 */
export function nameTerms(...names: string[]): string[] {
  const out = new Set<string>();
  for (const name of names) {
    const w = words(name);
    for (const x of w) {
      out.add(x);
      for (const y of runs(x)) out.add(y);
    }
    if (w.length) out.add(w.join(""));
  }
  return [...out];
}

/** Field weights, as the database's FTS ranking had them (name 8, keywords 2, subtitle 1). */
const BOOST = { name: 8, aliases: 8, keywords: 2, subtitle: 1, notes: 1 };

const OPTIONS = {
  idField: "n",
  fields: Object.keys(BOOST),
  storeFields: [],
  tokenize: (text: string) => text.split(" "),
  processTerm: (term: string) => term || null,
  extractField: (doc: Doc, field: string): string => {
    switch (field) {
      case "n":
        return String(doc.n);
      case "name":
        return nameTerms(doc.name, doc.id).join(" ");
      case "aliases":
        return nameTerms(...doc.aliases).join(" ");
      case "subtitle":
        return words(doc.subtitle).join(" ");
      case "notes":
        return words(doc.notes).join(" ");
      default:
        return doc.keywords;
    }
  },
};

/** Hand-written additions: aliases by `series\0id` (owner series), API notes by symbol path. */
export type IndexExtras = {
  aliases?: Map<string, string[]>;
  notes?: Map<string, string>;
};

export const recordKey = (series: string, id: string) => `${series}\u0000${id}`;

/** API symbol paths as the overlays write them: `Controller:setTask` is `Controller.setTask`. */
const symbolPath = (name: string) => name.replace(/:/g, ".");

/** Index every row; yields between chunks so a slow device keeps responding. */
export async function buildNameIndex(
  file: NameIndexFile,
  model: Model,
  { aliases, notes }: IndexExtras = {},
): Promise<NameIndex> {
  const docs = file.rows.map(([s, rawId, name, subtitle, keywords], n): Doc => {
    const series = file.series[s] ?? "";
    const id = rawId || name;
    const api = series === API_SERIES;
    return {
      n,
      series,
      id,
      name,
      subtitle,
      keywords,
      aliases: (!api && aliases?.get(recordKey(series, id))) || [],
      notes: (api && notes?.get(symbolPath(name))) || "",
    };
  });
  const search = new MiniSearch<Doc>(OPTIONS);
  await search.addAllAsync(docs, { chunkSize: 1000 });
  return { search, docs, model };
}

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

const SEARCH: SearchOptions = { prefix: true, combineWith: "AND", boost: BOOST };

/**
 * Every word as a prefix (all of them), or the words run together ("aim 120" as "aim120");
 * when neither matches, the same with typos allowed in longer words.
 */
function match(index: NameIndex, query: string) {
  const w = words(query).slice(0, 8);
  if (!w.length) return [];
  const run = (options: SearchOptions) => {
    const hits = index.search.search(w.join(" "), options);
    if (w.length < 2) return hits;
    const seen = new Set(hits.map((h) => h.id));
    return hits.concat(index.search.search(w.join(""), options).filter((h) => !seen.has(h.id)));
  };
  const exact = run(SEARCH);
  return exact.length
    ? exact
    : run({ ...SEARCH, fuzzy: (term) => (term.length >= 5 ? 0.2 : false) });
}

/**
 * Results of `query`, one group per series (the Lua API one group of its own), at most
 * `limit` per group, best first. An exact name, id or alias multiplies the score by 4 (an
 * API symbol's path or last segment by 2: `_G.F_16` stays below the F-16 records), so the
 * thing typed comes first.
 */
export function searchNames(index: NameIndex, query: string, limit: number): SourceHits[] {
  const wanted = squash(query);
  if (query.trim().length < MIN_QUERY || !wanted) return [];
  const groups = new Map<string, SourceHits>();
  for (const hit of match(index, query)) {
    const doc = index.docs[Number(hit.id)];
    if (!doc) continue;
    const api = doc.series === API_SERIES;
    const label = api ? "Lua API" : index.model.byId.get(doc.series)?.label;
    if (!label) continue;
    const exact = api
      ? squash(doc.name) === wanted || squash(doc.name.split(/[.:]/).pop() ?? "") === wanted
        ? 2
        : 1
      : squash(doc.name) === wanted ||
          squash(doc.id) === wanted ||
          doc.aliases.some((a) => squash(a) === wanted)
        ? 4
        : 1;
    const weight = WEIGHT[doc.series] ?? 1;
    let g = groups.get(doc.series);
    if (!g) {
      g = { source: { id: doc.series, label, weight }, results: [] };
      groups.set(doc.series, g);
    }
    const subtitle = api
      ? doc.subtitle.replace(/`/g, "")
      : doc.subtitle
          .split(" · ")
          .filter(Boolean)
          .map((part) => constantLabel(part))
          .join(" · ");
    g.results.push({
      key: doc.id,
      title: doc.name,
      ...(subtitle ? { subtitle } : {}),
      ...(!api && doc.id !== doc.name ? { detail: doc.id } : {}),
      href: api ? doc.id : recordHref(doc.series, doc.id),
      score: hit.score * weight * exact,
    });
  }
  const out = [...groups.values()];
  for (const g of out) {
    g.results.sort((a, b) => b.score - a.score);
    g.results.length = Math.min(g.results.length, limit);
  }
  return out.sort(
    (a, b) =>
      (b.results[0]?.score ?? 0) - (a.results[0]?.score ?? 0) ||
      a.source.label.localeCompare(b.source.label),
  );
}
