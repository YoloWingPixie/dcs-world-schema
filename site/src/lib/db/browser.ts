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
import { once } from "../once";
import { CONFIG_URL, WASM_URL, WORKER_URL } from "./boot";
import type { Query, Row } from "./reference";

export { CONFIG_URL };

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

/** Statements run one at a time in the worker; results are cached per statement. */
export const browserQuery: Query = (sql, params = []) =>
  once(`sql:${sql}\u0000${JSON.stringify(params)}`, () =>
    open().then(
      // The worker's query(sql, params) is sql.js exec(sql, params): params as one array.
      (w) => (w.db.query as (s: string, p: unknown[]) => unknown)(sql, params) as Promise<Row[]>,
    ),
  );

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
