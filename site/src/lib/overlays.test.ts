import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ANY_TARGET,
  loadOverlays,
  OverlayError,
  type OverlayTarget,
  overlayTargets,
  recordIdFromStem,
  recordStem,
} from "../../scripts/lib/overlays";
import { nodeQuery } from "../../tests/reference/db";
import { parseFrontmatter } from "./markdown";

function tree(files: Record<string, string>) {
  const dir = mkdtempSync(join(tmpdir(), "overlays-"));
  for (const [rel, text] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, rel)), { recursive: true });
    writeFileSync(join(dir, rel), text);
  }
  return dir;
}

const targets: Record<string, OverlayTarget> = {
  weapons: {
    record: (stem) => (stem === "AIM_120C" ? stem : null),
    field: (path) => ["massKg", "flight.motorStages.*.impulseS"].includes(path),
  },
};

describe("overlays", () => {
  it("merges intro, record notes with aliases, and field notes", () => {
    const dir = tree({
      "weapons/_index.md": "Intro **text**.",
      "weapons/AIM_120C.md": "---\naliases: [AMRAAM]\nseeAlso:\n  - /aircraft/\n---\nA note.",
      "weapons/_fields/massKg.md": "Launch mass.",
      "weapons/_fields/flight.motorStages.+.impulseS.md": "Per stage.",
    });
    const out = loadOverlays(dir, targets).get("weapons");
    expect(out?.intro?.html).toContain("<strong>text</strong>");
    expect(out?.records.get("AIM_120C")).toMatchObject({
      aliases: ["AMRAAM"],
      seeAlso: [{ label: "/aircraft/", href: "/aircraft/" }],
      text: "A note.",
    });
    expect(out?.fields.get("flight.motorStages.*.impulseS")?.html).toContain("Per stage.");
  });

  it("fails on stale series, records and fields, and unknown frontmatter keys", () => {
    const dir = tree({
      "spaceships/_index.md": "x",
      "weapons/AIM_999.md": "x",
      "weapons/_fields/noSuchField.md": "x",
      "weapons/AIM_120C.md": "---\nnickname: AMRAAM\n---\nx",
    });
    let error: unknown;
    try {
      loadOverlays(dir, targets);
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(OverlayError);
    const problems = (error as OverlayError).problems.join("\n");
    expect(problems).toContain('no series named "spaceships"');
    expect(problems).toContain('no record with id "AIM_999"');
    expect(problems).toContain('no field "noSuchField"');
    expect(problems).toContain('unknown frontmatter key "nickname"');
  });

  it("names records by exact id against the database, naming the id a slug stem should be", async () => {
    const check = await overlayTargets(nodeQuery());
    const weapons = check("weapons");
    expect(weapons?.record("AIM_120C")).toBe("AIM_120C");
    expect(weapons?.record("BLU-49/B")).toBe("BLU-49/B");
    // A slug (lib/series-display `slugify`) is not an id; the problem names the id.
    expect(weapons?.record("BLU-49-B")).toBeNull();
    expect(weapons?.hint?.("BLU-49-B")).toContain('"BLU-49/B"');
    expect(check("spaceships")).toBeNull();
    // A companion's fields are its parent's catalog's.
    expect(check("weapon_flight")?.field("aerodynamics.cx0")).toBe(true);
    let error: unknown;
    try {
      loadOverlays(tree({ "weapons/BLU-49-B.md": "x", "weapons/AIM_120C.md": "x" }), check);
    } catch (e) {
      error = e;
    }
    expect((error as OverlayError).problems).toEqual([
      'weapons/BLU-49-B.md: weapons has no record with id "BLU-49-B"; name it by the record\'s id, "BLU-49/B": BLU-49%2FB.md',
    ]);
    // The encoded id reads back as the id, with no database.
    const out = loadOverlays(
      tree({ "weapons/BLU-49%2FB.md": "---\naliases: [Rockeye]\n---\n" }),
      check,
    );
    expect(out.get("weapons")?.records.get("BLU-49/B")?.aliases).toEqual(["Rockeye"]);
    expect(
      loadOverlays(tree({ "weapons/BLU-49%2FB.md": "x" }), () => ANY_TARGET)
        .get("weapons")
        ?.records.has("BLU-49/B"),
    ).toBe(true);
    expect(recordStem("BLU-49/B")).toBe("BLU-49%2FB");
    expect(recordIdFromStem(recordStem("F-16C bl.50"))).toBe("F-16C bl.50");
    expect(recordStem("AIM_120C")).toBe("AIM_120C");
    expect(() => loadOverlays(tree({ "weapons/bad%2.md": "x" }), check)).toThrow(
      /encodeURIComponent/,
    );
  });

  it("are all current: every overlay names an exact id, series and field in the database", async () => {
    const out = loadOverlays(
      join(__dirname, "../../content/reference"),
      await overlayTargets(nodeQuery()),
    );
    expect(out.get("weapons")?.records.get("AIM_120C")).toBeDefined();
  });

  it("parses frontmatter and rejects non-mappings", () => {
    expect(parseFrontmatter("---\na: 1\n---\nbody")).toEqual({ data: { a: 1 }, body: "body" });
    expect(() => parseFrontmatter("---\n- x\n---\n", { file: "f.md" })).toThrow(/mapping/);
  });

  it("builds without data: stale series and records are kept for the runtime to ignore", () => {
    const dir = tree({ "spaceships/x-wing.md": "---\naliases: [T-65]\n---\nNote." });
    const out = loadOverlays(dir, () => ANY_TARGET);
    expect(out.get("spaceships")?.records.get("x-wing")?.aliases).toEqual(["T-65"]);
    expect(() =>
      loadOverlays(tree({ "a/b.md": "---\nnickname: x\n---\n" }), () => ANY_TARGET),
    ).toThrow(OverlayError);
  });
});
