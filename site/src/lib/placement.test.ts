import { beforeAll, describe, expect, it } from "vitest";
import { nodeQuery } from "../../tests/reference/db";
import { catalogFor, getRecord, loadModel, type Model } from "./db/reference";
import { headerChips, placeRecord, sectionFor } from "./placement";
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

describe("sectionFor", () => {
  it("names the section each field shows in, as the record page places it", async () => {
    const weapon = await load("weapons", "AIM_120C");
    const placement = placeRecord(weapon.catalog, weapon.doc, {
      enums: weapon.catalog.enums,
      system: "metric",
    });
    for (const section of placement.sections) {
      const keys =
        section.kind === "overview"
          ? section.fields.map((f) => (section.prefix ? `${section.prefix}.${f}` : f))
          : section.kind === "source"
            ? section.fields.map((f) => f.path)
            : [section.path];
      for (const key of keys) {
        expect(sectionFor(weapon.catalog, key), key).toMatchObject({
          id: section.id,
          title: section.title,
          companion: section.companion,
        });
      }
    }
  });

  it("puts fields under a top-level record or list in its section", () => {
    const aircraft = catalogFor(model, "aircraft");
    expect(sectionFor(aircraft, "stations[].accepts[].clsid")).toMatchObject({
      id: "stations",
      kind: "field",
      companion: false,
    });
    expect(sectionFor(aircraft, "flight.aerodynamics.table[].cx0")).toMatchObject({
      id: "flight-aerodynamics",
      companion: true,
    });
    expect(sectionFor(aircraft, "sourcePaths")).toMatchObject({ id: "provenance" });
    const weapons = catalogFor(model, "weapons");
    expect(sectionFor(weapons, "massKg")).toMatchObject({ id: "overview", title: "Overview" });
    expect(sectionFor(weapons, "flight.launchEnvelopes[].maxRangeM")).toMatchObject({
      id: "flight-launchEnvelopes",
    });
    expect(sectionFor(weapons, "flight.motorStages.*.impulseS")).toMatchObject({
      id: "flight-motorStages",
    });
  });
});
