import type { ReactNode } from "react";
import { Markdown } from "@/components/Markdown";
import type { ApiEnv, ApiOverlay, Example, FieldEntry, Member } from "@/lib/api/types";
import { ApiLink } from "./api-link";
import { LeadName, type Links, RichText, type SigLead, Signature, TypeRef } from "./type-ref";

export const ENV_LABEL: Record<ApiEnv, string> = {
  mission: "Mission",
  hooks: "Hooks",
  export: "Export",
  server: "Server",
};

export function EnvBadges({ envs }: { envs?: ApiEnv[] | undefined }) {
  if (!envs?.length) return null;
  return (
    <>
      {envs.map((e) => (
        <span key={e} className={`api-badge api-env api-env-${e}`}>
          {ENV_LABEL[e]}
        </span>
      ))}
    </>
  );
}

/** Overlay content, styled apart from the generated entry. */
export function OverlayBlock({ overlay }: { overlay: ApiOverlay }) {
  if (!overlay.html) return null;
  return (
    <aside className="api-overlay" aria-label="Notes">
      <Markdown html={overlay.html} handWritten className="api-prose" />
    </aside>
  );
}

/** "See also": overlay targets (resolved by the shell) after the generated pairs. */
export function SeeAlso({
  related,
  seeAlso,
  links,
}: {
  related?: Array<{ label: string; href: string }> | undefined;
  seeAlso?: string[] | undefined;
  links: Links;
}) {
  const items = [...(related ?? [])];
  for (const s of seeAlso ?? []) {
    const href = links[s];
    if (href && !items.some((i) => i.href === href)) items.push({ label: s, href });
  }
  if (!items.length) return null;
  return (
    <p className="api-related">
      <span className="api-sub-inline">See also</span>{" "}
      {items.map((r, i) => (
        <span key={r.href}>
          {i ? ", " : null}
          <ApiLink href={r.href}>
            <code>{r.label}</code>
          </ApiLink>
        </span>
      ))}
    </p>
  );
}

export function Examples({ examples, bare }: { examples: Example[]; bare?: boolean }) {
  return (
    <div className="api-examples">
      {bare ? null : <h4 className="api-sub">{examples.length > 1 ? "Examples" : "Example"}</h4>}
      {examples.map((ex, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: examples are static and ordered
        <figure key={i} className="api-example">
          {ex.description ? <figcaption>{ex.description}</figcaption> : null}
          <pre>
            <code className="language-lua">{ex.code}</code>
          </pre>
        </figure>
      ))}
    </div>
  );
}

/**
 * Named, typed items (parameters, record fields) in the record pages' row idiom:
 * `name . . . . type`, "optional" as a quiet mark, the description underneath.
 */
