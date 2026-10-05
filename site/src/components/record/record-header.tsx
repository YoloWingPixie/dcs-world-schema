"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { NavHint } from "@/lib/nav-hints";
import { SERIES_BY_ID, seriesHref } from "@/lib/series";
import { displayFor } from "@/lib/series-display";
import { RecordCompareActions } from "../compare-buttons";
import { RefLink } from "../ref-link";

type HeaderProps = {
  series: string;
  slug: string;
  name: string;
  id: string;
  /** Meta chips after the series chip, as display labels. */
  chips: string[];
  aliases?: string[] | undefined;
  readouts: ReactNode;
};

/** Breadcrumb and data plate; the same markup loading (from a hint) and loaded. */
export function RecordHeader({ series, slug, name, id, chips, aliases, readouts }: HeaderProps) {
  const info = SERIES_BY_ID.get(series);
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link href="/reference/">Reference</Link>
        <span aria-hidden="true">/</span>
        <RefLink href={seriesHref(series)}>{info?.label ?? series}</RefLink>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{name}</span>
      </nav>

      <header className="plate">
        <div className="plate-head">
          <div>
            <h1>{name}</h1>
            {aliases?.length ? <p className="plate-nick">{aliases.join(" · ")}</p> : null}
            <p className="plate-id">
              <span className="muted">ID</span> {id}
            </p>
            <div className="plate-chips">
              <span className="chip chip-accent">{info?.singular ?? series}</span>
              {chips.map((m) => (
                <span className="chip" key={m}>
                  {m}
                </span>
              ))}
            </div>
          </div>
          <RecordCompareActions series={series} slug={slug} name={name} />
        </div>
        {readouts}
      </header>
    </>
  );
}

/** Distinct chips of a " · " joined meta line. */
export function metaChips(meta: string | undefined, label: (m: string) => string = (m) => m) {
  return meta ? [...new Set(meta.split(" · ").filter(Boolean).map(label))] : [];
}

function BodySkeleton() {
  return (
    <div className="record-layout">
      <div className="toc">
        <div className="sk sk-line" />
        <div className="sk sk-line" />
      </div>
      <div>
        {[0, 1].map((i) => (
          <div className="section" key={i}>
            <div className="sk sk-heading" />
            {[0, 1, 2, 3, 4].map((j) => (
              <div className="sk sk-row" key={j} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * A record page while its data loads. With a hint (the link or search result the user
 * picked) the real header shows at once; without one, a placeholder of the same shape.
 */
export function RecordSkeleton({
  series,
  slug,
  hint,
}: {
  series: string;
  slug: string;
  hint?: NavHint | null | undefined;
}) {
  const readoutCount = Math.min(displayFor(series).readouts?.length ?? 4, 6);
  const readouts = (
    <div className="readouts">
      {Array.from({ length: readoutCount }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed placeholders
        <div className="readout" key={i}>
          <span className="readout-label">
            <span className="sk sk-text">Label</span>
          </span>
          <span className="readout-value">
            <span className="sk sk-text">000.0</span>
          </span>
        </div>
      ))}
    </div>
  );
  return (
    <div className="record" aria-busy="true">
      <span className="visually-hidden" role="status">
        Loading…
      </span>
      {hint ? (
        <RecordHeader
          series={series}
          slug={slug}
          name={hint.name}
          id={slug}
          chips={metaChips(hint.meta)}
          readouts={readouts}
        />
      ) : (
        <div className="record-skeleton">
          <div className="plate">
            <div className="sk sk-title" />
            <div className="sk sk-line" />
            <div className="sk sk-chips" />
            {readouts}
          </div>
        </div>
      )}
      <BodySkeleton />
    </div>
  );
}
