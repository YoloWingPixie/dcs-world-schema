/**
 * Publishes the reference database into a site folder:
 *
 *   <site>/data/reference.json                 what the browser opens (lib/db/browser.ts)
 *   <site>/data/reference.sqlite               single-file mode (local dev, e2e)
 *   <site>/data/db/<hash>/part.NNNNN           chunked mode (Cloudflare Pages)
 *   <site>/data/db/<hash>/model.<hash>.json    the model's tables, read without the database
 *   <site>/data/db/<hash>/names.<hash>.json    the search rows, searched in memory
 *   <site>/_redirects                 deep links under each series and /api/ serve the shell
 *
 * Chunked: Cloudflare Pages answers Range requests with the whole file (200), so each part
 * is fetched whole and is one sql.js-httpvfs request chunk. Parts live under the database's
 * content hash, so a new database never mixes with cached parts of an old one.
 *
 *   node scripts/split-sqlite.ts <site-dir> [--mode=full|chunked] [--part-size=bytes] [--db=path]
 *
 * The database is --db, else SITE_SQLITE or DCS_REF_SQLITE, else the newest
 * ../dist/dcs-world-reference-*.sqlite.
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
   * BOOT_GROUPS): every page, the API docs. Indexes into the part files.
   */
  boot?: { core: number[]; api: number[] };
  /**
   * The model's tables (`modelTables`), content-hashed: every page reads them at startup,
   * so they come as one small file rather than the database pages that hold them.
   */
  model: string;
  /** Every `search` row (`nameIndex`), content-hashed: the palette searches it in memory. */
  names: string;
  /** The released file and its hash, for display. */
  file: string;
  version: string | null;
  sha256: string;
  /**
   * Lua API pages per section and kind (`api_symbols` page rows), so the home contents can
   * count the API chapter without reading the database's API pages.
   */
  apiPages?: Record<string, Record<string, number>>;
};

/**
 * The pages a client reads first: [whole tables, tables or indexes whose interior pages].
 * Mirrors BOOT_GROUPS in tools/package/sqlite.py, which lays these pages out together.
 */
const BOOT_GROUPS: Record<"core" | "api", [string[], string[]]> = {
  core: [
    ["sqlite_schema", "sqlite_master"],
    [
      "record_views",
      "sqlite_autoindex_record_views_1",
      "series_views",
      "sqlite_autoindex_series_views_1",
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
      api: pick(BOOT_GROUPS.api),
    };
  } finally {
    db.close();
  }
}

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * SITE_SQLITE, else DCS_REF_SQLITE, else the newest ../dist/dcs-world-reference-*.sqlite,
 * else null. Here, not in lib/, as this file runs under plain Node (no extensionless imports).
 */
export function findDatabase(
  given = process.env.SITE_SQLITE || process.env.DCS_REF_SQLITE,
): string | null {
  if (given) return resolve(given);
  const dist = resolve(siteRoot, "../dist");
  return (
    (existsSync(dist) ? readdirSync(dist) : [])
      .filter((f) => /^dcs-world-reference-.*\.sqlite$/.test(f))
      .map((f) => join(dist, f))
      .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0] ?? null
  );
}

function sha256(data: string | Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

/**
 * The statements lib/db/reference.ts `readModelTables` runs (MODEL_SQL there; a test checks
 * they agree), so the browser builds the model from this file's rows without the database.
 */
const MODEL_SQL = {
  meta: "SELECT key, value FROM meta",
  series: "SELECT name, type_name, key_column, records FROM series ORDER BY rowid",
  schema_types: "SELECT name, definition FROM schema_types",
  ref_paths: "SELECT table_name, series, path, target, source_column, target_column FROM ref_paths",
};

/** The model's tables as rows (lib/db/reference.ts `ModelTables`). */
export function modelTables(
  path: string,
): Record<keyof typeof MODEL_SQL, Record<string, unknown>[]> {
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    const read = (sql: string) =>
      db
        .prepare(sql)
        .all()
        .map((r) => ({ ...r }));
    return {
      meta: read(MODEL_SQL.meta),
      series: read(MODEL_SQL.series),
      schema_types: read(MODEL_SQL.schema_types),
      ref_paths: read(MODEL_SQL.ref_paths),
    };
  } finally {
    db.close();
  }
}

