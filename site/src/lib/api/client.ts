"use client";

/**
 * What the API pages load: rows of the reference database (range requests, db/browser.ts)
 * merged with the hand-written overlays shipped with the site (public/overlays/api.json).
 */
import { BASE_PATH } from "../base-path";
import { humanize } from "../catalog";
import { loadSeriesIndex } from "../client-data";
import { browserQuery, transientQuery } from "../db/browser";
import { qi } from "../db/reference";
import { fetchJsonOr, once } from "../once";
import { facetParam, recordHref, SERIES_BY_ID, seriesHref } from "../series";
import { applyOverlays, existingRecords, getApiPage, listApiPages, overlayLinks } from "./db";
import { enumField, namesKey, seriesOfClass } from "./scripting";
import type { ApiOverlayFile, ApiPage, ApiSection, EnumValue, PageSummary } from "./types";

const NO_OVERLAYS: ApiOverlayFile = { symbols: {} };

export const loadApiOverlays = () =>
  once("api-overlays", () => fetchJsonOr(`${BASE_PATH}/overlays/api.json`, NO_OVERLAYS));

export const loadApiPages = () =>
  once("api-pages", (): Promise<PageSummary[]> => listApiPages(browserQuery));

/** A reference series an API page's objects or values are records of. */
export type DataLink = { label: string; href: string; count: number };

export type LoadedApiPage = { page: ApiPage };

/** What an API page shows once it is on screen: links into the reference data. */
export type ApiPageExtras = {
  /** Enum values with the reference record pages that exist (or their browse filter). */
  values?: Array<EnumValue & { href?: string; refLabel?: string }>;
  /** Reference series of the page (lib/api/scripting.ts, an enum's `valuesSeries`). */
  data?: DataLink[];
};

/** The series a page's objects (a class and its subclasses) or values are records of. */
function dataSeries(page: ApiPage): string[] {
  if (page.kind === "class") {
    const names = [page.name, ...(page.subclasses ?? []).map((c) => c.name)];
    return [...new Set(names.flatMap(seriesOfClass))];
  }
  if (page.kind !== "enum") return [];
  if (page.valuesSeries) return [page.valuesSeries];
  const field = enumField(page.name);
  return field ? [field.series] : [];
}

/** The page's series that hold records, with their counts (the `series` table's). */
async function dataLinks(page: ApiPage): Promise<DataLink[]> {
  const series = dataSeries(page);
  if (!series.length) return [];
  const rows = await transientQuery(
    `SELECT name, records FROM series WHERE name IN (${series.map(() => "?").join(", ")})`,
    series,
  );
  const counts = new Map(rows.map((r) => [String(r.name), Number(r.records ?? 0)]));
  return series.flatMap((id) => {
    const count = counts.get(id) ?? 0;
    const label = SERIES_BY_ID.get(id)?.label ?? humanize(id);
    return count > 0 ? [{ label, href: seriesHref(id), count }] : [];
  });
}

/**
 * Values of a fixed enum a record field holds (`Unit.SensorType` in a sensor's `category`):
 * each links to the series' browse page filtered on the constant name the records give for
 * that value (one GROUP BY over the series' table, which holds both; lib/api/scripting.ts
 * `namesKey`).
 */
async function facetValues(page: ApiPage): Promise<ApiPageExtras["values"]> {
  const found = enumField(page.name);
  const facet = found?.field.facet;
  if (!found || !facet || !page.values) return undefined;
  const { series, field } = found;
  // Only a facet the browse page offers (lib/db/reference.ts `getSeriesIndex`).
  const index = await loadSeriesIndex(series);
  if (!index.facets.some((f) => f.path === facet)) return undefined;
  const rows = await browserQuery(
    `SELECT ${qi(field.path)} AS v, ${qi(field.name)} AS n, count(*) AS c FROM ${qi(series)}
      WHERE n IS NOT NULL GROUP BY v, n`,
  );
  const names = new Map<unknown, Map<string, number>>();
  for (const { v, n, c } of rows) {
    if (typeof n !== "string") continue;
    const counts = names.get(v) ?? new Map<string, number>();
    counts.set(n, Number(c ?? 0));
    names.set(v, counts);
  }
  const label = SERIES_BY_ID.get(series)?.label.toLowerCase() ?? series;
  return page.values.map((v) => {
    const hits = [...(names.get(v.value)?.entries() ?? [])].filter(([n]) => namesKey(n, v.key));
    const [hit] = hits;
    if (hits.length !== 1 || !hit) return v;
    const [name, count] = hit;
    const qs = new URLSearchParams([[facetParam(facet), name]]);
    return { ...v, href: `${seriesHref(series)}?${qs}`, refLabel: `${count} ${label}` };
  });
}

/** Enum values whose reference record exists, linked to it (`valuesSeries`). */
async function recordValues(page: ApiPage): Promise<ApiPageExtras["values"]> {
  const series = page.valuesSeries;
  if (!page.values || !series) return undefined;
  const refs = page.values.map((v) => v.ref).filter((r): r is string => Boolean(r));
  const found = await existingRecords(transientQuery, series, refs);
  return page.values.map((v) =>
    v.ref && found.has(v.ref) ? { ...v, href: recordHref(series, v.ref) } : v,
  );
}

/** An API page with its overlays and see-also links: what renders first. */
export const loadApiPage = (section: ApiSection, name: string) =>
  once(`api:${section}:${name}`, async (): Promise<LoadedApiPage | null> => {
    const [raw, overlays] = await Promise.all([
      getApiPage(transientQuery, section, name),
      loadApiOverlays(),
    ]);
    if (!raw) return null;
    const page = applyOverlays(raw, overlays);
    for (const [path, href] of await overlayLinks(transientQuery, page)) page.links[path] ??= href;
    return { page };
  });

/**
 * A page's links into the reference data, filled in once the page is on screen: its series
 * and their counts, and its enum values' facet filters (or, without them, their records).
 * Failures leave the page without them.
 */
export const loadApiPageExtras = (section: ApiSection, name: string) =>
  once(`api-extras:${section}:${name}`, async (): Promise<ApiPageExtras> => {
    const loaded = await loadApiPage(section, name);
    if (!loaded) return {};
    const { page } = loaded;
    const [data, facets, records] = await Promise.all([
      dataLinks(page).catch(() => []),
      facetValues(page).catch(() => undefined),
      recordValues(page).catch(() => undefined),
    ]);
    const values = facets ?? records;
    return { ...(data.length ? { data } : {}), ...(values ? { values } : {}) };
  });
