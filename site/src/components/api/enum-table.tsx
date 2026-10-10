"use client";

import { useDeferredValue, useId, useMemo, useState } from "react";
import { enumValueId } from "@/lib/api/scripting";
import type { EnumValue } from "@/lib/api/types";
import { squash } from "@/lib/text";
import { RefLink } from "../ref-link";

/** Enum values; past a handful, filterable by key or value. */
export function EnumTable({
  name,
  values,
  seriesLabel,
}: {
  name: string;
  values: Array<EnumValue & { href?: string | undefined; refLabel?: string | undefined }>;
  seriesLabel?: string | undefined;
}) {
  const [query, setQuery] = useState("");
  const [linkedOnly, setLinkedOnly] = useState(false);
  const deferred = useDeferredValue(query);
  const inputId = useId();
  const filterable = values.length > 12;
  const anyLinked = values.some((v) => v.href);
  const rows = useMemo(() => {
    const q = squash(deferred);
    return values.filter(
      (v) =>
        (!linkedOnly || v.href) &&
        (!q || squash(v.key).includes(q) || squash(String(v.value)).includes(q)),
    );
  }, [values, deferred, linkedOnly]);
  const sameKV = values.every((v) => v.key === String(v.value));

  return (
    <div className="api-enum">
      {filterable ? (
        <div className="api-enum-bar">
          <label htmlFor={inputId} className="visually-hidden">
            Filter {name} values
          </label>
          <input
            id={inputId}
            className="input api-enum-filter"
            type="search"
            placeholder={`Filter ${values.length} values`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          {anyLinked && seriesLabel ? (
            <label className="check">
              <input
                type="checkbox"
                checked={linkedOnly}
                onChange={(e) => setLinkedOnly(e.target.checked)}
              />
              Linked only
            </label>
          ) : null}
          <span className="api-enum-count" aria-live="polite">
            {rows.length === values.length
              ? `${values.length} values`
              : `${rows.length} of ${values.length}`}
          </span>
        </div>
      ) : null}
      <div className="table-wrap api-table-wrap api-enum-scroll">
        <table className="table api-table">
          <caption className="visually-hidden">Values of {name}</caption>
          <thead>
            <tr>
              <th scope="col">{sameKV ? "Value" : "Key"}</th>
              {sameKV ? null : <th scope="col">Value</th>}
              {anyLinked ? <th scope="col">Reference</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.key} id={enumValueId(v.key)}>
                <td className="api-name-cell">
                  <code>{v.key}</code>
                </td>
                {sameKV ? null : (
                  <td>
                    <code className="api-value">{JSON.stringify(v.value)}</code>
                  </td>
                )}
                {anyLinked ? (
                  <td
                    className={v.href && !v.refLabel ? "api-ref-cell api-ref-page" : "api-ref-cell"}
                  >
                    {v.href ? (
                      <RefLink
                        href={v.href}
                        aria-label={`${v.key}: ${v.refLabel ?? `${seriesLabel ?? "record"} page`}`}
                      >
                        {v.refLabel ?? seriesLabel ?? "record"}
                      </RefLink>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                ) : null}
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  No results for “{query}”.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