/** Words: runs of letters and digits, lowercased (lib/search/engine.ts `words`). */
const words = (text: string) =>
  text
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);

/**
 * The `search` table for the in-memory search (lib/search/engine.ts `NameIndexFile`):
 * `[series index, id, name, subtitle, keywords]` per row, `id` empty when it is the name.
 * Most keywords are spellings of the name, which the search derives itself (engine.ts
 * `nameTerms`); `keywords` keeps the words none of those terms, nor a subtitle word, starts
 * with, as a prefix search finds the rest anyway.
 */
export function nameIndex(path: string): { series: string[]; rows: unknown[][] } {
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    const rows = db
      .prepare("SELECT series, id, name, subtitle, keywords FROM search ORDER BY rowid")
      .all() as { series: string; id: string; name: string; subtitle: string; keywords: string }[];
    const series: string[] = [];
    const at = new Map<string, number>();
    const split = (w: string) =>
      w
        .replace(/(\p{L})(\p{N})/gu, "$1 $2")
        .replace(/(\p{N})(\p{L})/gu, "$1 $2")
        .split(" ");
    const out = rows.map((r) => {
      let s = at.get(r.series);
      if (s === undefined) {
        s = series.push(r.series) - 1;
        at.set(r.series, s);
      }
      const named = [...words(r.name), ...words(r.id)];
      const have = new Set([
        ...named,
        ...named.flatMap(split),
        words(r.name).join(""),
        words(r.id).join(""),
        ...words(r.subtitle),
      ]);
      const extra = [...new Set(words(r.keywords))].filter(
        (w) => ![...have].some((h) => h.startsWith(w)),
      );
      return [s, r.id === r.name ? "" : r.id, r.name, r.subtitle, extra.join(" ")];
    });
    return { series, rows: out };
  } finally {
    db.close();
  }
}

/** Lua API pages per section and kind; {} for a database without the API docs. */
export function apiPageCounts(path: string): Record<string, Record<string, number>> {
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    const has = db
      .prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'api_symbols'")
      .get();
    if (!has) return {};
    const rows = db
      .prepare(
        `SELECT section, kind, COUNT(*) AS n FROM api_symbols WHERE name = ''
          GROUP BY section, kind ORDER BY section, kind`,
      )
      .all() as { section: string; kind: string; n: number }[];
    const out: Record<string, Record<string, number>> = {};
    for (const r of rows) out[r.section] = { ...out[r.section], [r.kind]: Number(r.n) };
    return out;
  } finally {
    db.close();
  }
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
  const hash = sha256(readFileSync(source));
  const file = basename(source);
  const dir = `db/${hash.slice(0, 16)}`;
  const model = JSON.stringify(modelTables(source));
  const names = JSON.stringify(nameIndex(source));
  const base = {
    model: `${dir}/model.${sha256(model).slice(0, 16)}.json`,
    names: `${dir}/names.${sha256(names).slice(0, 16)}.json`,
    databaseLengthBytes: size,
    file,
    version: /^dcs-world-reference-(.+)\.sqlite$/.exec(file)?.[1] ?? null,
    sha256: hash,
    apiPages: apiPageCounts(source),
  };

  let config: ReferenceConfig;
  if (mode === "full") {
    config = { serverMode: "full", url: "reference.sqlite", requestChunkSize: PAGE, ...base };
  } else {
    const parts = Math.ceil(size / partSize);
    const suffixLength = Math.max(5, String(parts - 1).length);
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
    existsSync(join(dataDir, firstFile)) &&
    existsSync(join(dataDir, config.model)) &&
    existsSync(join(dataDir, config.names));

  if (!unchanged) {
    rmSync(join(dataDir, "db"), { recursive: true, force: true });
    rmSync(join(dataDir, "reference.sqlite"), { force: true });
    mkdirSync(join(dataDir, dir), { recursive: true });
    writeFileSync(join(dataDir, config.model), model);
    writeFileSync(join(dataDir, config.names), names);
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
