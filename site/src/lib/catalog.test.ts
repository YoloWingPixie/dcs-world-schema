import { join } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { loadSchemaTypes } from "../../scripts/lib/schema";
import { nodeQuery } from "../../tests/reference/db";
import {
  buildSeriesCatalog,
  catalogKeyFor,
  companionRest,
  comparableValues,
  dcsKeyFromDescription,
  enumConstantLabel,
  rootFields,
  valuesAt,
  walkPath,
} from "./catalog";
import { loadModel, type Model, refResolver } from "./db/reference";
import { displayedNumber, pathLabel, plainValue, valuesDiffer } from "./format-field";
import { curveOf, surfacesOf } from "./record-tables";

/** The schema as written (types/entities), over the series the database lists. */
const types = loadSchemaTypes(join(__dirname, "../../../dcs-world-schema/types/entities"));
let model: Model;
beforeAll(async () => {
  model = await loadModel(nodeQuery());
});
const catalogOf = (series: string) => {
  const s = model.byId.get(series);
  if (!s) throw new Error(series);
  const comp = s.companion ? model.byId.get(s.companion) : undefined;
  return buildSeriesCatalog(
    types,
    series,
    { type: s.typeName, keyColumn: s.keyColumn },
    comp ? { type: comp.typeName, keyColumn: comp.keyColumn } : undefined,
    refResolver(model),
  );
};

