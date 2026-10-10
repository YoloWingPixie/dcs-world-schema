"use client";

/**
 * What the pages load, read live from the reference database (lib/db) and merged with
 * the hand-written overlays shipped with the site (public/overlays/reference.json).
 * Overlays naming a record or field the database no longer has are ignored.
 */
import { COMPANION_PREFIX } from "./catalog";
import { OVERLAYS_URL } from "./db/boot";
import { browserQuery, transientQuery } from "./db/browser";
import {
  catalogFor,
  fieldPaths,
  type GroupTarget,
  getBeaconRows,
  getFieldValues,
  getGroupTargets,
  getRecord,
  getSeriesIndex,
  keyedFieldPaths,
  loadModel as loadModelFrom,
  type Model,
  namesOf,
  referencedByGroup,
} from "./db/reference";
import { fetchJsonOr, once } from "./once";
import { slugify } from "./series-display";
import type {
  FieldPath,
  FieldValues,
  LinkTarget,
  Overlay,
  RecordDoc,
  SeriesCatalog,
  SeriesIndex,
} from "./types";
import { useLoaded } from "./use-loaded";

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

/*
 * Model and series-wide reads go through `browserQuery`, which keeps each statement's rows
 * for the page's lifetime. Reads whose callers keep the parsed result themselves (a record,
 * names, beacons, one referenced-by group) use the bounded `transientQuery`.
 */

export const loadModel = () => once("model", () => loadModelFrom(browserQuery));

const loadModelState = () =>
  loadModel().then(
    (model): { model: Model | null; failed: boolean } => ({ model, failed: false }),
    () => ({ model: null, failed: true }),
  );

/** The model once loaded, and whether it failed; `enabled` false leaves it unread. */
export function useModel(enabled = true): { model: Model | null; failed: boolean } {
  return useLoaded(loadModelState, enabled ? "" : null) ?? { model: null, failed: false };
}

const NO_OVERLAYS: OverlayFile = { series: {} };

export const loadOverlays = () => once("overlays", () => fetchJsonOr(OVERLAYS_URL, NO_OVERLAYS));

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

/** Every comparable concrete path of a series: plain fields, then keyed stages (one scan each). */
export const loadFieldPaths = (series: string) =>
  once(`paths:${series}`, async (): Promise<FieldPath[]> => {
    const model = await loadModel();
    const keyed = await keyedFieldPaths(browserQuery, model, series);
    return [...fieldPaths(catalogFor(model, series)), ...keyed];
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
      getRecord(transientQuery, model, series, id),
      overlaysLoading,
    ]);
    if (!doc) throw new Error(`No ${series} record ${id}.`);
    const overlay = recordOverlay(overlays, model, series, doc.id);
    return overlay ? { ...doc, overlay } : doc;
  });

/** Beacon rows by id, for map points (components/location-map). */
export const loadBeaconRows = (ids: string[]) =>
  once(`beacons:${ids.join("\u0000")}`, () => getBeaconRows(transientQuery, ids));

/** The full list of a capped "referenced by" group (`total` > `records.length`). */
export const loadReferencedByGroup = (series: string, id: string, from: string, path: string) =>
  once(`refby:${series}:${id}:${from}:${path}`, async (): Promise<LinkTarget[]> => {
    const model = await loadModel();
    return referencedByGroup(transientQuery, model, series, id, from, path);
  });

export const loadFieldValues = (series: string, path: string) =>
  once(`field:${series}:${path}`, async (): Promise<FieldValues> => {
    const model = await loadModel();
    return getFieldValues(browserQuery, model, series, path);
  });

/** Record names by id per series (`series -> id -> name`), for the ids wanted only. */
export const loadNames = async (wanted: Map<string, Set<string>>) =>
  namesOf(transientQuery, await loadModel(), wanted);

/** Per row id, the record a group-by ref field points at (lib/series-display `groupBy`). */
export const loadGroupTargets = (series: string, path: string) =>
  once(`group:${series}:${path}`, async (): Promise<Record<string, GroupTarget>> => {
    const model = await loadModel();
    return getGroupTargets(browserQuery, model, series, path);
  });
