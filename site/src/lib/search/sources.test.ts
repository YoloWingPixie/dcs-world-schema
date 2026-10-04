import { describe, expect, it } from "vitest";
import { ftsQuery } from "../db/reference";
import { deserializeIndex, mergeHits, searchIndex, serializeIndex } from "./engine";
import { SEARCH_PROVIDERS, SEARCH_SOURCES } from "./sources";
import type { SearchSource } from "./types";

describe("search registry", () => {
  it("has unique ids across prebuilt sources and live providers", () => {
    const ids = [...SEARCH_SOURCES.map((s) => s.id), ...SEARCH_PROVIDERS.map((p) => p.id)];
    expect(new Set(ids).size).toBe(ids.length);
    expect(SEARCH_PROVIDERS.map((p) => p.id)).toContain("reference");
  });

  it("every prebuilt source declares the contract fields", () => {
    for (const s of SEARCH_SOURCES) {
      expect(s.indexUrl.startsWith("/")).toBe(true);
      expect(typeof s.docToResult).toBe("function");
      expect(s.options.fields?.length).toBeGreaterThan(0);
    }
  });

  it("round-trips a prebuilt index and ranks groups by best hit", () => {
    const source: SearchSource = {
      id: "demo",
      label: "Demo",
      indexUrl: "/data/demo.json",
      options: { idField: "id", fields: ["t"], storeFields: ["t"] },
      docToResult: (d) => ({ key: String(d.id), title: String(d.t), href: `/demo/${d.id}/` }),
    };
    const index = deserializeIndex(
      serializeIndex(source.options, [
        { id: "a", t: "AIM-120C" },
        { id: "b", t: "R-27ER" },
      ]),
      source.options,
    );
    const hits = searchIndex(index, source, "aim");
    expect(hits[0]).toMatchObject({ title: "AIM-120C", href: "/demo/a/" });
    const merged = mergeHits([
      { source: { id: "empty", label: "Empty" }, results: [] },
      { source, results: hits },
    ]);
    expect(merged.map((g) => g.source.id)).toEqual(["demo"]);
  });

  it("turns a query into an FTS5 prefix match", () => {
    expect(ftsQuery("AIM-120C")).toBe('("aim"* "120c"*) OR "aim120c"*');
    expect(ftsQuery("batumi")).toBe('"batumi"*');
    expect(ftsQuery(" - ")).toBeNull();
  });
});
