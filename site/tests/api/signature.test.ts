import { describe, expect, it } from "vitest";
import { splitSignature, tokenText } from "../../src/components/api/signature";
import type { Token } from "../../src/lib/api/types";

const text = (parts: Token[][] | null) => parts?.map(tokenText);

describe("splitSignature", () => {
  it("splits at the outer parentheses and top-level commas", () => {
    const sig: Token[] = [
      "coord.LLtoLO(lat: number | ",
      { r: "LatLon" },
      ", lon?: number): ",
      { r: "Vec2" },
    ];
    const parts = splitSignature(sig);
    expect(text(parts)).toEqual([
      "coord.LLtoLO(",
      "lat: number | LatLon, ",
      "lon?: number",
      "): Vec2",
    ]);
    expect(
      parts
        ?.flat()
        .map((t) => tokenText([t]))
        .join(""),
    ).toBe(tokenText(sig));
  });

  it("keeps nested commas inside a parameter", () => {
    const parts = splitSignature([
      "f(a: table<string, number>, b: fun(x: number, y: number): boolean): nil",
    ]);
    expect(text(parts)).toEqual([
      "f(",
      "a: table<string, number>, ",
      "b: fun(x: number, y: number): boolean",
      "): nil",
    ]);
  });

  it("leaves one-parameter and parameterless signatures alone", () => {
    expect(splitSignature(["Unit.getByName(name: string): Unit?"])).toBeNull();
    expect(splitSignature(["timer.getTime(): number"])).toBeNull();
    expect(splitSignature(["Unit.name: string"])).toBeNull();
  });
});
