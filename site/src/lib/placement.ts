/**
 * Where each field of a record page goes, decided once: the header, the key-figure strip,
 * the Overview, a section of its own, or the Source section. components/record/record-view
 * renders the result as is.
 */
import { COMPANION_PREFIX, getPath, isRecord } from "./catalog";
import { coverageText, plainValue, rangePair, type ValueContext } from "./format-field";
import { rangeListOf } from "./record-tables";
import { displayFor } from "./series-display";
import type { CatalogEntry, RecordDoc, SeriesCatalog } from "./types";

type Json = Record<string, unknown>;

/** `hidden`: says nothing on this page (a companion's link back, a range's bounds). */
export type Slot = "header" | "strip" | "overview" | "section" | "source" | "hidden";

/** Fields the record header shows. */
const HEADER_FIELDS = new Set(["id"]);

/** One key figure under the title: a field's value, an array's length, a range list's coverage. */
export type StripItem =
  | { show: "value"; path: string; entry: CatalogEntry; value: unknown }
  | { show: "count"; path: string; entry: CatalogEntry; value: unknown[] }
  | { show: "coverage"; path: string; entry: CatalogEntry; value: unknown[]; text: string };

type SectionBase = {
  /** Element id (and contents anchor). */
  id: string;
  title: string;
  /** Holds the companion series' fields (the flight model of a weapon). */
  companion: boolean;
};

export type PlacedSection = SectionBase &
  (
    | {
        kind: "overview";
        typeName: string;
        /** Catalog path of `value` ("" for the record). */
        prefix: string;
        value: Json;
        /** The fields placed here. */
        fields: ReadonlySet<string>;
      }
    | { kind: "record"; entry: CatalogEntry; typeName: string; path: string; value: Json }
    | { kind: "records"; entry: CatalogEntry; path: string; rows: unknown[] }
    | {
        kind: "source";
        fields: Array<{ entry: CatalogEntry; path: string; value: unknown }>;
      }
  );

export type Placement = {
  /** The slot of each top-level field the record (or its companion) carries, by catalog path. */
  slots: Map<string, Slot>;
  strip: StripItem[];
  sections: PlacedSection[];
  /** Where the Scripting block goes: right after the record's Overview (an index into `sections`). */
  scriptingAt: number;
};

const valueAt = (doc: RecordDoc, path: string) =>
  path.startsWith(`${COMPANION_PREFIX}.`)
    ? getPath(doc.companion, path.slice(COMPANION_PREFIX.length + 1))
    : getPath(doc.data, path);

/**
 * The key figures under a record's title: the series' configured paths, else its first
 * top-level numbers with a unit. `#path` counts an array; a list of ranges reads as its
 * coverage. Only figures with a value; fewer than two make no strip (`[]`).
 */
export function stripFor(catalog: SeriesCatalog, doc: RecordDoc, vctx: ValueContext): StripItem[] {
  const paths =
    displayFor(doc.series).readouts ??
    Object.values(catalog.entries)
      .filter(
        (e) =>
          e.kind === "number" &&
          e.unit &&
          !e.path.includes(".") &&
          typeof doc.data[e.name] === "number",
      )
      .slice(0, 4)
      .map((e) => e.path);
  const items = paths.flatMap((spec): StripItem[] => {
    const count = spec.startsWith("#");
    const path = count ? spec.slice(1) : spec;
    const entry = catalog.entries[path];
    const value = valueAt(doc, path);
    if (!entry || value === undefined || value === null) return [];
    if (count) {
      return Array.isArray(value) && value.length
        ? [{ show: "count", path: spec, entry, value }]
        : [];
    }
    if (entry.kind === "records" && Array.isArray(value)) {
      const list = rangeListOf(catalog, entry, path);
      const text = list && coverageText(list.pair, value.filter(isRecord), vctx.system);
      return text ? [{ show: "coverage", path, entry, value, text }] : [];
    }
    if (typeof value === "number" && entry.kind === "number") {
      return [{ show: "value", path, entry, value }];
    }
    return plainValue(entry, value, vctx) ? [{ show: "value", path, entry, value }] : [];
  });
  return items.length >= 2 ? items : [];
}

