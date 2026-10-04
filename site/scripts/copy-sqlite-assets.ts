/**
 * Puts what the browser needs to query the reference database under public/:
 *
 *   public/sqlite/sqlite.worker.js, sql-wasm.wasm   from sql.js-httpvfs
 *   public/data/reference.sqlite                    the database (local dev, e2e)
 *
 * The database comes from SITE_SQLITE (a path), else the newest
 * ../dist/dcs-world-reference-*.sqlite. SITE_SQLITE=none skips it: a Pages deploy
 * adds the released file next to the built shell instead (.github/workflows/pages.yml).
 */
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const lib = join(siteRoot, "node_modules/sql.js-httpvfs/dist");
mkdirSync(join(siteRoot, "public/sqlite"), { recursive: true });
for (const file of ["sqlite.worker.js", "sql-wasm.wasm"]) {
  copyFileSync(join(lib, file), join(siteRoot, "public/sqlite", file));
}

const given = process.env.SITE_SQLITE;
if (given === "none") {
  console.log("sqlite assets: worker and wasm (no database)");
} else {
  let source = given ? resolve(given) : null;
  if (!source) {
    const dist = resolve(siteRoot, "../dist");
    source =
      (existsSync(dist) ? readdirSync(dist) : [])
        .filter((f) => /^dcs-world-reference-.*\.sqlite$/.test(f))
        .map((f) => join(dist, f))
        .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0] ?? null;
  }
  if (!source || !existsSync(source)) {
    throw new Error("No reference database: run `task package` or set SITE_SQLITE.");
  }
  const target = join(siteRoot, "public/data/reference.sqlite");
  mkdirSync(dirname(target), { recursive: true });
  if (!existsSync(target) || statSync(target).mtimeMs < statSync(source).mtimeMs) {
    copyFileSync(source, target);
  }
  console.log(`sqlite assets: worker, wasm and ${source} -> public/data/reference.sqlite`);
}
