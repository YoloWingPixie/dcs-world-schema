"use client";

import Link from "next/link";
import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from "react";
import { BASE_PATH } from "@/lib/base-path";
import { pushUrl } from "@/lib/history";
import { type NavHint, setNavHint } from "@/lib/nav-hints";

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
export function navigateReference(href: string) {
  const url = `${BASE_PATH}${href}`;
  if (shellMounted > 0) {
    pushUrl(url);
    window.scrollTo(0, 0);
  } else window.location.assign(url);
}

type Props = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  /** Site path without basePath. */
  href: string;
  children: ReactNode;
  /** Shown on the record page while it loads; defaults to the link text. */
  hint?: NavHint;
};

/** Scrolls to the element the URL's hash names (after a client-side page change). */
export function scrollToHash() {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (!id) return;
  document.getElementById(id)?.scrollIntoView();
}

/**
 * A link to a site path (a reference record or series page, an API page): plain <a>,
 * client-side inside the shell (which scrolls to a hash once the page renders), and a plain
 * hash jump within the same page.
 */
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
        const [path, hash] = href.split("#");
        if (hash !== undefined && path === window.location.pathname.slice(BASE_PATH.length)) return;
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

/**
 * A link to any site path: RefLink for the reference shell's pages (client-side, so the
 * database worker survives), next/link for the Next.js pages.
 */
export function SiteLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return isShellHref(href) ? (
    <RefLink href={href} className={className}>
      {children}
    </RefLink>
  ) : (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

/** Opens any site path: the shell for reference pages, the Next.js router otherwise. */
export function openHref(href: string, router: { push: (href: string) => void }) {
  if (isShellHref(href)) navigateReference(href);
  else router.push(href);
}