describe("catalog from every entity schema", () => {
  it("has a root type for every series and catalogs each one", () => {
    for (const s of model.series) {
      expect(types[s.typeName]?.kind, s.typeName).toBe("record");
      const catalog = catalogOf(s.id);
      expect(Object.keys(catalog.entries).length, s.id).toBeGreaterThan(1);
    }
  });

  it("walks nested records, arrays of records, refs, enums and units", () => {
    const aircraft = catalogOf("aircraft");
    expect(aircraft.entries["aero.maxTakeoffKg"]).toMatchObject({ kind: "number", unit: "kg" });
    expect(aircraft.entries.stations).toMatchObject({
      kind: "records",
      recordType: "Entity.Station",
    });
    expect(aircraft.entries["stations[].accepts[].clsid"]).toMatchObject({
      kind: "ref",
      ref: ["stores"],
    });
    expect(aircraft.entries.sensors).toMatchObject({ kind: "strings", ref: ["sensors"] });
    expect(aircraft.entries.kind).toMatchObject({ kind: "enum", enumType: "Entity.AircraftKind" });
    expect(aircraft.enums["Entity.AircraftKind"]?.values.ROTARY).toBe("rotary");
    // The companion series' tables chart against Mach and compare as curves.
    const mach = expect.objectContaining({ kind: "column", field: "mach", label: "Mach" });
    expect(aircraft.entries["flight.aerodynamics.table"]?.axis).toEqual(mach);
    expect(aircraft.entries["flight.aerodynamics.table[].cx0"]).toMatchObject({
      compareAs: "curve",
      axis: mach,
    });
    // The axis column itself is no curve.
    expect(aircraft.entries["flight.aerodynamics.table[].mach"]?.axis).toBeUndefined();
  });

  it("gives a record field's unit to its unsuffixed members", () => {
    const vehicles = catalogOf("ground_vehicles");
    expect(vehicles.entries["weaponSystems[].slewRateRadS.yaw"]).toMatchObject({
      kind: "number",
      unit: "rad/s",
    });
    expect(vehicles.entries["mobility.maxSlopeRad"]?.unit).toBe("rad");
    expect(vehicles.entries["weaponSystems[].sectorsRad"]).toMatchObject({
      kind: "matrix",
      unit: "rad",
      layout: "sectors",
    });
    // Members with their own suffix, or under an unsuffixed record, keep their own.
    expect(vehicles.entries["detection.sensor.beamWidthRad"]?.unit).toBe("rad");
    expect(catalogOf("weapons").entries["flight.gimbal.yawMaxRad"]?.unit).toBe("rad");
  });

  it("keeps the weapon page's Mach tables, keyed motor stages and envelopes", () => {
    const weapons = catalogOf("weapons");
    expect(weapons.entries["flight.aerodynamics.cx0"]).toMatchObject({
      kind: "numbers",
      axis: { kind: "sampled", step: { field: "machStep", fallback: 0.2 }, label: "Mach" },
      label: "Zero-lift drag coefficient",
      dcsKey: "Cx0",
    });
    expect(weapons.entries["flight.motorStages.*.impulseS"]?.compareAs).toBe("value");
    expect(catalogKeyFor("flight.motorStages.march.impulseS", weapons)).toBe(
      "flight.motorStages.*.impulseS",
    );
    expect(weapons.entries["flight.launchEnvelopes[].maxRangeM"]).toMatchObject({
      kind: "grid",
      compareAs: "surfaces",
      axis: { kind: "surface", rows: "altitudesM", cols: "speedsMs" },
    });
    // Stored once, on the envelope table and each of its grids.
    expect(weapons.entries["flight.launchEnvelopes"]?.axis).toBe(
      weapons.entries["flight.launchEnvelopes[].maxRangeM"]?.axis,
    );
    expect(weapons.entries.categoryName?.kind).toBe("enum");
  });

  it("gives an axis its curves or grids, its axis paths and its row and column labels", () => {
    const table = catalogOf("aircraft").entries["flight.engine.table"]?.axis;
    expect(table).toEqual({
      kind: "column",
      table: "flight.engine.table",
      field: "mach",
      label: "Mach",
      path: "flight.engine.table[].mach",
      columns: ["flight.engine.table[].thrustMilitary", "flight.engine.table[].thrustAfterburner"],
    });
    const envelope = catalogOf("weapons").entries["flight.launchEnvelopes"]?.axis;
    expect(envelope).toEqual({
      kind: "surface",
      table: "flight.launchEnvelopes",
      rows: "altitudesM",
      cols: "speedsMs",
      paths: {
        rows: "flight.launchEnvelopes[].altitudesM",
        cols: "flight.launchEnvelopes[].speedsMs",
      },
      labels: { rows: "Altitude", cols: "Speed" },
      columns: [
        "flight.launchEnvelopes[].maxRangeM",
        "flight.launchEnvelopes[].minRangeM",
        "flight.launchEnvelopes[].aspectDeg",
      ],
    });
    expect(catalogOf("weapons").entries.flight?.axis).toBeUndefined();
  });

  it("marks each series' record key, and the companion's link back to its parent", () => {
    expect(catalogOf("aircraft").entries.id?.role).toBe("key");
    expect(catalogOf("stores").entries.clsid?.role).toBe("key");
    expect(catalogOf("stores").entries.id).toBeUndefined();
    expect(catalogOf("callsigns").entries.country?.role).toBe("key");
    expect(catalogOf("weapons").entries["flight.weapon"]?.role).toBe("key");
    // Only the key: other refs to the parent series are data.
    expect(catalogOf("weapons").entries.warhead?.role).toBeUndefined();
  });

  it("marks arrays whose items are one list each", () => {
    expect(catalogOf("aircraft").entries["gun.mounts[].mixes"]?.layout).toBe("list-per-item");
    expect(catalogOf("aircraft").entries.stations?.layout).not.toBe("list-per-item");
  });

  it("marks arrays whose items hold nested tables as cards", () => {
    const aircraft = catalogOf("aircraft");
    // Stations' items hold their accepted stores (records): one card per station.
    expect(aircraft.entries.stations?.layout).toBe("cards");
    expect(aircraft.entries["stations[].accepts"]?.layout).toBe("cards");
    // Items of scalars only, or with a layout of their own, are not cards.
    expect(catalogOf("weapons").entries["flight.motorStages"]?.layout).toBeUndefined();
    expect(aircraft.entries["gun.mounts[].mixes"]?.layout).toBe("list-per-item");
  });

  it("marks roles, layouts, Mach steps, list titles and unit conversions once", () => {
    const weapons = catalogOf("weapons");
    expect(weapons.entries.sourcePaths?.role).toBe("provenance");
    expect(weapons.entries.sourcePaths?.compareAs).toBeUndefined();
    expect(weapons.entries["flight.aerodynamics.sourcePath"]?.role).toBe("provenance");
    expect(weapons.entries.massKg?.role).toBeUndefined();
    expect(weapons.entries["flight.launchEnvelopes"]?.layout).toBe("envelope");
    expect(weapons.entries["flight.motorStages"]).toMatchObject({ keyField: "stage" });
    expect(weapons.entries["flight.motorStages"]?.layout).toBeUndefined();
    expect(weapons.entries["flight.aerodynamics.cx0"]?.axis).toMatchObject({
      kind: "sampled",
      step: { field: "machStep", fallback: 0.2 },
    });
    expect(weapons.entries["flight.aerodynamics.cxCoeff"]?.axis).toBeUndefined();
    const aircraft = catalogOf("aircraft");
    expect(aircraft.entries["flight.aerodynamics.table"]?.layout).toBe("axis-table");
    const vehicles = catalogOf("ground_vehicles");
    expect(vehicles.entries["weaponSystems[].payloads"]).toMatchObject({
      titleFields: ["ammoName", "ammoDisplayName"],
      countFields: ["ammoCapacity", "portionAmmoCapacity"],
    });
    // Units resolve per entry: a range in metres reads in nm, an altitude in ft.
    const range = Object.values(weapons.entries).find(
      (e) => e.unit === "m" && /range/i.test(e.name),
    );
    expect(range?.conversions?.imperial?.to).toBe("nm");
    expect(weapons.entries["flight.gimbal.yawMaxRad"]?.conversions).toMatchObject({
      metric: { to: "°" },
      imperial: { to: "°" },
    });
    expect(weapons.entries.massKg?.conversions).toMatchObject({
      metric: null,
      imperial: { to: "lb" },
    });
  });

  it("marks lists of ranges and the range record that bounds them", () => {
    const radios = catalogOf("radios");
    expect(radios.entries.segments).toMatchObject({
      layout: "ranges",
      rangePair: { min: "segments[].minMHz", max: "segments[].maxMHz" },
    });
    expect(radios.entries.range?.bounds).toBe("segments");
    expect(radios.entries.segments?.bounds).toBeUndefined();
    // Tables with more columns, keyed arrays and axis tables are no range lists.
    for (const catalog of [catalogOf("aircraft"), catalogOf("weapons"), catalogOf("airbases")]) {
      for (const e of Object.values(catalog.entries)) {
        if (e.layout === "ranges") expect(e.keyField ?? e.axis, e.path).toBeUndefined();
      }
    }
  });

  it("names a record by its root title fields", () => {
    expect(catalogOf("weapons").titleFields).toEqual(["displayName"]);
    expect(catalogOf("radios").titleFields).toEqual(["name"]);
    // `displayName` is a title, not the constant name of a `display` code.
    expect(catalogOf("weapons").entries.displayName?.codeField).toBeUndefined();
  });

  it("labels a nested record's title field, standing alone, as that record", () => {
    const aircraft = catalogOf("aircraft");
    const name = aircraft.entries["defaultTask.name"];
    expect(name?.label).toBe("Name");
    expect(name?.standaloneLabel).toBe("Default task");
    expect(name && pathLabel(name, name.path)).toBe("Default task");
    expect(aircraft.entries.displayName?.standaloneLabel).toBeUndefined();
    expect(aircraft.entries["defaultTask.id"]?.standaloneLabel).toBeUndefined();
  });

  it("marks the link of a list of records, and its lists of links", () => {
    const aircraft = catalogOf("aircraft");
    expect(aircraft.entries["stations[].accepts"]).toMatchObject({ linkField: "clsid" });
    const payloads = catalogOf("ground_vehicles").entries["weaponSystems[].payloads"];
    expect(payloads?.linkField).toBe("weapon");
    expect(payloads?.linkListFields).toContain("gunAmmo");
    expect(aircraft.entries.stations?.linkField).toBeUndefined();
  });

  it("marks asset paths and cleans descriptions", () => {
    expect(catalogOf("stores").entries.picture).toMatchObject({
      role: "asset",
      compareAs: "value",
    });
    expect(catalogOf("liveries").entries.path?.role).toBe("asset");
    expect(catalogOf("stores").entries.displayName?.role).toBeUndefined();
    const all = model.series.flatMap((s) => Object.values(catalogOf(s.id).entries));
    expect(all.filter((e) => /^Optional\s+\w/.test(e.description))).toEqual([]);
    expect(catalogOf("weapons").entries["flight.aerodynamics.cx0"]?.dcsKey).toBe("Cx0");
  });

  it("labels the companion's fields once", () => {
    expect(catalogOf("weapons").entries.flight?.label).toBe("Flight model");
  });

  it("reads values along paths, keyed arrays and axis tables", () => {
    const weapons = catalogOf("weapons");
    const data = { id: "X", massKg: 100 };
    const flight = {
      motorStages: [{ stage: "boost", impulseS: 200 }],
      aerodynamics: { cx0: [0.1, 0.2] },
    };
    const values = comparableValues(weapons, data, flight);
    expect(values).toContainEqual({ path: "massKg", key: "massKg", value: 100 });
    expect(values).toContainEqual({
      path: "flight.motorStages.boost.impulseS",
      key: "flight.motorStages.*.impulseS",
      value: 200,
    });
    const aircraft = catalogOf("aircraft");
    const entry = aircraft.entries["flight.aerodynamics.table[].cx0"];
    if (!entry) throw new Error("no entry");
    const curve = valuesAt(
      entry,
      aircraft,
      {},
      {
        aerodynamics: {
          table: [
            { mach: 0, cx0: 0.02 },
            { mach: 0.5, cx0: 0.021 },
          ],
        },
      },
    );
    expect(curve).toEqual([{ path: entry.path, value: { x: [0, 0.5], y: [0.02, 0.021] } }]);
  });

  it("walks list items by position and keyed items by key, skipping empty values", () => {
    const weapons = catalogOf("weapons");
    const flight = {
      sourcePath: "_G/a#/x",
      motorStages: [
        { stage: "boost", impulseS: 1, sourcePath: "_G/a#/b" },
        { stage: "march", impulseS: 2 },
      ],
      launchEnvelopes: [
        { sourcePath: "_G/a#/e1" },
        { sourcePath: null },
        { sourcePath: "_G/a#/e3" },
      ],
    };
    expect(walkPath(weapons, "flight.motorStages.*.impulseS", {}, flight)).toEqual([
      {
        holder: "flight.motorStages[0]",
        concretePath: "flight.motorStages.boost.impulseS",
        value: 1,
      },
      {
        holder: "flight.motorStages[1]",
        concretePath: "flight.motorStages.march.impulseS",
        value: 2,
      },
    ]);
    expect(walkPath(weapons, "flight.launchEnvelopes[].sourcePath", {}, flight)).toEqual([
      {
        holder: "flight.launchEnvelopes[0]",
        concretePath: "flight.launchEnvelopes[0].sourcePath",
        value: "_G/a#/e1",
      },
      {
        holder: "flight.launchEnvelopes[2]",
        concretePath: "flight.launchEnvelopes[2].sourcePath",
        value: "_G/a#/e3",
      },
    ]);
    expect(walkPath(weapons, "flight.sourcePath", {}, flight)).toEqual([
      { holder: "flight", concretePath: "flight.sourcePath", value: "_G/a#/x" },
    ]);
    expect(walkPath(weapons, "sourcePaths", { sourcePaths: [] }, flight)).toEqual([]);
    expect(walkPath(weapons, "flight.sourcePath", {}, undefined)).toEqual([]);
  });
});

