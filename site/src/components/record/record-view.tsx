"use client";

import { memo, type ReactNode, useEffect, useMemo, useState } from "react";
import { companionLabel } from "@/lib/catalog";
import { loadReferencedByGroup, useRecord } from "@/lib/client-data";
import { storedValue, type ValueContext } from "@/lib/format-field";
import { LOCATION_ID, locationOf } from "@/lib/geo";
import type { NavHint } from "@/lib/nav-hints";
import { headerChips, type PlacedSection, placeRecord, type StripItem } from "@/lib/placement";
import { recordHref, SERIES_BY_ID, seriesHref } from "@/lib/series";
import type {
  CatalogEntry,
  LinkTarget,
  RecordDoc,
  ReferencedBy as RefGroup,
  SeriesCatalog,
} from "@/lib/types";
import { useUnitSystem } from "@/lib/unit-system";
import {
  Description,
  type FieldContext,
  FieldRow,
  fieldDataAttrs,
  ScalarValue,
  tipIdFor,
} from "../field-view";
import { LocationFigure } from "../location-map";
import { Markdown } from "../Markdown";
import { RefLink } from "../ref-link";
import { SeeAlso } from "../see-also";
import { ProvenanceValue, type RenderCtx } from "./blocks";
import { RecordGroup, RecordsBlock } from "./record-group";
import { RecordHeader, RecordSkeleton } from "./record-header";
import { SCRIPTING_ID, ScriptingBlock, useScripting } from "./scripting";

/** The tag beside a section's title: "flight model" on the companion's own sections, a table's row count. */
function sectionTag(section: PlacedSection, catalog: SeriesCatalog): string | null {
  if (section.companion) {
    return section.kind === "overview" ? null : companionLabel(catalog).toLowerCase();
  }
  return section.kind === "records" ? String(section.rows.length) : null;
}

