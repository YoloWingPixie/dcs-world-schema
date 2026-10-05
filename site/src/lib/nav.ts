/**
 * Top-level site sections, in header order. The header, the home page and the
 * footer read this list; add a section by appending an entry (no other wiring).
 *
 * `match` lists the path prefixes (without basePath) that mark the entry as the
 * current section; it defaults to `[href]`.
 */
import { SERIES } from "./series";

export type NavSection = {
  id: string;
  label: string;
  href: string;
  match?: string[];
};

export const NAV_SECTIONS: NavSection[] = [
  {
    id: "reference",
    label: "Reference",
    href: "/reference/",
    match: ["/reference", ...SERIES.map((s) => `/${s.id}/`)],
  },
  {
    id: "compare",
    label: "Compare",
    href: "/compare/",
  },
  {
    id: "api",
    label: "Lua API",
    href: "/api/",
  },
];

/** The nav entry the given pathname belongs to, if any. */
export function currentSection(
  pathname: string | null,
  sections: NavSection[] = NAV_SECTIONS,
): NavSection | null {
  if (!pathname) return null;
  return (
    sections.find((s) => (s.match ?? [s.href]).some((prefix) => pathname.startsWith(prefix))) ??
    null
  );
}
