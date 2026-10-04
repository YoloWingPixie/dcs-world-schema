"use client";

/**
 * The reference database in the browser: sql.js-httpvfs runs SQLite (wasm) in a worker
 * and reads the .sqlite file with HTTP range requests, page by page, as queries need
 * them. Nothing is downloaded whole; repeated pages come from the worker's cache.
 *
 * Files (scripts/copy-sqlite-assets.ts puts them under public/):
 *   /sqlite/sqlite.worker.js, /sqlite/sql-wasm.wasm   the worker and SQLite build
 *   /data/reference.sqlite                            the released database
 */
import type { WorkerHttpvfs } from "sql.js-httpvfs";
import type { Query, Row } from "./reference";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
/** Override with NEXT_PUBLIC_REFERENCE_DB (absolute URL or site path) at build time. */
export const DATABASE_URL =
  process.env.NEXT_PUBLIC_REFERENCE_DB ?? `${BASE_PATH}/data/reference.sqlite`;
/** Matches PAGE_SIZE in tools/package/sqlite.py: one request per page at most. */
const CHUNK = 4096;

let worker: Promise<WorkerHttpvfs> | null = null;

function absolute(url: string) {
  return new URL(url, window.location.href).toString();
}

function open(): Promise<WorkerHttpvfs> {
  worker ??= import("sql.js-httpvfs")
    .then(({ createDbWorker }) =>
      createDbWorker(
        [
          {
            from: "inline",
            config: { serverMode: "full", url: absolute(DATABASE_URL), requestChunkSize: CHUNK },
          },
        ],
        absolute(`${BASE_PATH}/sqlite/sqlite.worker.js`),
        absolute(`${BASE_PATH}/sqlite/sql-wasm.wasm`),
      ),
    )
    .catch((error: unknown) => {
      worker = null;
      throw error;
    });
  return worker;
}

/** Statements run one at a time in the worker; results are cached per statement. */
const cache = new Map<string, Promise<Row[]>>();

export const browserQuery: Query = (sql, params = []) => {
  const key = `${sql}\u0000${JSON.stringify(params)}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const promise = open().then(
    // The worker's query(sql, params) is sql.js exec(sql, params): params as one array.
    (w) => (w.db.query as (s: string, p: unknown[]) => unknown)(sql, params) as Promise<Row[]>,
  );
  promise.catch(() => cache.delete(key));
  cache.set(key, promise);
  return promise;
};

/** Bytes and requests so far (diagnostics, e2e measurements). */
export async function databaseStats() {
  const w = await open();
  return w.worker.getStats();
}

if (typeof window !== "undefined") {
  Object.assign(window, { __dcsRefStats: databaseStats, __dcsRefQuery: browserQuery });
}
