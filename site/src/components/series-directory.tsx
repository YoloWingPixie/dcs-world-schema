"use client";

import { useEffect, useState } from "react";
import { loadModel } from "@/lib/client-data";
import { type Model, seriesGroups } from "@/lib/db/reference";
import { seriesHref } from "@/lib/series";
import { RefLink } from "./ref-link";

export function useModel() {
  const [model, setModel] = useState<Model | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    loadModel().then(setModel, () => setFailed(true));
  }, []);
  return { model, failed };
}

/** Every browsable series in the database as a numbered contents list, with record counts. */
export function SeriesDirectory() {
  const { model, failed } = useModel();
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
  return (
    <ol className="contents">
      {seriesGroups(model).map((group, g) => (
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
    </ol>
  );
}

/** The data revision, from the database's meta: the home title block or the running footer. */
export function DataVersion({ variant }: { variant: "footer" | "home" }) {
  const { model } = useModel();
  const total = model?.series.filter((s) => !s.parent).reduce((n, s) => n + s.count, 0) ?? 0;
  const version = model?.meta.dcsVersion ?? "…";
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
      {model?.meta.extractedAt ? (
        <div>
          <dt>Extracted</dt>
          <dd>{model.meta.extractedAt.slice(0, 10)}</dd>
        </div>
      ) : null}
      <div>
        <dt>Records</dt>
        <dd>{model ? total.toLocaleString("en-US") : "…"}</dd>
      </div>
    </dl>
  );
}
