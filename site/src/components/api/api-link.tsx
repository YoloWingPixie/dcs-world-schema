"use client";

import type { MouseEvent, ReactNode } from "react";
import { navigateReference } from "../ref-link";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Scrolls to the element the URL's hash names (after a client-side page change). */
export function scrollToHash() {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (!id) return;
  document.getElementById(id)?.scrollIntoView();
}

/**
 * A link to a site path (an API page, a reference record): client-side inside the shell,
 * a plain hash jump within the same page.
 */
export function ApiLink({
  href,
  className,
  children,
  ...rest
}: {
  href: string;
  className?: string;
  children: ReactNode;
  "aria-label"?: string;
  title?: string;
  tabIndex?: number | undefined;
}) {
  return (
    <a
      {...rest}
      className={className}
      href={`${BASE_PATH}${href}`}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        if (
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        const [path] = href.split("#");
        if (path === window.location.pathname.slice(BASE_PATH.length)) return; // same page: hash jump
        event.preventDefault();
        navigateReference(href); // the shell scrolls to the hash once the page renders
      }}
    >
      {children}
    </a>
  );
}
