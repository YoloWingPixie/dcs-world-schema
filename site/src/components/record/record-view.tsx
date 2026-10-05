"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { COMPANION_PREFIX, getPath, isRecord } from "@/lib/catalog";
import { loadCatalog, loadRecord, loadReferencedByGroup } from "@/lib/client-data";
import type { ValueContext } from "@/lib/format-field";
import { constantLabel } from "@/lib/names";
import type { NavHint } from "@/lib/nav-hints";
import { recordHref, SERIES_BY_ID, seriesHref } from "@/lib/series";
import { displayFor } from "@/lib/series-display";
import type {
  CatalogEntry,
  LinkTarget,
  RecordDoc,
  ReferencedBy as RefGroup,
  SeriesCatalog,
} from "@/lib/types";
import { useUnitSystem } from "@/lib/unit-system";
import { formatWithUnit } from "@/lib/units";
import { Description, type FieldContext, fieldDataAttrs, tipIdFor } from "../field-view";
import { Markdown } from "../Markdown";
import { RefLink } from "../ref-link";
import type { RenderCtx } from "./blocks";
import { RecordGroup, RecordsBlock } from "./record-group";
import { metaChips, RecordHeader, RecordSkeleton } from "./record-header";

type Json = Record<string, unknown>;
type Section = {
  id: string;
  title: string;
  tag?: string | undefined;
  body: ReactNode;
};

const PROVENANCE = new Set(["sourcePaths", "sourcePath", "_source"]);
const HEADER_FIELDS = new Set(["id"]);

function useRecord(series: string, slug: string) {
  const [state, setState] = useState<{
    catalog: SeriesCatalog | null;
    doc: RecordDoc | null;
    error: string | null;
  }>({ catalog: null, doc: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ catalog: null, doc: null, error: null });
    Promise.all([loadCatalog(series), loadRecord(series, slug)]).then(
      ([catalog, doc]) => live && setState({ catalog, doc, error: null }),
      (error: unknown) => live && setState({ catalog: null, doc: null, error: String(error) }),
    );
    return () => {
      live = false;
    };
  }, [series, slug]);
  return state;
}

function sectionsFor(catalog: SeriesCatalog, doc: RecordDoc, ctx: RenderCtx): Section[] {
  const out: Section[] = [];
  const build = (root: Json, typeName: string, prefix: string, tag?: string) => {
    const fields = catalog.types[typeName]?.fields ?? [];
    const key = (name: string) => (prefix ? `${prefix}.${name}` : name);
    const complex = new Set(
      fields.filter((f) => {
        const k = catalog.entries[key(f)]?.kind;
        return k === "record" || k === "records";
      }),
    );
    // A companion's back-reference to its parent (weapon_flight.weapon) says nothing here.
    const backRefs = prefix
      ? fields.filter((f) => catalog.entries[key(f)]?.ref?.includes(doc.series))
      : [];
    const skip = new Set([
      ...complex,
      ...PROVENANCE,
      ...backRefs,
      ...(prefix ? [] : HEADER_FIELDS),
    ]);
    const hasScalars = fields.some(
      (f) => !skip.has(f) && root[f] !== undefined && catalog.entries[key(f)],
    );
    if (hasScalars) {
      out.push({
        id: prefix ? `${prefix}-overview` : "overview",
        title: prefix ? "Flight model" : "Overview",
        tag,
        body: (
          <RecordGroup
            typeName={typeName}
            prefix={prefix}
            concretePrefix={prefix}
            value={root}
            ctx={ctx}
            depth={0}
            skip={skip}
          />
        ),
      });
    }
    for (const name of fields) {
      if (!complex.has(name)) continue;
      const v = root[name];
      const entry = catalog.entries[key(name)];
      if (!entry || v === undefined || v === null) continue;
      if (Array.isArray(v) && v.length === 0) continue;
      const id = key(name).replace(/\./g, "-");
      if (entry.kind === "record" && isRecord(v) && entry.recordType) {
        out.push({
          id,
          title: entry.label,
          tag,
          body: (
            <RecordGroup
              typeName={entry.recordType}
              prefix={key(name)}
              concretePrefix={key(name)}
              value={v}
              ctx={ctx}
              depth={0}
            />
          ),
        });
      } else if (entry.kind === "records" && Array.isArray(v)) {
        out.push({
          id,
          title: `${entry.label}`,
          tag: tag ?? `${v.length}`,
          body: (
            <RecordsBlock
              entry={entry}
              rows={v}
              ctx={ctx}
              prefix={key(name)}
              concretePrefix={key(name)}
            />
          ),
        });
      }
    }
  };

  build(doc.data, catalog.rootType, "");
  const companionEntry = catalog.entries[COMPANION_PREFIX];
  if (doc.companion && companionEntry?.recordType) {
    build(doc.companion, companionEntry.recordType, COMPANION_PREFIX, "flight model");
  }

  // Source paths.
  const prov: Array<{ entry: CatalogEntry; path: string; value: unknown }> = [];
  for (const [root, prefix] of [
    [doc.data, ""],
    [doc.companion, COMPANION_PREFIX],
  ] as const) {
    if (!root) continue;
    for (const name of ["sourcePaths", "sourcePath"]) {
      const path = prefix ? `${prefix}.${name}` : name;
      const entry = catalog.entries[path];
      if (entry && root[name] !== undefined) prov.push({ entry, path, value: root[name] });
    }
  }
  if (prov.length) {
    out.push({
      id: "provenance",
      title: "Source",
      body: (
        <div className="fields">
          {prov.map((p) => (
            <ProvenanceRow key={p.path} {...p} ctx={ctx} />
          ))}
        </div>
      ),
    });
  }
  return out;
}

