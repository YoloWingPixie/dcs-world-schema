import { beforeAll, describe, expect, it } from "vitest";
import { nodeQuery } from "../../tests/reference/db";
import { catalogFor, getRecord, loadModel, type Model } from "./db/reference";
import { headerChips, placeRecord } from "./placement";
import type { RecordDoc } from "./types";

const q = nodeQuery();
let model: Model;
beforeAll(async () => {
  model = await loadModel(q);
});

async function load(series: string, id: string) {
  const doc = (await getRecord(q, model, series, id)) as RecordDoc;
  const catalog = catalogFor(model, series);
  const placement = placeRecord(catalog, doc, { enums: catalog.enums, system: "metric" });
  const shown = placement.sections.flatMap((s) =>
    s.kind === "overview"
      ? s.fields.map((f) => (s.prefix ? `${s.prefix}.${f}` : f))
      : s.kind === "source"
        ? s.fields.map((f) => f.path)
        : [s.path],
  );
  return { doc, catalog, shown };
}

describe("the record key", () => {
  it("shows in the header only, whatever the series keys by", async () => {
    expect((await load("stores", "{FAB-500-TA}")).shown).not.toContain("clsid");
    expect((await load("callsigns", "0")).shown).not.toContain("country");
    expect((await load("aircraft", "F-16C_50")).shown).not.toContain("id");
    // The companion's link back to its record.
    const weapon = await load("weapons", "AIM_120C");
    expect(weapon.shown).not.toContain("flight.weapon");
    expect(weapon.shown).not.toContain("id");
  });
});

describe("header chips", () => {
  it("label the record's top-level enum values once each", async () => {
    const { doc, catalog } = await load("stores", "{FAB-500-TA}");
    expect(headerChips(catalog, doc)).toEqual(["Single", "Bombs"]);
    const sensor = await load("sensors", "AGM_65D");
    expect(headerChips(sensor.catalog, sensor.doc)).toEqual(["IR", "Optical", "Infrared"]);
  });
});
