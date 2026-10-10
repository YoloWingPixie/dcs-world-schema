/**
 * Per-series presentation choices the schema cannot express: the headline readouts on a
 * record page, the default browse columns and facets, and the browse grouping. Every
 * series works without an entry here (the defaults pick from the catalog); entries only
 * refine. Record names and the meta line under them come from the database's `search` table.
 */

import display from "./series-display.json";

export type SeriesDisplay = {
  /**
   * Headline values on the record page (up to four): paths, `#path` for an array's count;
   * a list of ranges reads as its coverage.
   */
  readouts?: string[];
  /** Default browse columns (paths). */
  columns?: string[];
  /** Facet paths (default: enum, boolean and low-cardinality string fields). */
  facets?: string[];
  /** Browse grouped under headings by default (lib/browse-groups); `?group=flat` lists flat. */
  groupBy?: GroupBy;
};

export type GroupBy = {
  /** A ref field (the group is its first target, linked from the heading) or a column. */
  path: string;
  /** Column whose value groups a row the ref leaves empty. */
  fallback?: string;
  /** What a group is, for the toggle and headings: "airframe". */
  label: string;
  /** Default columns while grouped (the heading already names the group). */
  columns?: string[];
};

/**
 * The entries, in series-display.json: tools/package/sqlite.py reads the same file to
 * precompute every configured browse column, facet and group into the series views, so
 * browse loads only the columns a reader picks. Liveries group by the unit type their
 * folder is the entry point of; folders no unit uses (asset-pack props, weapon models)
 * group by the folder name.
 */
export const SERIES_DISPLAY = display as Record<string, SeriesDisplay>;

export function displayFor(series: string): SeriesDisplay {
  return SERIES_DISPLAY[series] ?? {};
}

/** Whether the browse page offers a facet: its values hold at least two distinct ones. */
export const offersFacet = (distinct: number): boolean => distinct >= 2;

/**
 * Whether the browse page offers facet `name` (a column's path or name) of a series: its
 * display lists it and it holds `distinct` values `offersFacet` takes (the API enum pages
 * link to a facet only then, lib/api/client.ts).
 */
export function offersConfiguredFacet(series: string, name: string, distinct: number): boolean {
  return (displayFor(series).facets ?? []).includes(name) && offersFacet(distinct);
}

/** URL-safe slug for an id; ids carry spaces, slashes, braces and parentheses. */
export function slugify(id: string): string {
  return id
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .replace(/-{2,}/g, "-");
}
