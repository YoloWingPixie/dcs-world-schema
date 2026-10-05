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
import type { WorkerHttpvfs } from "sql.js-httpvfs";
import type { Query, Row } from "./reference";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
/** Override with NEXT_PUBLIC_REFERENCE_CONFIG (absolute URL or site path) at build time. */
export const CONFIG_URL =
  process.env.NEXT_PUBLIC_REFERENCE_CONFIG ?? `${BASE_PATH}/data/reference.json`;

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
  file: string;
  version: string | null;
  sha256: string;
};

let config: Promise<ReferenceConfig> | null = null;
let worker: Promise<WorkerHttpvfs> | null = null;

function absolute(url: string, base = window.location.href) {
  return new URL(url, base).toString();
}

/** The served database's description (file name, version, layout). */
export function referenceConfig(): Promise<ReferenceConfig> {
  config ??= fetch(absolute(CONFIG_URL), { cache: "no-cache" })
    .then((res) => {
      if (!res.ok) throw new Error(`${CONFIG_URL}: HTTP ${res.status}`);
      return res.json() as Promise<ReferenceConfig>;
    })
    .catch((error: unknown) => {
      config = null;
      throw error;
    });
  return config;
}

function open(): Promise<WorkerHttpvfs> {
  worker ??= Promise.all([referenceConfig(), import("sql.js-httpvfs")])
    .then(([c, { createDbWorker }]) => {
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
        absolute(`${BASE_PATH}/sqlite/sqlite.worker.js`),
        absolute(`${BASE_PATH}/sqlite/sql-wasm.wasm`),
      );
    })
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