describe("constant names and labels", () => {
  it("shows a code's constant name in its place, lists included", () => {
    const radios = catalogOf("radios");
    expect(radios.entries.modulationName).toMatchObject({
      kind: "strings",
      codeField: "modulation",
      label: "Modulation",
      enumType: "Entity.RadioModulation",
    });
    expect(radios.entries["segments[].modulationName"]).toMatchObject({
      kind: "enum",
      codeField: "modulation",
      label: "Modulation",
    });
    // Explicit labels still win: `categoryName` reads "Category", its code "Category code".
    expect(catalogOf("weapons").entries.categoryName).toMatchObject({
      label: "Category",
      codeField: "category",
    });
    expect(catalogOf("weapons").entries.category?.label).toBe("Category code");
  });

  it("never takes provenance for a DCS key", () => {
    expect(catalogOf("radios").entries.band?.dcsKey).toBeNull();
    expect(dcsKeyFromDescription("Optional `Head_Type`, the seeker head type code.")).toBe(
      "Head_Type",
    );
  });

  it("keeps acronyms in constant labels", () => {
    expect(enumConstantLabel("V/UHF")).toBe("V/UHF");
    expect(enumConstantLabel("UHF")).toBe("UHF");
    expect(enumConstantLabel("AIRDROME")).toBe("Airdrome");
  });
});

