"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { lazy, Suspense, useEffect, useState } from "react";
import { loadModel, loadRecord, loadSeriesIndex } from "@/lib/client-data";
import type { Model } from "@/lib/db/reference";
import { getNavHint } from "@/lib/nav-hints";
import { parseReferencePath } from "@/lib/series";
import { RecordSkeleton } from "./record/record-header";
import { registerShell } from "./ref-link";

// Each view loads with the first page that needs it; this shell is in every page's bundle
// (it is the root not-found page).
const loadRecordView = () => import("./record/record-view");
const loadBrowseView = () => import("./browse-view");
const RecordView = lazy(() => loadRecordView().then((m) => ({ default: m.RecordView })));
const BrowseView = lazy(() => loadBrowseView().then((m) => ({ default: m.BrowseView })));
const ApiShell = lazy(() => import("./api/api-shell").then((m) => ({ default: m.ApiShell })));

function Skeleton() {
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

function NotFound() {
  useEffect(() => {
    document.title = "Not found · DCS World Reference";
  }, []);
  return (
    <div className="empty-state">
      <h1>Page not found</h1>
      <p>
        <Link href="/reference/">Reference</Link>
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
  useEffect(() => {
    setPath(pathname);
    // Fetch the view's code alongside the model rather than after it.
    const route = /^\/api(\/|$)/.test(pathname) ? null : parseReferencePath(pathname);
    if (route) (route.id === null ? loadBrowseView : loadRecordView)().catch(() => {});
    // And its data: the view picks up the same (memoized) promise.
    if (route?.id != null) loadRecord(route.series, route.id).catch(() => {});
    else if (route) loadSeriesIndex(route.series).catch(() => {});
  }, [pathname]);
  useEffect(() => {
    loadModel().then(setModel, () => setFailed(true));
  }, []);

  if (path === null) return null;
  if (/^\/api(\/|$)/.test(path)) {
    return (
      <Suspense fallback={<Skeleton />}>
        <ApiShell path={path} />
      </Suspense>
    );
  }
  const route = parseReferencePath(path);
  if (!route) return <NotFound />;
  if (failed) {
    return (
      <div className="empty-state">
        <h1>Failed to load data</h1>
        <p>Reload the page.</p>
      </div>
    );
  }
  if (route.id !== null) {
    const hint = getNavHint(path);
    const view = (
      <Suspense fallback={<RecordSkeleton series={route.series} slug={route.id} hint={hint} />}>
        <RecordView
          key={`${route.series}/${route.id}`}
          series={route.series}
          slug={route.id}
          hint={hint}
        />
      </Suspense>
    );
    // With a hint the record header shows while the model is still loading.
    if (!model) return hint ? view : <RecordSkeleton series={route.series} slug={route.id} />;
    const series = model.byId.get(route.series);
    if (!series || series.parent) return <NotFound />;
    return view;
  }
  if (!model) return <Skeleton />;
  const series = model.byId.get(route.series);
  if (!series || series.parent) return <NotFound />;
  return (
    <Suspense fallback={<Skeleton />}>
      <BrowseView key={route.series} series={route.series} count={series.count} />
    </Suspense>
  );
}
