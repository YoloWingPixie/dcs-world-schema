import { readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import { compareFields } from "../../scripts/lib/compare-fields";
import {
  catalogFor,
  fieldPaths,
  getField,
  keyedFieldPaths,
  loadModel,
  type Model,
} from "../../src/lib/db/reference";
import { nodeQuery } from "./db";
import { liveField, liveKeyedFieldPaths } from "./live-field-values";

const q = nodeQuery();
let model: Model;
beforeAll(async () => {
  model = await loadModel(q);
});

const browsable = () => model.series.filter((s) => !s.parent).map((s) => s.id);

describe("compare fields", () => {
  it("lists what the catalog compares (src/lib/compare-fields.json is current)", () => {
    const committed = JSON.parse(
      readFileSync(new URL("../../src/lib/compare-fields.json", import.meta.url), "utf8"),
    );
    expect(
      committed,
      "src/lib/compare-fields.json is stale: run `pnpm gen:compare-fields` in site/, then " +
        "`task package:sqlite` so the database precomputes the new list",
    ).toEqual(compareFields(model));
  });
});

describe("precomputed field values", () => {
  it("list the keyed paths a json_each scan finds", async () => {
    for (const series of browsable()) {
      expect(await keyedFieldPaths(q, model, series), series).toEqual(
        await liveKeyedFieldPaths(q, model, series),
      );
    }
    expect((await keyedFieldPaths(q, model, "weapons")).length).toBeGreaterThan(10);
  });

  it("equal the live read of every comparable path in every series", async () => {
    let paths = 0;
    for (const series of browsable()) {
      const all = [
        ...fieldPaths(catalogFor(model, series)),
        ...(await liveKeyedFieldPaths(q, model, series)),
      ];
      for (const { path } of all) {
        const live = await liveField(q, model, series, path);
        const stored = await getField(q, model, series, path);
        expect(stored.values, `${series} ${path}`).toEqual(live.values);
        expect(stored.links, `${series} ${path} links`).toEqual(live.links);
        paths++;
      }
    }
    expect(paths).toBeGreaterThan(700);
  }, 120_000);

  it("are empty for a path compare does not offer", async () => {
    expect(await getField(q, model, "aircraft", "stations")).toEqual({ values: {}, links: {} });
    expect(await getField(q, model, "weapons", "flight.motorStages.nope.impulseS")).toEqual({
      values: {},
      links: {},
    });
  });
});
