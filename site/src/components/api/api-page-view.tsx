import type { ApiPage, ApiSection, EnumValue, Member } from "@/lib/api/types";
import { ApiLink } from "./api-link";
import { EnumTable } from "./enum-table";
import {
  EnvBadges,
  Examples,
  FieldsTable,
  MemberEntry,
  OverlayBlock,
  SeeAlso,
} from "./member-entry";
import { type Links, RichText, Signature, TypeRef } from "./type-ref";

export const SECTION_LABEL: Record<ApiSection, string> = {
  mission: "Mission scripting",
  hooks: "Hooks (GameGUI)",
  export: "Export",
  server: "Server",
  types: "Types",
};

const KIND_LABEL: Record<ApiPage["kind"], string> = {
  class: "Class",
  singleton: "Global table",
  namespace: "Namespace",
  enum: "Enum",
  record: "Record type",
  table: "Table type",
  union: "Union type",
  array: "Array type",
};

const SERIES_LABEL: Record<string, string> = {
  aircraft: "aircraft",
  ground_vehicles: "ground unit",
  ships: "ship",
  structures: "structure",
  personnel: "personnel",
  weapons: "weapon",
  sensors: "sensor",
  attributes: "attribute",
  skills: "skill",
  formations: "formation",
  airbases: "airbase",
};

/** Pages past this many members list them compactly (the hooks `_G` has 1300). */
const COMPACT_AT = 120;

