"use client";

import { useRouter } from "next/navigation";
import type { MouseEvent } from "react";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Prefixes basePath onto site-relative links (`/x` but not `//x`). */
export function withBasePath(html: string): string {
  if (!BASE_PATH) return html;
  return html.replace(/href="\/(?!\/)/g, `href="${BASE_PATH}/`);
}

type Props = {
  /** HTML from lib/markdown.ts `renderMarkdown` (prebuilt at build time). */
  html: string;
  className?: string;
  /** Styles overlay content apart from data extracted from DCS. */
  handWritten?: boolean;
};

/** Renders prebuilt Markdown HTML; internal links navigate client-side. */
export function Markdown({ html, className, handWritten }: Props) {
  const router = useRouter();
  const onClick = (event: MouseEvent<HTMLDivElement>) => {
    const a = (event.target as HTMLElement).closest<HTMLAnchorElement>("a[data-internal]");
    if (!a || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    const href = a.getAttribute("href") ?? "";
    if (!href.startsWith("/") && !href.startsWith("?")) return;
    event.preventDefault();
    router.push(BASE_PATH && href.startsWith(BASE_PATH) ? href.slice(BASE_PATH.length) : href);
  };
  const classes = ["md", handWritten ? "md-overlay" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: delegates to real links, which handle keys
    // biome-ignore lint/a11y/noStaticElementInteractions: click delegation for links only
    <div className={classes} onClick={onClick}>
      {/* biome-ignore lint/security/noDangerouslySetInnerHtml: renderMarkdown escapes raw HTML */}
      <div className="md-body" dangerouslySetInnerHTML={{ __html: withBasePath(html) }} />
    </div>
  );
}
