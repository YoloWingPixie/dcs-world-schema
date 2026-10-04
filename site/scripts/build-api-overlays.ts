/**
 * Compiles the hand-written Lua API overlays (content/api, see its README) into
 * public/overlays/api.json, shipped with the site shell: `{ symbols: { <path>: overlay } }`.
 *
 * Only the overlays themselves are checked here (Markdown, frontmatter keys, duplicates).
 * Whether their symbols still exist is a data question: the site ignores stale ones at
 * runtime and `pnpm check:overlays <sqlite>` reports them.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { OverlayError, parseOverlay } from "../src/lib/api/overlays";
import type { ApiOverlayFile } from "../src/lib/api/types";
import { markdownToText, renderMarkdown } from "../src/lib/markdown";

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const contentDir = join(siteRoot, "content/api");
const out = join(siteRoot, "public/overlays/api.json");

export function compileApiOverlays(dir: string): ApiOverlayFile {
  const symbols: ApiOverlayFile["symbols"] = {};
  const files = existsSync(dir)
    ? readdirSync(dir)
        .filter((f) => f.endsWith(".md") && f.toLowerCase() !== "readme.md")
        .sort()
    : [];
  for (const f of files) {
    const { symbol, overlay, body } = parseOverlay(
      `content/api/${f}`,
      f,
      readFileSync(join(dir, f), "utf8"),
    );
    const taken = symbols[symbol];
    if (taken) {
      throw new OverlayError(
        `content/api/${f}: '${symbol}' is already overlaid by ${taken.source}`,
      );
    }
    if (body) {
      overlay.html = renderMarkdown(body);
      overlay.text = markdownToText(body);
    }
    symbols[symbol] = overlay;
  }
  return { symbols };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const file = compileApiOverlays(contentDir);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, JSON.stringify(file));
  console.log(`api overlays: ${Object.keys(file.symbols).length} -> ${out}`);
}
