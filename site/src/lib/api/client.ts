"use client";

/**
 * What the API pages load: rows of the reference database (range requests, db/browser.ts)
 * merged with the hand-written overlays shipped with the site (public/overlays/api.json).
 */
import { loadModel, loadSeriesIndex } from "../client-data";
import { browserQuery } from "../db/browser";
import { recordHref, SERIES_BY_ID, seriesHref } from "../series";
import { applyOverlays, existingRecords, getApiPage, listApiPages, overlayLinks } from "./db";
import { enumField, namesKey, seriesOfClass } from "./scripting";
import type { ApiOverlayFile, ApiPage, ApiSection, EnumValue, PageSummary } from "./types";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const NO_OVERLAYS: ApiOverlayFile = { symbols: {} };

const memo = new Map<string, Promise<unknown>>();
function once<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = memo.get(key);
  if (hit) return hit as Promise<T>;
  const promise = load();
  promise.catch(() => memo.delete(key));
  memo.set(key, promise);
  return promise;
}

export const loadApiOverlays = () =>
  once(
    "api-overlays",
    (): Promise<ApiOverlayFile> =>
      fetch(`${BASE_PATH}/overlays/api.json`)
        .then((r) => (r.ok ? (r.json() as Promise<ApiOverlayFile>) : NO_OVERLAYS))
        .catch(() => NO_OVERLAYS),
  );

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
 * that value (the series' browse rows carry both; lib/api/scripting.ts `namesKey`).
 */
async function facetValues(page: ApiPage): Promise<LoadedApiPage["values"]> {
  const found = enumField(page.name);
  if (!found?.field.facet || !page.values) return undefined;
  const { series, field } = found;
  const index = await loadSeriesIndex(series);
  const at = (path: string) => index.columns.indexOf(path);
  const [vi, ni] = [at(field.path), at(field.name)];
  if (vi < 0 || ni < 0 || !index.facets.some((f) => f.path === field.facet)) return undefined;
  const names = new Map<unknown, Map<string, number>>();
  for (const row of index.rows) {
    const [v, n] = [row[3 + vi], row[3 + ni]];
    if (typeof n !== "string") continue;
    const counts = names.get(v) ?? new Map<string, number>();
    counts.set(n, (counts.get(n) ?? 0) + 1);
    names.set(v, counts);
  }
  const label = SERIES_BY_ID.get(series)?.label.toLowerCase() ?? series;
  return page.values.map((v) => {
    const hits = [...(names.get(v.value)?.entries() ?? [])].filter(([n]) => namesKey(n, v.key));
    const [hit] = hits;
    if (hits.length !== 1 || !hit) return v;
    const [name, count] = hit;
    const qs = new URLSearchParams([[`f.${field.facet}`, name]]);
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
