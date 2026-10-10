/**
 * The Lua API as a chapter of the contents list (home, /reference): the API home's own
 * groupings (components/api/api-home.tsx), each counted from the API page rows.
 */
import type { Query } from "../db/reference";

/** Pages per section and kind: `apiPages` in /data/reference.json, or `apiPageCounts`. */
export type ApiPageCounts = Record<string, Record<string, number>>;

export type ApiContentsEntry = {
  /** The API home's section anchor. */
  id: string;
  label: string;
  href: string;
  blurb: string;
  count: number;
};

const sum = (o: Record<string, number> | undefined, pick: (kind: string) => boolean = () => true) =>
  Object.entries(o ?? {}).reduce((n, [k, v]) => n + (pick(k) ? v : 0), 0);

/** The chapter's sections, in the API home's order; sections with no pages are left out. */
export function apiContents(counts: ApiPageCounts): ApiContentsEntry[] {
  const entries: ApiContentsEntry[] = [
    {
      id: "classes",
      label: "Classes",
      href: "/api/#classes",
      blurb: "Unit, Group, Airbase, Weapon: the objects a mission script is handed.",
      count: sum(counts.mission, (k) => k === "class"),
    },
    {
      id: "globals",
      label: "Global tables and namespaces",
      href: "/api/#globals",
      blurb: "coalition, world, timer, trigger.action and the other mission globals.",
      count: sum(counts.mission, (k) => k !== "class"),
    },
    {
      id: "hooks",
      label: "Hooks (GameGUI)",
      href: "/api/#hooks",
      blurb: "The server and GUI hooks environment: DCS, net, Sim and their tables.",
      count: sum(counts.hooks),
    },
    {
      id: "export",
      label: "Export",
      href: "/api/#export",
      blurb: "Globals of the Export.lua environment.",
      count: sum(counts.export),
    },
    {
      id: "server",
      label: "Server",
      href: "/api/#server",
      blurb: "Globals of the dedicated server environment.",
      count: sum(counts.server),
    },
    {
      id: "types",
      label: "Types",
      href: "/api/#types",
      blurb: "Records, enums and unions the functions take and return: DcsTask, DcsId, AI.",
      count: sum(counts.types),
    },
  ];
  return entries.filter((e) => e.count > 0);
}

/** The counts from the database itself (one read of the page-row index). */
export async function apiPageCounts(q: Query): Promise<ApiPageCounts> {
  const rows = await q(
    `SELECT section, kind, COUNT(*) AS n FROM api_symbols WHERE name = '' GROUP BY section, kind`,
  );
  const out: ApiPageCounts = {};
  for (const r of rows) {
    const section = String(r.section);
    out[section] = { ...out[section], [String(r.kind)]: Number(r.n ?? 0) };
  }
  return out;
}
