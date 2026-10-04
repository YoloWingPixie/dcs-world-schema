import { Fragment } from "react";
import type { Token } from "@/lib/api/types";
import { ApiLink } from "./api-link";

export type Links = Record<string, string>;

/** Display tokens; `{ r }` tokens link to their type's page when the page knows it. */
export function Tokens({ tokens, links }: { tokens: Token[]; links: Links }) {
  return (
    <>
      {tokens.map((t, i) => {
        const key = `${i}-${typeof t === "string" ? t : t.r}`;
        if (typeof t === "string") return <Fragment key={key}>{t}</Fragment>;
        const href = links[t.r];
        return href ? (
          <ApiLink key={key} href={href} className="api-type">
            {t.r}
          </ApiLink>
        ) : (
          <span key={key} className="api-type api-type-unresolved">
            {t.r}
          </span>
        );
      })}
    </>
  );
}

/** A type in Lua style, every type name linked. */
export function TypeRef({ tokens, links }: { tokens: Token[]; links: Links }) {
  return (
    <code className="api-typeref">
      <Tokens tokens={tokens} links={links} />
    </code>
  );
}

/** A Lua-style signature: `Unit.getByName(name: string): Unit?`. */
export function Signature({ tokens, links }: { tokens: Token[]; links: Links }) {
  return (
    <code className="api-sig">
      <Tokens tokens={tokens} links={links} />
    </code>
  );
}

/** Schema text: `backticked` spans become code, linked when they name a known type. */
export function RichText({ text, links }: { text: string; links: Links }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        const key = `${i}-${part.length}`;
        if (/^`[^`]+`$/.test(part)) {
          const inner = part.slice(1, -1);
          const href = links[inner];
          return href ? (
            <ApiLink key={key} href={href} className="api-code-link">
              <code>{inner}</code>
            </ApiLink>
          ) : (
            <code key={key}>{inner}</code>
          );
        }
        return <Fragment key={key}>{part}</Fragment>;
      })}
    </>
  );
}
