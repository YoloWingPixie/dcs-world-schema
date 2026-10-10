/**
 * The `_G` dump files behind a record's `sourcePaths` (published by scripts/copy-lua-assets.ts
 * under data/lua/<hash>/), fetched only when the "View Lua" drawer opens.
 */

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** One dump path the drawer can show: the file and, for a block, the pointer into it. */
export type LuaSource = {
  /** `_G/a/b`. */
  path: string;
  /** `/x/[1]` for a block's subtree, "" for the whole file. */
  pointer: string;
};

/** `{ path, pointer }` of `<dump path>[#<pointer>]`. */
export function splitSourcePath(sourcePath: string): LuaSource {
  const hash = sourcePath.indexOf("#");
  return hash < 0
    ? { path: sourcePath, pointer: "" }
    : { path: sourcePath.slice(0, hash), pointer: sourcePath.slice(hash + 1) };
}

/** The dump-relative file of a dump path (`_G/a/b` -> `a/b.lua`); null if it is none. */
export function dumpFile(path: string): string | null {
  if (!path.startsWith("_G/") || path.length === 3) return null;
  const rel = path.slice(3);
  if (rel.split("/").some((s) => s === "" || s === "." || s === "..")) return null;
  return `${rel}.lua`;
}

/** `F-16C_50` of `_G/db/Units/Planes/Plane/F-16C_50`. */
export const fileStem = (path: string) => path.slice(path.lastIndexOf("/") + 1);

export type LuaBlock = {
  /** Where the record holds it, e.g. `flight.aerodynamics`. */
  label: string;
  sourcePath: string;
};

/**
 * The dump paths of a record: its `sourcePaths` (data first, then the companion's) and the
 * `sourcePath` of every block, by file in first-seen order.
 */
export function recordSources(
  data: Record<string, unknown> | undefined,
  companion?: Record<string, unknown> | undefined,
  companionPrefix = "flight",
): { files: string[]; blocks: LuaBlock[] } {
  const files: string[] = [];
  const blocks: LuaBlock[] = [];
  const addFile = (p: string) => {
    if (dumpFile(p) && !files.includes(p)) files.push(p);
  };
  const roots: Array<[Record<string, unknown> | undefined, string]> = [
    [data, ""],
    [companion, companionPrefix],
  ];
  for (const [root] of roots) {
    const paths = root?.sourcePaths;
    if (Array.isArray(paths)) for (const p of paths) if (typeof p === "string") addFile(p);
  }
  if (!files.length) return { files, blocks };
  const walk = (node: unknown, label: string) => {
    if (Array.isArray(node)) {
      node.forEach((v, i) => {
        walk(v, `${label}[${i}]`);
      });
    } else if (node && typeof node === "object") {
      for (const [k, v] of Object.entries(node)) {
        if (k === "sourcePath" && typeof v === "string") {
          const { path, pointer } = splitSourcePath(v);
          if (dumpFile(path)) {
            if (pointer) blocks.push({ label: label || "(record)", sourcePath: v });
            addFile(path);
          }
        } else if (k !== "sourcePaths") {
          walk(v, label ? `${label}.${k}` : k);
        }
      }
    }
  };
  for (const [root, prefix] of roots) if (root) walk(root, prefix);
  return { files, blocks };
}

type LuaConfig = { base: string; files: number; bytes: number; sha256: string };

/** A dump file this build does not have (its lua.json or the file is absent). */
export class LuaMissing extends Error {}

let config: Promise<LuaConfig | null> | null = null;
const texts = new Map<string, Promise<string>>();

/** data/lua.json; null when the build published no Lua (scripts/copy-lua-assets.ts). */
function loadConfig(): Promise<LuaConfig | null> {
  if (!config) {
    const loading = fetch(`${BASE_PATH}/data/lua.json`).then(async (r) => {
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`data/lua.json: HTTP ${r.status}`);
      return (await r.json()) as LuaConfig;
    });
    loading.catch(() => {
      config = null;
    });
    config = loading;
  }
  return config;
}

/** Whether this build has Lua files to show. */
export const luaAvailable = () => loadConfig().then((c) => c !== null);

/** The text of the dump file of `path` (`_G/a/b`); LuaMissing when the build lacks it. */
export function loadLua(path: string): Promise<string> {
  const hit = texts.get(path);
  if (hit) return hit;
  const file = dumpFile(path);
  const promise = (async () => {
    if (!file) throw new LuaMissing(`Not a dump path: ${path}`);
    const conf = await loadConfig();
    if (!conf) throw new LuaMissing("This build has no Lua files.");
    const url = `${BASE_PATH}/data/${conf.base}${file.split("/").map(encodeURIComponent).join("/")}`;
    const r = await fetch(url);
    if (r.status === 404) throw new LuaMissing(`No Lua file for ${path}.`);
    if (!r.ok) throw new Error(`No Lua file for ${path} (HTTP ${r.status}).`);
    return r.text();
  })();
  promise.catch(() => texts.delete(path));
  texts.set(path, promise);
  return promise;
}

/** Each path's shortest trailing segments that no other path in `paths` ends with. */
export function shortLabels(paths: string[]): string[] {
  const parts = paths.map((p) => p.split("/"));
  return parts.map((segs, i) => {
    for (let n = 1; n < segs.length; n++) {
      const tail = segs.slice(-n).join("/");
      if (parts.every((o, j) => j === i || o.slice(-n).join("/") !== tail)) return tail;
    }
    return segs.join("/");
  });
}
