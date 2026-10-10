/**
 * Reports overlays (content/reference, content/api) whose target is not in a
 * reference database: `pnpm check:overlays <path/to/reference.sqlite>`. Exits 1 when
 * any is stale. The site itself ignores stale overlays, so this never blocks a deploy.
 */
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { COMPANION_PREFIX } from "../src/lib/catalog";
import { catalogFor, loadModel, qi } from "../src/lib/db/reference";
import { slugify } from "../src/lib/series-display";
import { staleApiOverlays } from "./check-api-overlays";
import { loadOverlays, OverlayError } from "./lib/overlays";
import { nodeQuery } from "./lib/sqlite";

const siteRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const path = process.argv[2];
if (!path) {
  console.error("usage: pnpm check:overlays <reference.sqlite>");
  process.exit(2);
}
const q = nodeQuery(resolve(path));
const model = await loadModel(q);

const ids = new Map<string, Map<string, string>>();
for (const s of model.series) {
  const rows = await q(`SELECT ${qi(s.keyColumn)} AS id FROM ${qi(s.id)}`);
  const map = new Map<string, string>();
  for (const r of rows) {
    const id = String(r.id);
    map.set(id, id);
    map.set(slugify(id), id);
  }
  ids.set(s.id, map);
}

const apiStale = await staleApiOverlays(q);
for (const message of apiStale) console.error(message);
if (apiStale.length) process.exitCode = 1;

try {
  loadOverlays(join(siteRoot, "content/reference"), (series) => {
    const s = model.byId.get(series);
    if (!s) return null;
    const owner = s.parent ?? s.id;
    const catalog = catalogFor(model, owner);
    return {
      record: (stem) => ids.get(series)?.get(stem) ?? null,
      field: (p) => Boolean(catalog.entries[s.parent ? `${COMPANION_PREFIX}.${p}` : p]),
    };
  });
  console.log(`overlays: all current against ${path}`);
} catch (error) {
  if (error instanceof OverlayError) {
    console.error(error.message);
    process.exit(1);
  }
  throw error;
}
