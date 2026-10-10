/**
 * Top-level site sections, in header order. The header's nav and phone menu read this
 * list, and so does site link routing (`PAGE_ROOTS`, components/ref-link `isShellHref`);
 * add a section by appending an entry (no other wiring).
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
  /**
   * `page`: a Next.js page. `shell`: client-routed by the reference shell from the 404 page
   * (components/ref-link `isShellHref`).
   */
  kind: "page" | "shell";
  /**
   * `false`: the link does not prefetch (a shell section's route tree prefetch gets the
   * 404 shell back).
   */
  prefetch?: false;
  /** The header link's class. */
  className?: string;
  /** The link opens the compare selection (its href and count from components/header `useNavLinks`). */
  compare?: true;
};

export const NAV_SECTIONS: NavSection[] = [
  {
    id: "reference",
    label: "Reference",
    href: "/reference/",
    match: ["/reference", ...SERIES.map((s) => `/${s.id}/`)],
    kind: "page",
    className: "nav-browse",
  },
  {
    id: "compare",
    label: "Compare",
    href: "/compare/",
    kind: "page",
    compare: true,
  },
  {
    id: "api",
    label: "Lua API",
    href: "/api/",
    kind: "shell",
    prefetch: false,
  },
];

/** Next.js pages outside the sections: the home page and search. */
const OTHER_PAGES = ["/", "/search/"];

/** A site path's first segment ("" for the home page). */
export const pathRoot = (href: string) => href.split(/[/?#]/).filter(Boolean)[0] ?? "";

/** The first path segments of the Next.js pages (everything else is the reference shell). */
export const PAGE_ROOTS: ReadonlySet<string> = new Set(
  [...OTHER_PAGES, ...NAV_SECTIONS.filter((s) => s.kind === "page").map((s) => s.href)].map(
    pathRoot,
  ),
);

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
