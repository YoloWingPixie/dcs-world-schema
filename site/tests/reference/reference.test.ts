import { beforeAll, describe, expect, it } from "vitest";
import {
  catalogFor,
  getFieldValues,
  getGroupTargets,
  getRecord,
  getSeriesIndex,
  keyedFieldPaths,
  loadModel,
  type Model,
  referencedByGroup,
  storageOf,
} from "../../src/lib/db/reference";
import { refName } from "../../src/lib/format-field";
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
      compareAs: "curve",
      axis: { kind: "column", field: "mach", label: "Mach" },
    });
    const weapons = catalogFor(model, "weapons");
    expect(weapons.entries["flight.aerodynamics.cx0"]).toMatchObject({
      kind: "numbers",
      axis: { kind: "sampled", label: "Mach" },
    });
    expect(weapons.entries["flight.launchEnvelopes[].maxRangeM"]?.axis).toMatchObject({
      kind: "surface",
      rows: "altitudesM",
      cols: "speedsMs",
    });
    expect(weapons.titleFields).toEqual(["displayName"]);
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

  it("lists one whole referenced-by group, direct or second hop, named as on the page", async () => {
    const doc = await getRecord(q, model, "weapons", "AIM_120C");
    for (const [from, path] of [
      ["stores", "delivers[].weapon"],
      ["aircraft", "via:stores"],
    ] as const) {
      const shown = doc?.referencedBy.find((g) => g.series === from && g.path === path);
      const all = await referencedByGroup(q, model, "weapons", "AIM_120C", from, path, shown?.via);
      expect(all.length).toBe(shown?.total ?? shown?.records.length);
      const names = new Map(all);
      for (const [id, name] of shown?.records ?? []) expect(names.get(id)).toBe(name);
    }
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

describe("browse and compare", () => {
  it("browses a series from its scalar columns with facets", async () => {
    const index = await getSeriesIndex(q, model, "stores");
    expect(index.count).toBe(model.byId.get("stores")?.count);
    expect(index.facets.map((f) => f.path)).toContain("kind");
    const row = index.rows.find((r) => r[0] === "{5CE2FF2A-645A-4197-B48D-8720AC69394F}");
    expect(row?.[1]).toBe("AIM-9X Sidewinder IR AAM");
  });

  it("uses the facets and columns configured for a series", async () => {
    const index = await getSeriesIndex(q, model, "beacons");
    expect(index.facets.map((f) => f.path)).toEqual(["typeName", "theatre"]);
    expect(index.visible).toEqual(["typeName", "theatre", "callsign", "frequencyHz", "channel"]);
  });

  it("keeps ref columns' ids, naming their records in a link table per column", async () => {
    const index = await getSeriesIndex(q, model, "beacons");
    const catalog = catalogFor(model, "beacons");
    const at = 2 + index.columns.indexOf("airbase");
    const row = index.rows.find((r) => r[at] === "Afghanistan.10");
    expect(row).toBeDefined();
    const entry = catalog.entries.airbase;
    if (!entry) throw new Error("no airbase");
    expect(refName(entry, row?.[at], index.links.airbase)).toBe("Camp Bastion");
    expect(index.links.callsign).toBeUndefined();
  });

  it("reads one field across records: columns, nested JSON, keyed and axis paths", async () => {
    expect((await getFieldValues(q, model, "weapons", "massKg")).AIM_120C).toBeCloseTo(161.48);
    expect((await getFieldValues(q, model, "aircraft", "aero.maxTakeoffKg"))["F-16C_50"]).toBe(
      19187,
    );
    // A Mach-sampled list: a curve over Mach at the record's own step, else DCS's 0.2.
    const cx0 = await getFieldValues(q, model, "weapons", "flight.aerodynamics.cx0");
    const machs = (id: string) => (cx0[id] as { x: number[] }).x.slice(0, 3);
    expect(machs("AIM_120C")).toEqual([0, 0.2, 0.4]);
    expect(machs("AGM_84H")).toEqual([0, 0.1, 0.2]);
    const curve = await getFieldValues(q, model, "aircraft", "flight.aerodynamics.table[].cx0");
    expect((curve["F-16C_50"] as { x: number[] }).x.length).toBeGreaterThan(5);
    const keyed = await keyedFieldPaths(q, model, "weapons");
    const impulse = keyed.find((k) => k.key === "flight.motorStages.*.impulseS");
    expect(impulse).toBeDefined();
    const stage = await getFieldValues(q, model, "weapons", impulse?.path ?? "");
    expect(Object.keys(stage).length).toBeGreaterThan(0);
    const env = await getFieldValues(q, model, "weapons", "flight.launchEnvelopes[].maxRangeM");
    expect(Object.keys(env).length).toBeGreaterThan(10);
  });

  it("reads every storage alike: an empty list is no value, a join keeps list order", async () => {
    expect(storageOf(model, "liveries", "unitTypes")?.ref?.table).toBe("liveries__unitTypes");
    expect(storageOf(model, "beacons", "theatre")?.ref?.table).toBe("beacons");
    expect(storageOf(model, "weapons", "flight.aerodynamics.cx0")).toMatchObject({
      table: "weapon_flight",
      column: "aerodynamics",
      json: "$.cx0",
      ref: null,
    });
    // A plain column, nested JSON and a join table: no record holds an empty list.
    for (const [series, path] of [
      ["liveries", "countries"],
      ["aircraft", "attributes"],
      ["aircraft", "sensors"],
    ] as const) {
      const values = await getFieldValues(q, model, series, path);
      expect(Object.values(values).some((v) => Array.isArray(v) && v.length === 0)).toBe(false);
    }
    const values = await getFieldValues(q, model, "aircraft", "attributes");
    const doc = await getRecord(q, model, "aircraft", "F-16C_50");
    expect(values["F-16C_50"]).toEqual(doc?.data.attributes);
  });

  it("carries the configured paths outside its columns, as one field's read gives them", async () => {
    for (const [series, paths] of [
      ["aircraft", ["aero.maxTakeoffKg", "attributes", "defaultTask.name", "performance.machMax"]],
      ["weapons", ["flight.machMax"]],
      ["stores", ["aero.dragIndex", "aero.massKg"]],
    ] as const) {
      const index = await getSeriesIndex(q, model, series);
      expect(Object.keys(index.fields).sort()).toEqual([...paths]);
      for (const path of paths) {
        expect(index.fields[path]?.values, `${series} ${path}`).toEqual(
          await getFieldValues(q, model, series, path),
        );
      }
    }
    const aircraft = await getSeriesIndex(q, model, "aircraft");
    const attributes = aircraft.fields.attributes;
    const ids = attributes?.values["F-16C_50"] as string[];
    expect(ids).toEqual((await getRecord(q, model, "aircraft", "F-16C_50"))?.data.attributes);
    for (const id of ids) expect(attributes?.links.attributes?.[id], id).toBeTruthy();
  });
});

describe("group targets", () => {
  it("resolves each livery's airframe through the unitTypes join table", async () => {
    const targets = await getGroupTargets(q, model, "liveries", "unitTypes");
    const [id, target] =
      Object.entries(targets).find(([, t]) => t[0] === "aircraft" && t[1] === "F-16C_50") ?? [];
    expect(id).toMatch(/F-16C_50/);
    expect(target?.[2]).not.toBe("");
    expect(Object.values(targets).some((t) => t[0] === "ground_vehicles")).toBe(true);
    expect(Object.keys(targets).length).toBeGreaterThan(1000);
  });

  it("resolves a scalar ref and ignores a non-ref path", async () => {
    const beacons = await getGroupTargets(q, model, "beacons", "theatre");
    expect(Object.values(beacons)[0]?.[0]).toBe("theatres");
    expect(await getGroupTargets(q, model, "liveries", "entryPoint")).toEqual({});
  });
});
