"use client";

import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from "react";
import { type NavHint, setNavHint } from "@/lib/nav-hints";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

let shellMounted = 0;

/** The reference shell (app/not-found.tsx) registers itself while it is on screen. */
export function registerShell(): () => void {
  shellMounted++;
  return () => {
    shellMounted--;
  };
}

/**
 * Navigate to a reference path (`/weapons/AIM_120C/`). Inside the shell this is a
 * history push (Next.js syncs usePathname with native pushState), so the database
 * worker and its page cache survive; elsewhere it is a normal page load, which the host
 * answers with the shell (404.html).
 */
export function navigateReference(href: string, { replace = false } = {}) {
  const url = `${BASE_PATH}${href}`;
  if (shellMounted > 0) {
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    window.scrollTo(0, 0);
  } else if (replace) window.location.replace(url);
  else window.location.assign(url);
}

type Props = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  /** Site path without basePath. */
  href: string;
  children: ReactNode;
  /** Shown on the record page while it loads; defaults to the link text. */
  hint?: NavHint;
};

/** A link to a reference record or series page (plain <a>, client-side inside the shell). */
export function RefLink({ href, onClick, children, hint, ...rest }: Props) {
  return (
    <a
      {...rest}
      href={`${BASE_PATH}${href}`}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(event);
        const name = hint ?? (typeof children === "string" ? { name: children } : null);
        if (name) setNavHint(href, name);
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        event.preventDefault();
        navigateReference(href);
      }}
    >
      {children}
    </a>
  );
}

/** Site sections that are Next.js pages (everything else is the reference shell). */
const PAGE_ROOTS = new Set(["", "compare", "reference", "search"]);

export function isShellHref(href: string): boolean {
  const first = href.split(/[/?#]/).filter(Boolean)[0] ?? "";
  return !PAGE_ROOTS.has(first);
}

/** Opens any site path: the shell for reference pages, the Next.js router otherwise. */
export function openHref(href: string, router: { push: (href: string) => void }) {
  if (isShellHref(href)) navigateReference(href);
  else router.push(href);
}
