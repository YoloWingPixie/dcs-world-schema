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

/** Every browsable series in the database, grouped, with record counts. */
export function SeriesDirectory() {
  const { model, failed } = useModel();
  if (failed) return <p className="muted">Failed to load data. Reload the page.</p>;
  if (!model) {
    return (
      <div className="home-sections" aria-busy="true">
        <div className="series-grid">
          {Array.from({ length: 8 }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: placeholders
            <div className="series-card sk-card" key={i}>
              <div className="sk sk-line" />
              <div className="sk sk-line" />
            </div>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="home-sections">
      {seriesGroups(model).map((group) => (
        <section key={group.id} aria-labelledby={`group-${group.id}`}>
          <h2 className="series-group-title" id={`group-${group.id}`}>
            {group.label}
          </h2>
          <div className="series-grid">
            {group.series.map((s) => (
              <RefLink key={s.id} href={seriesHref(s.id)} className="series-card">
                <span className="series-card-head">
                  <span className="series-card-name">{s.label}</span>
                  <span className="series-card-count">{s.count.toLocaleString("en-US")}</span>
                </span>
                <span className="series-card-blurb">{s.blurb}</span>
              </RefLink>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** "DCS World 2.9.x · 10,902 records" from the database's meta. */
export function DataVersion({ variant }: { variant: "footer" | "home" }) {
  const { model } = useModel();
  const total = model?.series.filter((s) => !s.parent).reduce((n, s) => n + s.count, 0) ?? 0;
  if (variant === "footer") {
    return (
      <span>
        DCS World <span className="mono">{model?.meta.dcsVersion ?? "…"}</span>
        {model?.meta.extractedAt ? ` · ${model.meta.extractedAt.slice(0, 10)}` : ""} · Not
        affiliated with Eagle Dynamics
      </span>
    );
  }
  return (
    <p className="version-line">
      <span>
        DCS World <strong>{model?.meta.dcsVersion ?? "…"}</strong>
      </span>
      <span>
        <strong>{model ? total.toLocaleString("en-US") : "…"}</strong> records
      </span>
    </p>
  );
}
