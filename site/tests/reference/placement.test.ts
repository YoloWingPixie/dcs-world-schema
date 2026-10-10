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
  return { doc, placement: placeRecord(catalog, doc, vctx) };
}

describe("record placement", () => {
  it("puts every top-level field the record carries in exactly one slot", async () => {
    const { doc, placement } = await place("weapons", "AIM_120C");
    const carried = [
      ...Object.keys(doc.data).filter((k) => k !== "_source"),
      ...Object.keys(doc.companion ?? {})
        .filter((k) => k !== "_source")
        .map((k) => `flight.${k}`),
    ];
    for (const path of carried) expect(placement.slots.has(path), path).toBe(true);
    expect(placement.slots.get("id")).toBe("header");
    expect(placement.slots.get("sourcePaths")).toBe("source");
    expect(placement.slots.get("flight.sourcePaths")).toBe("source");
    // The companion's link back to its weapon says nothing on the weapon's page.
    expect(placement.slots.get("flight.weapon")).toBe("hidden");
    const stripped = placement.strip.filter((s) => s.show === "value").map((s) => s.path);
    for (const path of stripped.filter((p) => !p.includes("."))) {
      expect(placement.slots.get(path)).toBe("strip");
    }
    // Each overview field is in no other section.
    const overview = placement.sections.find((s) => s.id === "overview");
    if (overview?.kind !== "overview") throw new Error("no overview");
    for (const f of overview.fields) expect(placement.slots.get(f)).toBe("overview");
  });

  it("orders sections: Overview (Scripting after it), own sections, the companion's, Source", async () => {
    const { placement } = await place("weapons", "AIM_120C");
    const ids = placement.sections.map((s) => s.id);
    expect(ids[0]).toBe("overview");
    expect(placement.scriptingAt).toBe(1);
    expect(ids.at(-1)).toBe("provenance");
    const flight = placement.sections.filter((s) => s.companion);
    expect(flight[0]?.id).toBe("flight-overview");
    expect(flight.every((s) => ids.indexOf(s.id) > ids.indexOf("overview"))).toBe(true);
  });

  it("drops a range record that only bounds its list of ranges", async () => {
    const { placement } = await place("radios", "F4U-1D_CW__radio1");
    expect(placement.slots.get("range")).toBe("hidden");
    expect(placement.slots.get("segments")).toBe("section");
    expect(placement.strip[0]).toMatchObject({ show: "coverage", text: "100–150, 220–390 MHz" });
  });
});