describe("refs", () => {
  it("resolves ref types to series, unit unions to every unit series", () => {
    const resolve = refResolver(model);
    expect(resolve("Entity.Store")).toEqual(["stores"]);
    expect(resolve("Entity.Aircraft | Entity.GroundVehicle | Entity.Ship")).toEqual([
      "aircraft",
      "ground_vehicles",
      "ships",
    ]);
    // A companion's records live on its parent's pages.
    expect(resolve("Entity.WeaponFlight")).toEqual(["weapons"]);
  });
});

describe("table curves and envelope surfaces", () => {
  it("keep x and y aligned, skipping rows without a number in both", () => {
    const rows = [
      { mach: 0, cx0: 0.02 },
      { mach: 0.5 },
      { mach: 1, cx0: "x" },
      7,
      { mach: 2, cx0: 0.03 },
    ];
    expect(curveOf(rows, "mach", "cx0")).toEqual({ x: [0, 2], y: [0.02, 0.03] });
    expect(curveOf([{ mach: 1 }], "mach", "cx0")).toBeNull();
    expect(curveOf(undefined, "mach", "cx0")).toBeNull();
  });

  it("are what valuesAt gives a record for the column or grid", () => {
    const aircraft = catalogOf("aircraft");
    const cx0 = aircraft.entries["flight.aerodynamics.table[].cx0"];
    if (cx0?.axis?.kind !== "column") throw new Error("no axis column");
    const table = [{ mach: 0, cx0: 0.02 }, { mach: 0.5 }, { mach: 1, cx0: 0.04 }];
    expect(valuesAt(cx0, aircraft, {}, { aerodynamics: { table } })).toEqual([
      { path: cx0.path, value: curveOf(table, cx0.axis.field, cx0.name) },
    ]);

    const weapons = catalogOf("weapons");
    const grid = Object.values(weapons.entries).find(
      (e) => e.axis?.kind === "surface" && e.kind !== "records",
    );
    if (grid?.axis?.kind !== "surface") throw new Error("no surface grid");
    const { rows, cols } = grid.axis;
    const items = [
      { [rows]: [1, 2], [cols]: [3], [grid.name]: [[5], [6]] },
      { [rows]: [1], [cols]: [3] },
      { [rows]: [4], [cols]: [3, 4], [grid.name]: [[7, 8]] },
    ];
    const surfaces = surfacesOf(items, grid.axis, grid.name);
    expect(surfaces).toEqual([
      { rows: [1, 2], cols: [3], z: [[5], [6]] },
      { rows: [4], cols: [3, 4], z: [[7, 8]] },
    ]);
    const flight = { [grid.axis.table.slice("flight.".length)]: items };
    expect(valuesAt(grid, weapons, {}, flight)).toEqual([{ path: grid.path, value: surfaces }]);
  });
});

