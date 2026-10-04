import type { Options } from "minisearch";

/** One row in the palette or a results list. */
export type SearchResultItem = {
  /** Unique within its source. */
  key: string;
  title: string;
  /** Short secondary line (kind, role, one or two key values). */
  subtitle?: string;
  /** Monospace identifier shown at the end of the row (DCS id, Lua name). */
  detail?: string;
  /** Site path without basePath, e.g. `/aircraft/?id=F-16C_50` or `/api/coalition/`. */
  href: string;
};

/** A stored MiniSearch document as returned by `search()` (stored fields + `id`). */
export type StoredDoc = Record<string, unknown> & { id: string | number };

/**
 * A prebuilt search index the global palette merges with the others.
 *
 * The index file is `MiniSearch#toJSON()` output written at build time with the same
 * `options` (see engine.ts `serializeIndex`). The palette fetches it lazily.
 */
export type SearchSource = {
  /** Stable id: chip value and `?in=` URL value. Lowercase, no spaces. */
  id: string;
  /** Group heading and filter-chip label. */
  label: string;
  /** Index JSON path under the site root, without basePath: `/data/search/weapons.json`. */
  indexUrl: string;
  /** MiniSearch options; must equal the options the index was built with. */
  options: Options<StoredDoc>;
  /** Turns a stored document into a result row. */
  docToResult: (doc: StoredDoc) => SearchResultItem;
  /** Score multiplier when ranking groups against each other (default 1). */
  weight?: number;
  /** Lower loads first and wins ties (default 100). */
  priority?: number;
};

/** A results group: a source, or one group of a provider (a reference series). */
export type SearchGroup = Pick<SearchSource, "id" | "label" | "weight" | "priority">;

export type SourceHits = {
  source: SearchGroup;
  results: Array<SearchResultItem & { score: number }>;
};

/**
 * A search that runs its own query (no prebuilt index file), for data the palette cannot
 * hold in memory: the reference database, queried with FTS5 over HTTP range requests.
 * `search` returns any number of groups; `warm` starts loading ahead of the first query.
 */
export type SearchProvider = {
  id: string;
  label: string;
  search: (query: string, limitPerGroup: number) => Promise<SourceHits[]>;
  warm?: () => void;
};
