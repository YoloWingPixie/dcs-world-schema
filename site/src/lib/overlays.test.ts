import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ANY_TARGET,
  loadOverlays,
  OverlayError,
  type OverlayTarget,
} from "../../scripts/lib/overlays";
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
    record: (stem) => ({ AIM_120C: "AIM_120C", "aim-120c": "AIM_120C" })[stem] ?? null,
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
      "weapons/aim-120c.md": "---\nnickname: AMRAAM\n---\nx",
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
    expect(problems).toContain('no record with id or slug "AIM_999"');
    expect(problems).toContain('no field "noSuchField"');
    expect(problems).toContain('unknown frontmatter key "nickname"');
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
