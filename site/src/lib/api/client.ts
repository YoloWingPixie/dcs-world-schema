"use client";

import { BASE_PATH } from "../base-path";
/**
 * What the API pages load: rows of the reference database (range requests, db/browser.ts)
 * merged with the hand-written overlays shipped with the site (public/overlays/api.json).
 */
import { loadModel } from "../client-data";
import { browserQuery } from "../db/browser";
import { qi } from "../db/reference";
import { fetchJsonOr, once } from "../once";
import { recordHref, SERIES_BY_ID, seriesHref } from "../series";
import { displayFor } from "../series-display";
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

export type LoadedApiPage = {
  page: ApiPage;
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

async function dataLinks(page: ApiPage): Promise<DataLink[]> {
  const series = dataSeries(page);
  if (!series.length) return [];
  const model = await loadModel();
  return series.flatMap((id) => {
    const s = model.byId.get(id);
    return s && s.count > 0 ? [{ label: s.label, href: seriesHref(id), count: s.count }] : [];
  });
}

/**
 * Values of a fixed enum a record field holds (`Unit.SensorType` in a sensor's `category`):
 * each links to the series' browse page filtered on the constant name the records give for
 * that value (one GROUP BY over the series' table, which holds both; lib/api/scripting.ts
 * `namesKey`).
 */
async function facetValues(page: ApiPage): Promise<LoadedApiPage["values"]> {
  const found = enumField(page.name);
  const facet = found?.field.facet;
  if (!found || !facet || !page.values) return undefined;
  const { series, field } = found;
  // The browse page's facets: configured (lib/series-display), shown with two values or more.
  if (!displayFor(series).facets?.includes(facet)) return undefined;
  const rows = await browserQuery(
    `SELECT ${qi(field.path)} AS v, ${qi(field.name)} AS n, count(*) AS c FROM ${qi(series)}
      WHERE n IS NOT NULL GROUP BY v, n`,
  );
  const facetKey = facet === field.name ? "n" : "v";
  if (new Set(rows.map((r) => r[facetKey])).size < 2) return undefined;
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
    const qs = new URLSearchParams([[`f.${facet}`, name]]);
    return { ...v, href: `${seriesHref(series)}?${qs}`, refLabel: `${count} ${label}` };
  });
}

export const loadApiPage = (section: ApiSection, name: string) =>
  once(`api:${section}:${name}`, async (): Promise<LoadedApiPage | null> => {
    const [raw, overlays] = await Promise.all([
      getApiPage(browserQuery, section, name),
      loadApiOverlays(),
    ]);
    if (!raw) return null;
    const page = applyOverlays(raw, overlays);
    const [seeAlso, data, facets] = await Promise.all([
      overlayLinks(browserQuery, page),
      dataLinks(page).catch(() => []),
      facetValues(page).catch(() => undefined),
    ]);
    for (const [path, href] of seeAlso) page.links[path] ??= href;
    const out: LoadedApiPage = data.length ? { page, data } : { page };
    if (facets) return { ...out, values: facets };
    if (!page.values || !page.valuesSeries) return out;
    const series = page.valuesSeries;
    const refs = page.values.map((v) => v.ref).filter((r): r is string => Boolean(r));
    const found = await existingRecords(browserQuery, series, refs);
    return {
      ...out,
      values: page.values.map((v) =>
        v.ref && found.has(v.ref) ? { ...v, href: recordHref(series, v.ref) } : v,
      ),
    };
  });