describe("compare shapes", () => {
  it("marks each comparable entry with the shape of its value, and only those", () => {
    const aircraft = catalogOf("aircraft");
    const weapons = catalogOf("weapons");
    expect(aircraft.entries["aero.maxTakeoffKg"]?.compareAs).toBe("value");
    // A plain number list is one value; a ref list too.
    expect(weapons.entries["flight.aerodynamics.cxCoeff"]?.compareAs).toBe("value");
    expect(aircraft.entries.sensors?.compareAs).toBe("value");
    expect(weapons.entries["flight.aerodynamics.cx0"]?.compareAs).toBe("samples");
    // A table column is a number per row, but compares as one curve over the table.
    expect(aircraft.entries["flight.aerodynamics.table[].cx0"]).toMatchObject({
      kind: "number",
      compareAs: "curve",
    });
    expect(weapons.entries["flight.launchEnvelopes[].maxRangeM"]?.compareAs).toBe("surfaces");
    // Tables, axis columns, provenance and list items do not compare.
    expect(aircraft.entries["flight.aerodynamics.table"]?.compareAs).toBeUndefined();
    expect(aircraft.entries["flight.aerodynamics.table[].mach"]?.compareAs).toBeUndefined();
    expect(weapons.entries.sourcePaths?.compareAs).toBeUndefined();
    expect(aircraft.entries["stations[].accepts[].clsid"]?.compareAs).toBeUndefined();
  });

  it("tells apart curves whose summaries match", () => {
    const aircraft = catalogOf("aircraft");
    const path = "flight.aerodynamics.table[].cx0";
    const entry = aircraft.entries[path];
    if (!entry) throw new Error(path);
    const curve = (mid: number) => ({
      aerodynamics: {
        table: [
          { mach: 0, cx0: 0.2 },
          { mach: 0.5, cx0: mid },
          { mach: 1, cx0: 0.9 },
        ],
      },
    });
    const curveValue = (companion: object) =>
      comparableValues(aircraft, {}, companion as Record<string, unknown>).find(
        (v) => v.path === path,
      )?.value;
    const [a, b, c] = [curveValue(curve(0.3)), curveValue(curve(0.4)), curveValue(curve(0.3))];
    const vctx = { enums: {}, system: "metric" as const };
    // Same count and range: the same text, but different curves.
    expect(plainValue(entry, a, vctx)).toBe(plainValue(entry, b, vctx));
    const number = displayedNumber(entry, "metric");
    expect(valuesDiffer([a, b], number)).toBe(true);
    expect(valuesDiffer([a, c], number)).toBe(false);
    // A missing value differs from a present one; two missing ones do not.
    expect(valuesDiffer([a, undefined])).toBe(true);
    expect(valuesDiffer([undefined, undefined])).toBe(false);
  });
});

describe("root fields", () => {
  it("are the root type's fields in schema order, without the companion's", () => {
    for (const s of model.series) {
      const catalog = catalogOf(s.id);
      const fields = rootFields(catalog);
      expect(fields.map((e) => e.name)).toEqual(
        (types[s.typeName]?.fields ? Object.keys(types[s.typeName]?.fields ?? {}) : []).filter(
          (n) => n !== "_source",
        ),
      );
      for (const e of fields) expect(e.path).toBe(e.name);
    }
    expect(rootFields(catalogOf("weapons")).some((e) => e.path.startsWith("flight"))).toBe(false);
  });

  it("splits companion paths from the record's own", () => {
    expect(companionRest("flight")).toBe("");
    expect(companionRest("flight.aerodynamics.cx0")).toBe("aerodynamics.cx0");
    expect(companionRest("flightCeiling")).toBeNull();
    expect(companionRest("aero.massKg")).toBeNull();
  });
});
