/** Shorter queries match most rows: too broad to read. */
export const MIN_QUERY = 2;

/** One row in the palette or a results list. */
export type SearchResultItem = {
  /** Unique within its group. */
  key: string;
  title: string;
  /** Short secondary line (kind, role, one or two key values). */
  subtitle?: string;
  /** Monospace identifier shown at the end of the row (DCS id, Lua name). */
  detail?: string;
  /** Site path without basePath, e.g. `/aircraft/F-16C_50/` or `/api/coalition/`. */
  href: string;
};

/** A results group: a reference series, or the Lua API. */
export type SearchGroup = {
  /** Stable id: the filter chip's value. */
  id: string;
  /** Group heading and filter-chip label. */
  label: string;
  /** Score multiplier when ranking groups against each other. */
  weight?: number;
};

export type SourceHits = {
  source: SearchGroup;
  results: Array<SearchResultItem & { score: number }>;
};
