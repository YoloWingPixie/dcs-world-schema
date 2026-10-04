"use client";

/**
 * What the API pages load: rows of the reference database (range requests, db/browser.ts)
 * merged with the hand-written overlays shipped with the site (public/overlays/api.json).
 */
import { browserQuery } from "../db/browser";
import { recordHref } from "../series";
import { applyOverlays, existingRecords, getApiPage, listApiPages, overlayLinks } from "./db";
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

export type LoadedApiPage = {
  page: ApiPage;
  /** Enum values with the reference record pages that exist. */
  values?: Array<EnumValue & { href?: string }>;
};

export const loadApiPage = (section: ApiSection, name: string) =>
  once(`api:${section}:${name}`, async (): Promise<LoadedApiPage | null> => {
    const [raw, overlays] = await Promise.all([
      getApiPage(browserQuery, section, name),
      loadApiOverlays(),
    ]);
    if (!raw) return null;
    const page = applyOverlays(raw, overlays);
    const seeAlso = await overlayLinks(browserQuery, page);
    for (const [path, href] of seeAlso) page.links[path] ??= href;
    if (!page.values || !page.valuesSeries) return { page };
    const series = page.valuesSeries;
    const refs = page.values.map((v) => v.ref).filter((r): r is string => Boolean(r));
    const found = await existingRecords(browserQuery, series, refs);
    return {
      page,
      values: page.values.map((v) =>
        v.ref && found.has(v.ref) ? { ...v, href: recordHref(series, v.ref) } : v,
      ),
    };
  });
