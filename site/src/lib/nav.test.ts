import { describe, expect, it } from "vitest";
import { isShellHref } from "@/components/ref-link";
import { currentSection, NAV_SECTIONS, PAGE_ROOTS, pathRoot } from "./nav";

const section = (id: string) => NAV_SECTIONS.find((s) => s.id === id);

describe("nav sections", () => {
  it("carry what the header needs: prefetch, class and the compare selection", () => {
    expect(section("api")).toMatchObject({ kind: "shell", prefetch: false });
    expect(section("reference")).toMatchObject({ kind: "page", className: "nav-browse" });
    expect(section("compare")).toMatchObject({ kind: "page", compare: true });
    expect(NAV_SECTIONS.filter((s) => s.compare).map((s) => s.id)).toEqual(["compare"]);
    // Only a shell section skips prefetch (its route tree is the 404 shell).
    for (const s of NAV_SECTIONS) expect(s.prefetch === false).toBe(s.kind === "shell");
  });

  it("give the Next.js page roots: page sections, home and search", () => {
    expect([...PAGE_ROOTS].sort()).toEqual(["", "compare", "reference", "search"]);
    expect(pathRoot("/compare/?s=weapons")).toBe("compare");
    expect(pathRoot("/")).toBe("");
  });

  it("route a section's links by its kind", () => {
    for (const s of NAV_SECTIONS) expect(isShellHref(s.href)).toBe(s.kind === "shell");
    expect(isShellHref("/aircraft/F-16C_50/")).toBe(true);
    expect(isShellHref("/search/?q=aim")).toBe(false);
    expect(isShellHref("/")).toBe(false);
  });

  it("mark the section a path belongs to", () => {
    expect(currentSection("/aircraft/F-16C_50/")?.id).toBe("reference");
    expect(currentSection("/compare/")?.id).toBe("compare");
    expect(currentSection("/api/Unit/")?.id).toBe("api");
    expect(currentSection("/search/")).toBeNull();
  });
});
