import { beforeAll, describe, expect, it } from "vitest";
import {
  browseEntry,
  catalogFor,
  getSeriesIndex,
  loadModel,
  type Model,
} from "../../src/lib/db/reference";
import { SERIES_DISPLAY } from "../../src/lib/series-display";
import { nodeQuery } from "./db";

const q = nodeQuery();
let model: Model;
beforeAll(async () => {
  model = await loadModel(q);
});

/**
 * Every configured path, with the rule it must meet: a path that no longer resolves is
 * dropped quietly by the site, so it fails here.
 */
function configuredPaths(): Array<{ series: string; use: string; path: string }> {
  return Object.entries(SERIES_DISPLAY).flatMap(([series, d]) => [
    ...(d.readouts ?? []).map((path) => ({ series, use: "readout", path })),
    ...(d.columns ?? []).map((path) => ({ series, use: "column", path })),
    ...(d.facets ?? []).map((path) => ({ series, use: "facet", path })),
    ...(d.groupBy ? [{ series, use: "groupBy", path: d.groupBy.path }] : []),
    ...(d.groupBy?.fallback ? [{ series, use: "column", path: d.groupBy.fallback }] : []),
    ...(d.groupBy?.columns ?? []).map((path) => ({ series, use: "column", path })),
  ]);
}

describe("SERIES_DISPLAY", () => {
  it("names only series the database has", () => {
    for (const series of Object.keys(SERIES_DISPLAY)) {
      expect(model.byId.has(series), series).toBe(true);
    }
  });

  it("resolves every configured path in its series' catalog", () => {
    const unresolved = configuredPaths().filter(({ series, use, path }) => {
      const catalog = catalogFor(model, series);
      if (use === "column" || use === "facet") {
        return browseEntry(catalog, path, use) === null;
      }
      if (use === "groupBy") return !catalog.entries[path]?.ref;
      // Readouts (lib/placement `stripFor`): `#path` counts a list, a list of ranges reads
      // as its coverage, any other path is one value.
      const count = path.startsWith("#");
      const entry = catalog.entries[count ? path.slice(1) : path];
      if (!entry) return true;
      if (count) return !["records", "numbers", "strings"].includes(entry.kind);
      if (entry.kind === "records") return entry.layout !== "ranges";
      return entry.compareAs !== "value";
    });
    expect(unresolved).toEqual([]);
  });

  it("puts configured nested and list-valued paths in the browse index", async () => {
    const aircraft = await getSeriesIndex(q, model, "aircraft");
    expect(aircraft.visible).toEqual(SERIES_DISPLAY.aircraft?.columns);
    expect(aircraft.facets.map((f) => f.path)).toEqual(
      expect.arrayContaining(["defaultTask.name", "attributes"]),
    );
    expect(aircraft.facets.find((f) => f.path === "defaultTask.name")?.label).toBe("Default task");
    const ground = await getSeriesIndex(q, model, "ground_vehicles");
    expect(ground.facets.map((f) => f.path)).toEqual(["attributes"]);
  });
});