const isEmpty = (v: unknown) => v === null || (Array.isArray(v) && v.length === 0);

/** Assigns every field of `doc` to one slot and builds the page's sections from them. */
export function placeRecord(catalog: SeriesCatalog, doc: RecordDoc, vctx: ValueContext): Placement {
  const slots = new Map<string, Slot>();
  const strip = stripFor(catalog, doc, vctx);
  // A key figure in the strip is not repeated in an Overview (named sections keep theirs).
  const inStrip = new Set(strip.filter((s) => s.show === "value").map((s) => s.path));
  const sections: PlacedSection[] = [];
  const source: Array<{ entry: CatalogEntry; path: string; value: unknown }> = [];
  let scriptingAt = 0;

  const place = (root: Json, typeName: string, prefix: string) => {
    const companion = prefix !== "";
    const fields = catalog.types[typeName]?.fields ?? [];
    const key = (name: string) => (prefix ? `${prefix}.${name}` : name);
    const entryOf = (name: string) => catalog.entries[key(name)];
    // A range record (`range`: min/max) that only bounds a sibling list of ranges says nothing new.
    const hasRangeList = fields.some((f) => {
      const e = entryOf(f);
      return e?.kind === "records" && Array.isArray(root[f]) && rangeListOf(catalog, e, key(f));
    });
    const isBounds = (e: CatalogEntry) =>
      hasRangeList &&
      e.kind === "record" &&
      Boolean(e.recordType) &&
      (catalog.types[e.recordType ?? ""]?.fields.length ?? 0) === 2 &&
      rangePair(catalog, e.recordType ?? "", e.path) !== null;

    const overview = new Set<string>();
    const own: PlacedSection[] = [];
    for (const name of fields) {
      const entry = entryOf(name);
      const value = root[name];
      if (!entry || value === undefined) continue;
      const slot = ((): Slot => {
        if (entry.role === "provenance") return "source";
        if (!companion && HEADER_FIELDS.has(name)) return "header";
        // A companion's link back to its parent (weapon_flight.weapon) says nothing here.
        if (companion && entry.ref?.includes(doc.series)) return "hidden";
        if (entry.kind === "record" || entry.kind === "records") {
          if (isEmpty(value) || isBounds(entry)) return "hidden";
          if (entry.kind === "record" && isRecord(value) && entry.recordType) {
            own.push({
              kind: "record",
              id: key(name).replace(/\./g, "-"),
              title: entry.label,
              companion,
              entry,
              typeName: entry.recordType,
              path: key(name),
              value,
            });
            return "section";
          }
          if (entry.kind === "records" && Array.isArray(value)) {
            own.push({
              kind: "records",
              id: key(name).replace(/\./g, "-"),
              title: entry.label,
              companion,
              entry,
              path: key(name),
              rows: value,
            });
            return "section";
          }
          return "hidden";
        }
        if (inStrip.has(key(name))) return "strip";
        return "overview";
      })();
      slots.set(key(name), slot);
      if (slot === "overview") overview.add(name);
      if (slot === "source") source.push({ entry, path: key(name), value });
    }
    if (overview.size) {
      sections.push({
        kind: "overview",
        id: companion ? `${prefix}-overview` : "overview",
        title: companion ? "Flight model" : "Overview",
        companion,
        typeName,
        prefix,
        value: root,
        fields: overview,
      });
      if (!companion) scriptingAt = sections.length;
    }
    sections.push(...own);
  };

  place(doc.data, catalog.rootType, "");
  const companionEntry = catalog.entries[COMPANION_PREFIX];
  if (doc.companion && companionEntry?.recordType) {
    place(doc.companion, companionEntry.recordType, COMPANION_PREFIX);
  }
  if (source.length) {
    sections.push({
      kind: "source",
      id: "provenance",
      title: "Source",
      companion: false,
      fields: source,
    });
  }
  return { slots, strip, sections, scriptingAt };
}