function CompactMembers({ members, links }: { members: Member[]; links: Links }) {
  return (
    <div className="table-wrap api-table-wrap">
      <table className="table api-table api-compact">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Signature or type</th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.anchor} id={m.anchor}>
              <td className="api-name-cell">
                <a href={`#${m.anchor}`} className="api-compact-name">
                  {m.name}
                </a>
              </td>
              <td>
                {m.sig ? (
                  // The signature without the repeated qualified name.
                  <Signature
                    tokens={m.sig.map((t, i) =>
                      i === 0 && typeof t === "string" ? t.slice(m.qualified.length) : t,
                    )}
                    links={links}
                  />
                ) : m.kind === "constant" ? (
                  <code>{JSON.stringify(m.value)}</code>
                ) : (
                  <TypeRef tokens={m.type ?? ["any"]} links={links} />
                )}
              </td>
              <td className="api-desc-cell">
                {m.description ? <RichText text={m.description} links={links} /> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One API page. `values` carry record links resolved by the shell. */
export function ApiPageView({
  page,
  values,
}: {
  page: ApiPage;
  values?: Array<EnumValue & { href?: string | undefined }> | undefined;
}) {
  const links = page.links;
  const total = page.groups.reduce((n, g) => n + g.members.length, 0);
  const compact = total > COMPACT_AT;
  const pageEnv = page.environment?.join();
  const inherited = page.inherited ?? [];
  const toc: Array<{ id: string; title: string }> = [];
  if (page.values) toc.push({ id: "values", title: "Values" });
  if (page.anyOf) toc.push({ id: "members", title: "Members" });
  if (page.arrayOf) toc.push({ id: "element", title: "Element type" });
  for (const g of page.groups) toc.push({ id: `g-${g.id}`, title: g.title });
  if (inherited.length) toc.push({ id: "inherited", title: "Inherited" });
  if (page.usedBy.length) toc.push({ id: "used-by", title: "Used by" });

  const crumbs: Array<{ label: string; href: string }> = [
    { label: "Lua API", href: "/api/" },
    { label: SECTION_LABEL[page.section], href: `/api/#${page.section}` },
  ];
  if (page.parent) crumbs.push({ label: page.parent.name, href: page.parent.href });
  const showEnv = page.environment?.join() !== (page.section === "types" ? "" : page.section);

  return (
    <div className="api-page">
      <nav className="crumbs" aria-label="Breadcrumb">
        {crumbs.map((c) => (
          <span key={c.label} className="api-crumb">
            <ApiLink href={c.href}>{c.label}</ApiLink>
            <span aria-hidden="true"> /</span>
          </span>
        ))}
        <span aria-current="page">{page.name}</span>
      </nav>

      <header className="plate api-plate">
        <div className="plate-head">
          <div>
            <h1 className="api-title">{page.name}</h1>
            <div className="plate-chips">
              <span className="chip chip-accent">{KIND_LABEL[page.kind] ?? page.kind}</span>
              <span className="chip">{SECTION_LABEL[page.section]}</span>
              {showEnv ? <EnvBadges envs={page.environment} /> : null}
              {page.addedVersion ? (
                <span className="chip">since DCS {page.addedVersion}</span>
              ) : null}
              {page.deprecated ? <span className="chip api-chip-warn">Deprecated</span> : null}
            </div>
          </div>
        </div>
        {page.description ? (
          <p className="api-lede">
            <RichText text={page.description} links={links} />
          </p>
        ) : (
          <p className="api-lede api-desc-missing">No description in the schema yet.</p>
        )}
        {page.inherits?.length || page.subclasses?.length ? (
          <dl className="api-hier">
            {page.inherits?.length ? (
              <div>
                <dt>Inherits</dt>
                <dd>
                  {page.inherits.map((p, i) => (
                    <span key={p.name}>
                      {i ? ", " : null}
                      {p.href ? <ApiLink href={p.href}>{p.name}</ApiLink> : p.name}
                    </span>
                  ))}
                </dd>
              </div>
            ) : null}
            {page.subclasses?.length ? (
              <div>
                <dt>Inherited by</dt>
                <dd>
                  {page.subclasses.map((p, i) => (
                    <span key={p.name}>
                      {i ? ", " : null}
                      <ApiLink href={p.href}>{p.name}</ApiLink>
                    </span>
                  ))}
                </dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </header>

      <div className="record-layout">
        {toc.length > 1 || (!compact && total > 0) ? (
          <nav className="toc api-toc" aria-label="On this page">
            <span className="toc-title">On this page</span>
            {toc.map((t) => (
              <a key={t.id} href={`#${t.id}`}>
                {t.title}
              </a>
            ))}
            {!compact
              ? page.groups.map((g) => (
                  <div key={g.id} className="api-toc-members">
                    {g.members.map((m) => (
                      <a key={m.anchor} href={`#${m.anchor}`} className="api-toc-member">
                        {m.name}
                      </a>
                    ))}
                  </div>
                ))
              : null}
          </nav>
        ) : (
          <div />
        )}

        <div className="api-body">
          {page.overlay ? <OverlayBlock overlay={page.overlay} /> : null}
          <SeeAlso seeAlso={page.overlay?.seeAlso} links={links} />
          {page.examples?.length ? <Examples examples={page.examples} /> : null}

          {page.values ? (
            <section id="values" className="section" aria-labelledby="values-h">
              <div className="section-head">
                <h2 id="values-h">Values</h2>
                <span className="section-blurb">
                  {page.values.length} values
                  {page.valuesSeries
                    ? `; linked ones open the ${SERIES_LABEL[page.valuesSeries] ?? page.valuesSeries} reference page`
                    : ""}
                </span>
              </div>
              <EnumTable
                name={page.name}
                values={values ?? page.values}
                seriesLabel={page.valuesSeries ? SERIES_LABEL[page.valuesSeries] : undefined}
              />
            </section>
          ) : null}

          {page.anyOf ? (
            <section id="members" className="section" aria-labelledby="members-h">
              <div className="section-head">
                <h2 id="members-h">Members</h2>
                <span className="section-blurb">A value of any one of these types</span>
              </div>
              <ul className="api-union">
                {page.anyOf.map((t, i) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: members are ordered
                  <li key={i}>
                    <TypeRef tokens={t} links={links} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {page.arrayOf ? (
            <section id="element" className="section" aria-labelledby="element-h">
              <div className="section-head">
                <h2 id="element-h">Element type</h2>
              </div>
              <p className="api-returns">
                <TypeRef tokens={page.arrayOf} links={links} />
              </p>
            </section>
          ) : null}

          {page.groups.map((g) => (
            <section
              key={g.id}
              id={`g-${g.id}`}
              className="section"
              aria-labelledby={`g-${g.id}-h`}
            >
              <div className="section-head">
                <h2 id={`g-${g.id}-h`}>{g.title}</h2>
                <span className="section-blurb">{g.members.length}</span>
              </div>
              {compact ? (
                <CompactMembers members={g.members} links={links} />
              ) : page.section === "types" && g.members.every((m) => m.kind === "field") ? (
                <FieldsTable fields={g.members} links={links} />
              ) : (
                g.members.map((m) => (
                  <MemberEntry key={m.anchor} member={m} links={links} pageEnv={pageEnv} />
                ))
              )}
            </section>
          ))}

          {inherited.length ? (
            <section id="inherited" className="section" aria-labelledby="inherited-h">
              <div className="section-head">
                <h2 id="inherited-h">Inherited</h2>
                <span className="section-blurb">Declared by a parent; documented there</span>
              </div>
              {inherited.map((g) => (
                <div key={g.from} className="api-inherited">
                  <h3 className="api-sub">
                    From <ApiLink href={g.href}>{g.from}</ApiLink>
                  </h3>
                  <ul className="api-inherited-list">
                    {g.members.map((m) => (
                      <li key={m.name}>
                        <ApiLink href={`${g.href}#${m.anchor}`}>
                          <code>{m.qualified}</code>
                        </ApiLink>
                        {m.summary ? (
                          <span className="api-inherited-sum">
                            <RichText text={m.summary} links={links} />
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          ) : null}

          {page.usedBy.length ? (
            <section id="used-by" className="section" aria-labelledby="used-by-h">
              <div className="section-head">
                <h2 id="used-by-h">Used by</h2>
                <span className="section-blurb">Functions taking or returning {page.name}</span>
              </div>
              <ul className="api-usedby">
                {page.usedBy.map((u) => (
                  <li key={u.href + u.label}>
                    <ApiLink href={u.href}>
                      <code>{u.label}</code>
                    </ApiLink>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
