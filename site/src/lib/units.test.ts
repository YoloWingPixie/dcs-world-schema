import { describe, expect, it } from "vitest";
import {
  convertValue,
  displayUnit,
  formatNumber,
  formatPlain,
  formatStored,
  formatWithUnit,
  isSentinelAngle,
  roundSignificant,
  stripUnitSuffix,
  unitFor,
  unitGap,
  withUnit,
} from "./units";

describe("units from field-name suffixes", () => {
  it("reads the schema's suffix convention", () => {
    expect(unitFor("massKg")).toBe("kg");
    expect(unitFor("rangeMaxM")).toBe("m");
    expect(unitFor("workTimeS")).toBe("s");
    expect(unitFor("finDeflectionMaxRad")).toBe("rad");
    expect(unitFor("rangeKm")).toBe("km");
    expect(unitFor("gimbalAzimuthMaxDeg")).toBe("°");
    expect(unitFor("navigationGain")).toBeNull();
  });

  it("knows the few units stated only in prose", () => {
    expect(unitFor("machMax")).toBe("Mach");
    expect(unitFor("gLoadLimit")).toBe("g");
  });

  it("strips the suffix for labels", () => {
    expect(stripUnitSuffix("fuelMassKg")).toBe("fuelMass");
    expect(stripUnitSuffix("cx0")).toBe("cx0");
  });
});

describe("number formatting", () => {
  it("trims trailing zeros and keeps small coefficients readable", () => {
    expect(formatNumber(161.48)).toBe("161.48");
    expect(formatNumber(0.2)).toBe("0.2");
    expect(formatNumber(-0.0024)).toBe("-0.0024");
    expect(formatNumber(8e-5)).toBe("8.00e-5");
    expect(formatNumber(61000)).toBe("61,000");
    expect(formatNumber(4)).toBe("4");
  });

  it("writes plain strings with units", () => {
    expect(formatPlain(161.48, "kg")).toBe("161.48 kg");
    expect(formatPlain(60, "°")).toBe("60°");
    expect(formatPlain(4, "Mach")).toBe("Mach 4");
  });
});

describe("metric / imperial conversion", () => {
  const imp = (v: number, unit: string | null, name?: string) =>
    convertValue(v, unit, "imperial", name);

  it("converts each metric unit to its imperial pair", () => {
    expect(imp(161.48, "kg")).toMatchObject({ unit: "lb", value: 356 });
    expect(imp(61, "km")).toMatchObject({ unit: "nm", value: 32.94 });
    expect(imp(15240, "m", "hMaxM")).toMatchObject({ unit: "ft", value: 50000 });
    expect(imp(61000, "m", "rangeMaxM")).toMatchObject({ unit: "nm", value: 32.94 });
    expect(imp(300, "m/s", "vOptMs")).toMatchObject({ unit: "kt", value: 583.2 });
    expect(imp(10, "m/s", "climbRateMs")).toMatchObject({ unit: "ft/min", value: 1969 });
    expect(imp(2120.04, "km/h")).toMatchObject({ unit: "kt", value: 1145 });
    expect(imp(28, "m²")).toMatchObject({ unit: "ft²", value: 301.4 });
    expect(imp(1000, "N")).toMatchObject({ unit: "lbf", value: 224.8 });
    expect(imp(100, "kgf")).toMatchObject({ unit: "lbf", value: 220.5 });
  });

  it("never converts degrees, time, Mach, g, frequencies, calibres or unknown units", () => {
    for (const unit of ["°", "°/s", "s", "Mach", "g", "Hz", "MHz", "mm", "rpm", null, "parsec"]) {
      expect(imp(12.5, unit)).toEqual({ value: 12.5, unit, converted: false });
    }
  });

  it("leaves metric untouched and keeps sensible precision", () => {
    expect(convertValue(161.48, "kg", "metric")).toEqual({
      value: 161.48,
      unit: "kg",
      converted: false,
    });
    expect(roundSignificant(355.99977, 4)).toBe(356);
    expect(formatPlain(161.48, "kg", "imperial")).toBe("356 lb");
    expect(formatWithUnit(161.48, "kg", "imperial").stored).toBe("161.48 kg");
  });

  it("reads the new suffixes", () => {
    expect(unitFor("rollRateMaxRadS")).toBe("rad/s");
    expect(unitFor("slewRateDegS")).toBe("°/s");
    expect(unitFor("maxSpeedKmh")).toBe("km/h");
    expect(unitFor("v0Ms")).toBe("m/s");
    expect(unitFor("wingAreaM2")).toBe("m²");
    expect(unitFor("caliberMm")).toBe("mm");
    expect(unitFor("frequencyHz")).toBe("Hz");
    expect(unitFor("minMHz")).toBe("MHz");
  });
});

