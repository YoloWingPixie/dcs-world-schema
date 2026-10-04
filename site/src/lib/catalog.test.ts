import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadSchemaTypes } from "../../scripts/lib/schema";
import { buildSeriesCatalog, catalogKeyFor, comparableValues, valuesAt } from "./catalog";
import { pack, unpack } from "./pack";
import { BROWSABLE_SERIES, SERIES, SERIES_BY_ID, seriesForRef } from "./series";

const types = loadSchemaTypes(join(__dirname, "../../../dcs-world-schema/types/entities"));
const catalogOf = (series: string) => {
  const info = SERIES_BY_ID.get(series);
  if (!info) throw new Error(series);
  const comp = info.companion ? SERIES_BY_ID.get(info.companion) : undefined;
  return buildSeriesCatalog(types, series, info.type, comp ? { type: comp.type } : undefined);
};

describe("catalog from every entity schema", () => {
  it("has a root type for every series and catalogs each one", () => {
    for (const s of SERIES) {
      expect(types[s.type]?.kind, s.type).toBe("record");
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
      comparable: false,
    });
    expect(aircraft.entries.sensors).toMatchObject({ kind: "strings", ref: ["sensors"] });
    expect(aircraft.entries.kind).toMatchObject({ kind: "enum", enumType: "Entity.AircraftKind" });
    expect(aircraft.enums["Entity.AircraftKind"]?.values.ROTARY).toBe("rotary");
    // The companion series' tables chart against Mach and compare as curves.
    expect(aircraft.entries["flight.aerodynamics.table"]?.axis).toBe("mach");
    expect(aircraft.entries["flight.aerodynamics.table[].cx0"]).toMatchObject({
      comparable: true,
      axis: "mach",
    });
  });

  it("keeps the weapon page's Mach tables, keyed motor stages and envelopes", () => {
    const weapons = catalogOf("weapons");
    expect(weapons.entries["flight.aerodynamics.cx0"]).toMatchObject({
      kind: "numbers",
      axis: "mach",
      label: "Zero-lift drag coefficient",
      dcsKey: "Cx0",
    });
    expect(weapons.entries["flight.motorStages.*.impulseS"]?.comparable).toBe(true);
    expect(catalogKeyFor("flight.motorStages.march.impulseS", weapons)).toBe(
      "flight.motorStages.*.impulseS",
    );
    expect(weapons.entries["flight.launchEnvelopes[].maxRangeM"]).toMatchObject({
      kind: "grid",
      comparable: true,
      axis: "grid:altitudesM,speedsMs",
    });
    expect(weapons.entries.categoryName?.kind).toBe("enum");
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
});

describe("refs", () => {
  it("resolves ref types to series, unit unions to every unit series", () => {
    expect(seriesForRef("Entity.Store")).toEqual(["stores"]);
    expect(seriesForRef("Entity.Aircraft | Entity.GroundVehicle | Entity.Ship")).toEqual([
      "aircraft",
      "ground_vehicles",
      "ships",
    ]);
  });

  it("every browsable series is a page; companions are not", () => {
    expect(BROWSABLE_SERIES.map((s) => s.id)).not.toContain("weapon_flight");
    expect(BROWSABLE_SERIES.map((s) => s.id)).toContain("airbases");
  });
});

describe("transport packing", () => {
  it("round-trips arrays of records, nested scalar objects included", () => {
    const value = {
      stands: [
        { name: "1", limits: { maxHeightM: 18, shelter: false }, position: { x: 1, z: 2 } },
        { name: "2", limits: { maxHeightM: 20, shelter: true } },
        { name: "3", position: { x: 5, z: 6 }, tags: ["a"] },
      ],
      plain: [1, 2, 3],
    };
    const packed = pack(value) as { stands: { $c: unknown[] } };
    expect(packed.stands.$c).toContainEqual(["limits", "maxHeightM"]);
    expect(unpack(JSON.parse(JSON.stringify(packed)))).toEqual(value);
  });
});
