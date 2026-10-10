import { describe, expect, it } from "vitest";
import {
  beaconPoint,
  decimal,
  dms,
  googleUrl,
  isGeoField,
  latLonOf,
  locationOf,
  osmUrl,
} from "./geo";

describe("latLonOf", () => {
  it("reads degrees and ignores map metres", () => {
    expect(latLonOf({ latitude: 34.2, longitude: 62.2, x: 1, z: 2 })).toEqual({
      lat: 34.2,
      lon: 62.2,
    });
    expect(latLonOf({ x: 25820.9, z: -371274.6 })).toBeNull();
    expect(latLonOf({ latitude: 120, longitude: 0 })).toBeNull();
    expect(latLonOf(null)).toBeNull();
  });
});

describe("dms", () => {
  it("formats hemispheres and pads", () => {
    expect(dms(34.2079055, "lat")).toBe("34°12′28.46″N");
    expect(dms(62.2279408, "lon")).toBe("062°13′40.59″E");
    expect(dms(-51.8228, "lat")).toBe("51°49′22.08″S");
    expect(dms(-58.4472, "lon")).toBe("058°26′49.92″W");
  });

  it("carries rounded seconds into the minute", () => {
    expect(dms(10 + 59 / 60 + 59.9999 / 3600, "lat")).toBe("11°00′00.00″N");
  });
});

describe("links out", () => {
  const p = { lat: 31.838947, lon: 64.219237 };
  it("builds OSM and Google URLs", () => {
    expect(decimal(p)).toBe("31.838947, 64.219237");
    expect(osmUrl(p)).toBe(
      "https://www.openstreetmap.org/?mlat=31.838947&mlon=64.219237#map=15/31.838947/64.219237",
    );
    expect(googleUrl(p)).toBe(
      "https://www.google.com/maps/search/?api=1&query=31.838947%2C64.219237",
    );
  });
});

describe("locationOf", () => {
  it("places a beacon at its own coordinates", () => {
    const loc = locationOf("beacons", { latitude: 31.8, longitude: 64.2 }, "Bastion");
    expect(loc?.points).toEqual([{ lat: 31.8, lon: 64.2, kind: "record", label: "Bastion" }]);
  });

  it("reads an airbase's reference point, runways, stands and beacons", () => {
    const th = (lat: number) => ({ threshold: { latitude: lat, longitude: 62.2, x: 0, z: 0 } });
    const loc = locationOf(
      "airbases",
      {
        referencePoint: { latitude: 34.2, longitude: 62.2, x: 0, z: 0 },
        runways: [{ designator: "18/36", directions: [th(34.22), th(34.19)] }],
        stands: [{ name: "33", position: { latitude: 34.19, longitude: 62.22 } }, { name: "x" }],
        beacons: ["Afghanistan.airfield1_0"],
      },
      "Herat",
    );
    expect(loc?.points[0]).toMatchObject({ lat: 34.2, kind: "record" });
    expect(loc?.lines).toEqual([
      { from: { lat: 34.22, lon: 62.2 }, to: { lat: 34.19, lon: 62.2 }, label: "Runway 18/36" },
    ]);
    expect(loc?.extras).toHaveLength(1);
    expect(loc?.beaconIds).toEqual(["Afghanistan.airfield1_0"]);
    expect(loc?.beaconsArePoints).toBe(false);
  });

  it("takes a navaid's position from its equipment", () => {
    const loc = locationOf("navaids", { equipment: ["a", "b"] }, "ISO");
    expect(loc).toMatchObject({ points: [], beaconIds: ["a", "b"], beaconsArePoints: true });
    expect(locationOf("navaids", { equipment: [] }, "ISO")).toBeNull();
  });

  it("is null for series without coordinates", () => {
    expect(locationOf("aircraft", { latitude: 1, longitude: 2 }, "F-16")).toBeNull();
    expect(locationOf("airbases", { referencePoint: { x: 1, z: 2 } }, "x")).toBeNull();
  });
});

describe("beaconPoint", () => {
  it("labels by callsign and type", () => {
    expect(
      beaconPoint(
        { latitude: 1, longitude: 2, callsign: "ISO", typeName: "BEACON_TYPE_ILS_LOCALIZER" },
        "equipment",
        "id",
      ),
    ).toEqual({ lat: 1, lon: 2, kind: "equipment", label: "ISO · ILS LOCALIZER" });
  });
});

it("isGeoField", () => {
  expect(isGeoField("latitude")).toBe(true);
  expect(isGeoField("longitudeDeg")).toBe(false);
});