export function ParamList({
  items,
  label,
}: {
  items: Array<{
    key: string;
    id?: string | undefined;
    name: string;
    optional?: boolean | undefined;
    type: ReactNode;
    extra?: ReactNode;
    description?: ReactNode;
  }>;
  label: string;
}) {
  return (
    <ul className="api-params" aria-label={label}>
      {items.map((it) => (
        <li key={it.key} id={it.id} className="api-param">
          <div className="api-param-head">
            <code className="api-param-name">{it.name}</code>
            {it.optional ? <span className="api-opt">optional</span> : null}
            <span className="api-leader" aria-hidden="true" />
            <span className="api-param-type">{it.type}</span>
          </div>
          {it.extra || it.description ? (
            <div className="api-param-desc">
              {it.description}
              {it.extra}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Record fields (types, nested tables). */
export function FieldsTable({
  fields,
  links,
}: {
  fields: Array<FieldEntry | Member>;
  links: Links;
}) {
  const showRequired = fields.some((f) => f.required !== undefined);
  return (
    <ParamList
      label="Fields"
      items={fields.map((f) => ({
        key: f.name,
        id: "anchor" in f ? f.anchor : undefined,
        name: f.name,
        optional: showRequired && f.required === false,
        type: f.sig ? (
          <Signature tokens={f.sig} links={links} />
        ) : (
          <TypeRef tokens={f.type ?? ["any"]} links={links} />
        ),
        description: f.description ? <RichText text={f.description} links={links} /> : null,
        extra: (
          <>
            {f.fields?.length ? (
              <span className="api-nested"> Fields: {f.fields.map((x) => x.name).join(", ")}.</span>
            ) : null}
            {f.overlay ? <OverlayBlock overlay={f.overlay} /> : null}
          </>
        ),
      }))}
    />
  );
}

/** What a member is, in the words its heading would use. */
export function memberKind(m: Member): string {
  return m.kind === "function" ? (m.call === ":" ? "method" : "function") : m.kind;
}

/** One row of an entry: the hanging label, then its content. */
function Row({ label, warn, children }: { label: string; warn?: boolean; children: ReactNode }) {
  return (
    <div className="api-row">
      <dt className={warn ? "api-label api-label-warn" : "api-label"}>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * One function, field, constant or namespace, with its anchor, set as a reference-manual
 * entry: the number and the signature as its heading (the name strong), the description
 * under it, then labelled rows only for structured extras (parameters, fields, notes…).
 */
export function MemberEntry({
  member: m,
  links,
  pageEnv,
  pageSince,
  number,
  showKind,
}: {
  member: Member;
  links: Links;
  pageEnv?: string | undefined;
  /** The page's own "since": an entry says its version only when it differs. */
  pageSince?: string | undefined;
  /** "2.3": the entry's number in the page. */
  number?: string | undefined;
  /** The section mixes kinds: say which this one is. */
  showKind?: boolean | undefined;
}) {
  const isFn = m.kind === "function";
  const envs = m.environment && m.environment.join() !== pageEnv ? m.environment : undefined;
  const params = m.params ?? [];
  const since = m.overlay?.since ?? (m.addedVersion !== "unknown" ? m.addedVersion : undefined);
  const lead: SigLead = {
    owner: m.qualified.endsWith(m.name) ? m.qualified.slice(0, -m.name.length) : "",
    name: m.qualified.endsWith(m.name) ? m.name : m.qualified,
  };
  const related = [...(m.related ?? [])];
  for (const s of m.overlay?.seeAlso ?? []) {
    const href = links[s];
    if (href && !related.some((i) => i.href === href)) related.push({ label: s, href });
  }
  const aside = [
    showKind ? memberKind(m) : null,
    m.readonly ? "read-only" : null,
    envs?.length ? envs.map((e) => ENV_LABEL[e]).join(", ") : null,
    since && since !== pageSince ? `since ${since}` : null,
  ].filter(Boolean);
  return (
    <article className="api-member" id={m.anchor} aria-labelledby={`${m.anchor}-h`}>
      <h3 id={`${m.anchor}-h`} className="api-member-head">
        <a href={`#${m.anchor}`} className="api-anchor" aria-label={`Link to ${m.qualified}`}>
          {number ?? "#"}
        </a>
        {m.sig ? (
          // With a PARAMETERS list the heading names the parameters only; without one it
          // gives the typed signature, one parameter per line past what the line holds.
          <Signature
            tokens={m.sig}
            links={links}
            wrap
            wrapAt={88}
            lead={lead}
            brief={isFn && params.length > 0}
          />
        ) : m.kind === "constant" ? (
          <code className="api-sig">
            <LeadName lead={lead} /> = {JSON.stringify(m.value)}
          </code>
        ) : m.kind === "namespace" ? (
          <code className="api-sig">
            {m.href ? (
              <ApiLink href={m.href}>
                <LeadName lead={lead} />
              </ApiLink>
            ) : (
              <LeadName lead={lead} />
            )}
          </code>
        ) : (
          <code className="api-sig">
            <LeadName lead={lead} />: <TypeRef tokens={m.type ?? ["any"]} links={links} />
          </code>
        )}
        {aside.length ? <span className="api-member-aside">{aside.join(", ")}</span> : null}
      </h3>

      {m.description || (isFn && m.params === null) ? (
        <div className="api-member-desc">
          {m.description ? (
            <p className="api-desc">
              <RichText text={m.description} links={links} />
            </p>
          ) : null}
          {isFn && m.params === null ? <p className="api-note">Signature unknown.</p> : null}
        </div>
      ) : null}

      {m.deprecated ||
      (isFn && params.length) ||
      (isFn && m.returns?.length && m.returnValueExample) ||
      (!isFn && m.fields?.length) ||
      m.examples?.length ||
      m.overlay?.html ||
      related.length ? (
        <dl className="api-entry">
          {m.deprecated ? (
            <Row label="Deprecated" warn>
              <p className="api-deprecated">
                {typeof m.deprecated === "string" ? m.deprecated : "Do not use in new scripts."}
              </p>
            </Row>
          ) : null}

          {isFn && params.length ? (
            <Row label="Parameters">
              <ParamList
                label={`Parameters of ${m.qualified}`}
                items={params.map((p) => ({
                  key: p.name,
                  name: p.name,
                  optional: p.optional,
                  type: <TypeRef tokens={p.t} links={links} />,
                  description: p.description ? (
                    <RichText text={p.description} links={links} />
                  ) : null,
                  extra:
                    p.default !== undefined ? (
                      <span className="api-default">
                        Default <code>{p.default}</code>.
                      </span>
                    ) : null,
                }))}
              />
            </Row>
          ) : null}

          {/* The heading already ends in the return type: a row only when it adds to it. */}
          {isFn && m.returns?.length && m.returnValueExample ? (
            <Row label="Returns">
              <p className="api-returns">
                {m.returns.map((r, i) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: return values are positional
                  <span key={i}>
                    {i ? ", " : null}
                    <TypeRef tokens={r} links={links} />
                  </span>
                ))}
                <span className="api-default">
                  For example <code>{m.returnValueExample}</code>.
                </span>
              </p>
            </Row>
          ) : null}

          {!isFn && m.fields?.length ? (
            <Row label="Fields">
              <FieldsTable fields={m.fields} links={links} />
            </Row>
          ) : null}

          {m.examples?.length ? (
            <Row label={m.examples.length > 1 ? "Examples" : "Example"}>
              <Examples examples={m.examples} bare />
            </Row>
          ) : null}

          {m.overlay?.html ? (
            <Row label="Note">
              <OverlayBlock overlay={m.overlay} />
            </Row>
          ) : null}

          {related.length ? (
            <Row label="See also">
              <p className="api-related">
                {related.map((r, i) => (
                  <span key={r.href}>
                    {i ? ", " : null}
                    <ApiLink href={r.href}>
                      <code>{r.label}</code>
                    </ApiLink>
                  </span>
                ))}
              </p>
            </Row>
          ) : null}
        </dl>
      ) : null}
    </article>
  );
}
