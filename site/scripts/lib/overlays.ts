/**
 * Hand-written overlays for the reference (content/reference/, see its README):
 *
 *   <series>/_index.md            intro on the browse page
 *   <series>/<id or slug>.md      note on a record page
 *   <series>/_fields/<path>.md    note on a field (tooltip, compare header)
 *
 * Every problem (unknown series, record or field; unknown frontmatter key; bad
 * frontmatter value) is collected and thrown together as one OverlayError.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { markdownToText, parseFrontmatter, renderMarkdown } from "../../src/lib/markdown";
import type { Overlay } from "../../src/lib/types";

export class OverlayError extends Error {
  constructor(public readonly problems: string[]) {
    super(`Stale or invalid overlays in content/reference:\n  - ${problems.join("\n  - ")}`);
  }
}

export type LoadedOverlay = Overlay & { text: string };

export type SeriesOverlays = {
  intro?: LoadedOverlay;
  /** By record id. */
  records: Map<string, LoadedOverlay>;
  /** By catalog path. */
  fields: Map<string, LoadedOverlay>;
};

export type OverlayTarget = {
  /** Record id for a file stem (an id or a slug), or null. */
  record(stem: string): string | null;
  /** Whether the catalog has this field path. */
  field(path: string): boolean;
};

const RECORD_KEYS = ["aliases", "seeAlso"] as const;
const OTHER_KEYS = ["seeAlso"] as const;

function seeAlsoOf(value: unknown, file: string, problems: string[]) {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) {
    problems.push(`${file}: seeAlso must be a list`);
    return undefined;
  }
  const out: Array<{ label: string; href: string }> = [];
  for (const item of value) {
    if (typeof item === "string") out.push({ label: item, href: item });
    else if (
      item &&
      typeof item === "object" &&
      typeof (item as { href?: unknown }).href === "string"
    ) {
      const { href, label } = item as { href: string; label?: unknown };
      out.push({ href, label: typeof label === "string" ? label : href });
    } else problems.push(`${file}: each seeAlso entry is a URL or { label, href }`);
  }
  return out;
}

function aliasesOf(value: unknown, file: string, problems: string[]) {
  if (value === undefined) return undefined;
  const list = typeof value === "string" ? [value] : value;
  if (!Array.isArray(list) || list.some((a) => typeof a !== "string")) {
    problems.push(`${file}: aliases must be a string or a list of strings`);
    return undefined;
  }
  return list as string[];
}

function readOverlay(
  path: string,
  file: string,
  allowed: readonly string[],
  problems: string[],
): LoadedOverlay | null {
  let parsed: ReturnType<typeof parseFrontmatter>;
  try {
    parsed = parseFrontmatter(readFileSync(path, "utf8"), { file, allowed });
  } catch (error) {
    problems.push((error as Error).message);
    return null;
  }
  const overlay: LoadedOverlay = {
    html: parsed.body ? renderMarkdown(parsed.body) : "",
    text: markdownToText(parsed.body),
  };
  const aliases = aliasesOf(parsed.data.aliases, file, problems);
  const seeAlso = seeAlsoOf(parsed.data.seeAlso, file, problems);
  if (aliases?.length) overlay.aliases = aliases;
  if (seeAlso?.length) overlay.seeAlso = seeAlso;
  return overlay;
}

/** Field file stems are catalog paths; `*` (keyed arrays) may be written `+`. */
export const fieldPathFromStem = (stem: string) => stem.replace(/\+/g, "*");

/** Accepts every series, record stem and field (build time: no data to check against). */
export const ANY_TARGET: OverlayTarget = { record: (stem) => stem, field: () => true };

export function loadOverlays(
  contentDir: string,
  targets: Record<string, OverlayTarget> | ((series: string) => OverlayTarget | null),
): Map<string, SeriesOverlays> {
  const targetOf = (series: string) =>
    typeof targets === "function" ? targets(series) : (targets[series] ?? null);
  const out = new Map<string, SeriesOverlays>();
  if (!existsSync(contentDir)) return out;
  const problems: string[] = [];
  const rel = (p: string) => relative(contentDir, p).replace(/\\/g, "/");

  for (const dir of readdirSync(contentDir).sort()) {
    const dirPath = join(contentDir, dir);
    if (!statSync(dirPath).isDirectory()) {
      if (dir !== "README.md")
        problems.push(`${dir}: only series folders and README.md belong here`);
      continue;
    }
    const target = targetOf(dir);
    if (!target) {
      problems.push(`${dir}/: no series named "${dir}"`);
      continue;
    }
    const series: SeriesOverlays = { records: new Map(), fields: new Map() };
    out.set(dir, series);
    for (const name of readdirSync(dirPath).sort()) {
      const path = join(dirPath, name);
      if (name === "_fields" && statSync(path).isDirectory()) {
        for (const fieldFile of readdirSync(path).sort()) {
          const file = rel(join(path, fieldFile));
          if (!fieldFile.endsWith(".md")) {
            problems.push(`${file}: overlays are .md files`);
            continue;
          }
          const fieldPath = fieldPathFromStem(fieldFile.slice(0, -3));
          if (!target.field(fieldPath)) {
            problems.push(`${file}: ${dir} has no field "${fieldPath}"`);
            continue;
          }
          const overlay = readOverlay(join(path, fieldFile), file, OTHER_KEYS, problems);
          if (overlay) series.fields.set(fieldPath, overlay);
        }
        continue;
      }
      const file = rel(path);
      if (!name.endsWith(".md")) {
        problems.push(`${file}: overlays are .md files`);
        continue;
      }
      const stem = name.slice(0, -3);
      if (stem === "_index") {
        const overlay = readOverlay(path, file, OTHER_KEYS, problems);
        if (overlay) series.intro = overlay;
        continue;
      }
      const id = target.record(stem);
      if (id === null) {
        problems.push(`${file}: ${dir} has no record with id or slug "${stem}"`);
        continue;
      }
      if (series.records.has(id)) {
        problems.push(`${file}: a second overlay for ${dir} record "${id}"`);
        continue;
      }
      const overlay = readOverlay(path, file, RECORD_KEYS, problems);
      if (overlay) series.records.set(id, overlay);
    }
  }
  if (problems.length) throw new OverlayError(problems);
  return out;
}
