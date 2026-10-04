import { readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { Query } from "../../src/lib/db/reference";

/** The newest built database in dist/ (or DCS_REF_SQLITE). */
export function sqlitePath(): string {
  const given = process.env.DCS_REF_SQLITE;
  if (given) return resolve(given);
  const dist = resolve(__dirname, "../../../dist");
  const files = readdirSync(dist)
    .filter((f) => /^dcs-world-reference-.*\.sqlite$/.test(f))
    .map((f) => join(dist, f))
    .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  if (!files[0]) throw new Error("No dist/dcs-world-reference-*.sqlite: run `task package`.");
  return files[0];
}

/** A Query over node:sqlite, counting statements. */
export function nodeQuery(path = sqlitePath()): Query & { count: number } {
  const db = new DatabaseSync(path, { readOnly: true });
  const q = (async (sql: string, params: unknown[] = []) => {
    q.count++;
    return db.prepare(sql).all(...(params as never[])) as Record<string, unknown>[];
  }) as Query & { count: number };
  q.count = 0;
  return q;
}
