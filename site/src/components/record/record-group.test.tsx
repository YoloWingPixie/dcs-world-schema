import { isValidElement, type ReactElement } from "react";
import { beforeAll, describe, expect, it } from "vitest";
import { catalogFor, loadModel, type Model } from "@/lib/db/reference";
import type { SeriesCatalog } from "@/lib/types";
import { nodeQuery } from "../../../tests/reference/db";
import { FieldRow, ScalarValue } from "../field-view";
import {
  HeatGrid,
  JsonValue,
  MachCard,
  NumberList,
  ProvenanceValue,
  type RenderCtx,
  SectorTable,
  StringList,
} from "./blocks";
import { blockFor, RecordsBlock, recordsLayoutFor } from "./record-group";

let model: Model;
beforeAll(async () => {
  model = await loadModel(nodeQuery());
});

const ctxOf = (catalog: SeriesCatalog): RenderCtx => ({
  catalog,
  vctx: { enums: catalog.enums, system: "metric", links: {} },
  fctx: { series: "test", slug: "x", recordName: "X" },
});

/** The component a block renders, and its body's when it is a field row. */
function shape(node: unknown) {
  if (!isValidElement(node)) return { type: null, body: null };
  const el = node as ReactElement<{ body?: unknown; children?: unknown }>;
  const body = el.props.body;
  return { type: el.type, body: isValidElement(body) ? body.type : null };
}

describe("blockFor", () => {
  it("places a group's fields by kind, layout and role", () => {
    const weapons = catalogFor(model, "weapons");
    const ctx = ctxOf(weapons);
    const group = (path: string, value: unknown, holder = {}) => {
      const entry = weapons.entries[path];
      if (!entry) throw new Error(path);
      const block = blockFor(entry, value, ctx, { in: "group", path, holder, depth: 0 });
      return { slot: block.slot, ...shape(block.node) };
    };
    expect(group("massKg", 150)).toEqual({ slot: "row", type: FieldRow, body: null });
    expect(group("sourcePaths", ["_G/a"])).toEqual({
      slot: "wide",
      type: FieldRow,
      body: ProvenanceValue,
    });
    expect(group("flight.aerodynamics.cx0", [0.1, 0.2], { machStep: 0.1 })).toEqual({
      slot: "chart",
      type: MachCard,
      body: null,
    });
    expect(group("flight.launchEnvelopes", [{}])).toMatchObject({ slot: "nested", type: "div" });
    expect(group("flight.aerodynamics", {})).toMatchObject({ slot: "nested", type: "div" });
    expect(group("flight.launchEnvelopes[].maxRangeM", [[1]])).toEqual({
      slot: "wide",
      type: FieldRow,
      body: HeatGrid,
    });
  });

  it("reads the same kinds the same way in a table cell", () => {
    const aircraft = catalogFor(model, "aircraft");
    const vehicles = catalogFor(model, "ground_vehicles");
    const cell = (catalog: SeriesCatalog, path: string, value: unknown) => {
      const entry = catalog.entries[path];
      if (!entry) throw new Error(path);
      return shape(blockFor(entry, value, ctxOf(catalog), { in: "cell", path }).node).type;
    };
    expect(cell(aircraft, "stations[].accepts", [{ clsid: "{X}" }])).toBe(RecordsBlock);
    expect(cell(vehicles, "weaponSystems[].sectorsRad", [[0, 1]])).toBe(SectorTable);
    expect(cell(aircraft, "stations[].accepts[].clsid", "{X}")).toBe(ScalarValue);
    const strings = Object.values(aircraft.entries).find(
      (e) => e.kind === "strings" && e.path.includes("[]") && !e.codeField,
    );
    if (strings) expect(cell(aircraft, strings.path, ["a"])).toBe(StringList);
    const numbers = Object.values(vehicles.entries).find(
      (e) => e.kind === "numbers" && e.path.includes("[]") && !e.axis,
    );
    if (numbers) expect(cell(vehicles, numbers.path, [1, 2])).toBe(NumberList);
    expect(cell(aircraft, "stations", [{}])).toBe(RecordsBlock);
    const any = Object.values(aircraft.entries).find((e) => e.kind === "any");
    if (any) expect(cell(aircraft, any.path, { a: 1 })).toBe(JsonValue);
  });
});

describe("recordsLayoutFor", () => {
  it("lays out arrays of records by their catalog layout, for their place", () => {
    const aircraft = catalogFor(model, "aircraft");
    const weapons = catalogFor(model, "weapons");
    const radios = catalogFor(model, "radios");
    const layout = (catalog: SeriesCatalog, path: string, place: "group" | "cell") => {
      const entry = catalog.entries[path];
      if (!entry) throw new Error(path);
      return recordsLayoutFor(entry, place);
    };
    expect(layout(weapons, "flight.launchEnvelopes", "group")).toBe("envelope");
    expect(layout(aircraft, "flight.aerodynamics.table", "group")).toBe("axis-table");
    expect(layout(aircraft, "stations", "group")).toBe("table");
    expect(layout(aircraft, "gun.mounts[].mixes", "group")).toBe("list-per-item");
    const ranges = Object.values(radios.entries).find((e) => e.layout === "ranges");
    if (ranges) expect(layout(radios, ranges.path, "group")).toBe("ranges");
    // In a cell: items by their link, one line per item, else a compact table.
    expect(layout(aircraft, "stations[].accepts", "cell")).toBe("linked");
    expect(layout(aircraft, "gun.mounts[].mixes", "cell")).toBe("list-per-item");
    expect(layout(aircraft, "stations", "cell")).toBe("table");
    expect(layout(weapons, "flight.launchEnvelopes", "cell")).toBe("table");
  });
});
