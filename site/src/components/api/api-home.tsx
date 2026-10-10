"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { ENV_LABEL, SECTION_LABEL } from "@/lib/api/routes";
import type { ApiSection, PageSummary } from "@/lib/api/types";
import { replaceUrl } from "@/lib/history";
import { naturalCompare, naturalCompareBase } from "@/lib/text";
import { RefLink } from "../ref-link";

type Filter = "all" | "mission" | "hooks" | "export" | "server";

const ENVS: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "All" },
  ...(["mission", "hooks", "export", "server"] as const).map((id) => ({
    id,
    label: ENV_LABEL[id],
  })),
];

const KIND_ORDER: Record<string, number> = { class: 0, singleton: 1, namespace: 2 };

function PageCard({ p }: { p: PageSummary }) {
  return (
    <RefLink href={p.href} className="api-card">
      <span className="api-card-name">{p.name}</span>
      <span className="api-card-meta">
        {p.kind === "singleton" ? "global" : p.kind}, {p.count}{" "}
        {p.count === 1 ? "member" : "members"}
      </span>
      {p.summary ? <span className="api-card-sum">{p.summary}</span> : null}
    </RefLink>
  );
}

/** A group of the type list: its namespace, or the shared first group. */
type TypeGroup = { id: string; label: string };

/** The types listed first, open: records, enums and unions outside the namespaces below. */
const MAIN_TYPES: TypeGroup = { id: "", label: "Records, enums and unions" };

/** Namespaces whose types (`DcsTask.Orbit`) list in a group of their own, after the main one. */
const TYPE_NAMESPACES = new Set(["AI", "DcsId", "DcsTask"]);

function typeGroup(name: string): TypeGroup {
  const dot = name.indexOf(".");
  const namespace = dot < 0 ? "" : name.slice(0, dot);
  return TYPE_NAMESPACES.has(namespace) ? { id: namespace, label: namespace } : MAIN_TYPES;
}

/** API home lists: environment filter, globals per environment, then types. */
export function ApiHome({ pages }: { pages: PageSummary[] }) {
  const [env, setEnv] = useState<Filter>("all");
  const [typeQuery, setTypeQuery] = useState("");
  const typeInput = useId();

  useEffect(() => {
    const h = window.location.hash.slice(1);
    if (h === "mission" || h === "hooks" || h === "export" || h === "server") setEnv(h);
  }, []);

  const bySection = useMemo(() => {
    const m = new Map<ApiSection, PageSummary[]>();
    for (const p of pages) m.set(p.section, [...(m.get(p.section) ?? []), p]);
    for (const list of m.values()) {
      list.sort(
        (a, b) =>
          (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) ||
          naturalCompareBase(a.name, b.name),
      );
    }
    return m;
  }, [pages]);

  const types = useMemo(() => {
    const q = typeQuery.trim().toLowerCase();
    const list = (bySection.get("types") ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q),
    );
    const groups = new Map<string, { group: TypeGroup; list: PageSummary[] }>();
    for (const p of list) {
      const group = typeGroup(p.name);
      const entry = groups.get(group.id) ?? { group, list: [] };
      entry.list.push(p);
      groups.set(group.id, entry);
    }
    // The main group first ("" sorts first), then the namespaces by name.
    return [...groups.values()].sort((a, b) => naturalCompare(a.group.id, b.group.id));
  }, [bySection, typeQuery]);

  const show = (s: Filter) => env === "all" || env === s;
  const mission = bySection.get("mission") ?? [];

  const count = (pred: (p: PageSummary) => boolean) => pages.filter(pred).length;
  return (
    <>
      <section className="api-hero" aria-labelledby="api-title">
        <h1 id="api-title" className="page-title">
          DCS World Lua API
        </h1>
        <p className="version-line">
          <span>
            <strong>{count((p) => p.kind === "class")}</strong> classes
          </span>
          <span>
            <strong>{count((p) => p.section !== "types" && p.kind !== "class")}</strong> global
            tables
          </span>
          <span>
            <strong>{count((p) => p.section === "types")}</strong> types
          </span>
        </p>
      </section>
      <fieldset className="api-envbar">
        <legend className="visually-hidden">Environment</legend>
        {ENVS.map((e) => (
          <button
            key={e.id}
            type="button"
            className="seg-btn api-env-btn"
            aria-pressed={env === e.id}
            onClick={() => {
              setEnv(e.id);
              try {
                replaceUrl(e.id === "all" ? "#" : `#${e.id}`);
              } catch {
                // History blocked: the filter still applies.
              }
            }}
          >
            {e.label}
          </button>
        ))}
      </fieldset>

      {show("mission") ? (
        <section id="mission" className="section" aria-labelledby="mission-h">
          <div className="section-head">
            <h2 id="mission-h">
              Mission scripting <span className="section-tag">{mission.length}</span>
            </h2>
          </div>
          <h3 className="api-sub" id="classes">
            Classes
          </h3>
          <div className="api-cards">
            {mission
              .filter((p) => p.kind === "class")
              .map((p) => (
                <PageCard key={p.href} p={p} />
              ))}
          </div>
          <h3 className="api-sub" id="globals">
            Global tables and namespaces
          </h3>
          <div className="api-cards">
            {mission
              .filter((p) => p.kind !== "class")
              .map((p) => (
                <PageCard key={p.href} p={p} />
              ))}
          </div>
        </section>
      ) : null}

      {(["hooks", "export", "server"] as const).map((s) =>
        show(s) && bySection.get(s)?.length ? (
          <section key={s} id={s} className="section" aria-labelledby={`${s}-h`}>
            <div className="section-head">
              <h2 id={`${s}-h`}>
                {SECTION_LABEL[s]}{" "}
                <span className="section-tag">{bySection.get(s)?.length ?? 0}</span>
              </h2>
            </div>
            <div className="api-cards api-cards-dense">
              {(bySection.get(s) ?? []).map((p) => (
                <PageCard key={p.href} p={p} />
              ))}
            </div>
          </section>
        ) : null,
      )}

      {show("server") && !bySection.get("server")?.length ? (
        <section id="server" className="section" aria-labelledby="server-h">
          <div className="section-head">
            <h2 id="server-h">Server</h2>
          </div>
          <p className="api-note">
            Mission members tagged <span className="api-badge api-env api-env-server">Server</span>{" "}
            (most of{" "}
            <RefLink href="/api/net/">
              <code>net</code>
            </RefLink>
            ) run here.
          </p>
        </section>
      ) : null}

      {env === "all" || env === "mission" ? (
        <section id="types" className="section" aria-labelledby="types-h">
          <div className="section-head">
            <h2 id="types-h">
              Types <span className="section-tag">{bySection.get("types")?.length ?? 0}</span>
            </h2>
          </div>
          <div className="api-enum-bar">
            <label htmlFor={typeInput} className="visually-hidden">
              Filter types
            </label>
            <input
              id={typeInput}
              className="input api-enum-filter"
              type="search"
              placeholder="Filter types"
              value={typeQuery}
              onChange={(e) => setTypeQuery(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          {types.map(({ group, list }) => (
            <details
              key={group.id}
              className="api-typegroup"
              open={group.id === MAIN_TYPES.id || !!typeQuery}
            >
              <summary>
                <span>{group.label}</span> <span className="muted">{list.length}</span>
              </summary>
              <ul className="api-typelist">
                {list.map((p) => (
                  <li key={p.href}>
                    <RefLink href={p.href}>
                      <code>{p.name}</code>
                    </RefLink>
                    <span className="api-typelist-kind">{p.kind}</span>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </section>
      ) : null}
    </>
  );
}
