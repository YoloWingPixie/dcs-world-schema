"use client";

// The entry heads set names in Plex Mono semibold, which only the API pages use.
import "@fontsource/ibm-plex-mono/latin-600.css";
import "./api.css";
import { useEffect, useState } from "react";
import { type LoadedApiPage, loadApiPage, loadApiPages } from "@/lib/api/client";
import { parseApiPath } from "@/lib/api/routes";
import type { PageSummary } from "@/lib/api/types";
import { ApiHome } from "./api-home";
import { ApiLink, scrollToHash } from "./api-link";
import { ApiPageView, SECTION_LABEL } from "./api-page-view";

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

function Missing({ what }: { what: string }) {
  useEffect(() => {
    document.title = "Not found · Lua API · DCS World Reference";
  }, []);
  return (
    <div className="empty-state">
      <h1>No such API page</h1>
      <p>
        <code>{what}</code> not found. <ApiLink href="/api/">Lua API</ApiLink>
      </p>
    </div>
  );
}

function Failed() {
  return (
    <div className="empty-state">
      <h1>Failed to load data</h1>
      <p>Reload the page.</p>
    </div>
  );
}

/**
 * Every `/api/...` page, rendered client side from the reference database (served by the
 * shell in app/not-found.tsx, like the reference pages): the home listing or one page.
 */
export function ApiShell({ path }: { path: string }) {
  const route = parseApiPath(path);
  const [home, setHome] = useState<PageSummary[] | null>(null);
  const [loaded, setLoaded] = useState<{ key: string; data: LoadedApiPage | null } | null>(null);
  const [failed, setFailed] = useState(false);
  const key = route && !route.home ? `${route.section}:${route.name}` : "";

  useEffect(() => {
    setFailed(false);
    const route = parseApiPath(path);
    if (!route) return;
    if (route.home) {
      document.title = "Lua API · DCS World Reference";
      loadApiPages().then(setHome, () => setFailed(true));
      return;
    }
    let live = true;
    loadApiPage(route.section, route.name).then(
      (data) => {
        if (!live) return;
        setLoaded({ key: `${route.section}:${route.name}`, data });
        if (data) {
          const where = route.section === "mission" ? "" : ` (${SECTION_LABEL[route.section]})`;
          document.title = `${route.name}${where} · Lua API · DCS World Reference`;
        }
      },
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [path]);

  // Deep links and links to another page's member: scroll once the page is on screen.
  const isHome = Boolean(route?.home);
  useEffect(() => {
    if (loaded?.key === key || (isHome && home)) requestAnimationFrame(scrollToHash);
  }, [loaded, home, key, isHome]);

  if (!route) return <Missing what={path} />;
  if (failed) return <Failed />;
  if (route.home) {
    return <div className="api-home">{home ? <ApiHome pages={home} /> : <Skeleton />}</div>;
  }
  if (loaded?.key !== key) return <Skeleton />;
  if (!loaded.data) return <Missing what={route.name} />;
  return (
    <ApiPageView
      key={key}
      page={loaded.data.page}
      values={loaded.data.values}
      data={loaded.data.data}
    />
  );
}
