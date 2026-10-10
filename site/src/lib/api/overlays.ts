/**
 * Hand-written overlays of the Lua API docs (content/api/*.md, see its README). A file's
 * key is its name without `.md` (or frontmatter `symbol`): a page (`Unit`,
 * `DcsTask.Task.Orbit`) or a member (`Unit.getByName`, `trigger.action.outText`).
 *
 * Build time (scripts/build-api-overlays.ts) only parses them: Markdown and frontmatter
 * keys. Whether their symbols still exist is a data question: the site ignores stale
 * ones (db.ts `applyOverlays`) and `pnpm check:overlays <sqlite>` reports them.
 */
import { parseFrontmatter } from "../markdown";
import type { ApiOverlay, ApiSection } from "./types";

export const OVERLAY_KEYS = [
  "summary",
  "description",
  "seeAlso",
  "deprecated",
  "since",
  "symbol",
  "section",
] as const;

export class OverlayError extends Error {
  override name = "OverlayError";
}

const SECTIONS: ApiSection[] = ["mission", "hooks", "export", "server", "types"];

export type ParsedOverlay = { symbol: string; overlay: ApiOverlay; body: string };

/** Parses one overlay file; `fileName` is its base name (`Unit.getByName.md`). */
export function parseOverlay(source: string, fileName: string, text: string): ParsedOverlay {
  const fail = (msg: string) => new OverlayError(`${source}: ${msg}`);
  let meta: Record<string, unknown>;
  let body: string;
  try {
    ({ data: meta, body } = parseFrontmatter(text, { file: source, allowed: OVERLAY_KEYS }));
  } catch (error) {
    throw new OverlayError((error as Error).message);
  }
  const str = (k: string) => {
    const v = meta[k];
    if (v === undefined) return undefined;
    if (typeof v !== "string" || !v.trim()) throw fail(`'${k}' must be a non-empty string`);
    return v.trim();
  };
  const seeAlso = meta.seeAlso ?? [];
  if (!Array.isArray(seeAlso) || seeAlso.some((s) => typeof s !== "string")) {
    throw fail("'seeAlso' must be a list of symbol paths");
  }
  const deprecated = meta.deprecated;
  if (
    deprecated !== undefined &&
    typeof deprecated !== "boolean" &&
    typeof deprecated !== "string"
  ) {
    throw fail("'deprecated' must be true/false or a message");
  }
  const section = str("section");
  if (section && !SECTIONS.includes(section as ApiSection)) {
    throw fail(`'section' must be one of ${SECTIONS.join(", ")}`);
  }
  const overlay: ApiOverlay = { source };
  const summary = str("summary");
  const description = str("description");
  if (section) overlay.section = section as ApiSection;
  if (summary) overlay.summary = summary;
  if (description) overlay.description = description;
  if (seeAlso.length) overlay.seeAlso = (seeAlso as string[]).map((s) => s.replace(/:/g, "."));
  if (deprecated !== undefined && deprecated !== false) overlay.deprecated = deprecated;
  if (meta.since !== undefined) overlay.since = String(meta.since);
  const symbol = (str("symbol") ?? fileName.replace(/\.md$/i, "")).replace(/:/g, ".");
  return { symbol, overlay, body: body.trim() };
}

/**
 * Symbols (and seeAlso targets) of `overlays` that `exists` does not know: the stale ones,
 * as messages naming the file.
 */
export function staleOverlays(
  overlays: Record<string, ApiOverlay>,
  exists: (symbol: string, section?: ApiSection) => boolean,
): string[] {
  const out: string[] = [];
  for (const [symbol, o] of Object.entries(overlays)) {
    if (!exists(symbol, o.section)) {
      out.push(`${o.source}: '${symbol}' is no symbol of the Lua API (stale overlay?)`);
    }
    for (const s of o.seeAlso ?? []) {
      if (!exists(s)) out.push(`${o.source}: seeAlso '${s}' is no symbol of the Lua API`);
    }
  }
  return out;
}
