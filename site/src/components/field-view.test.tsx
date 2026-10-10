import { describe, expect, it } from "vitest";
import type { CatalogEntry } from "@/lib/types";
import { fieldDataAttrs, readFieldTarget } from "./field-view";

const entry = {
  path: "massKg",
  name: "massKg",
  label: "Mass",
  kind: "number",
  unit: "kg",
  unitNotStated: false,
  description: "",
  dcsKey: null,
  compareAs: "value",
} as CatalogEntry;

/** The element dataset the attributes give (`data-field-label` -> `fieldLabel`). */
const datasetOf = (attrs: Record<string, string>) => ({
  dataset: Object.fromEntries(
    Object.entries(attrs).map(([k, v]) => [
      k.slice(5).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase()),
      v,
    ]),
  ),
});

describe("field data attributes", () => {
  const ctx = { series: "weapons", slug: "AIM_120C", recordName: "AIM-120C" };
  const vctx = { enums: {}, system: "metric" as const };

  it("read back as the field they were written for", () => {
    const attrs = fieldDataAttrs(entry, "massKg", 161.5, ctx, vctx);
    expect(attrs["data-field"]).toBe("massKg");
    expect(readFieldTarget(datasetOf(attrs))).toEqual({
      path: "massKg",
      label: "Mass",
      comparable: true,
      text: attrs["data-field-text"],
      stored: attrs["data-field-stored"] ?? null,
      series: "weapons",
      record: "AIM_120C",
      recordName: "AIM-120C",
    });
    const { compareAs: _compareAs, ...notCompared } = entry;
    const off = fieldDataAttrs(notCompared, "massKg", 1, ctx, vctx, "Weight");
    expect(readFieldTarget(datasetOf(off))).toMatchObject({ comparable: false, label: "Weight" });
  });

  it("read as nothing when an attribute is missing or malformed", () => {
    const attrs = fieldDataAttrs(entry, "massKg", 161.5, ctx, vctx);
    for (const name of ["data-field", "data-series", "data-record", "data-field-comparable"]) {
      const { [name]: _, ...rest } = attrs;
      expect(readFieldTarget(datasetOf(rest)), name).toBeNull();
    }
    expect(readFieldTarget(datasetOf({ ...attrs, "data-field-comparable": "maybe" }))).toBeNull();
  });
});
