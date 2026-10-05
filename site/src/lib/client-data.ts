"use client";

/**
 * What the pages load, read live from the reference database (lib/db) and merged with
 * the hand-written overlays shipped with the site (public/overlays/reference.json).
 * Overlays naming a record or field the database no longer has are ignored.
 */
import { COMPANION_PREFIX } from "./catalog";
import { browserQuery } from "./db/browser";
import {
  catalogFor,
  getFieldValues,
  getRecord,
  getSeriesIndex,
  keyedFieldPaths,
  loadModel as loadModelFrom,
  type Model,
  referencedByGroup,
} from "./db/reference";
import { slugify } from "./series-display";
import type {
  FieldValues,
  LinkTarget,
  Overlay,
  RecordDoc,
  SeriesCatalog,
  SeriesIndex,
  SiteManifest,
} from "./types";

export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export type OverlayFile = {
  series: Record<
    string,
    {
      intro?: Overlay & { text: string };
      records: Record<string, Overlay & { text: string }>;
      fields: Record<string, Overlay & { text: string }>;
    }
  >;
};

const memo = new Map<string, Promise<unknown>>();
function once<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = memo.get(key);
  if (hit) return hit as Promise<T>;
  const promise = load();
  promise.catch(() => memo.delete(key));
  memo.set(key, promise);
  return promise;
}

export const loadModel = () => once("model", () => loadModelFrom(browserQuery));

const NO_OVERLAYS: OverlayFile = { series: {} };
const OVERLAYS_URL = `${BASE_PATH}/overlays/reference.json`;

export const loadOverlays = () =>
  once(
    "overlays",
    (): Promise<OverlayFile> =>
      fetch(OVERLAYS_URL)
        .then((r) => (r.ok ? (r.json() as Promise<OverlayFile>) : NO_OVERLAYS))
        .catch(() => NO_OVERLAYS),
  );

/** The overlay of a record (and of its companion record), matched by id or slug. */
export function recordOverlay(file: OverlayFile, model: Model, series: string, id: string) {
  const pick = (s: string) => file.series[s]?.records[id] ?? file.series[s]?.records[slugify(id)];
  const own = pick(series);
  const companion = model.byId.get(series)?.companion;
  const comp = companion ? pick(companion) : undefined;
  if (!own && !comp) return undefined;
  const merged: Overlay & { text: string } = {
    html: (own?.html ?? "") + (comp?.html ?? ""),
    text: `${own?.text ?? ""} ${comp?.text ?? ""}`.trim(),
  };
  const aliases = [...(own?.aliases ?? []), ...(comp?.aliases ?? [])];
  const seeAlso = [...(own?.seeAlso ?? []), ...(comp?.seeAlso ?? [])];
  if (aliases.length) merged.aliases = aliases;
  if (seeAlso.length) merged.seeAlso = seeAlso;
  return merged;
}

export const loadManifest = () =>
  once("manifest", async (): Promise<SiteManifest> => {
    const model = await loadModel();
    return {
      dcsVersion: model.meta.dcsVersion ?? "",
      extractedAt: model.meta.extractedAt ?? "",
      series: model.series.map((s) => ({ id: s.id, count: s.count, fields: 0 })),
    };
  });

export const loadCatalog = (series: string) =>
  once(`catalog:${series}`, async (): Promise<SeriesCatalog> => {
    const [model, overlays] = await Promise.all([loadModel(), loadOverlays()]);
    const base = catalogFor(model, series);
    const catalog: SeriesCatalog = { ...base, entries: { ...base.entries } };
    const notes = (s: string, prefix: string) => {
      for (const [path, o] of Object.entries(overlays.series[s]?.fields ?? {})) {
        const key = (prefix + path).replace(/\+/g, "*");
        const entry = catalog.entries[key];
        if (entry && o.html) catalog.entries[key] = { ...entry, note: o.html };
      }
    };
    notes(series, "");
    const companion = model.byId.get(series)?.companion;
    if (companion) notes(companion, `${COMPANION_PREFIX}.`);
    return catalog;
  });

/** Comparable concrete paths, keyed stages included. */
export const loadFieldPaths = (series: string) =>
  once(`paths:${series}`, async () => {
    const [model, catalog] = await Promise.all([loadModel(), loadCatalog(series)]);
    return [...catalog.fieldPaths, ...(await keyedFieldPaths(browserQuery, model, series))];
  });

export const loadSeriesIndex = (series: string) =>
  once(`index:${series}`, async (): Promise<SeriesIndex> => {
    const [model, overlays] = await Promise.all([loadModel(), loadOverlays()]);
    const index = await getSeriesIndex(browserQuery, model, series);
    const intro = overlays.series[series]?.intro;
    return intro ? { ...index, intro } : index;
  });

export const loadRecord = (series: string, id: string) =>
  once(`record:${series}:${id}`, async (): Promise<RecordDoc> => {
    const overlaysLoading = loadOverlays();
    const model = await loadModel();
    const [doc, overlays] = await Promise.all([
      getRecord(browserQuery, model, series, id),
      overlaysLoading,
    ]);
    if (!doc) throw new Error(`No ${series} record ${id}.`);
    const overlay = recordOverlay(overlays, model, series, doc.id);
    return overlay ? { ...doc, overlay } : doc;
  });

/** The full list of a capped "referenced by" group (`total` > `records.length`). */
export const loadReferencedByGroup = (series: string, id: string, from: string, path: string) =>
  once(`refby:${series}:${id}:${from}:${path}`, async (): Promise<LinkTarget[]> => {
    const model = await loadModel();
    return referencedByGroup(browserQuery, model, series, id, from, path);
  });

export const loadFieldValues = (series: string, path: string) =>
  once(`field:${series}:${path}`, async (): Promise<FieldValues> => {
    const model = await loadModel();
    return getFieldValues(browserQuery, model, series, path);
  });
