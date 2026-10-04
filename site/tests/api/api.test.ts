import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { compileApiOverlays } from "../../scripts/build-api-overlays";
import { staleApiOverlays } from "../../scripts/check-api-overlays";
import {
  applyOverlays,
  existingRecords,
  getApiPage,
  listApiPages,
  resolveSymbols,
  searchApi,
} from "../../src/lib/api/db";
import { OverlayError, parseOverlay } from "../../src/lib/api/overlays";
import { apiHref, parseApiPath } from "../../src/lib/api/routes";
import type { ApiPage, Token } from "../../src/lib/api/types";
import { nodeQuery } from "../reference/db";

const q = nodeQuery();
const text = (tokens: Token[] | undefined) =>
  (tokens ?? []).map((t) => (typeof t === "string" ? t : t.r)).join("");
const member = (page: ApiPage | null, name: string) =>
  page?.groups.flatMap((g) => g.members).find((m) => m.name === name);

describe("routes", () => {
  it("round-trips page paths", () => {
    expect(apiHref("mission", "trigger.action")).toBe("/api/trigger/action/");
    expect(apiHref("types", "DcsTask.Task.Orbit")).toBe("/api/types/DcsTask/Task/Orbit/");
    expect(parseApiPath("/api/types/DcsTask/Task/Orbit/")).toEqual({
      home: false,
      section: "types",
      name: "DcsTask.Task.Orbit",
    });
    expect(parseApiPath("/api/hooks/DCS/")).toMatchObject({ section: "hooks", name: "DCS" });
    expect(parseApiPath("/api/")).toEqual({ home: true });
    expect(parseApiPath("/weapons/AIM_120C/")).toBeNull();
  });
});

describe("API pages from the database", () => {
  it("lists every page through one query", async () => {
    const pages = await listApiPages(q);
    expect(pages.filter((p) => p.kind === "class")).toHaveLength(10);
    expect(pages.filter((p) => p.section === "types").length).toBeGreaterThan(300);
    expect(pages.some((p) => p.section === "hooks" && p.name === "DCS")).toBe(true);
    const unit = pages.find((p) => p.name === "Unit" && p.section === "mission");
    expect(unit?.href).toBe("/api/Unit/");
    expect(unit?.count).toBeGreaterThan(40);
  });

  it("renders Unit: signatures, inheritance, type links, used-by", async () => {
    const before = q.count;
    const unit = await getApiPage(q, "mission", "Unit");
    expect(q.count - before).toBe(2);
    const getByName = member(unit, "getByName");
    expect(text(getByName?.sig)).toBe("Unit.getByName(name: string): Unit?");
    expect(getByName?.anchor).toBe("getByName");
    expect(unit?.links.Unit).toBe("/api/Unit/");
    expect(unit?.links["Unit.Category"]).toBe("/api/types/Unit/Category/");
    const fromObject = unit?.inherited?.find((g) => g.from === "Object");
    expect(fromObject?.href).toBe("/api/Object/");
    expect(fromObject?.members.map((m) => m.qualified)).toContain("Unit:isExist");
    expect(unit?.usedBy.map((u) => u.label)).toContain("Unit.getByName");
    expect(await getApiPage(q, "mission", "NoSuchThing")).toBeNull();
  });

  it("has namespaces, types and environments", async () => {
    const action = await getApiPage(q, "mission", "trigger.action");
    expect(action?.parent).toEqual({ name: "trigger", href: "/api/trigger/" });
    expect(text(member(action, "outText")?.sig)).toBe(
      "trigger.action.outText(text: string, displayTime: number, clearview?: boolean)",
    );
    const orbit = await getApiPage(q, "types", "DcsTask.Task.Orbit");
    expect(orbit?.links["DcsTask.Task.OrbitParams"]).toBe("/api/types/DcsTask/Task/OrbitParams/");
    const dcs = await getApiPage(q, "hooks", "DCS");
    expect(dcs?.groups.flatMap((g) => g.members).length).toBeGreaterThan(100);
  });

  it("links DcsId values to reference records that exist", async () => {
    const weapons = await getApiPage(q, "types", "DcsId.WeaponType");
    expect(weapons?.valuesSeries).toBe("weapons");
    const refs = (weapons?.values ?? []).flatMap((v) => (v.ref ? [v.ref] : []));
    const found = await existingRecords(q, "weapons", refs);
    expect(found.has("AIM_120C")).toBe(true);
    expect(found.size).toBeGreaterThan(400);
    expect(found.size).toBeLessThan(refs.length);
  });

  it("resolves symbol paths", async () => {
    const hrefs = await resolveSymbols(q, ["Group.getByName", "DcsTask.Task.Orbit", "Nope.nope"]);
    expect(hrefs.get("Group.getByName")).toBe("/api/Group/#getByName");
    expect(hrefs.get("DcsTask.Task.Orbit")).toBe("/api/types/DcsTask/Task/Orbit/");
    expect(hrefs.has("Nope.nope")).toBe(false);
  });

  it("searches the API rows of the shared FTS index", async () => {
    expect((await searchApi(q, "outText"))[0]?.path).toBe("trigger.action.outText");
    expect((await searchApi(q, "trigger.action.outText"))[0]?.href).toBe(
      "/api/trigger/action/#outText",
    );
    expect((await searchApi(q, "Controller.setTask"))[0]?.path).toBe("Controller:setTask");
    expect((await searchApi(q, "getByName")).map((h) => h.path)).toContain("Unit.getByName");
  });
});

describe("overlays", () => {
  const dir = () => mkdtempSync(join(tmpdir(), "api-overlays-"));

  it("compile and layer onto the page; stale ones are ignored", async () => {
    const d = dir();
    writeFileSync(
      join(d, "Unit.getByName.md"),
      "---\nsummary: Look a unit up.\nsince: 1.2.0\nseeAlso: [Group.getByName]\n---\n\n## Caveats\n\nReturns `nil` for dead units.\n",
    );
    writeFileSync(join(d, "Unit.gone.md"), "Stale.");
    const file = compileApiOverlays(d);
    const unit = applyOverlays((await getApiPage(q, "mission", "Unit")) as ApiPage, file);
    const m = member(unit, "getByName");
    expect(m?.summary).toBe("Look a unit up.");
    expect(m?.overlay?.html).toContain("<code>nil</code>");
    expect(m?.overlay?.text).toContain("dead units");
    expect(m?.overlay?.seeAlso).toEqual(["Group.getByName"]);
    expect(await staleApiOverlays(q, d)).toEqual([
      "content/api/Unit.gone.md: 'Unit.gone' is no symbol of the Lua API (stale overlay?)",
    ]);
  });

  it("the repository overlays are current", async () => {
    expect(await staleApiOverlays(q, resolve(__dirname, "../../content/api"))).toEqual([]);
  });

  it("reject unknown frontmatter keys and escape raw HTML", () => {
    expect(() => parseOverlay("content/api/Unit.md", "Unit.md", "---\ntitel: x\n---\n")).toThrow(
      OverlayError,
    );
    const d = dir();
    writeFileSync(join(d, "Unit.md"), "<script>alert(1)</script>");
    expect(compileApiOverlays(d).symbols.Unit?.html).not.toContain("<script>");
  });
});