describe("radians shown as degrees", () => {
  it("converts rad and rad/s to degrees in both systems", () => {
    for (const system of ["metric", "imperial"] as const) {
      expect(convertValue(Math.PI / 9, "rad", system, "fovRad")).toEqual({
        value: 20,
        unit: "°",
        converted: true,
      });
      expect(convertValue(1.5, "rad/s", system, "rollRateMaxRadS")).toEqual({
        value: 85.94,
        unit: "°/s",
        converted: true,
      });
      expect(displayUnit("rad", system)).toBe("°");
      expect(displayUnit("rad/s", system)).toBe("°/s");
    }
  });

  it("rounds away float noise from DCS's own approximations", () => {
    expect(convertValue(Math.PI, "rad", "metric").value).toBe(180);
    expect(convertValue(0.785, "rad", "metric").value).toBe(44.98);
    expect(convertValue(-0.5236, "rad", "metric").value).toBe(-30);
    expect(convertValue(0.0017, "rad", "metric").value).toBe(0.0974);
  });

  it("formats degrees without a space and keeps the radian value as the stored form", () => {
    const f = formatWithUnit(Math.PI / 9, "rad", "metric", "fovRad");
    expect(f).toMatchObject({ text: "20", unit: "°", stored: "0.3491 rad" });
    expect(formatPlain(Math.PI / 9, "rad")).toBe("20°");
    expect(formatPlain(1.5, "rad/s", "imperial")).toBe("85.94°/s");
    expect(formatWithUnit(1.5, "rad/s", "imperial").stored).toBe("1.5 rad/s");
  });

  it("gives a stored form only when the display converts", () => {
    expect(formatStored(0.5, "rad", "metric")).toBe("0.5 rad");
    expect(formatStored(0.5, "rad", "imperial")).toBe("0.5 rad");
    expect(formatStored(161.48, "kg", "metric")).toBeNull();
    expect(formatStored(161.48, "kg", "imperial")).toBe("161.48 kg");
    expect(formatStored(30, "°", "imperial")).toBeNull();
    expect(formatStored(3, null, "imperial")).toBeNull();
  });
});

describe("unit spacing", () => {
  it("sets degree signs tight and other units apart", () => {
    expect(withUnit("60", "°")).toBe("60°");
    expect(withUnit("12", "°/s")).toBe("12°/s");
    expect(withUnit("9.45", "m")).toBe("9.45 m");
    expect(withUnit("3", null)).toBe("3");
    expect(unitGap("°")).toBe("");
    expect(unitGap("kg")).toBe(" ");
  });
});

describe("sentinel angles", () => {
  it("shows a radian value beyond a full turn raw, not as degrees", () => {
    expect(isSentinelAngle(-100, "rad")).toBe(true);
    expect(isSentinelAngle(Math.PI, "rad")).toBe(false);
    expect(isSentinelAngle(-100, "m")).toBe(false);
    expect(convertValue(-100, "rad", "metric", "reloadAngleYRad")).toEqual({
      value: -100,
      unit: "rad",
      converted: false,
    });
    expect(formatPlain(-100, "rad")).toBe("-100 rad");
    expect(formatStored(-100, "rad", "metric")).toBeNull();
  });

  it("reads the renamed angle fields' units", () => {
    expect(unitFor("reloadAngleYRad")).toBe("rad");
    expect(unitFor("trackingRateMaxRadS")).toBe("rad/s");
    expect(unitFor("aoaMaxDeg")).toBe("°");
    expect(unitFor("angle100Deg")).toBe("°");
  });
});
