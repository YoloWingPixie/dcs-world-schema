import { Fragment } from "react";
import type { Token } from "@/lib/api/types";
import { ApiLink } from "./api-link";
import { signatureParams, splitSignature, tokenText, WRAP_AT } from "./signature";

export type Links = Record<string, string>;

/** Display tokens; `{ r }` tokens link to their type's page when the page knows it. */
export function Tokens({
  tokens,
  links,
  unfocusable,
}: {
  tokens: Token[];
  links: Links;
  /** The tokens are not shown: keep their links out of the tab order. */
  unfocusable?: boolean;
}) {
  return (
    <>
      {tokens.map((t, i) => {
        const key = `${i}-${typeof t === "string" ? t : t.r}`;
        if (typeof t === "string") return <Fragment key={key}>{t}</Fragment>;
        const href = links[t.r];
        return href ? (
          <ApiLink
            key={key}
            href={href}
            className="api-type"
            tabIndex={unfocusable ? -1 : undefined}
          >
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

/** The owner and name a signature starts with (`Object:` and `getName`). */
export type SigLead = { owner: string; name: string };

/**
 * The leading `Owner:name` of a qualified name, the owner quiet and the name strong. The
 * text stays the full qualified name, so it copies as written.
 */
export function LeadName({ lead }: { lead: SigLead }) {
  return (
    <>
      {lead.owner ? <span className="api-sig-owner">{lead.owner}</span> : null}
      <span className="api-sig-name">{lead.name}</span>
    </>
  );
}

/** Tokens, with the first one's `Owner:name` prefix set by `LeadName`. */
function LeadTokens({
  tokens,
  links,
  lead,
}: {
  tokens: Token[];
  links: Links;
  lead?: SigLead | undefined;
}) {
  const first = tokens[0];
  const prefix = lead ? lead.owner + lead.name : "";
  if (!lead || typeof first !== "string" || !first.startsWith(prefix)) {
    return <Tokens tokens={tokens} links={links} />;
  }
  return (
    <>
      <LeadName lead={lead} />
      <Tokens tokens={[first.slice(prefix.length), ...tokens.slice(1)]} links={links} />
    </>
  );
}

/**
 * A Lua-style signature: `Unit.getByName(name: string): Unit?`. With `wrap`, a long one
 * (or any with two or more parameters, on a phone) sets each parameter on its own line:
 * block spans, so the text is unchanged. With `lead`, the owner is quiet and the name
 * strong.
 */
export function Signature({
  tokens,
  links,
  wrap,
  wrapAt = WRAP_AT,
  lead,
  brief,
}: {
  tokens: Token[];
  links: Links;
  wrap?: boolean;
  /** Characters past which a wrapping signature sets one parameter per line. */
  wrapAt?: number;
  lead?: SigLead | undefined;
  /**
   * Show parameter names only (a list below gives their types). The annotations stay in
   * the text, hidden, so the signature still reads and copies in full; it is the title.
   */
  brief?: boolean;
}) {
  const split = brief ? signatureParams(tokens) : null;
  if (split) {
    return (
      <code className="api-sig api-sig-brief" title={tokenText(tokens)}>
        <LeadTokens tokens={split.head} links={links} lead={lead} />
        {split.params.map((p, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: parameters are positional
          <Fragment key={i}>
            <Tokens tokens={p.name} links={links} />
            {p.type.length ? (
              <span className="api-sig-ptype">
                <Tokens tokens={p.type} links={links} unfocusable />
              </span>
            ) : null}
            <Tokens tokens={p.sep} links={links} />
          </Fragment>
        ))}
        <Tokens tokens={split.tail} links={links} />
      </code>
    );
  }
  const parts = wrap ? splitSignature(tokens) : null;
  if (!parts) {
    return (
      <code className="api-sig">
        <LeadTokens tokens={tokens} links={links} lead={lead} />
      </code>
    );
  }
  return (
    <code
      className={
        tokenText(tokens).length > wrapAt
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
          <LeadTokens tokens={part} links={links} lead={i === 0 ? lead : undefined} />
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
