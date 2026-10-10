/**
 * Writes src/lib/compare-fields.json: every series' comparable fields (`compareAs` set in
 * its catalog, scripts/lib/compare-fields.ts), which `task package:sqlite`
 * (tools/package/site_views.py) precomputes into the database's `field_values`. The
 * catalog is built from the database's own `schema_types`, so run this against a fresh
 * database after a schema change, then package again:
 *
 *   pnpm gen:compare-fields [path/to/reference.sqlite]
 *
 * The reference tests (tests/reference/field-values.test.ts) fail while the file differs
 * from what the test database gives.
 */
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadModel } from "../src/lib/db/reference";
import { compareFields } from "./lib/compare-fields";
import { nodeQuery } from "./lib/sqlite";

const siteRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const out = join(siteRoot, "src/lib/compare-fields.json");
const given = process.argv[2];
const q = nodeQuery(...(given ? [resolve(given)] : []));
const spec = compareFields(await loadModel(q));
writeFileSync(out, `${JSON.stringify(spec)}\n`);
execFileSync(join(siteRoot, "node_modules/.bin/biome"), ["format", "--write", out], {
  cwd: siteRoot,
  stdio: "ignore",
});
const fields = Object.values(spec).reduce((n, s) => n + s.fields.length, 0);
console.log(`compare fields: ${fields} in ${Object.keys(spec).length} series -> ${out}`);
