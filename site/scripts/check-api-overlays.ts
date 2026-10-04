/**
 * Stale Lua API overlays (content/api) against a reference database: symbols or seeAlso
 * targets missing from its `api_symbols`. Called by scripts/check-overlays.ts.
 */
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { staleOverlays } from "../src/lib/api/overlays";
import type { Query } from "../src/lib/db/reference";
import { compileApiOverlays } from "./build-api-overlays";

const siteRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

export async function staleApiOverlays(
  q: Query,
  dir = join(siteRoot, "content/api"),
): Promise<string[]> {
  const { symbols } = compileApiOverlays(dir);
  const rows = await q("SELECT DISTINCT section, path FROM api_symbols").catch(() => []);
  if (!rows.length) return ["content/api: the database has no Lua API tables (api_symbols)"];
  const known = new Map<string, Set<string>>();
  for (const r of rows) {
    const path = String(r.path);
    known.set(path, (known.get(path) ?? new Set()).add(String(r.section)));
  }
  return staleOverlays(symbols, (symbol, section) => {
    const sections = known.get(symbol);
    return Boolean(sections && (!section || sections.has(section)));
  });
}
