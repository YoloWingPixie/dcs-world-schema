"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { loadModel } from "@/lib/client-data";
import type { Model } from "@/lib/db/reference";
import { parseReferencePath } from "@/lib/series";
import { ApiShell } from "./api/api-shell";
import { BrowseView } from "./browse-view";
import { RecordView } from "./record/record-view";
import { registerShell } from "./ref-link";

function NotFound() {
  useEffect(() => {
    document.title = "Not found · DCS World Reference";
  }, []);
  return (
    <div className="empty-state">
      <h1>Page not found</h1>
      <p>Nothing lives at this address.</p>
      <p>
        <Link href="/">Search the reference</Link> or{" "}
        <Link href="/reference/">browse every series</Link>.
      </p>
    </div>
  );
}

/**
 * Every reference page: `/<series>/` (browse) and `/<series>/<id>/` (a record), rendered
 * client side from the database. The host serves this for any path it has no file for
 * (404.html, with status 200 under each series via _redirects; the not-found route in
 * `next dev`), so new series and records need no build.
 */
export function ReferenceShell() {
  const pathname = usePathname();
  const [model, setModel] = useState<Model | null>(null);
  const [failed, setFailed] = useState(false);
  const [path, setPath] = useState<string | null>(null);

  useEffect(() => registerShell(), []);
  // Read the address after mount: the static HTML is the same for every path.
  useEffect(() => setPath(pathname), [pathname]);
  useEffect(() => {
    loadModel().then(setModel, () => setFailed(true));
  }, []);

  if (path === null) return null;
  if (/^\/api(\/|$)/.test(path)) return <ApiShell path={path} />;
  const route = parseReferencePath(path);
  if (!route) return <NotFound />;
  if (failed) {
    return (
      <div className="empty-state">
        <h1>The reference database did not load</h1>
        <p>Check your connection and reload the page.</p>
      </div>
    );
  }
  if (!model) {
    return (
      <div className="record-skeleton" aria-busy="true">
        <span className="visually-hidden">Loading…</span>
        <div className="sk sk-title" />
        <div className="sk sk-line" />
        <div className="sk sk-row" />
        <div className="sk sk-row" />
      </div>
    );
  }
  const series = model.byId.get(route.series);
  if (!series || series.parent) return <NotFound />;
  if (route.id !== null) {
    return <RecordView key={`${route.series}/${route.id}`} series={route.series} slug={route.id} />;
  }
  return <BrowseView key={route.series} series={route.series} count={series.count} />;
}
