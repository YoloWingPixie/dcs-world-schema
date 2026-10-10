import { beforeAll, describe, expect, it } from "vitest";
import { catalogFor, getRecord, loadModel, type Model } from "../../src/lib/db/reference";
import type { ValueContext } from "../../src/lib/format-field";
import { placeRecord } from "../../src/lib/placement";
import type { RecordDoc } from "../../src/lib/types";
import { nodeQuery } from "./db";

const q = nodeQuery();
let model: Model;
beforeAll(async () => {
  model = await loadModel(q);
});

async function place(series: string, id: string) {
  const doc = (await getRecord(q, model, series, id)) as RecordDoc;
  const catalog = catalogFor(model, series);
  const vctx: ValueContext = { enums: catalog.enums, system: "metric", links: doc.links };
  return { doc, catalog, placement: placeRecord(catalog, doc, vctx) };
}

/** Top-level catalog paths each section shows, by section id. */
function placed(placement: ReturnType<typeof placeRecord>): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const s of placement.sections) {
    const paths =
      s.kind === "overview"
        ? s.fields.map((f) => (s.prefix ? `${s.prefix}.${f}` : f))
        : s.kind === "source"
          ? s.fields.map((f) => f.path)
          : [s.path];
    out.set(s.id, paths);
  }
  return out;
}

describe("record placement", () => {
  it("puts every top-level field the record carries in at most one place", async () => {
    const { doc, placement } = await place("weapons", "AIM_120C");
    const bySection = placed(placement);
    const all = [...bySection.values()].flat();
    expect(new Set(all).size).toBe(all.length);
    expect(bySection.get("provenance")).toEqual(
      expect.arrayContaining(["sourcePaths", "flight.sourcePaths"]),
    );
    // The header shows the id; the companion's link back to its weapon says nothing here.
    expect(all).not.toContain("id");
    expect(all).not.toContain("flight.weapon");
    // Key figures in the strip are not repeated in an Overview.
    const stripped = placement.strip.filter((s) => s.show === "value").map((s) => s.path);
    for (const path of stripped) expect(all, path).not.toContain(path);
    // Everything else the record carries is placed.
    const carried = Object.keys(doc.data).filter(
      (k) => k !== "_source" && k !== "id" && !stripped.includes(k),
    );
    for (const path of carried) expect(all, path).toContain(path);
  });

  it("puts friendly classifications first in every Overview", async () => {
    const { placement, catalog } = await place("weapons", "AIM_120C");
    for (const s of placement.sections) {
      if (s.kind !== "overview") continue;
      const kinds = s.fields.map((f) => catalog.entries[s.prefix ? `${s.prefix}.${f}` : f]?.kind);
      // Numbers last, the companion's Overview included.
      const firstNumber = kinds.indexOf("number");
      if (firstNumber >= 0)
        expect(kinds.slice(firstNumber).every((k) => k === "number")).toBe(true);
    }
    const overview = placement.sections.find((s) => s.id === "overview");
    if (overview?.kind !== "overview") throw new Error("no overview");
    expect(overview.fields.slice(0, 2)).toEqual(["categoryName", "subcategoryName"]);
  });

  it("orders sections: Overview (Scripting after it), own sections, the companion's, Source", async () => {
    const { placement } = await place("weapons", "AIM_120C");
    const ids = placement.sections.map((s) => s.id);
    expect(ids[0]).toBe("overview");
    expect(placement.scriptingAt).toBe(1);
    expect(ids.at(-1)).toBe("provenance");
    const flight = placement.sections.filter((s) => s.companion);
    expect(flight[0]).toMatchObject({ id: "flight-overview", title: "Flight model" });
    expect(flight.every((s) => ids.indexOf(s.id) > ids.indexOf("overview"))).toBe(true);
  });

  it("drops a range record that only bounds its list of ranges", async () => {
    const { placement } = await place("radios", "F4U-1D_CW__radio1");
    const all = [...placed(placement).values()].flat();
    expect(all).not.toContain("range");
    expect(placed(placement).get("segments")).toEqual(["segments"]);
    expect(placement.strip[0]).toMatchObject({ show: "coverage", text: "100–150, 220–390 MHz" });
  });
});
