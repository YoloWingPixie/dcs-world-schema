import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { locate, parsePointer } from "./locate";
import { dumpFile, recordSources, shortLabels, splitSourcePath } from "./source";
import { tokenize } from "./tokenize";

function spans(text: string) {
  const t = tokenize(text);
  return t.kinds.map((k, i) => [k, text.slice(t.starts[i], t.ends[i])]);
}

describe("tokenize", () => {
  it("colours keys, strings, numbers, literals and comments", () => {
    const text = `_G["a"]["b c"] = {\n\tx = 1.5e3, ["y z"] = "s\\"q", [2] = true, -- note\n\tf = nil, g == h }`;
    expect(spans(text)).toEqual([
      ["string", '"a"'],
      ["key", '"b c"'],
      ["key", "x"],
      ["number", "1.5e3"],
      ["key", '"y z"'],
      ["string", '"s\\"q"'],
      ["number", "2"],
      ["literal", "true"],
      ["comment", "-- note"],
      ["key", "f"],
      ["literal", "nil"],
    ]);
  });

  it("reads long strings and comments", () => {
    expect(spans("a = [==[x]]y]==] --[[c\nd]] b")).toEqual([
      ["key", "a"],
      ["string", "[==[x]]y]==]"],
      ["comment", "--[[c\nd]]"],
    ]);
  });

  it("dims markers but not an anchor's table", () => {
    const text = `t = { f = __dcs{kind="function"}, a = __dcs{kind="anchor", id=1, value={ k = "v" }}, r = __dcs{kind="ref", id=1} }`;
    expect(spans(text)).toEqual([
      ["key", "t"],
      ["key", "f"],
      ["marker", '__dcs{kind="function"}'],
      ["key", "a"],
      ["marker", '__dcs{kind="anchor", id=1, value='],
      ["key", "k"],
      ["string", '"v"'],
      ["marker", "}"],
      ["key", "r"],
      ["marker", '__dcs{kind="ref", id=1}'],
    ]);
  });
});

describe("locate", () => {
  const text = [
    '_G["x"]["y"] = {',
    "\tclient = {",
    "\t\tfm = { 1, 2, { c = 3 } },",
    '\t\t["a/b"] = __dcs{kind="anchor", id=1, value={ z = 1 }},',
    "\t},",
    '\tother = __dcs{kind="ref", id=1},',
    "\t[true] = 5, [0.5] = 6,",
    "}",
  ].join("\n");
  const at = (p: string) => {
    const hit = locate(text, p);
    return hit && { text: text.slice(hit.start, hit.end), partial: hit.partial };
  };

  it("parses pointers as dump_paths does", () => {
    expect(parsePointer("/a~1b/[1]/~2x/[true]/[0.5]/~0")).toEqual(["a/b", 1, "[x", true, 0.5, "~"]);
    expect(parsePointer("")).toEqual([]);
  });

  it("finds entries by key and position", () => {
    expect(at("/client/fm")).toEqual({ text: "fm = { 1, 2, { c = 3 } }", partial: false });
    expect(at("/client/fm/[3]/c")).toEqual({ text: "c = 3", partial: false });
    expect(at("/[true]")).toEqual({ text: "[true] = 5", partial: false });
    expect(at("/[0.5]")).toEqual({ text: "[0.5] = 6", partial: false });
  });

  it("follows anchors and refs", () => {
    expect(at("/client/a~1b/z")?.text).toBe("z = 1");
    expect(at("/other/z")?.text).toBe("z = 1");
  });

  it("marks the deepest table when a key is missing", () => {
    expect(at("/client/nope")).toEqual({
      text: text.slice(text.indexOf("client = {"), text.indexOf("\t},") + 2),
      partial: true,
    });
    expect(at("/client/fm/[1]/x")?.partial).toBe(true);
  });
});

describe("source", () => {
  it("maps dump paths to files", () => {
    expect(dumpFile("_G/db/Units/Planes/Plane/F-16C_50")).toBe(
      "db/Units/Planes/Plane/F-16C_50.lua",
    );
    expect(dumpFile("_G/a/../b")).toBeNull();
    expect(dumpFile("db/x")).toBeNull();
    expect(splitSourcePath("_G/a#/b/[1]")).toEqual({ path: "_G/a", pointer: "/b/[1]" });
  });

  it("labels files by their shortest distinct tail", () => {
    expect(shortLabels(["_G/bombs/X", "_G/weapons_table/weapons/bombs/X", "_G/a/Y"])).toEqual([
      "_G/bombs/X",
      "weapons/bombs/X",
      "Y",
    ]);
  });

  it("collects a record's files and blocks", () => {
    const got = recordSources(
      { sourcePaths: ["_G/a/x"], radar: { sourcePath: "_G/a/x#/radar" } },
      { sourcePaths: ["_G/b/y"], stages: [{ sourcePath: "_G/c/z#/s" }] },
    );
    expect(got.files).toEqual(["_G/a/x", "_G/b/y", "_G/c/z"]);
    expect(got.blocks).toEqual([
      { label: "radar", sourcePath: "_G/a/x#/radar" },
      { label: "flight.stages[0]", sourcePath: "_G/c/z#/s" },
    ]);
    expect(recordSources({ radar: { sourcePath: "_G/a/x#/r" } }).files).toEqual([]);
  });
});

// Every block pointer of the committed data resolves in the dump (not committed): the
// cached ../.datamine/_G of the data's DCS version, else the tree copy-lua-assets collected.
const repo = resolve(__dirname, "../../../..");
const latest = join(repo, "dcs-world-reference/latest");
function dumpTree(): string | null {
  const version = existsSync(join(latest, "manifest.json"))
    ? (JSON.parse(readFileSync(join(latest, "manifest.json"), "utf8")) as { dcsVersion: string })
        .dcsVersion
    : null;
  const g = join(repo, ".datamine/_G");
  const marker = join(g, "__DCS_VERSION__.lua");
  if (version && existsSync(marker) && readFileSync(marker, "utf8").trim() === version) return g;
  const collected = join(repo, ".datamine/site-lua");
  return version && existsSync(collected) ? collected : null;
}
const tree = dumpTree();
describe.skipIf(!tree)("dump files", () => {
  it("hold every block sourcePath", () => {
    const missing: string[] = [];
    let checked = 0;
    const records = (readdirSync(latest, { recursive: true }) as string[]).filter(
      (f) => f.endsWith(".json") && !/^api[\\/]/.test(f),
    );
    for (const f of records) {
      const json = readFileSync(join(latest, f), "utf8");
      for (const m of json.matchAll(/"sourcePath": "([^"]+#\/[^"]*)"/g)) {
        const { path, pointer } = splitSourcePath(m[1] as string);
        const file = join(tree as string, dumpFile(path) as string);
        const hit = existsSync(file) ? locate(readFileSync(file, "utf8"), pointer) : null;
        checked++;
        if (!hit || hit.partial) missing.push(m[1] as string);
      }
    }
    expect(checked).toBeGreaterThan(0);
    expect(missing.slice(0, 10)).toEqual([]);
  }, 60_000);
});
