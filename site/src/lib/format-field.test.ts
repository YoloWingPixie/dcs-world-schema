import { describe, expect, it } from "vitest";
import {
  coverageText,
  isAngleSectors,
  plainValue,
  rangePair,
  rangeText,
  sectorRanges,
  storedValue,
} from "./format-field";
import { enumDisplay } from "./names";
import type { CatalogEntry } from "./types";

const entry = (over: Partial<CatalogEntry>): CatalogEntry => ({
  path: "x",
  name: "x",
  label: "X",
  type: "number",
  kind: "number",
  unit: null,
  unitNotStated: false,
  description: "",
  dcsKey: null,
  owner: "Entity.Test",
  comparable: false,
  ...over,
});

const vctx = (system: "metric" | "imperial") => ({ enums: {}, system });
const rad = (deg: number) => (deg * Math.PI) / 180;

const sectors = entry({
  path: "weaponSystems[].sectorsRad",
  name: "sectorsRad",
  type: "Entity.AngleSector[]",
  kind: "matrix",
  unit: "rad",
});
// T-72B's main gun: two sectors as DCS stores them.
const t72 = [
  [rad(145), rad(-145), rad(-4), rad(14)],
  [rad(-145), rad(145), rad(3.5), rad(14)],
];

describe("traverse sectors", () => {
  it("recognises AngleSector arrays only", () => {
    expect(isAngleSectors(sectors, t72)).toBe(true);
    expect(isAngleSectors(sectors, [[rad(90), rad(-170)]])).toBe(true);
    expect(isAngleSectors(sectors, [[1, 2, 3]])).toBe(false);
    expect(isAngleSectors({ ...sectors, type: "Entity.ArmourRow[]" }, t72)).toBe(false);
  });

  it("shows each sector as degree ranges in both systems", () => {
    for (const system of ["metric", "imperial"] as const) {
      expect(sectorRanges(sectors, t72, system)).toEqual([
        { azimuth: "145° to -145°", elevation: "-4° to 14°" },
        { azimuth: "-145° to 145°", elevation: "3.5° to 14°" },
      ]);
    }
    expect(sectorRanges(sectors, [[rad(90), rad(-170)]], "metric")).toEqual([
      { azimuth: "90° to -170°", elevation: null },
    ]);
  });

  it("copies as degrees and keeps the radians as the stored form", () => {
    expect(plainValue(sectors, t72, vctx("metric"))).toBe(
      "azimuth 145° to -145°, elevation -4° to 14°; azimuth -145° to 145°, elevation 3.5° to 14°",
    );
    expect(storedValue(sectors, t72, "metric")).toBe(
      "[2.531, -2.531, -0.0698, 0.2443], [-2.531, 2.531, 0.0611, 0.2443] rad",
    );
  });
});

describe("stored values", () => {
  it("gives the stored radians in metric, metric units only in imperial", () => {
    const fov = entry({ name: "fovRad", unit: "rad" });
    const mass = entry({ name: "massKg", unit: "kg" });
    expect(plainValue(fov, rad(20), vctx("metric"))).toBe("20°");
    expect(storedValue(fov, 0.3491, "metric")).toBe("0.3491 rad");
    expect(storedValue(mass, 161.48, "metric")).toBeNull();
    expect(storedValue(mass, 161.48, "imperial")).toBe("161.48 kg");
  });
});

describe("ranges", () => {
  const min = entry({ path: "segments[].minMHz", name: "minMHz", unit: "MHz" });
  const max = entry({ path: "segments[].maxMHz", name: "maxMHz", unit: "MHz" });
  const catalog = {
    types: { "Entity.RadioSegment": { description: "", fields: ["minMHz", "maxMHz", "x"] } },
    entries: { [min.path]: min, [max.path]: max },
  };

  it("finds a type's min/max pair", () => {
    expect(rangePair(catalog, "Entity.RadioSegment", "segments[]")).toEqual({ min, max });
    expect(rangePair(catalog, "Entity.Other", "segments[]")).toBeNull();
  });

  it("writes one range or the coverage of several", () => {
    const pair = { min, max };
    expect(rangeText(pair, { minMHz: 100, maxMHz: 150 }, "metric")).toBe("100–150 MHz");
    expect(rangeText(pair, { minMHz: 100 }, "metric")).toBeNull();
    const rows = [
      { minMHz: 100, maxMHz: 150 },
      { minMHz: 220, maxMHz: 390 },
    ];
    expect(coverageText(pair, rows, "imperial")).toBe("100–150, 220–390 MHz");
  });
});

describe("enum labels", () => {
  it("shows one form when label and code differ only in case", () => {
    const band = entry({ name: "band", kind: "enum", enumType: "Entity.RadioBand" });
    expect(enumDisplay(band, "V/UHF", {})).toEqual({
      label: "V/UHF",
      raw: "V/UHF",
      rewrite: false,
    });
    expect(enumDisplay(band, "AIRDROME", {})).toMatchObject({ label: "Airdrome", raw: "Airdrome" });
  });

  it("shows the code beside a label only when the label rewrites it", () => {
    const e = entry({ name: "x", kind: "enum" });
    expect(enumDisplay(e, "MODULATION_AM", {})).toMatchObject({ label: "AM", rewrite: false });
    expect(enumDisplay(e, "BEACON_TYPE_VOR_DME", {})).toMatchObject({ rewrite: false });
    expect(enumDisplay(e, "wsType_AA_Missile", {})).toMatchObject({
      label: "Air-to-air missile",
      rewrite: true,
    });
    expect(enumDisplay(e, "OPTIC_SENSOR_IR", {})).toMatchObject({
      label: "Infrared",
      rewrite: true,
    });
    expect(plainValue(e, "MODULATION_AM", vctx("metric"))).toBe("AM");
    expect(plainValue(e, "OPTIC_SENSOR_IR", vctx("metric"))).toBe("Infrared (OPTIC_SENSOR_IR)");
    // The code stays in the tooltip and field menu as the stored form.
    expect(storedValue(e, "MODULATION_AM", "metric", {})).toBe("MODULATION_AM");
    expect(storedValue(e, "AIRDROME", "metric", {})).toBeNull();
  });

  it("lists constant names by their labels", () => {
    const names = entry({ name: "modulationName", kind: "strings", codeField: "modulation" });
    expect(plainValue(names, ["MODULATION_AM", "MODULATION_FM"], vctx("metric"))).toBe("AM, FM");
  });
});
