/**
 * Lua API docs read from the reference database (tables `api_symbols`, `api_type_uses`
 * and the `search` rows of series `api`; see tools/package/api_docs.py), with any `Query`:
 * the browser's range-request worker or node:sqlite in tests.
 */
import { ftsQuery, type Query } from "../db/reference";
import { apiHref } from "./routes";
import type { ApiOverlay, ApiOverlayFile, ApiPage, ApiSection, Member, PageSummary } from "./types";

export const API_SERIES = "api";

/** Every page, for the home listing (one covering index read). */
export async function listApiPages(q: Query): Promise<PageSummary[]> {
  const rows = await q(
    `SELECT section, page, kind, parent, members, summary FROM api_symbols
      WHERE name = '' ORDER BY section, page`,
  );
  return rows.map((r) => ({
    section: String(r.section) as ApiSection,
    name: String(r.page),
    href: apiHref(String(r.section) as ApiSection, String(r.page)),
    kind: String(r.kind) as PageSummary["kind"],
    parent: String(r.parent ?? ""),
    summary: String(r.summary ?? ""),
    count: Number(r.members ?? 0),
  }));
}

/** A page with its members (stored together: one range of pages) and its "used by". */
export async function getApiPage(
  q: Query,
  section: ApiSection,
  name: string,
): Promise<ApiPage | null> {
  const [rows, uses] = await Promise.all([
    q(`SELECT name, entry FROM api_symbols WHERE section = ? AND page = ? ORDER BY rowid`, [
      section,
      name,
    ]),
    q(`SELECT label, href FROM api_type_uses WHERE section = ? AND type = ? ORDER BY label`, [
      section,
      name,
    ]),
  ]);
  const head = rows.find((r) => r.name === "");
  if (!head) return null;
  const entry = JSON.parse(String(head.entry)) as Omit<
    ApiPage,
    "groups" | "section" | "name" | "href" | "usedBy"
  > & {
    groups: Array<{ id: string; title: string }>;
  };
  const members = rows
    .filter((r) => r.name !== "")
    .map((r) => ({ ...(JSON.parse(String(r.entry)) as Member), name: String(r.name) }));
  return {
    ...entry,
    section,
    name,
    href: apiHref(section, name),
    groups: entry.groups.map((g) => ({ ...g, members: members.filter((m) => m.group === g.id) })),
    links: entry.links ?? {},
    usedBy: uses.map((u) => ({ label: String(u.label), href: String(u.href) })),
  };
}

/** Which of `ids` are records of `series` (enum values link only to existing records). */
export async function existingRecords(
  q: Query,
  series: string,
  ids: string[],
): Promise<Set<string>> {
  const out = new Set<string>();
  for (let i = 0; i < ids.length; i += 500) {
    const chunk = ids.slice(i, i + 500);
    const rows = await q(
      `SELECT id FROM search WHERE series = ? AND id IN (${chunk.map(() => "?").join(",")})`,
      [series, ...chunk],
    );
    for (const r of rows) out.add(String(r.id));
  }
  return out;
}

/** Site paths of symbol paths (`Unit.getByName`, `DcsTask.Task.Orbit`), where they exist. */
export async function resolveSymbols(q: Query, paths: string[]): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  const wanted = [...new Set(paths.map((p) => p.replace(/:/g, ".")))];
  if (!wanted.length) return out;
  const rows = await q(
    `SELECT section, page, name, path, entry FROM api_symbols
      WHERE path IN (${wanted.map(() => "?").join(",")})
      ORDER BY CASE section WHEN 'mission' THEN 0 WHEN 'types' THEN 1 ELSE 2 END`,
    wanted,
  );
  for (const r of rows) {
    const path = String(r.path);
    if (out.has(path)) continue;
    const base = apiHref(String(r.section) as ApiSection, String(r.page));
    if (r.name === "") out.set(path, base);
    else {
      const m = JSON.parse(String(r.entry)) as Member;
      out.set(path, m.href ?? `${base}#${m.anchor}`);
    }
  }
  return out;
}

/** Overlays naming this page or its members, layered on (stale ones never match). */
export function applyOverlays(page: ApiPage, file: ApiOverlayFile): ApiPage {
  const pick = (symbol: string): ApiOverlay | undefined => {
    const o = file.symbols[symbol];
    return o && (!o.section || o.section === page.section) ? o : undefined;
  };
  const layer = <
    T extends {
      description?: string;
      summary?: string;
      deprecated?: boolean | string;
      overlay?: ApiOverlay;
    },
  >(
    node: T,
    o: ApiOverlay | undefined,
  ): T => {
    if (!o) return node;
    const out: T = { ...node, overlay: o };
    if (o.description) out.description = o.description;
    if (o.summary) out.summary = o.summary;
    if (o.deprecated !== undefined) out.deprecated = o.deprecated;
    return out;
  };
  return {
    ...layer(page, pick(page.name)),
    groups: page.groups.map((g) => ({
      ...g,
      members: g.members.map((m) => layer(m, pick(`${page.name}.${m.name}`))),
    })),
  };
}

/** seeAlso targets of the page's overlays, resolved; unresolvable ones are dropped. */
export async function overlayLinks(q: Query, page: ApiPage): Promise<Map<string, string>> {
  const all = [
    ...(page.overlay?.seeAlso ?? []),
    ...page.groups.flatMap((g) => g.members.flatMap((m) => m.overlay?.seeAlso ?? [])),
  ];
  return resolveSymbols(q, all);
}

export type ApiSearchHit = { href: string; path: string; subtitle: string; score: number };

/** FTS over the `search` rows of the API (one MATCH with the reference rows' index). */
export async function searchApi(q: Query, query: string, limit = 40): Promise<ApiSearchHit[]> {
  const match = ftsQuery(query);
  if (!match) return [];
  const rows = await q(
    `SELECT s.id AS id, s.name AS name, s.subtitle AS subtitle,
            bm25(search_fts, 8.0, 2.0, 1.0) AS score
       FROM search_fts JOIN search s ON s.rowid = search_fts.rowid
      WHERE search_fts MATCH ? AND s.series = ? ORDER BY score LIMIT ?`,
    [match, API_SERIES, limit],
  );
  const wanted = query
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
  return rows
    .map((r) => {
      const path = String(r.name);
      const last = path.split(/[.:]/).pop() ?? path;
      const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");
      const exact = norm(path) === wanted || norm(last) === wanted;
      return {
        href: String(r.id),
        path,
        subtitle: String(r.subtitle ?? ""),
        score: -Number(r.score ?? 0) * (exact ? 3 : 1),
      };
    })
    .sort((a, b) => b.score - a.score);
}
