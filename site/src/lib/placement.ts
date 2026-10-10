/**
 * Where each field of a record page goes, decided once: the header, the key-figure strip,
 * the Overview, a section of its own, or the Source section. components/record/record-view
 * renders the result as is.
 */
import { COMPANION_PREFIX, getPath, rootFor } from "./catalog";
import { coverageText, plainValue, type ValueContext } from "./format-field";
import { isRecord, type Json } from "./json";
import { enumDisplay } from "./names";
import { rangeListOf } from "./record-tables";
import { displayFor } from "./series-display";
import type { CatalogEntry, RecordDoc, SeriesCatalog } from "./types";

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
        /** The fields placed here, friendly classifications first (enum names, then the rest, then numbers). */
        fields: readonly string[];
      }
    | { kind: "record"; entry: CatalogEntry; typeName: string; path: string; value: Json }
    | { kind: "records"; entry: CatalogEntry; path: string; rows: unknown[] }
    | {
        kind: "source";
        fields: Array<{ entry: CatalogEntry; path: string; value: unknown }>;
      }
  );

export type Placement = {
  strip: StripItem[];
  sections: PlacedSection[];
  /** Where the Scripting block goes: right after the record's Overview (an index into `sections`). */
  scriptingAt: number;
};

const valueAt = (doc: RecordDoc, path: string) => {
  const { root, rest } = rootFor<Json>(path, doc.data, doc.companion);
  return getPath(root, rest);
};

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
      const list = rangeListOf(catalog, entry);
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

/**
 * The classification chips under a record's title: its top-level enum values (string ones
 * first, then the constant names beside codes, `categoryName`), each label shown once. The
 * same fields, in the same order, as the subtitle the search table holds.
 */
export function headerChips(catalog: SeriesCatalog, doc: RecordDoc): string[] {
  const fields = catalog.types[catalog.rootType]?.fields ?? [];
  const enums = fields
    .map((name) => catalog.entries[name])
    .filter((e): e is CatalogEntry => e?.kind === "enum");
  const chips = [
    ...enums.filter((e) => !e.codeField && typeof doc.data[e.name] === "string"),
    ...enums.filter((e) => e.codeField && typeof doc.data[e.name] === "string"),
  ].map((e) => enumDisplay(e, doc.data[e.name], catalog.enums).label);
  return [...new Set(chips)];
}

const isEmpty = (v: unknown) => v === null || (Array.isArray(v) && v.length === 0);

/** Overview order: enum names first, numbers last, schema order otherwise. */
const overviewRank = (e: CatalogEntry, value: unknown) =>
  e.kind === "enum" && typeof value === "string" ? 0 : e.kind === "number" ? 2 : 1;

/** Assigns every field of `doc` to one place and builds the page's sections from them. */
export function placeRecord(catalog: SeriesCatalog, doc: RecordDoc, vctx: ValueContext): Placement {
  const strip = stripFor(catalog, doc, vctx);
  // A key figure in the strip is not repeated in an Overview (named sections keep theirs).
  const inStrip = new Set(strip.filter((s) => s.show === "value").map((s) => s.path));
  const sections: PlacedSection[] = [];
  const source: Array<{ entry: CatalogEntry; path: string; value: unknown }> = [];
  let scriptingAt = 0;

  const place = (root: Json, typeName: string, prefix: string) => {
    const companion = prefix !== "";
    const key = (name: string) => (prefix ? `${prefix}.${name}` : name);
    // A range record (`range`: min/max) that only bounds a present list of ranges says nothing new.
    const isBounds = (e: CatalogEntry) => {
      const list = e.bounds ? catalog.entries[e.bounds] : undefined;
      return Boolean(list && Array.isArray(root[list.name]));
    };

    const overview: Array<{ name: string; rank: number }> = [];
    const own: PlacedSection[] = [];
    for (const name of catalog.types[typeName]?.fields ?? []) {
      const entry = catalog.entries[key(name)];
      const value = root[name];
      if (!entry || value === undefined) continue;
      if (entry.role === "provenance") {
        source.push({ entry, path: key(name), value });
        continue;
      }
      // The header shows the record's key; a companion's (weapon_flight.weapon) is the record.
      if (entry.role === "key") continue;
      if (entry.kind === "record" || entry.kind === "records") {
        if (isEmpty(value) || isBounds(entry)) continue;
        const base = { id: key(name).replace(/\./g, "-"), title: entry.label, companion, entry };
        if (entry.kind === "record" && isRecord(value) && entry.recordType) {
          own.push({ ...base, kind: "record", typeName: entry.recordType, path: key(name), value });
        } else if (entry.kind === "records" && Array.isArray(value)) {
          own.push({ ...base, kind: "records", path: key(name), rows: value });
        }
        continue;
      }
      if (!inStrip.has(key(name))) overview.push({ name, rank: overviewRank(entry, value) });
    }
    if (overview.length) {
      sections.push({
        kind: "overview",
        id: companion ? `${prefix}-overview` : "overview",
        title: companion ? (catalog.entries[prefix]?.label ?? prefix) : "Overview",
        companion,
        typeName,
        prefix,
        value: root,
        fields: overview.sort((a, b) => a.rank - b.rank).map((f) => f.name),
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
  return { strip, sections, scriptingAt };
}
