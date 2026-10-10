import { DatabaseSync } from "node:sqlite";
import type { Query } from "../../src/lib/db/reference";
import { findDatabase } from "../split-sqlite";

/** A read-only Query over node:sqlite (default: findDatabase()), counting statements. */
export function nodeQuery(path = findDatabase()): Query & { count: number } {
  if (!path) throw new Error("No dist/dcs-world-reference-*.sqlite: run `task package`.");
  const db = new DatabaseSync(path, { readOnly: true });
  const q = (async (sql: string, params: unknown[] = []) => {
    q.count++;
    return db.prepare(sql).all(...(params as never[])) as Record<string, unknown>[];
  }) as Query & { count: number };
  q.count = 0;
  return q;
}
