import type { ApiSection } from "./types";

const PREFIXED: ApiSection[] = ["types", "hooks", "export", "server"];

/**
 * A page's path: dots become segments (`/api/trigger/action/`), types and other
 * environments get a prefix (`/api/types/DcsTask/Task/Orbit/`, `/api/hooks/DCS/`).
 * Mirrors tools/package/api_docs.py `page_href`.
 */
export function apiHref(section: ApiSection, name: string): string {
  const path = name
    .split(".")
    .map((p) => encodeURIComponent(p))
    .join("/");
  return section === "mission" ? `/api/${path}/` : `/api/${section}/${path}/`;
}

/** `/api/...` (basePath removed) -> home, a page, or null when not an API path. */
export function parseApiPath(
  pathname: string,
): { home: true } | { home: false; section: ApiSection; name: string } | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] !== "api") return null;
  const rest = parts.slice(1);
  if (!rest.length) return { home: true };
  let section: ApiSection = "mission";
  if ((PREFIXED as string[]).includes(rest[0] ?? "") && rest.length > 1) {
    section = rest.shift() as ApiSection;
  }
  try {
    return { home: false, section, name: rest.map((p) => decodeURIComponent(p)).join(".") };
  } catch {
    return null;
  }
}

export const isApiPath = (pathname: string) => /^\/api(\/|$)/.test(pathname);
