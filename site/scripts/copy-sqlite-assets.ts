/**
 * Puts what the browser needs to query the reference database under public/:
 *
 *   public/sqlite/sqlite.worker.js, sql-wasm.wasm   from sql.js-httpvfs (worker patched below)
 *   public/data/reference.json + the database       scripts/split-sqlite.ts
 *   public/_redirects                               deep links serve the shell (Cloudflare Pages)
 *
 * The database comes from SITE_SQLITE (a path), else the newest
 * ../dist/dcs-world-reference-*.sqlite; SITE_DB_MODE=chunked splits it as deployed
 * (default: one file). SITE_SQLITE=none skips it: the deploy adds the database next to
 * the built shell (.github/workflows/site.yml).
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { findDatabase, type Mode, publish } from "./split-sqlite";

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const lib = join(siteRoot, "node_modules/sql.js-httpvfs/dist");
mkdirSync(join(siteRoot, "public/sqlite"), { recursive: true });
copyFileSync(join(lib, "sql-wasm.wasm"), join(siteRoot, "public/sqlite/sql-wasm.wasm"));

// sql.js-httpvfs 0.8.12 drops the config's maxReadSpeed; pass it through so chunked mode
// can cap read-ahead at one part (a request never spans two part files).
const worker = readFileSync(join(lib, "sqlite.worker.js"), "utf8");
const call = "logPageReads:!0,maxReadHeads:3,";
if (worker.split(call).length !== 2) {
  throw new Error("sql.js-httpvfs worker changed: update the maxReadSpeed patch");
}
writeFileSync(
  join(siteRoot, "public/sqlite/sqlite.worker.js"),
  worker.replace(call, `${call}maxReadSpeed:e.maxReadSpeed,`),
);

if (process.env.SITE_SQLITE === "none") {
  console.log("sqlite assets: worker and wasm (no database)");
} else {
  const source = findDatabase();
  if (!source || !existsSync(source)) {
    throw new Error("No reference database: run `task package` or set SITE_SQLITE.");
  }
  const mode: Mode = process.env.SITE_DB_MODE === "chunked" ? "chunked" : "full";
  const config = publish(join(siteRoot, "public"), source, mode);
  console.log(`sqlite assets: worker, wasm and ${config.file} (${mode}) -> public/data`);
}
