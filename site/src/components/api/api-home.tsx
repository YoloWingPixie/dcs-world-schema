"use client";

import { useEffect, useId, useMemo, useState } from "react";
import type { ApiSection, PageSummary } from "@/lib/api/types";
import { ApiLink } from "./api-link";

type Filter = "all" | "mission" | "hooks" | "export" | "server";

const ENVS: Array<{ id: Filter; label: string; blurb: string }> = [
  { id: "all", label: "All", blurb: "" },
  {
    id: "mission",
    label: "Mission",
    blurb: "Mission scripting: triggers, DO SCRIPT and mission Lua files.",
  },
  {
    id: "hooks",
    label: "Hooks",
    blurb: "GameGUI hooks (Saved Games/DCS/Scripts/Hooks): the server and UI side.",
  },
  { id: "export", label: "Export", blurb: "Export.lua: cockpit and telemetry export." },
  { id: "server", label: "Server", blurb: "The dedicated server's own Lua state." },
];

const SECTION_TITLE = { hooks: "Hooks (GameGUI)", export: "Export", server: "Server" } as const;

const KIND_ORDER: Record<string, number> = { class: 0, singleton: 1, namespace: 2 };

function PageCard({ p }: { p: PageSummary }) {
  return (
    <ApiLink href={p.href} className="api-card">
      <span className="api-card-name">{p.name}</span>
      <span className="api-card-meta">
        {p.kind === "singleton" ? "global" : p.kind} · {p.count}
      </span>
      {p.summary ? <span className="api-card-sum">{p.summary}</span> : null}
    </ApiLink>
  );
}

function typeGroup(name: string): string {
  if (name.startsWith("DcsTask.")) return "DcsTask: AI tasks, commands and options";
  if (name.startsWith("DcsId.")) return "DcsId: DCS ids (unit, weapon, airbase types)";
  if (name.startsWith("AI.")) return "AI";
  return "Records, enums and unions";
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
          a.name.localeCompare(b.name, "en", { sensitivity: "base" }),
      );
    }
    return m;
  }, [pages]);

  const types = useMemo(() => {
    const q = typeQuery.trim().toLowerCase();
    const list = (bySection.get("types") ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q),
    );
    const groups = new Map<string, PageSummary[]>();
    for (const p of list)
      groups.set(typeGroup(p.name), [...(groups.get(typeGroup(p.name)) ?? []), p]);
    return [...groups.entries()].sort(([a], [b]) =>
      a.startsWith("Records") ? -1 : b.startsWith("Records") ? 1 : a.localeCompare(b),
    );
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
        <p className="lede">
          Every global, class, function and type the schema describes, with signatures in Lua style
          and each type linked to its page. Start from <ApiLink href="/api/Unit/">Unit</ApiLink>,{" "}
          <ApiLink href="/api/trigger/action/">trigger.action</ApiLink> or{" "}
          <ApiLink href="/api/Controller/">Controller</ApiLink>, or press{" "}
          <span className="kbd">Ctrl K</span> and type a function name.
        </p>
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
            className="api-env-btn"
            aria-pressed={env === e.id}
            onClick={() => {
              setEnv(e.id);
              try {
                window.history.replaceState(null, "", e.id === "all" ? "#" : `#${e.id}`);
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
            <h2 id="mission-h">Mission scripting</h2>
            <span className="section-blurb">{ENVS[1]?.blurb}</span>
          </div>
          <h3 className="api-sub">Classes</h3>
          <div className="api-cards">
            {mission
              .filter((p) => p.kind === "class")
              .map((p) => (
                <PageCard key={p.href} p={p} />
              ))}
          </div>
          <h3 className="api-sub">Global tables and namespaces</h3>
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
              <h2 id={`${s}-h`}>{SECTION_TITLE[s]}</h2>
              <span className="section-blurb">
                {ENVS.find((e) => e.id === s)?.blurb} Generated from the API dump; most entries have
                no description yet.
              </span>
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
            <span className="section-blurb">{ENVS[4]?.blurb}</span>
          </div>
          <p className="api-note">
            The schema has no globals of its own for the server state yet. Mission scripting members
            tagged <span className="api-badge api-env api-env-server">Server</span> (most of{" "}
            <ApiLink href="/api/net/">net</ApiLink>) also run there.
          </p>
        </section>
      ) : null}

      {env === "all" || env === "mission" ? (
        <section id="types" className="section" aria-labelledby="types-h">
          <div className="section-head">
            <h2 id="types-h">Types</h2>
            <span className="section-blurb">
              Records, enums and unions the mission API takes and returns
            </span>
          </div>
          <div className="api-enum-bar">
            <label htmlFor={typeInput} className="visually-hidden">
              Filter types
            </label>
            <input
              id={typeInput}
              className="input api-enum-filter"
              type="search"
              placeholder="Filter types (Vec3, Orbit, WeaponType)"
              value={typeQuery}
              onChange={(e) => setTypeQuery(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          {types.map(([group, list]) => (
            <details
              key={group}
              className="api-typegroup"
              open={group.startsWith("Records") || !!typeQuery}
            >
              <summary>
                <span>{group}</span> <span className="muted">{list.length}</span>
              </summary>
              <ul className="api-typelist">
                {list.map((p) => (
                  <li key={p.href}>
                    <ApiLink href={p.href}>
                      <code>{p.name}</code>
                    </ApiLink>
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
