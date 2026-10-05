/**
 * Publishes the reference database into a site folder:
 *
 *   <site>/data/reference.json        what the browser opens (lib/db/browser.ts)
 *   <site>/data/reference.sqlite      single-file mode (local dev, e2e)
 *   <site>/data/db/<hash>/part.NNNNN  chunked mode (Cloudflare Pages)
 *   <site>/_redirects                 deep links under each series and /api/ serve the shell
 *
 * Chunked: Cloudflare Pages answers Range requests with the whole file (200), so each part
 * is fetched whole and is one sql.js-httpvfs request chunk. Parts live under the database's
 * content hash, so a new database never mixes with cached parts of an old one.
 *
 *   node scripts/split-sqlite.ts <site-dir> [--mode=full|chunked] [--part-size=bytes] [--db=path]
 *
 * The database is --db, else SITE_SQLITE, else the newest ../dist/dcs-world-reference-*.sqlite.
 * Runs under plain Node (type stripping): node: imports only.
 */
import { createHash } from "node:crypto";
import {
  closeSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  readSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

export type Mode = "full" | "chunked";

/** Matches PAGE_SIZE in tools/package/sqlite.py. */
const PAGE = 4096;
/** 32 KiB: ~1,330 parts for 44 MB (Pages allows 20,000 files); ~70 requests, ~2 MB per record page. */
export const DEFAULT_PART_SIZE = 32 * 1024;

export type ReferenceConfig = {
  /** sql.js-httpvfs config; url / urlPrefix are relative to this file. */
  serverMode: Mode;
  url?: string;
  urlPrefix?: string;
  serverChunkSize?: number;
  suffixLength?: number;
  requestChunkSize: number;
  /** Read-ahead cap (patched into the worker by copy-sqlite-assets): one part per request. */
  maxReadSpeed?: number;
  databaseLengthBytes: number;
  /**
   * Chunked: the parts each page reads first, fetched in parallel at startup (see
   * BOOT_GROUPS): every page, search, the API docs. Indexes into the part files.
   */
  boot?: { core: number[]; search: number[]; api: number[] };
  /** The released file and its hash, for display. */
  file: string;
  version: string | null;
  sha256: string;
};

/**
 * The pages a client reads first: [whole tables, tables or indexes whose interior pages].
 * Mirrors BOOT_GROUPS in tools/package/sqlite.py, which lays these pages out together.
 */
const BOOT_GROUPS: Record<"core" | "search" | "api", [string[], string[]]> = {
  core: [
    ["sqlite_schema", "sqlite_master", "meta", "series", "ref_paths", "schema_types"],
    [
      "record_views",
      "sqlite_autoindex_record_views_1",
      "series_views",
      "sqlite_autoindex_series_views_1",
    ],
  ],
  search: [
    ["search_fts_config"],
    [
      "search",
      "sqlite_autoindex_search_1",
      "search__names",
      "search_fts_data",
      "search_fts_idx",
      "search_fts_docsize",
    ],
  ],
  api: [
    [],
    [
      "api_symbols",
      "sqlite_autoindex_api_symbols_1",
      "api_symbols__path",
      "api_symbols__pages",
      "api_type_uses",
      "sqlite_autoindex_api_type_uses_1",
    ],
  ],
};

/** Part indexes holding each boot group's pages (dbstat), each group without earlier ones. */
export function bootParts(path: string, partSize: number): NonNullable<ReferenceConfig["boot"]> {
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    const seen = new Set<number>();
    const marks = (n: number) => Array.from({ length: n }, () => "?").join(",");
    const pick = ([whole, upper]: [string[], string[]]) => {
      const pages = new Set<number>([1]);
      const rows = [
        ...(whole.length
          ? db
              .prepare(`SELECT pageno FROM dbstat WHERE name IN (${marks(whole.length)})`)
              .all(...whole)
          : []),
        ...db
          .prepare(
            `SELECT pageno FROM dbstat WHERE name IN (${marks(upper.length)}) AND pagetype = 'internal'`,
          )
          .all(...upper),
        ...db
          .prepare(
            `SELECT rootpage AS pageno FROM sqlite_master WHERE name IN (${marks(upper.length)})`,
          )
          .all(...upper),
      ] as { pageno: number }[];
      for (const r of rows) pages.add(Number(r.pageno));
      const parts = [...new Set([...pages].map((p) => Math.floor(((p - 1) * PAGE) / partSize)))]
        .filter((p) => !seen.has(p))
        .sort((a, b) => a - b);
      for (const p of parts) seen.add(p);
      return parts;
    };
    return {
      core: pick(BOOT_GROUPS.core),
      search: pick(BOOT_GROUPS.search),
      api: pick(BOOT_GROUPS.api),
    };
  } finally {
    db.close();
  }
}

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** SITE_SQLITE, else the newest ../dist/dcs-world-reference-*.sqlite, else null. */
export function findDatabase(given = process.env.SITE_SQLITE): string | null {
  if (given) return resolve(given);
  const dist = resolve(siteRoot, "../dist");
  return (
    (existsSync(dist) ? readdirSync(dist) : [])
      .filter((f) => /^dcs-world-reference-.*\.sqlite$/.test(f))
      .map((f) => join(dist, f))
      .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0] ?? null
  );
}

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function seriesNames(path: string): string[] {
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    return (db.prepare("SELECT name FROM series ORDER BY name").all() as { name: string }[]).map(
      (r) => r.name,
    );
  } finally {
    db.close();
  }
}

