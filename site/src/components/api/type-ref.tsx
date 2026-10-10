import { Fragment } from "react";
import type { Token } from "@/lib/api/types";
import { ApiLink } from "./api-link";
import { splitSignature, tokenText, WRAP_AT } from "./signature";

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

/**
 * A Lua-style signature: `Unit.getByName(name: string): Unit?`. With `wrap`, a long one
 * (or any with two or more parameters, on a phone) sets each parameter on its own line:
 * block spans, so the text is unchanged.
 */
export function Signature({
  tokens,
  links,
  wrap,
}: {
  tokens: Token[];
  links: Links;
  wrap?: boolean;
}) {
  const parts = wrap ? splitSignature(tokens) : null;
  if (!parts) {
    return (
      <code className="api-sig">
        <Tokens tokens={tokens} links={links} />
      </code>
    );
  }
  return (
    <code
      className={
        tokenText(tokens).length > WRAP_AT
          ? "api-sig api-sig-split api-sig-wrap"
          : "api-sig api-sig-split"
      }
    >
      {parts.map((part, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: parts are positional
          key={i}
          className={
            i === 0 ? "api-sig-head" : i === parts.length - 1 ? "api-sig-tail" : "api-sig-param"
          }
        >
          <Tokens tokens={part} links={links} />
        </span>
      ))}
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
