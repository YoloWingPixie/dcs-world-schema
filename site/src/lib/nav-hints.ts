import { parseReferencePath, recordHref } from "./series";

/** What a link already knows about the record it opens, shown before the data loads. */
export type NavHint = {
  name: string;
  /** Meta chips as display labels, joined by " · " (a search result's subtitle). */
  meta?: string;
};

const KEY = "dcs-ref:nav-hints";
const MAX = 50;
const hints = new Map<string, NavHint>();
let restored = false;

/** One key per record, whatever the href's query, hash or encoding. */
function keyOf(href: string): string | null {
  const route = parseReferencePath(href.split(/[?#]/)[0] ?? "");
  return route?.id ? recordHref(route.series, route.id) : null;
}

// Mirrored to sessionStorage so hints survive full page loads (home -> record) and back/forward.
function restore() {
  if (restored) return;
  restored = true;
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "[]") as Array<[string, NavHint]>;
    for (const [k, v] of saved) if (!hints.has(k)) hints.set(k, v);
  } catch {}
}

function persist() {
  try {
    sessionStorage.setItem(KEY, JSON.stringify([...hints].slice(-MAX)));
  } catch {}
}

export function setNavHint(href: string, hint: NavHint) {
  const key = keyOf(href);
  const name = hint.name.trim();
  if (!key || !name) return;
  restore();
  hints.delete(key);
  hints.set(key, hint.meta ? { name, meta: hint.meta } : { name });
  while (hints.size > MAX) hints.delete(hints.keys().next().value as string);
  persist();
}

export function getNavHint(href: string): NavHint | null {
  const key = keyOf(href);
  if (!key) return null;
  restore();
  return hints.get(key) ?? null;
}