function ProvenanceRow({
  entry,
  path,
  value,
  ctx,
}: {
  entry: CatalogEntry;
  path: string;
  value: unknown;
  ctx: RenderCtx;
}) {
  const list = Array.isArray(value) ? value.map(String) : [String(value)];
  return (
    <div className="field field-wide" tabIndex={0} aria-describedby={tipIdFor(ctx.fctx, path)}>
      <span className="field-label">
        {path.startsWith(COMPANION_PREFIX)
          ? `Flight model ${entry.label.toLowerCase()}`
          : entry.label}
      </span>
      <div className="field-body">
        <ul className="path-list">
          {list.map((v) => (
            <li key={v}>{v}</li>
          ))}
        </ul>
      </div>
      <Description entry={entry} id={tipIdFor(ctx.fctx, path)} />
    </div>
  );
}

const groupSize = (g: RefGroup) => Math.max(g.total ?? 0, g.records.length);

/** One referring series and path; long groups arrive capped and load in full on request. */
function RefByGroup({ doc, group: g }: { doc: RecordDoc; group: RefGroup }) {
  const [all, setAll] = useState<LinkTarget[] | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "failed">("idle");
  const info = SERIES_BY_ID.get(g.series);
  const records = all ?? g.records;
  const total = all ? all.length : groupSize(g);
  const capped = !all && total > g.records.length;
  const listId = `refby-${g.series}-${g.path}`.replace(/[^\w-]/g, "_");

  const showAll = () => {
    setStatus("loading");
    loadReferencedByGroup(doc.series, doc.id, g.series, g.path).then(
      (list) => {
        setAll(list);
        setStatus("idle");
      },
      () => setStatus("failed"),
    );
  };

  return (
    <div className="refby-group">
      <h3 className="subgroup-title">
        {info?.label ?? g.series}
        <span className="refby-path">
          {g.path === "carriers" ? (
            g.label
          ) : (
            <>
              via <code>{g.path}</code>
            </>
          )}
        </span>
        <span className="muted"> ({total})</span>
      </h3>
      <ul className="link-list" id={listId} aria-busy={status === "loading"}>
        {records.map(([slug, name]) => (
          <li key={slug}>
            <RefLink className="ref-link" href={recordHref(g.series, slug)}>
              {name}
            </RefLink>
          </li>
        ))}
      </ul>
      {capped ? (
        <p className="refby-more">
          <button
            type="button"
            className="btn"
            aria-controls={listId}
            disabled={status === "loading"}
            onClick={showAll}
          >
            {status === "loading" ? "Loading…" : `Show all ${total.toLocaleString("en-US")}`}
          </button>
          {status === "failed" ? (
            <span className="muted" role="alert">
              {" "}
              Failed to load data.
            </span>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

function ReferencedBy({ doc }: { doc: RecordDoc }) {
  if (!doc.referencedBy.length) return null;
  return (
    <div className="refby">
      {doc.referencedBy.map((g) => (
        <RefByGroup key={`${g.series}|${g.path}`} doc={doc} group={g} />
      ))}
    </div>
  );
}

function Readouts({ doc, ctx }: { doc: RecordDoc; ctx: RenderCtx }) {
  // Hinted headline values, else the first top-level numbers that carry a unit.
  const paths =
    displayFor(doc.series).readouts ??
    Object.values(ctx.catalog.entries)
      .filter(
        (e) =>
          e.kind === "number" &&
          e.unit &&
          !e.path.includes(".") &&
          typeof doc.data[e.name] === "number",
      )
      .slice(0, 4)
      .map((e) => e.path);
  const items = paths
    .map((path) => {
      const entry = ctx.catalog.entries[path];
      const value = path.startsWith(`${COMPANION_PREFIX}.`)
        ? getPath(doc.companion, path.slice(COMPANION_PREFIX.length + 1))
        : getPath(doc.data, path);
      return entry ? { path, entry, value } : null;
    })
    .filter((x): x is NonNullable<typeof x> => Boolean(x));
  if (!items.length) return null;
  return (
    <div className="readouts">
      {items.map(({ path, entry, value }) => {
        const f =
          typeof value === "number"
            ? formatWithUnit(value, entry.unit, ctx.vctx.system, entry.name)
            : null;
        const tipId = `tip-readout-${path.replace(/\W/g, "_")}`;
        return f ? (
          <div
            key={path}
            className="readout"
            tabIndex={0}
            aria-describedby={tipId}
            {...fieldDataAttrs(entry, path, value, ctx.fctx, ctx.vctx)}
          >
            <span className="readout-label">{entry.label}</span>
            <span className="readout-value">
              {f.text}
              {f.unit ? <span className="unit"> {f.unit}</span> : null}
            </span>
            <Description entry={entry} id={tipId} stored={f.stored} />
          </div>
        ) : (
          <div key={path} className="readout">
            <span className="readout-label">{entry.label}</span>
            <span className="readout-value readout-empty">—</span>
          </div>
        );
      })}
    </div>
  );
}

/** A record page of any series, rendered from its catalog (client side, from per-record JSON). */
export function RecordView({
  series,
  slug,
  hint,
}: {
  series: string;
  slug: string;
  /** Name (and meta) from the link that led here, shown until the record loads. */
  hint?: NavHint | null;
}) {
  const info = SERIES_BY_ID.get(series);
  const { catalog, doc, error } = useRecord(series, slug);
  const system = useUnitSystem();

  const title = doc?.name ?? hint?.name;
  useEffect(() => {
    if (title) document.title = `${title} · DCS World Reference`;
  }, [title]);

  const ctx = useMemo<RenderCtx | null>(() => {
    if (!catalog || !doc) return null;
    const vctx: ValueContext = { enums: catalog.enums, system, links: doc.links };
    const fctx: FieldContext = { series, slug: doc.slug, recordName: doc.name };
    return { catalog, vctx, fctx };
  }, [catalog, doc, system, series]);

  const sections = useMemo(
    () => (catalog && doc && ctx ? sectionsFor(catalog, doc, ctx) : []),
    [catalog, doc, ctx],
  );

  if (error) {
    return (
      <div className="empty-state">
        <h1>No such {info?.singular ?? "record"}</h1>
        <p>
          <RefLink href={seriesHref(series)}>{info?.label ?? series}</RefLink>
        </p>
      </div>
    );
  }
  if (!catalog || !doc || !ctx) return <RecordSkeleton series={series} slug={slug} hint={hint} />;

  const chips = metaChips(doc.meta, constantLabel);
  const refCount = doc.referencedBy.reduce((n, g) => n + groupSize(g), 0);
  const toc = [
    ...sections.map((s) => ({
      id: s.id,
      title: s.title,
      flight: s.tag === "flight model" && s.title !== "Flight model",
    })),
    ...(refCount ? [{ id: "referenced-by", title: "Referenced by", flight: false }] : []),
  ];

  return (
    <div className="record">
      <RecordHeader
        series={series}
        slug={doc.slug}
        name={doc.name}
        id={doc.id}
        chips={chips}
        aliases={doc.overlay?.aliases}
        readouts={<Readouts doc={doc} ctx={ctx} />}
      />

      {doc.overlay?.html || doc.overlay?.seeAlso?.length ? (
        <section className="overlay-note" aria-label="Note">
          {doc.overlay.html ? <Markdown html={doc.overlay.html} handWritten /> : null}
          {doc.overlay.seeAlso?.length ? (
            <p className="see-also">
              See also{" "}
              {doc.overlay.seeAlso.map((s, i) => (
                <span key={s.href}>
                  {i ? ", " : ""}
                  {/^[a-z]+:/i.test(s.href) ? (
                    <a href={s.href} rel="noopener noreferrer">
                      {s.label}
                    </a>
                  ) : (
                    <Link href={s.href}>{s.label}</Link>
                  )}
                </span>
              ))}
            </p>
          ) : null}
        </section>
      ) : null}

      <div className="record-layout">
        <nav className="toc" aria-label="On this page">
          <span className="toc-title">On this page</span>
          {toc.map((s) => (
            <a key={s.id} href={`#${s.id}`} className={s.flight ? "toc-sub" : undefined}>
              {s.title}
            </a>
          ))}
        </nav>
        <div className="record-body">
          {sections.map((section) => (
            <section
              key={section.id}
              id={section.id}
              className="section"
              aria-labelledby={`${section.id}-h`}
            >
              <div className="section-head">
                <h2 id={`${section.id}-h`}>
                  {section.title}
                  {section.tag ? <span className="section-tag">{section.tag}</span> : null}
                </h2>
              </div>
              {section.body}
            </section>
          ))}
          {refCount ? (
            <section id="referenced-by" className="section" aria-labelledby="referenced-by-h">
              <div className="section-head">
                <h2 id="referenced-by-h">
                  Referenced by <span className="section-tag">{refCount}</span>
                </h2>
              </div>
              <ReferencedBy doc={doc} />
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
