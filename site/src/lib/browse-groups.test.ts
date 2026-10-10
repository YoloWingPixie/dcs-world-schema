import { describe, expect, it } from "vitest";
import { columnWidth, groupRows, layoutItems, visibleRange } from "./browse-groups";

type R = { name: string; unit?: string };
const rows: R[] = [
  { name: "Desert", unit: "M-1 Abrams" },
  { name: "Aggressor", unit: "F-16CM bl.50" },
  { name: "Prop" },
  { name: "Woodland", unit: "M-1 Abrams" },
  { name: "Grey", unit: "F-16CM bl.50" },
];
const groupOf = (r: R) =>
  r.unit ? { key: r.unit, label: r.unit } : { key: "none", label: "No airframe" };

describe("groupRows", () => {
  it("sorts groups by label, keeps row order inside, sends `last` keys to the end", () => {
    const groups = groupRows(rows, groupOf, (k) => k === "none");
    expect(groups.map((g) => g.label)).toEqual(["F-16CM bl.50", "M-1 Abrams", "No airframe"]);
    expect(groups[0]?.rows.map((r) => r.name)).toEqual(["Aggressor", "Grey"]);
    expect(groups[1]?.rows.map((r) => r.name)).toEqual(["Desert", "Woodland"]);
  });

  it("only makes groups that have rows", () => {
    const groups = groupRows(
      rows.filter((r) => r.name !== "Prop"),
      groupOf,
    );
    expect(groups.map((g) => g.key)).toEqual(["F-16CM bl.50", "M-1 Abrams"]);
    expect(groupRows([], groupOf)).toEqual([]);
  });

  it("orders numbered labels numerically", () => {
    const g = groupRows(
      [
        { name: "a", unit: "F-15" },
        { name: "b", unit: "F-5" },
      ],
      groupOf,
    );
    expect(g.map((x) => x.label)).toEqual(["F-5", "F-15"]);
  });
});

describe("layoutItems and visibleRange", () => {
  it("puts a head before each group's rows with cumulative tops", () => {
    const { items, tops } = layoutItems({ groups: groupRows(rows, groupOf) }, 10, 30);
    expect(items.map((i) => (i.kind === "group" ? `#${i.number}` : i.row.name))).toEqual([
      "#1",
      "Aggressor",
      "Grey",
      "#2",
      "Desert",
      "Woodland",
      "#3",
      "Prop",
    ]);
    expect(tops).toEqual([0, 30, 40, 50, 80, 90, 100, 130, 140]);
  });

  it("lays flat rows at a fixed pitch", () => {
    const { items, tops } = layoutItems({ rows }, 10, 30);
    expect(items).toHaveLength(5);
    expect(tops.at(-1)).toBe(50);
  });

  it("finds the items a viewport overlaps", () => {
    const { tops } = layoutItems({ groups: groupRows(rows, groupOf) }, 10, 30);
    expect(visibleRange(tops, 0, 35, 0)).toEqual([0, 2]);
    expect(visibleRange(tops, 45, 30, 0)).toEqual([2, 4]);
    expect(visibleRange(tops, 45, 30, 1)).toEqual([1, 5]);
    expect(visibleRange(tops, 1000, 30, 2)).toEqual([5, 8]);
    expect(visibleRange([0], 0, 100, 2)).toEqual([0, 0]);
  });
});

describe("columnWidth", () => {
  it("sizes to the 90th percentile of all cells, at least the head, at most 30ch", () => {
    const lengths = [...Array.from({ length: 95 }, () => 8), 60, 60, 60, 60, 60];
    expect(columnWidth(lengths, 4)).toBe(9);
    expect(columnWidth([3, 3], 12)).toBe(14);
    expect(columnWidth([], 2)).toBe(6);
    expect(columnWidth([80, 80], 4)).toBe(30);
  });
});