/**
 * Each client-routed section serves the shell (404.html, which Pages serves at /404) with
 * status 200. Rules apply even where a file exists, so they name sections, not `/*`.
 */
export function redirects(series: string[]): string {
  const prefixes = [...new Set(["api", ...series])].filter((s) => /^[a-z][a-z0-9_]*$/.test(s));
  return `${prefixes.flatMap((p) => [`/${p} /${p}/ 301`, `/${p}/* /404 200`]).join("\n")}\n`;
}

export function publish(
  siteDir: string,
  source: string,
  mode: Mode,
  partSize = DEFAULT_PART_SIZE,
): ReferenceConfig {
  if (partSize % PAGE !== 0) throw new Error(`part size must be a multiple of ${PAGE}`);
  const dataDir = join(siteDir, "data");
  const configPath = join(dataDir, "reference.json");
  const size = statSync(source).size;
  const hash = sha256(source);
  const file = basename(source);
  const base = {
    databaseLengthBytes: size,
    file,
    version: /^dcs-world-reference-(.+)\.sqlite$/.exec(file)?.[1] ?? null,
    sha256: hash,
  };

  let config: ReferenceConfig;
  if (mode === "full") {
    config = { serverMode: "full", url: "reference.sqlite", requestChunkSize: PAGE, ...base };
  } else {
    const parts = Math.ceil(size / partSize);
    const suffixLength = Math.max(5, String(parts - 1).length);
    const dir = `db/${hash.slice(0, 16)}`;
    config = {
      serverMode: "chunked",
      urlPrefix: `${dir}/part.`,
      serverChunkSize: partSize,
      suffixLength,
      requestChunkSize: partSize,
      maxReadSpeed: partSize,
      boot: bootParts(source, partSize),
      ...base,
    };
  }

  const previous = existsSync(configPath)
    ? (JSON.parse(readFileSync(configPath, "utf8")) as ReferenceConfig)
    : null;
  const firstFile =
    mode === "full"
      ? "reference.sqlite"
      : `${config.urlPrefix}${"0".padStart(config.suffixLength ?? 0, "0")}`;
  const unchanged =
    previous !== null &&
    JSON.stringify(previous) === JSON.stringify(config) &&
    existsSync(join(dataDir, firstFile));

  if (!unchanged) {
    rmSync(join(dataDir, "db"), { recursive: true, force: true });
    rmSync(join(dataDir, "reference.sqlite"), { force: true });
    mkdirSync(dataDir, { recursive: true });
    if (mode === "full") {
      copyFileSync(source, join(dataDir, "reference.sqlite"));
    } else {
      const prefix = join(dataDir, config.urlPrefix ?? "");
      mkdirSync(dirname(prefix), { recursive: true });
      const fd = openSync(source, "r");
      const buffer = Buffer.alloc(partSize);
      try {
        for (let i = 0, offset = 0; offset < size; i++, offset += partSize) {
          const n = readSync(fd, buffer, 0, Math.min(partSize, size - offset), offset);
          writeFileSync(
            `${prefix}${String(i).padStart(config.suffixLength ?? 0, "0")}`,
            buffer.subarray(0, n),
          );
        }
      } finally {
        closeSync(fd);
      }
    }
    writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`);
  }
  writeFileSync(join(siteDir, "_redirects"), redirects(seriesNames(source)));
  return config;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const flag = (name: string) =>
    args.find((a) => a.startsWith(`--${name}=`))?.slice(name.length + 3);
  const siteDir = args.find((a) => !a.startsWith("--"));
  const mode = (flag("mode") ?? "chunked") as Mode;
  const source = findDatabase(flag("db"));
  if (!siteDir || (mode !== "full" && mode !== "chunked")) {
    console.error(
      "usage: node scripts/split-sqlite.ts <site-dir> [--mode=full|chunked] [--part-size=bytes] [--db=path]",
    );
    process.exit(2);
  }
  if (!source || !existsSync(source)) {
    console.error("No reference database: run `task package` or pass --db.");
    process.exit(1);
  }
  const partSize = Number(flag("part-size") ?? DEFAULT_PART_SIZE);
  const config = publish(resolve(siteDir), source, mode, partSize);
  const detail =
    config.serverMode === "chunked"
      ? `${Math.ceil(config.databaseLengthBytes / partSize)} parts of ${partSize} bytes`
      : "one file";
  console.log(`${config.file} -> ${siteDir}/data (${config.serverMode}, ${detail})`);
}
