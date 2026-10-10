import { beforeAll, describe, expect, it } from "vitest";
import { findDatabase, modelTables, nameIndex } from "../../scripts/split-sqlite";
import { loadModel, type Model, modelFrom, readModelTables } from "../../src/lib/db/reference";
import {
  buildNameIndex,
  type NameIndex,
  type NameIndexFile,
  recordKey,
  searchNames,
} from "../../src/lib/search/engine";
import { nodeQuery } from "./db";

const q = nodeQuery();
const path = findDatabase() ?? "";
const roundTrip = <T>(value: T): T => JSON.parse(JSON.stringify(value));

describe("static model (scripts/split-sqlite.ts)", () => {
  it("holds the rows the model statements read", async () => {
    expect(roundTrip(modelTables(path))).toEqual(roundTrip(await readModelTables(q)));
  });

  it("builds the same model as the database", async () => {
    expect(modelFrom(roundTrip(modelTables(path)))).toEqual(await loadModel(q));
  });
});

describe("name index search (lib/search/engine.ts)", () => {
  let model: Model;
  let index: NameIndex;
  beforeAll(async () => {
    model = await loadModel(q);
    const file = roundTrip(nameIndex(path)) as NameIndexFile;
    index = await buildNameIndex(file, model, {
      aliases: new Map([[recordKey("weapons", "AIM_120C"), ["AMRAAM"]]]),
      notes: new Map([["Controller.setTask", "Replaces the current task; pushTask stacks one."]]),
    });
  });
  const top = (query: string, group: string) =>
    searchNames(index, query, 10).find((g) => g.source.id === group)?.results ?? [];

  it("indexes every search row", () => {
    expect(index.docs.length).toBeGreaterThan(15000);
  });

  it("finds a name however it is spelled", () => {
    for (const query of ["aim120c", "AIM-120C", "aim 120c", "AIM_120C"]) {
      expect(top(query, "weapons")[0]?.href, query).toBe("/weapons/AIM_120C/");
    }
  });

  it("puts exact names first and their series group first", () => {
    const groups = searchNames(index, "batumi", 10);
    expect(groups[0]?.source.id).toBe("airbases");
    expect(groups[0]?.results[0]).toMatchObject({ title: "Batumi" });
  });

  it("finds overlay aliases and keyword-only words", () => {
    expect(top("amraam", "weapons")[0]?.href).toBe("/weapons/AIM_120C/");
    expect(top("warthog", "aircraft").map((r) => r.detail ?? r.title)).toContain("A-10C");
  });

  it("allows a typo when nothing matches exactly", () => {
    expect(top("batumu", "airbases")[0]?.title).toBe("Batumi");
  });

  it("searches the Lua API rows and their notes", () => {
    expect(top("outText", "api")[0]?.title).toBe("trigger.action.outText");
    expect(top("trigger.action.outText", "api")[0]?.href).toBe("/api/trigger/action/#outText");
    expect(top("Controller.setTask", "api")[0]?.title).toBe("Controller:setTask");
    expect(top("getByName", "api").map((r) => r.title)).toContain("Unit.getByName");
    expect(top("pushTask stacks", "api").map((r) => r.title)).toContain("Controller:setTask");
  });

  it("ignores queries too short to read", () => {
    expect(searchNames(index, "a", 10)).toEqual([]);
    expect(searchNames(index, " - ", 10)).toEqual([]);
  });
});
