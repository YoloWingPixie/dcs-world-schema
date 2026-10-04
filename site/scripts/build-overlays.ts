/**
 * Compiles the hand-written reference overlays (content/reference, see its README) into
 * public/overlays/reference.json, shipped with the site shell:
 *
 *   { series: { <series>: { intro?, records: { <id or slug>: overlay }, fields: { <path>: overlay } } } }
 *
 * Only the overlays themselves are checked here (Markdown, frontmatter keys). Whether
 * their series, records and fields still exist is a data question: the site ignores
 * stale ones at runtime and `pnpm check:overlays <sqlite>` reports them.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Overlay } from "../src/lib/types";
import { ANY_TARGET, type LoadedOverlay, loadOverlays } from "./lib/overlays";

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const contentDir = join(siteRoot, "content/reference");
const out = join(siteRoot, "public/overlays/reference.json");

const strip = ({ html, aliases, seeAlso, text }: LoadedOverlay): Overlay & { text: string } => ({
  html,
  text,
  ...(aliases ? { aliases } : {}),
  ...(seeAlso ? { seeAlso } : {}),
});

const overlays = loadOverlays(contentDir, () => ANY_TARGET);
const series: Record<string, unknown> = {};
for (const [name, o] of overlays) {
  series[name] = {
    ...(o.intro ? { intro: strip(o.intro) } : {}),
    records: Object.fromEntries([...o.records].map(([k, v]) => [k, strip(v)])),
    fields: Object.fromEntries([...o.fields].map(([k, v]) => [k, strip(v)])),
  };
}
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify({ series }));
console.log(`overlays: ${overlays.size} series -> ${out}`);
