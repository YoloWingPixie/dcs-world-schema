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
 *   /data/db/<hash>/model.<hash>.json                 the model's tables (`model`), read
 *                                                     without the worker
 *   /data/db/<hash>/names.<hash>.json                 the search rows (`names`), searched
 *                                                     in memory (lib/search)
 */
import { createDbWorker, type WorkerHttpvfs } from "sql.js-httpvfs";
import { boundedCache, once } from "../once";
import type { NameIndexFile } from "../search/engine";
import { CONFIG_URL, DB_FREE_PATHS, WASM_URL, WORKER_URL } from "./boot";
import type { ModelTables, Query, Row } from "./reference";

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
  boot?: { core: number[]; api: number[] };
  /** The model's tables (lib/db/reference.ts `ModelTables`), relative to this file. */
  model: string;
  /** The search rows (lib/search/engine.ts `NameIndexFile`), relative to this file. */
  names: string;
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

/** A static file reference.json names (its URLs are relative to it), parsed. */
function fetchReferenceFile<T>(url: string): Promise<T> {
  const full = absolute(url, absolute(CONFIG_URL));
  return fetch(full).then((res) => {
    if (!res.ok) throw new Error(`${full}: HTTP ${res.status}`);
    return res.json() as Promise<T>;
  });
}

/**
 * A static file reference.json names under `key`, once per page; the boot script may have
 * started it (`window[global]`). A failed early fetch gets one more try.
 */
function referenceFile<T>(key: "model" | "names", global: string): Promise<T> {
  return once(`reference-file:${key}`, () => {
    const w = window as unknown as Record<string, Promise<T> | undefined>;
    const early = w[global];
    w[global] = undefined;
    const load = () => referenceConfig().then((c) => fetchReferenceFile<T>(c[key]));
    return early ? early.catch(load) : load();
  });
}

/** The model's tables (lib/client-data.ts `loadModel`). */
export const modelTables = () => referenceFile<ModelTables>("model", "__dcsModel");

/** The search rows (lib/search/client.ts), also fetched ahead of the palette. */
export const nameIndexFile = () => referenceFile<NameIndexFile>("names", "__dcsNames");

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
 * page's lifetime. For stable reads (views, a record, a series' names); statements that
 * change with the input go through `transientQuery`, whose cache is bounded.
 */
export const browserQuery: Query = (sql, params = []) =>
  once(`sql:${keyOf(sql, params)}`, () => run(sql, params));

/** The last `size` statements' results (in-flight ones included); failures are not kept. */
function boundedQuery(size: number, load: Query): Query {
  const cached = boundedCache(size, (key) => load(...(JSON.parse(key) as [string, unknown[]])));
  return (sql, params = []) => cached(keyOf(sql, params));
}

/** Parameterised lookups that change with the input (names, symbol paths). */
export const transientQuery: Query = boundedQuery(32, run);

/** Bytes and requests so far (diagnostics, e2e measurements). */
export async function databaseStats() {
  const w = await open();
  return w.worker.getStats();
}

/** Start the worker and fetch the startup parts (chunked), which the boot script skipped. */
function warmDatabase() {
  open().catch(() => undefined);
  referenceConfig()
    .then((c) => {
      if (c.serverMode !== "chunked" || !c.urlPrefix) return;
      for (const i of c.boot?.core ?? []) {
        const part = c.urlPrefix + String(i).padStart(c.suffixLength ?? 5, "0");
        fetch(absolute(part, absolute(CONFIG_URL)), { priority: "low" }).catch(() => {});
      }
    })
    .catch(() => undefined);
}

if (typeof window !== "undefined") {
  Object.assign(window, { __dcsRefStats: databaseStats, __dcsRefQuery: browserQuery });
  if (!new RegExp(DB_FREE_PATHS).test(window.location.pathname)) {
    // Start the worker (and its wasm) as soon as this code runs, not on the first query.
    open().catch(() => undefined);
  } else {
    // A page without database reads warms it once loaded and idle, for the next page; a
    // query before then (a client-side navigation) starts the worker itself.
    const idle = () =>
      typeof window.requestIdleCallback === "function"
        ? window.requestIdleCallback(warmDatabase, { timeout: 2000 })
        : setTimeout(warmDatabase, 500);
    if (document.readyState === "complete") idle();
    else window.addEventListener("load", idle, { once: true });
  }
}
