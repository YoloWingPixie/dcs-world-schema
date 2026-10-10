import type { Overlay } from "@/lib/types";
import { SiteLink } from "./ref-link";

/** An overlay's "See also" line: site links route client-side, external ones open as links. */
export function SeeAlso({ links }: { links: Overlay["seeAlso"] }) {
  if (!links?.length) return null;
  return (
    <p className="see-also">
      See also{" "}
      {links.map((s, i) => (
        <span key={s.href}>
          {i ? ", " : ""}
          {/^[a-z]+:/i.test(s.href) ? (
            <a href={s.href} rel="noopener noreferrer">
              {s.label}
            </a>
          ) : (
            <SiteLink href={s.href}>{s.label}</SiteLink>
          )}
        </span>
      ))}
    </p>
  );
}
