/**
 * Publishes the _G dump files the records point into, for the "View Lua" drawer:
 *
 *   public/data/lua.json              { base, files, bytes, sha256 }: its absence hides View Lua
 *   public/data/lua/<hash>/<a/b>.lua  one per dump file (`_G/a/b`), byte for byte
 *
 * The directory is the tree's content hash, so a new tree never mixes with cached files of
 * an old one (public/_headers marks it immutable).
 *
 * The files come from the dump, which is not committed: tools/datamine/dump_lua.py `collect`
 * copies the ones the records of ../dcs-world-reference/latest reference out of
 * ../.datamine/_G when it is that DCS version, else out of the dump's release asset
 * (dump_lua.py `pack`; cached in ../.datamine/, downloaded when absent, GITHUB_TOKEN if set).
 * Without either, or without uv, the site builds without Lua.
 *
 *   SITE_LUA=<dir>   publish an already collected tree (CI: .github/workflows/site.yml)
 *   SITE_LUA=none    publish none
 *   SITE_LUA_REQUIRED=1  fail instead of building without Lua
 *
 *   node scripts/copy-lua-assets.ts [site-dir]   (default: public)
 */

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export type LuaConfig = {
  /** Directory of the files, relative to data/ (ends in "/"). */
  base: string;
  files: number;
  bytes: number;
  sha256: string;
};

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Every file under `root` as POSIX relative paths, sorted. */
export function listTree(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) out.push(relative(root, path).split(sep).join("/"));
    }
  };
  walk(root);
  return out.sort();
}

/** Content hash of a tree: each file's path and bytes, in path order. */
export function treeHash(root: string, files: string[]): { sha256: string; bytes: number } {
  const hash = createHash("sha256");
  let bytes = 0;
  for (const rel of files) {
    const data = readFileSync(join(root, rel));
    bytes += data.length;
    hash.update(rel).update("\0").update(data).update("\0");
  }
  return { sha256: hash.digest("hex"), bytes };
}

/** Remove published Lua files: the drawer's button then stays hidden. */
export function clearLua(siteDir: string) {
  rmSync(join(siteDir, "data/lua.json"), { force: true });
  rmSync(join(siteDir, "data/lua"), { recursive: true, force: true });
}

export function publishLua(siteDir: string, tree: string): LuaConfig | null {
  const dataDir = join(siteDir, "data");
  const configPath = join(dataDir, "lua.json");
  const outRoot = join(dataDir, "lua");
  if (!existsSync(tree)) {
    clearLua(siteDir);
    return null;
  }
  const files = listTree(tree);
  const { sha256, bytes } = treeHash(tree, files);
  const dir = sha256.slice(0, 16);
  const config: LuaConfig = { base: `lua/${dir}/`, files: files.length, bytes, sha256 };

  const previous = existsSync(configPath) ? readFileSync(configPath, "utf8") : null;
  const text = `${JSON.stringify(config, null, 2)}\n`;
  const first = files[0];
  if (previous === text && (!first || existsSync(join(outRoot, dir, first)))) return config;

  rmSync(outRoot, { recursive: true, force: true });
  for (const rel of files) {
    const target = join(outRoot, dir, rel);
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(join(tree, rel), target);
  }
  mkdirSync(dataDir, { recursive: true });
  writeFileSync(configPath, text);
  return config;
}

const repoRoot = resolve(siteRoot, "..");
const cacheDir = join(repoRoot, ".datamine");
const REPO =
  process.env.SITE_LUA_REPO ?? process.env.GITHUB_REPOSITORY ?? "YoloWingPixie/dcs-world-schema";

function readText(path: string): string | null {
  try {
    return readFileSync(path, "utf8").trim();
  } catch {
    return null;
  }
}

/** The release asset of the data's DCS version, downloaded into .datamine/ when absent. */
async function dumpArchive(tag: string, asset: string): Promise<string> {
  const path = join(cacheDir, asset);
  if (existsSync(path)) return path;
  const url = `https://github.com/${REPO}/releases/download/${tag}/${asset}`;
  const token = process.env.GITHUB_TOKEN;
  const response = await fetch(url, token ? { headers: { Authorization: `Bearer ${token}` } } : {});
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  mkdirSync(cacheDir, { recursive: true });
  writeFileSync(`${path}.part`, Buffer.from(await response.arrayBuffer()));
  renameSync(`${path}.part`, path);
  return path;
}

/** Collect the referenced dump files into .datamine/site-lua (dump_lua.py); the tree. */
async function collectLocal(): Promise<string> {
  const manifest = join(repoRoot, "dcs-world-reference/latest/manifest.json");
  const version = (JSON.parse(readFileSync(manifest, "utf8")) as { dcsVersion: string }).dcsVersion;
  const gDir = join(cacheDir, "_G");
  const source =
    readText(join(gDir, "__DCS_VERSION__.lua")) === version
      ? ["--g-dir", gDir]
      : ["--archive", await dumpArchive(`dcs-dump-${version}`, `dcs-g-dump-${version}.tar.gz`)];
  const out = join(cacheDir, "site-lua");
  const run = spawnSync(
    "uv",
    ["run", "python", "-m", "tools.datamine.dump_lua", "collect", ...source, "--out", out],
    { cwd: repoRoot, stdio: ["ignore", "inherit", "inherit"] },
  );
  if (run.error) throw run.error;
  if (run.status !== 0) throw new Error(`dump_lua collect exited ${run.status}`);
  return out;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const siteDir = resolve(process.argv[2] ?? join(siteRoot, "public"));
  const given = process.env.SITE_LUA;
  let config: LuaConfig | null = null;
  let reason = "SITE_LUA=none";
  try {
    if (given !== "none") {
      const tree = given ? resolve(given) : await collectLocal();
      if (!existsSync(tree)) throw new Error(`no ${tree}`);
      config = publishLua(siteDir, tree);
    }
  } catch (e) {
    reason = e instanceof Error ? e.message : String(e);
    if (process.env.SITE_LUA_REQUIRED === "1") throw e;
  }
  if (!config) clearLua(siteDir);
  console.log(
    config
      ? `lua assets: ${config.files} files (${(config.bytes / 1e6).toFixed(1)} MB) -> data/${config.base}`
      : `lua assets: none (${reason}); View Lua stays hidden`,
  );
}
