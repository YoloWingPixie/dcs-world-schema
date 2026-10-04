import { Markdown } from "@/components/Markdown";
import type { ApiEnv, ApiOverlay, Example, FieldEntry, Member } from "@/lib/api/types";
import { ApiLink } from "./api-link";
import { type Links, RichText, Signature, TypeRef } from "./type-ref";

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
        <span
          key={e}
          className={`api-badge api-env api-env-${e}`}
          title={`Environment: ${ENV_LABEL[e]}`}
        >
          {ENV_LABEL[e]}
        </span>
      ))}
    </>
  );
}

/** Hand-written content: marked, quietly, as not generated from the schema. */
export function OverlayBlock({ overlay }: { overlay: ApiOverlay }) {
  if (!overlay.html) return null;
  return (
    <aside className="api-overlay" aria-label="Hand-written notes" title={`From ${overlay.source}`}>
      <Markdown html={overlay.html} handWritten="Hand-written" className="api-prose" />
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

export function Examples({ examples }: { examples: Example[] }) {
  return (
    <div className="api-examples">
      <h4 className="api-sub">{examples.length > 1 ? "Examples" : "Example"}</h4>
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
    <div className="table-wrap api-table-wrap">
      <table className="table api-table">
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Type</th>
            <th scope="col">Description</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.name} id={"anchor" in f ? f.anchor : undefined}>
              <td className="api-name-cell">
                <code>{f.name}</code>
                {showRequired && f.required === false ? (
                  <span className="api-opt">optional</span>
                ) : null}
              </td>
              <td>
                {f.sig ? (
                  <Signature tokens={f.sig} links={links} />
                ) : (
                  <TypeRef tokens={f.type ?? ["any"]} links={links} />
                )}
              </td>
              <td className="api-desc-cell">
                {f.description ? <RichText text={f.description} links={links} /> : null}
                {f.fields?.length ? (
                  <span className="api-nested">
                    {" "}
                    Fields: {f.fields.map((x) => x.name).join(", ")}.
                  </span>
                ) : null}
                {f.overlay ? <OverlayBlock overlay={f.overlay} /> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One function, field, constant or namespace, with its anchor. */
export function MemberEntry({
  member: m,
  links,
  pageEnv,
}: {
  member: Member;
  links: Links;
  pageEnv?: string | undefined;
}) {
  const isFn = m.kind === "function";
  const envs = m.environment && m.environment.join() !== pageEnv ? m.environment : undefined;
  const params = m.params ?? [];
  return (
    <article className="api-member" id={m.anchor} aria-labelledby={`${m.anchor}-h`}>
      <header className="api-member-head">
        <h3 id={`${m.anchor}-h`} className="api-member-name">
          <a href={`#${m.anchor}`} className="api-anchor" aria-label={`Link to ${m.qualified}`}>
            #
          </a>
          {m.kind === "namespace" && m.href ? (
            <ApiLink href={m.href}>{m.qualified}</ApiLink>
          ) : (
            <span>{m.name}</span>
          )}
        </h3>
        <span className="api-member-badges">
          <span className="api-badge">
            {isFn ? (m.call === ":" ? "method" : "function") : m.kind}
          </span>
          {m.readonly ? <span className="api-badge">read-only</span> : null}
          <EnvBadges envs={envs} />
          {m.deprecated ? <span className="api-badge api-badge-warn">deprecated</span> : null}
          {m.addedVersion ? (
            <span className="api-badge api-badge-quiet" title="DCS version that added it">
              since {m.addedVersion}
            </span>
          ) : null}
          {m.overlay?.since ? (
            <span className="api-badge api-badge-quiet" title="From the hand-written notes">
              since {m.overlay.since}
            </span>
          ) : null}
        </span>
      </header>

      <div className="api-member-sig">
        {m.sig ? (
          <Signature tokens={m.sig} links={links} />
        ) : m.kind === "constant" ? (
          <code className="api-sig">
            {m.qualified} = {JSON.stringify(m.value)}
          </code>
        ) : m.kind === "namespace" ? (
          <code className="api-sig">{m.qualified}</code>
        ) : (
          <code className="api-sig">
            {m.qualified}: <TypeRef tokens={m.type ?? ["any"]} links={links} />
          </code>
        )}
      </div>

      {typeof m.deprecated === "string" ? (
        <p className="api-deprecated">Deprecated: {m.deprecated}</p>
      ) : null}
      {m.description ? (
        <p className="api-desc">
          <RichText text={m.description} links={links} />
        </p>
      ) : (
        <p className="api-desc api-desc-missing">No description in the schema yet.</p>
      )}

      {isFn && m.params === null ? (
        <p className="api-note">Signature unknown: the API dump does not record one.</p>
      ) : null}

      {isFn && params.length ? (
        <div className="table-wrap api-table-wrap">
          <table className="table api-table">
            <caption className="visually-hidden">Parameters of {m.qualified}</caption>
            <thead>
              <tr>
                <th scope="col">Parameter</th>
                <th scope="col">Type</th>
                <th scope="col">Description</th>
              </tr>
            </thead>
            <tbody>
              {params.map((p) => (
                <tr key={p.name}>
                  <td className="api-name-cell">
                    <code>{p.name}</code>
                    {p.optional ? <span className="api-opt">optional</span> : null}
                  </td>
                  <td>
                    <TypeRef tokens={p.t} links={links} />
                    {p.default !== undefined ? (
                      <span className="api-default">
                        default <code>{p.default}</code>
                      </span>
                    ) : null}
                  </td>
                  <td className="api-desc-cell">
                    {p.description ? <RichText text={p.description} links={links} /> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {isFn && m.returns?.length ? (
        <p className="api-returns">
          <span className="api-sub-inline">Returns</span>{" "}
          {m.returns.map((r, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: return values are positional
            <span key={i}>
              {i ? ", " : null}
              <TypeRef tokens={r} links={links} />
            </span>
          ))}
          {m.returnValueExample ? (
            <span className="api-default">
              e.g. <code>{m.returnValueExample}</code>
            </span>
          ) : null}
        </p>
      ) : null}

      {!isFn && m.fields?.length ? <FieldsTable fields={m.fields} links={links} /> : null}
      {m.examples?.length ? <Examples examples={m.examples} /> : null}
      {m.overlay ? <OverlayBlock overlay={m.overlay} /> : null}
      <SeeAlso related={m.related} seeAlso={m.overlay?.seeAlso} links={links} />
    </article>
  );
}
