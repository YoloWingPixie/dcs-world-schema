"use client";

import { Fragment, useEffect, useState } from "react";
import type { ScriptingRow, ScriptingText } from "@/lib/api/record-scripting";
import { SCRIPTING } from "@/lib/api/scripting";
import { browserQuery } from "@/lib/db/browser";
import type { RecordDoc } from "@/lib/types";
import { ApiLink } from "../api/api-link";

export const SCRIPTING_ID = "scripting";

/** How long a record page settles before its Scripting rows load. */
const SETTLE_MS = 500;

/**
 * The record's Scripting rows, loaded once the record is on screen (the API code and its
 * database pages are not part of a record page's first load): `loading` until then, null
 * when the series has none or the API data confirms none.
 */
export function useScripting(doc: RecordDoc | null): ScriptingRow[] | "loading" | null {
  const [rows, setRows] = useState<{ key: string; rows: ScriptingRow[] } | null>(null);
  const key = doc ? `${doc.series}/${doc.id}` : "";
  useEffect(() => {
    if (!doc || !SCRIPTING[doc.series]) return;
    let live = true;
    const done = (list: ScriptingRow[]) =>
      live && setRows({ key: `${doc.series}/${doc.id}`, rows: list });
    // After the record's own reads have settled: these database pages are extra, and the
    // record's first load should not wait behind them.
    const start = () =>
      import("@/lib/api/record-scripting")
        .then((m) => m.loadScripting(browserQuery, doc.series, doc.id, doc.data))
        // No API data: the record reads the same without the block.
        .then(done, () => done([]));
    const timer = window.setTimeout(() => {
      if ("requestIdleCallback" in window) window.requestIdleCallback(start, { timeout: 1000 });
      else start();
    }, SETTLE_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [doc]);
  if (!doc || !SCRIPTING[doc.series]) return null;
  if (rows?.key !== key) return "loading";
  return rows.rows.length ? rows.rows : null;
}

/** Long Lua names break after their dots, not mid-name. */
function breakable(text: string) {
  return text.split(/(?<=[.[])/).map((part, i, all) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: fixed pieces of one string
    <Fragment key={i}>
      {part}
      {i < all.length - 1 ? <wbr /> : null}
    </Fragment>
  ));
}

function Text({ t }: { t: ScriptingText }) {
  const body = t.code ? <code>{breakable(t.text)}</code> : t.text;
  return t.href ? <ApiLink href={t.href}>{body}</ApiLink> : body;
}

/** Labelled rows, as the record's own fields: the API member or role, a leader, the value. */
export function ScriptingBlock({ rows }: { rows: ScriptingRow[] | "loading" }) {
  if (rows === "loading") {
    return (
      <div className="fields script-fields" aria-busy="true">
        <span className="visually-hidden">Loading…</span>
        <div className="sk sk-row" />
        <div className="sk sk-row" />
        <div className="sk sk-row" />
      </div>
    );
  }
  return (
    <div className="fields script-fields">
      {rows.map((r) => (
        <div key={r.id} className="field script-field" data-scripting={r.id}>
          <span className="field-label">
            <span className="script-label">
              <Text t={r.label} />
              {r.verb ? <span className="script-verb"> {r.verb}</span> : null}
            </span>
          </span>
          <span className="field-value">
            <Text t={r.value} />
            {r.note ? <span className="secondary">{r.note}</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}
