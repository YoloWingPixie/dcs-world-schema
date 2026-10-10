/**
 * Address-bar updates that are not navigations: one style for the whole site. The state is
 * null, so Next.js's patched History methods keep their own state and sync the router
 * (useSearchParams, usePathname); the record page is memoised and does not re-render.
 */

/** Pushes a new history entry (an in-page link the Back button should undo). */
export function pushUrl(url: string): void {
  window.history.pushState(null, "", url);
}

/** Replaces the address (a reference page's own path change, `?query` and `#hash` included). */
export function replaceUrl(url: string): void {
  window.history.replaceState(null, "", url);
}

/**
 * Replaces the current address's query (path and hash kept): `URLSearchParams`, or a string
 * already encoded (`lua=_G/a/b` with readable slashes). Nothing happens when it is unchanged.
 */
export function replaceQuery(query: URLSearchParams | string): void {
  const qs = String(query);
  const { pathname, search, hash } = window.location;
  const next = `${pathname}${qs ? `?${qs}` : ""}${hash}`;
  if (next !== `${pathname}${search}${hash}`) replaceUrl(next);
}
