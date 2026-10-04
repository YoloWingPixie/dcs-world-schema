import { beforeAll, describe, expect, it } from "vitest";
import { valuesAt } from "../../src/lib/catalog";
import {
  catalogFor,
  getFieldValues,
  getRecord,
  getSeriesIndex,
  keyedFieldPaths,
  loadModel,
  type Model,
  searchReference,
} from "../../src/lib/db/reference";
import { nodeQuery } from "./db";

const q = nodeQuery();
let model: Model;
beforeAll(async () => {
  model = await loadModel(q);
});

describe("model from the database's own description", () => {
  it("lists every series, infers companions and unit series", () => {
    expect(model.byId.get("weapon_flight")?.parent).toBe("weapons");
    expect(model.byId.get("weapons")?.companion).toBe("weapon_flight");
    expect(model.byId.get("aircraft_flight")?.parent).toBe("aircraft");
    expect(model.byId.get("ground_vehicles")?.unit).toBe(true);
    expect(model.byId.get("stores")?.unit).toBe(false);
    expect(model.meta.dcsVersion).toMatch(/^\d+\.\d+/);
  });

  it("builds every series' catalog from schema_types", () => {
    for (const s of model.series) {
      expect(Object.keys(catalogFor(model, s.id).entries).length, s.id).toBeGreaterThan(1);
    }
    const aircraft = catalogFor(model, "aircraft");
    expect(aircraft.entries["stations[].accepts[].clsid"]).toMatchObject({
      kind: "ref",
      ref: ["stores"],
    });
    expect(aircraft.entries.kind?.kind).toBe("enum");
    expect(aircraft.entries["flight.aerodynamics.table[].cx0"]).toMatchObject({
      comparable: true,
      axis: "mach",
    });
    const weapons = catalogFor(model, "weapons");
    expect(weapons.entries["flight.aerodynamics.cx0"]).toMatchObject({
      kind: "numbers",
      axis: "mach",
    });
    expect(weapons.entries["flight.launchEnvelopes[].maxRangeM"]?.axis).toBe(
      "grid:altitudesM,speedsMs",
    );
    const liveries = catalogFor(model, "liveries");
    expect(liveries.entries.unitTypes?.ref).toEqual(
      expect.arrayContaining(["aircraft", "ground_vehicles", "ships"]),
    );
  });
});

describe("records", () => {
  it("decodes a row with its companion, links and reverse references", async () => {
    const doc = await getRecord(q, model, "weapons", "AIM_120C");
    expect(doc?.name).toBe("AIM-120C");
    expect(doc?.data.massKg).toBeCloseTo(161.48);
    expect(Array.isArray((doc?.companion?.aerodynamics as { cx0?: unknown })?.cx0)).toBe(true);
    expect(doc?.links.warheads?.AIM_120C).toBeDefined();
    const stores = doc?.referencedBy.find((g) => g.series === "stores");
    expect(stores?.path).toBe("delivers[].weapon");
    expect(stores?.records.length).toBeGreaterThan(0);
    // Units reach it through stores (second hop).
    const via = doc?.referencedBy.find((g) => g.series === "aircraft" && g.path === "via:stores");
    expect(via?.records.map((r) => r[0])).toContain("F-16C_50");
    // A weapon is not "referenced by" its own flight model.
    expect(doc?.referencedBy.some((g) => g.series === "weapon_flight")).toBe(false);
  });

  it("resolves refs on an aircraft and finds the aircraft from a store", async () => {
    const f16 = await getRecord(q, model, "aircraft", "F-16C_50");
    expect(f16?.data.flyable).toBe(true);
    expect(f16?.links.stores?.["{5CE2FF2A-645A-4197-B48D-8720AC69394F}"]).toBe(
      "AIM-9X Sidewinder IR AAM",
    );
    expect(f16?.links.sensors?.["AN/APG-68"]).toBeDefined();
    const store = await getRecord(q, model, "stores", "{5CE2FF2A-645A-4197-B48D-8720AC69394F}");
    const by = store?.referencedBy.find((g) => g.series === "aircraft");
    expect(by?.records.map((r) => r[0])).toContain("F-16C_50");
    const sensor = await getRecord(q, model, "sensors", "AN/APG-68");
    expect(sensor?.referencedBy.flatMap((g) => g.records.map((r) => r[0]))).toContain("F-16C_50");
  });

  it("handles integer keys, nested-per-theatre ids and missing records", async () => {
    expect((await getRecord(q, model, "countries", "2"))?.name).toBe("USA");
    const batumi = await getRecord(q, model, "airbases", "Caucasus.22");
    expect(batumi?.name).toBe("Batumi");
    expect(batumi?.links.theatres?.Caucasus).toBeDefined();
    expect(await getRecord(q, model, "weapons", "NOPE")).toBeNull();
  });
});

describe("browse, compare and search", () => {
  it("browses a series from its scalar columns with facets", async () => {
    const index = await getSeriesIndex(q, model, "stores");
    expect(index.count).toBe(model.byId.get("stores")?.count);
    expect(index.facets.map((f) => f.path)).toContain("kind");
    const row = index.rows.find((r) => r[0] === "{5CE2FF2A-645A-4197-B48D-8720AC69394F}");
    expect(row?.[1]).toBe("AIM-9X Sidewinder IR AAM");
  });

  it("reads one field across records: columns, nested JSON, keyed and axis paths", async () => {
    expect((await getFieldValues(q, model, "weapons", "massKg")).values.AIM_120C).toBeCloseTo(
      161.48,
    );
    expect(
      (await getFieldValues(q, model, "aircraft", "aero.maxTakeoffKg")).values["F-16C_50"],
    ).toBe(19187);
    const cx0 = await getFieldValues(q, model, "weapons", "flight.aerodynamics.cx0");
    expect(Array.isArray(cx0.values.AIM_120C)).toBe(true);
    const curve = await getFieldValues(q, model, "aircraft", "flight.aerodynamics.table[].cx0");
    expect((curve.values["F-16C_50"] as { x: number[] }).x.length).toBeGreaterThan(5);
    const keyed = await keyedFieldPaths(q, model, "weapons");
    const impulse = keyed.find((k) => k.key === "flight.motorStages.*.impulseS");
    expect(impulse).toBeDefined();
    const stage = await getFieldValues(q, model, "weapons", impulse?.path ?? "");
    expect(Object.keys(stage.values).length).toBeGreaterThan(0);
    const env = await getFieldValues(q, model, "weapons", "flight.launchEnvelopes[].maxRangeM");
    expect(Object.keys(env.values).length).toBeGreaterThan(10);
    expect(valuesAt).toBeTypeOf("function");
  });

  it("searches across series with FTS5", async () => {
    const hits = await searchReference(q, "aim120c");
    expect(hits.some((h) => h.series === "weapons" && h.id === "AIM_120C")).toBe(true);
    const batumi = await searchReference(q, "batumi");
    expect(batumi[0]).toMatchObject({ series: "airbases", name: "Batumi" });
    expect(await searchReference(q, "  ")).toEqual([]);
  });
});
