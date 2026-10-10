"use client";

/**
 * The reference database in the browser: sql.js-httpvfs runs SQLite (wasm) in a worker
 * and reads the database over HTTP as queries need it. Nothing is downloaded whole;
 * repeated pages come from the worker's cache.
 *
 * Files (scripts/copy-sqlite-assets.ts and scripts/split-sqlite.ts put them under public/):
 *   /sqlite/sqlite.worker.js, /sqlite/sql-wasm.wasm   the worker and SQLite build
 *   /data/reference.json                              how the database is served:
 *     "full"     one file read with Range requests (local dev, e2e)
 *     "chunked"  parts under a content-hashed path, each fetched whole (Cloudflare Pages)
 */
import { createDbWorker, type WorkerHttpvfs } from "sql.js-httpvfs";
import { boundedCache, once } from "../once";
import { CONFIG_URL, prefetchParts, WASM_URL, WORKER_URL } from "./boot";
import type { Query, Row } from "./reference";

/** /data/reference.json (scripts/split-sqlite.ts). */
export type ReferenceConfig = {
  serverMode: "full" | "chunked";
  url?: string;
  urlPrefix?: string;
  serverChunkSize?: number;
  suffixLength?: number;
  requestChunkSize: number;
  maxReadSpeed?: number;
  databaseLengthBytes: number;
  boot?: { core: number[]; search: number[]; api: number[] };
  file: string;
  version: string | null;
  sha256: string;
  /** Lua API pages per section and kind (the home contents' API chapter). */
  apiPages?: Record<string, Record<string, number>>;
};

function absolute(url: string, base = window.location.href) {
  return new URL(url, base).toString();
}

/** The served database's description (file name, version, layout). */
export function referenceConfig(): Promise<ReferenceConfig> {
  return once("reference-config", () => {
    // Started by the inline boot script (lib/db/boot.ts) when the page loaded.
    const early = (window as { __dcsRefConfig?: Promise<ReferenceConfig> }).__dcsRefConfig;
    (window as { __dcsRefConfig?: unknown }).__dcsRefConfig = undefined;
    return (
      early ??
      fetch(absolute(CONFIG_URL)).then((res) => {
        if (!res.ok) throw new Error(`${CONFIG_URL}: HTTP ${res.status}`);
        return res.json() as Promise<ReferenceConfig>;
      })
    );
  });
}

function open(): Promise<WorkerHttpvfs> {
  return once("reference-worker", () =>
    referenceConfig().then((c) => {
      const base = absolute(CONFIG_URL);
      const inline =
        c.serverMode === "chunked"
          ? {
              serverMode: "chunked" as const,
              urlPrefix: absolute(c.urlPrefix ?? "", base),
              serverChunkSize: c.serverChunkSize ?? c.requestChunkSize,
              suffixLength: c.suffixLength ?? 5,
              databaseLengthBytes: c.databaseLengthBytes,
              requestChunkSize: c.requestChunkSize,
              // Read by the patched worker (scripts/copy-sqlite-assets.ts).
              maxReadSpeed: c.maxReadSpeed ?? c.requestChunkSize,
            }
          : {
              serverMode: "full" as const,
              url: absolute(c.url ?? "reference.sqlite", base),
              requestChunkSize: c.requestChunkSize,
            };
      return createDbWorker(
        [{ from: "inline", config: inline }],
        absolute(WORKER_URL),
        absolute(WASM_URL),
      );
    }),
  );
}

/** One statement in the worker (sql.js exec(sql, params): params as one array). */
const run: Query = (sql, params = []) =>
  open().then(
    (w) => (w.db.query as (s: string, p: unknown[]) => unknown)(sql, params) as Promise<Row[]>,
  );

const keyOf = (sql: string, params: unknown[]) => JSON.stringify([sql, params]);

/**
 * Statements run one at a time in the worker; results are cached per statement for the
 * page's lifetime. For stable reads (views, a record, a series' names); per-keystroke
 * statements go through `searchQuery` or `transientQuery`, whose caches are bounded.
 */
export const browserQuery: Query = (sql, params = []) =>
  once(`sql:${keyOf(sql, params)}`, () => run(sql, params));

/** A superseded search, dropped before it reached the worker. */
export class StaleQueryError extends Error {
  constructor() {
    super("Superseded by a newer search");
    this.name = "StaleQueryError";
  }
}

/** The last `size` statements' results (in-flight ones included); failures are not kept. */
function boundedQuery(size: number, load: Query): Query {
  const cached = boundedCache(size, (key) => load(...(JSON.parse(key) as [string, unknown[]])));
  return (sql, params = []) => cached(keyOf(sql, params));
}

/** Parameterised lookups that change with the input (alias rows, symbol paths). */
export const transientQuery: Query = boundedQuery(32, run);

// Full-text searches wait for the one before them; one superseded while it waits is
// dropped, so a slow short query never queues a stale one ahead of the newest.
let latestSearch = 0;
let searchTail: Promise<unknown> = Promise.resolve();

/** FTS searches: bounded cache, newest first (identical statements share one run). */
export const searchQuery: Query = boundedQuery(16, (sql, params = []) => {
  const ticket = ++latestSearch;
  const result = searchTail.then(() => {
    if (ticket !== latestSearch) throw new StaleQueryError();
    return run(sql, params);
  });
  searchTail = result.catch(() => undefined);
  return result;
});

/** Fetch the search index's database parts (`boot.search`), as /search does at startup. */
export function prefetchSearchParts(): Promise<void> {
  return once("prefetch:search", () =>
    referenceConfig().then((c) => prefetchParts(c, absolute(CONFIG_URL), c.boot?.search ?? [])),
  );
}

/** Bytes and requests so far (diagnostics, e2e measurements). */
export async function databaseStats() {
  const w = await open();
  return w.worker.getStats();
}

if (typeof window !== "undefined") {
  Object.assign(window, { __dcsRefStats: databaseStats, __dcsRefQuery: browserQuery });
  // Start the worker (and its wasm) as soon as this code runs, not on the first query.
  open().catch(() => undefined);
}
