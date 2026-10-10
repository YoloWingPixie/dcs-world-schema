"use client";

import { type ApiContentsEntry, apiContents, apiPageCounts } from "@/lib/api/contents";
import { loadMeta, useModel } from "@/lib/client-data";
import { browserQuery, referenceConfig } from "@/lib/db/browser";
import { seriesGroups } from "@/lib/db/reference";
import { seriesHref } from "@/lib/series";
import { useLoaded } from "@/lib/use-loaded";
import { RefLink } from "./ref-link";

/**
 * The API chapter's sections and page counts: from /data/reference.json (already fetched at
 * startup), else, for a config without them, one read of the database's API page index.
 */
const loadApiContents = () =>
  referenceConfig()
    .then((c) => c.apiPages ?? apiPageCounts(browserQuery))
    .then(apiContents, (): ApiContentsEntry[] => []);

function useApiContents(): ApiContentsEntry[] | null {
  return useLoaded(loadApiContents);
}

/** The Lua API as the chapter after the data: the API home's groupings, with page counts. */
function ApiChapter({ number, entries }: { number: number; entries: ApiContentsEntry[] }) {
  if (!entries.length) return null;
  return (
    <li className="contents-chapter">
      <h2 className="contents-chapter-title" id="group-api">
        <span className="contents-num">{number}</span>
        <RefLink href="/api/" className="contents-chapter-link">
          Lua scripting API
        </RefLink>
      </h2>
      <ol className="contents-entries" aria-labelledby="group-api">
        {entries.map((e, i) => (
          <li key={e.id} className="contents-entry">
            <RefLink href={e.href} className="contents-link">
              <span className="contents-num">
                {number}.{i + 1}
              </span>
              <span className="contents-name">{e.label}</span>
              <span className="contents-leader" aria-hidden="true" />
              <span className="contents-count series-card-count">
                {e.count.toLocaleString("en-US")}
                <span className="visually-hidden"> {e.count === 1 ? "page" : "pages"}</span>
              </span>
            </RefLink>
            <p className="contents-blurb">{e.blurb}</p>
          </li>
        ))}
      </ol>
    </li>
  );
}

/**
 * Every browsable series in the database as a numbered contents list, with record counts,
 * then the Lua API chapter.
 */
export function SeriesDirectory() {
  const { model, failed } = useModel();
  const api = useApiContents();
  if (failed) return <p className="muted">Failed to load data. Reload the page.</p>;
  if (!model) {
    return (
      <div className="contents" aria-busy="true">
        {Array.from({ length: 3 }, (_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: placeholders
          <div className="contents-chapter" key={i}>
            <div className="sk sk-heading" />
            <div className="sk sk-line" />
            <div className="sk sk-line" />
            <div className="sk sk-line" />
          </div>
        ))}
      </div>
    );
  }
  const groups = seriesGroups(model);
  return (
    <ol className="contents">
      {groups.map((group, g) => (
        <li key={group.id} className="contents-chapter">
          <h2 className="contents-chapter-title" id={`group-${group.id}`}>
            <span className="contents-num">{g + 1}</span>
            {group.label}
          </h2>
          <ol className="contents-entries" aria-labelledby={`group-${group.id}`}>
            {group.series.map((s, i) => (
              <li key={s.id} className="contents-entry">
                <RefLink href={seriesHref(s.id)} className="contents-link">
                  <span className="contents-num">
                    {g + 1}.{i + 1}
                  </span>
                  <span className="contents-name">{s.label}</span>
                  <span className="contents-leader" aria-hidden="true" />
                  <span className="contents-count series-card-count">
                    {s.count.toLocaleString("en-US")}
                    <span className="visually-hidden"> records</span>
                  </span>
                </RefLink>
                {s.blurb ? <p className="contents-blurb">{s.blurb}</p> : null}
              </li>
            ))}
          </ol>
        </li>
      ))}
      {api ? <ApiChapter number={groups.length + 1} entries={api} /> : null}
    </ol>
  );
}

/** The data revision, from the database's meta: the home title block or the running footer. */
export function DataVersion({ variant }: { variant: "footer" | "home" }) {
  // The footer, on every page, reads the revision alone; the home page counts the records.
  const meta = useLoaded(loadMeta);
  const { model } = useModel(variant === "home");
  const total = model?.series.filter((s) => !s.parent).reduce((n, s) => n + s.count, 0) ?? 0;
  const version = meta?.dcsVersion ?? "…";
  if (variant === "footer") {
    return (
      <>
        <span>DCS World Reference, revision {version}</span>
        <span>Not affiliated with Eagle Dynamics</span>
      </>
    );
  }
  return (
    <dl className="title-meta">
      <div>
        <dt>Revision</dt>
        <dd>{version}</dd>
      </div>
      {meta?.extractedAt ? (
        <div>
          <dt>Extracted</dt>
          <dd>{meta.extractedAt.slice(0, 10)}</dd>
        </div>
      ) : null}
      <div>
        <dt>Records</dt>
        <dd>{model ? total.toLocaleString("en-US") : "…"}</dd>
      </div>
    </dl>
  );
}
