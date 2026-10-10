import { describe, expect, it } from "vitest";
import { apiContents, apiPageCounts } from "../../src/lib/api/contents";
import { getApiPage, listApiPages } from "../../src/lib/api/db";
import { loadScripting } from "../../src/lib/api/record-scripting";
import { enumField, namesKey, SCRIPTING, seriesOfClass } from "../../src/lib/api/scripting";
import type { Token } from "../../src/lib/api/types";
import { getRecord, loadModel } from "../../src/lib/db/reference";
import { nodeQuery } from "../reference/db";

const q = nodeQuery();
const refs = (tokens: Token[][] | Token[] | undefined): string[] =>
  (tokens ?? []).flat().flatMap((t) => (typeof t === "string" ? [] : [t.r]));

describe("contents chapter", () => {
  it("counts every API page under the API home's groupings", async () => {
    const counts = await apiPageCounts(q);
    const entries = apiContents(counts);
    const pages = await listApiPages(q);
    expect(entries.reduce((n, e) => n + e.count, 0)).toBe(pages.length);
    expect(entries.map((e) => e.id)).toEqual(
      expect.arrayContaining(["classes", "globals", "types"]),
    );
    expect(entries.find((e) => e.id === "classes")?.count).toBe(
      pages.filter((p) => p.section === "mission" && p.kind === "class").length,
    );
  });
});

describe("the data and the API", () => {
  it("names only enums that list the series' records, and members that exist", async () => {
    for (const [series, spec] of Object.entries(SCRIPTING)) {
      for (const name of spec.enums.map((e) => e.replace("{theatre}", "Caucasus"))) {
        const page = await getApiPage(q, "types", name);
        expect(page?.kind, name).toBe("enum");
        expect(page?.valuesSeries, name).toBe(series);
      }
      for (const name of spec.values?.flatMap((v) => v.enums) ?? []) {
        expect((await getApiPage(q, "types", name))?.kind, name).toBe("enum");
      }
      if (spec.class) expect((await getApiPage(q, "mission", spec.class))?.kind).toBe("class");
      for (const path of [spec.member, ...(spec.fields ?? []).map((f) => f.member)]) {
        if (!path) continue;
        const [page, name] = path.split(".") as [string, string];
        const p = await getApiPage(q, "mission", page);
        expect(
          p?.groups.flatMap((g) => g.members).some((m) => m.name === name),
          path,
        ).toBe(true);
      }
    }
  });

  it("getTypeName returns the enums the record pages cite", async () => {
    const unit = await getApiPage(q, "mission", "Unit");
    const getTypeName = unit?.groups
      .flatMap((g) => g.members)
      .find((m) => m.name === "getTypeName");
    const returned = refs(getTypeName?.returns);
    expect(returned).toContain("DcsId.UnitType");
    const union = await getApiPage(q, "types", "DcsId.UnitType");
    const members = refs(union?.anyOf);
    for (const series of seriesOfClass("Unit")) {
      for (const e of SCRIPTING[series]?.enums ?? []) expect(members, e).toContain(e);
    }
    const weapon = await getApiPage(q, "mission", "Weapon");
    const w = weapon?.groups.flatMap((g) => g.members).find((m) => m.name === "getTypeName");
    expect(refs(w?.returns)).toEqual(SCRIPTING.weapons?.enums);
  });

  it("maps DCS constant names to enum keys", () => {
    expect(namesKey("SENSOR_OPTICAL", "OPTIC")).toBe(true);
    expect(namesKey("OPTIC_SENSOR_LLTV", "LLTV")).toBe(true);
    expect(namesKey("RADAR_AS", "TV")).toBe(false);
    expect(namesKey("RADAR_MULTIROLE", "IR")).toBe(false);
    expect(enumField("Unit.SensorType")?.series).toBe("sensors");
    expect(enumField("Weapon.Category")).toBeNull();
  });

  it("builds a record's Scripting rows from the API data", async () => {
    const model = await loadModel(q);
    const f16 = await getRecord(q, model, "aircraft", "F-16C_50");
    if (!f16) throw new Error("no F-16C_50");
    const rows = await loadScripting(q, "aircraft", f16.id, f16.data);
    expect(rows.map((r) => r.id)).toEqual([
      "class",
      "member",
      "enum-DcsId.AircraftType",
      "attributes",
    ]);
    expect(rows[1]).toMatchObject({
      label: { text: "Unit:getTypeName()", href: "/api/Unit/#getTypeName" },
      value: { text: '"F-16C_50"' },
    });
    expect(rows[2]?.value.href).toBe("/api/types/DcsId/AircraftType/#v-F-16CM%2520bl.50");

    const batumi = await getRecord(q, model, "airbases", "Caucasus.22");
    if (!batumi) throw new Error("no Caucasus.22");
    const ab = await loadScripting(q, "airbases", batumi.id, batumi.data);
    expect(ab.find((r) => r.id === "field-airdromeId")?.value.text).toBe("22");
    expect(ab.find((r) => r.id === "value-category")?.value.text).toBe("Airbase.Category.AIRDROME");
    expect(ab.map((r) => r.id)).toContain("enum-DcsId.Theatre.Caucasus.AirdromeId");

    // A record no enum lists keeps only what the API confirms.
    expect(await loadScripting(q, "aircraft", "no-such-type", {})).toEqual(rows.slice(0, 1));
  });
});
