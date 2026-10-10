import { describe, expect, it } from "vitest";
import { collidingIds, frequencyText, LINK_DETAILS, withDetail } from "./link-details";

describe("link details", () => {
  const beacon = LINK_DETAILS.beacons ?? (() => null);

  it("tells same-named beacons apart by type and tuning", () => {
    expect(beacon({ typeName: "BEACON_TYPE_TACAN", channel: 97, frequencyHz: 122500000 })).toBe(
      "TACAN 97",
    );
    expect(beacon({ typeName: "BEACON_TYPE_VOR_DME", channel: 57, frequencyHz: 112000000 })).toBe(
      "VOR/DME 112.00 MHz",
    );
    expect(beacon({ typeName: "BEACON_TYPE_AIRPORT_HOMER", frequencyHz: 395000 })).toBe(
      "Airport NDB 395 kHz",
    );
    expect(beacon({})).toBeNull();
  });

  it("only touches names that collide", () => {
    expect(
      collidingIds([
        ["a", "KERMAN"],
        ["b", "KERMAN"],
        ["c", "SHIRAZ"],
      ]),
    ).toEqual(["a", "b"]);
    expect(withDetail("KERMAN", "TACAN 97")).toBe("KERMAN · TACAN 97");
    expect(withDetail("KERMAN", null)).toBe("KERMAN");
    expect(frequencyText(290000000)).toBe("290.00 MHz");
  });
});
