/**
 * Reports overlays (content/reference, content/api) whose target is not in a
 * reference database: `pnpm check:overlays <path/to/reference.sqlite>`. Exits 1 when
 * any is stale. The site build (scripts/build-overlays.ts) fails on stale reference
 * overlays too, when it has a database.
 */
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { staleApiOverlays } from "./check-api-overlays";
import { loadOverlays, OverlayError, overlayTargets } from "./lib/overlays";
import { nodeQuery } from "./lib/sqlite";

const siteRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const path = process.argv[2];
if (!path) {
  console.error("usage: pnpm check:overlays <reference.sqlite>");
  process.exit(2);
}
const q = nodeQuery(resolve(path));

const apiStale = await staleApiOverlays(q);
for (const message of apiStale) console.error(message);
if (apiStale.length) process.exitCode = 1;

try {
  loadOverlays(join(siteRoot, "content/reference"), await overlayTargets(q));
  console.log(`overlays: all current against ${path}`);
} catch (error) {
  if (error instanceof OverlayError) {
    console.error(error.message);
    process.exit(1);
  }
  throw error;
}
