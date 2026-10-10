import { describe, expect, it } from "vitest";
import {
  compareKey,
  coverageText,
  displayedNumber,
  isAngleSectors,
  plainValue,
  rangeText,
  refName,
  sectorRanges,
  storedValue,
  surfaceAxes,
  valuesDiffer,
} from "./format-field";
import { present } from "./json";
import { enumDisplay } from "./names";
import type { CatalogEntry } from "./types";

const entry = (over: Partial<CatalogEntry>): CatalogEntry => ({
  path: "x",
  name: "x",
  label: "X",
  kind: "number",
  unit: null,
  unitNotStated: false,
  description: "",
  dcsKey: null,
  ...over,
});

const vctx = (system: "metric" | "imperial") => ({ enums: {}, system });
const rad = (deg: number) => (deg * Math.PI) / 180;

const sectors = entry({
  path: "weaponSystems[].sectorsRad",
  name: "sectorsRad",
  kind: "matrix",
  unit: "rad",
  layout: "sectors",
});
// T-72B's main gun: two sectors as DCS stores them.
const t72 = [
  [rad(145), rad(-145), rad(-4), rad(14)],
  [rad(-145), rad(145), rad(3.5), rad(14)],
];

describe("traverse sectors", () => {
  it("recognises sector-shaped values of `sectors` fields only", () => {
    expect(isAngleSectors(sectors, t72)).toBe(true);
    expect(isAngleSectors(sectors, [[rad(90), rad(-170)]])).toBe(true);
    expect(isAngleSectors(sectors, [[1, 2, 3]])).toBe(false);
    expect(isAngleSectors({ ...sectors, layout: "envelope" }, t72)).toBe(false);
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

describe("compare keys", () => {
  it("compare deep values, object keys in any order, numbers as the display rounds them", () => {
    expect(compareKey({ x: [0, 0.5], y: [0.123456, 2] })).toBe(
      compareKey({ y: [0.12346, 2], x: [0, 0.5] }),
    );
    expect(compareKey({ x: [0, 0.5], y: [0.1234, 2] })).not.toBe(
      compareKey({ x: [0, 0.5], y: [0.1244, 2] }),
    );
    // A number and its text are not the same value.
    expect(compareKey(1)).not.toBe(compareKey("1"));
    expect(compareKey([[1, 2]])).not.toBe(compareKey([[2, 1]]));
  });

  it("round numbers as the display shows them", () => {
    const angle = entry({ name: "fovRad", unit: "rad" });
    const deg = displayedNumber(angle, "metric");
    // 0.349 rad and 0.3491 rad both read "20°".
    expect(deg(0.349)).toBe(deg(0.3491));
    expect(valuesDiffer([0.349, 0.3491], deg)).toBe(false);
    expect(valuesDiffer([0.349, 0.3491])).toBe(true);
  });

  it("flag values that differ, a missing one among them", () => {
    expect(valuesDiffer([1, 1.00001])).toBe(false);
    expect(valuesDiffer([1, 2])).toBe(true);
    expect(valuesDiffer([1, undefined])).toBe(true);
    expect(valuesDiffer([[1, 2]])).toBe(false);
  });
});

describe("ref names", () => {
  const ref = entry({ kind: "ref", ref: ["theatres", "airbases"] });
  const links = {
    airbases: { "Caucasus.18": "Sochi-Adler" },
    theatres: { Caucasus: ["Caucasus", "The Caucasus"] as [string, string] },
  };
  it("name the record a ref value points at, from the link table", () => {
    expect(refName(ref, "Caucasus.18", links)).toBe("Sochi-Adler");
    expect(refName(ref, "Caucasus", links)).toBe("The Caucasus");
  });
  it("fall back to the value as written", () => {
    expect(refName(ref, "Nevada", links)).toBe("Nevada");
    expect(refName(ref, 7, undefined)).toBe("7");
    // A series the entry does not ref is not read.
    expect(refName(entry({ kind: "ref", ref: ["aircraft"] }), "Caucasus.18", links)).toBe(
      "Caucasus.18",
    );
  });
});

describe("present", () => {
  it("counts any value but absent, null and an empty list", () => {
    for (const v of [0, "", false, [0], {}]) expect(present(v)).toBe(true);
    for (const v of [undefined, null, []]) expect(present(v)).toBe(false);
  });
});

describe("surface axes", () => {
  const catalog = {
    entries: {
      "env[].altitudesM": entry({ path: "env[].altitudesM", label: "Altitudes", unit: "m" }),
      "env[].speedsMs": entry({ path: "env[].speedsMs", label: "Speeds", unit: "m/s" }),
    },
  };
  const axis = {
    kind: "surface" as const,
    table: "env",
    rows: "altitudesM",
    cols: "speedsMs",
    paths: { rows: "env[].altitudesM", cols: "env[].speedsMs" },
    labels: { rows: "Altitude", cols: "Speed" },
    columns: [],
  };
  it("label an envelope's axis entries for one value, keeping their units", () => {
    const axes = surfaceAxes(catalog, axis);
    expect(axes?.rows).toMatchObject({ label: "Altitude", unit: "m" });
    expect(axes?.cols).toMatchObject({ label: "Speed", unit: "m/s" });
    // The catalog's own entries keep their labels.
    expect(catalog.entries["env[].altitudesM"].label).toBe("Altitudes");
  });
  it("are null for another axis, or without the axis fields", () => {
    expect(surfaceAxes(catalog, undefined)).toBeNull();
    expect(
      surfaceAxes(catalog, { kind: "sampled", step: { field: "s", fallback: 0.2 }, label: "Mach" }),
    ).toBeNull();
    expect(surfaceAxes({ entries: {} }, axis)).toBeNull();
  });
});