const SectionBody = memo(function SectionBody({
  section,
  ctx,
}: {
  section: PlacedSection;
  ctx: RenderCtx;
}) {
  switch (section.kind) {
    case "overview":
      return (
        <RecordGroup
          typeName={section.typeName}
          prefix={section.prefix}
          value={section.value}
          ctx={ctx}
          depth={0}
          only={section.fields}
        />
      );
    case "record":
      return (
        <RecordGroup
          typeName={section.typeName}
          prefix={section.path}
          value={section.value}
          ctx={ctx}
          depth={0}
        />
      );
    case "records":
      return (
        <RecordsBlock
          entry={section.entry}
          rows={section.rows}
          ctx={ctx}
          prefix={section.path}
          place="group"
        />
      );
    case "source":
      return (
        <div className="fields">
          {section.fields.map(({ entry, path, value, companion }) => (
            <FieldRow
              key={path}
              entry={entry}
              path={path}
              value={value}
              ctx={ctx.fctx}
              vctx={ctx.vctx}
              label={
                companion
                  ? `${companionLabel(ctx.catalog)} ${entry.label.toLowerCase()}`
                  : entry.label
              }
              body={<ProvenanceValue value={value} />}
            />
          ))}
        </div>
      );
  }
});

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
    loadReferencedByGroup(doc.series, doc.id, g.series, g.path, g.via).then(
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
          {g.via ? (
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

type Readout = {
  path: string;
  label: string;
  /** A field's own value (field menu, tooltip), else a figure derived from one. */
  entry: CatalogEntry | null;
  value: unknown;
  text: ReactNode;
  stored?: string | null;
};

/** The strip's figures as display text. */
function readoutOf(item: StripItem, vctx: ValueContext): Readout {
  const { path, entry, value } = item;
  if (item.show === "count") {
    return { path, label: entry.label, entry: null, value, text: item.value.length };
  }
  if (item.show === "coverage") {
    return { path, label: "Coverage", entry: null, value, text: item.text };
  }
  const text = <ScalarValue entry={entry} value={value} vctx={vctx} />;
  const stored = storedValue(entry, value, vctx.system, vctx.enums);
  return { path, label: entry.label, entry, value, text, stored };
}

const Readouts = memo(function Readouts({ items, ctx }: { items: Readout[]; ctx: RenderCtx }) {
  if (!items.length) return null;
  return (
    <div className="readouts">
      {items.map(({ path, label, entry, value, text, stored }) => {
        // Apart from the same field's row further down the page.
        const tipId = tipIdFor(ctx.fctx, `readout.${path}`);
        return entry ? (
          <div
            key={path}
            className="readout"
            tabIndex={0}
            aria-describedby={tipId}
            {...fieldDataAttrs(entry, path, value, ctx.fctx, ctx.vctx)}
          >
            <span className="readout-label">{label}</span>
            <span className="readout-value">{text}</span>
            <Description entry={entry} id={tipId} stored={stored ?? null} />
          </div>
        ) : (
          <div key={path} className="readout">
            <span className="readout-label">{label}</span>
            <span className="readout-value">{text}</span>
          </div>
        );
      })}
    </div>
  );
});

/**
 * A record page of any series, rendered from its catalog (client side, from per-record JSON).
 * Memoised: its props name the record, so a query-string change elsewhere (the Lua drawer's
 * `?lua=`) does not re-render it.
 */
export const RecordView = memo(function RecordView({
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

  const location = useMemo(
    () => (doc ? locationOf(series, doc.data, doc.name) : null),
    [doc, series],
  );

  const ctx = useMemo<RenderCtx | null>(() => {
    if (!catalog || !doc) return null;
    const vctx: ValueContext = { enums: catalog.enums, system, links: doc.links };
    const fctx: FieldContext = {
      series,
      slug: doc.slug,
      recordName: doc.name,
      hasLocation: location !== null,
    };
    return { catalog, vctx, fctx };
  }, [catalog, doc, system, series, location]);

  const placement = useMemo(
    () => (catalog && doc && ctx ? placeRecord(catalog, doc, ctx.vctx) : null),
    [catalog, doc, ctx],
  );
  const readouts = useMemo(
    () => (placement && ctx ? placement.strip.map((item) => readoutOf(item, ctx.vctx)) : []),
    [placement, ctx],
  );
  const scripting = useScripting(doc);

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
  if (!catalog || !doc || !ctx || !placement) {
    return <RecordSkeleton series={series} slug={slug} hint={hint} />;
  }

  const placed = placement.sections.map((section) => ({
    id: section.id,
    title: section.title,
    tag: sectionTag(section, catalog),
    sub: section.companion && section.kind !== "overview",
    body: <SectionBody section={section} ctx={ctx} />,
  }));
  // Where the data meets the Lua API: right after the Overview, so it is seen.
  const sections =
    scripting && placed.length
      ? [
          ...placed.slice(0, placement.scriptingAt),
          {
            id: SCRIPTING_ID,
            title: "Scripting",
            tag: null,
            sub: false,
            body: <ScriptingBlock rows={scripting} />,
          },
          ...placed.slice(placement.scriptingAt),
        ]
      : placed;

  const chips = headerChips(catalog, doc);
  const refCount = doc.referencedBy.reduce((n, g) => n + groupSize(g), 0);
  // The Location figure leads the body (a numbered section): first here too.
  const toc = [
    ...(location ? [{ id: LOCATION_ID, title: "Location", sub: false }] : []),
    ...sections.map((s) => ({ id: s.id, title: s.title, sub: s.sub })),
    ...(refCount ? [{ id: "referenced-by", title: "Referenced by", sub: false }] : []),
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
        readouts={<Readouts items={readouts} ctx={ctx} />}
      />

      {doc.overlay?.html || doc.overlay?.seeAlso?.length ? (
        <section className="overlay-note" aria-label="Note">
          {doc.overlay.html ? <Markdown html={doc.overlay.html} handWritten /> : null}
          <SeeAlso links={doc.overlay.seeAlso} />
        </section>
      ) : null}

      <div className="record-layout">
        <nav className="toc" aria-label="On this page">
          <span className="toc-title">On this page</span>
          {toc.map((s) => (
            <a key={s.id} href={`#${s.id}`} className={s.sub ? "toc-sub" : undefined}>
              {s.title}
            </a>
          ))}
        </nav>
        <div className="record-body">
          {location ? <LocationFigure key={`${series}/${doc.id}`} location={location} /> : null}
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
});
