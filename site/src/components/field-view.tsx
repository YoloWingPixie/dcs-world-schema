"use client";

import type { ReactNode } from "react";
import { plainValue, resolveLink, storedValue, type ValueContext } from "@/lib/format-field";
import { enumDisplay } from "@/lib/names";
import { recordHref } from "@/lib/series";
import type { CatalogEntry } from "@/lib/types";
import { formatWithUnit, isSentinelAngle, unitGap } from "@/lib/units";
import { MoreIcon } from "@/ui/icons";
import { Markdown } from "./Markdown";
import { RefLink } from "./ref-link";

/** Which record a rendered field belongs to (the field menu reads it from data attributes). */
export type FieldContext = { series: string; slug: string; recordName: string };

/**
 * Data attributes the field context menu reads (components/field-menu.tsx):
 * any element with `data-field` gets compare / add / copy on right-click, ⋯, Shift+F10 or C.
 */
export function fieldDataAttrs(
  entry: CatalogEntry,
  path: string,
  value: unknown,
  ctx: FieldContext,
  vctx: ValueContext,
  label = entry.label,
) {
  const stored = storedValue(entry, value, vctx.system, vctx.enums);
  const text = plainValue(entry, value, vctx);
  return {
    "data-field": path,
    "data-field-label": label,
    "data-field-comparable": entry.comparable ? "true" : "false",
    "data-field-text": text,
    ...(stored && stored !== text ? { "data-field-stored": stored } : {}),
    "data-series": ctx.series,
    "data-record": ctx.slug,
    "data-record-name": ctx.recordName,
  } as const;
}

/** Backticked spans in schema descriptions become <code>. */
export function renderDescription(text: string): ReactNode[] {
  const clean = text.replace(/^Optional\s+(\w)/, (_, c: string) => c.toUpperCase());
  return clean.split(/(`[^`]+`)/g).map((part, i) =>
    part.startsWith("`") && part.endsWith("`") ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: static split of a fixed string
      <code key={i}>{part.slice(1, -1)}</code>
    ) : (
      part
    ),
  );
}

export function Description({
  entry,
  id,
  stored,
  notes,
}: {
  entry: CatalogEntry;
  id: string;
  stored?: string | null;
  /** Per-record facts beside the value: its code, its provenance. */
  notes?: string[] | undefined;
}) {
  return (
    <div className="tip" id={id} role="tooltip">
      {renderDescription(entry.description)}
      {stored ? <span className="tip-stored">Stored as {stored}</span> : null}
      {notes?.map((n) => (
        <span className="tip-stored" key={n}>
          {n}
        </span>
      ))}
      {entry.note ? (
        <div className="tip-note">
          <Markdown html={entry.note} handWritten />
        </div>
      ) : null}
    </div>
  );
}

export function MoreButton({ label }: { label: string }) {
  return (
    <span className="field-actions">
      <button
        type="button"
        className="field-more"
        data-field-menu-button=""
        aria-haspopup="menu"
        aria-label={`Actions for ${label}`}
        title="Actions (C)"
      >
        <MoreIcon />
      </button>
    </span>
  );
}

export function RecordLink({
  entry,
  raw,
  vctx,
}: {
  entry: Pick<CatalogEntry, "ref">;
  raw: unknown;
  vctx: ValueContext;
}) {
  const link = resolveLink(entry, raw, vctx.links);
  if (!link) return <span className="ref-missing">{String(raw)}</span>;
  return (
    <RefLink className="ref-link" href={recordHref(link.series, link.slug)}>
      {link.name}
    </RefLink>
  );
}

/** A scalar value with its unit (converted for display), enum label or record link. */
export function ScalarValue({
  entry,
  value,
  vctx,
}: {
  entry: CatalogEntry;
  value: unknown;
  vctx: ValueContext;
}) {
  if (value === undefined || value === null) return <span className="muted">—</span>;
  if (entry.kind === "ref") return <RecordLink entry={entry} raw={value} vctx={vctx} />;
  if (entry.codeField && Array.isArray(value)) {
    return <>{value.map((v) => enumDisplay(entry, v, vctx.enums).label).join(", ")}</>;
  }
  if (entry.kind === "enum") {
    const d = enumDisplay(entry, value, vctx.enums);
    if (d.rewrite) {
      return (
        <>
          <span className="friendly">{d.label}</span>
          <span className="enum-raw">{d.raw}</span>
        </>
      );
    }
    return <>{d.label}</>;
  }
  if (typeof value === "number") {
    const f = formatWithUnit(value, entry.unit, vctx.system, entry.name);
    return (
      <>
        {f.text}
        {f.unit ? (
          <>
            {unitGap(f.unit)}
            <span className="unit">{f.unit}</span>
          </>
        ) : null}
        {isSentinelAngle(value, entry.unit) ? (
          <>
            {" "}
            <span className="secondary unit-note">raw, not an angle</span>
          </>
        ) : null}
        {entry.unitNotStated ? (
          <>
            {" "}
            <span className="secondary unit-note">unit not stated</span>
          </>
        ) : null}
      </>
    );
  }
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value === "string") return <>{value}</>;
  return <code className="json">{JSON.stringify(value)}</code>;
}

export const tipIdFor = (ctx: FieldContext, path: string) =>
  `tip-${ctx.series}-${path.replace(/[^A-Za-z0-9_-]/g, "_")}`;

/** One field row: label (description on hover), value, actions. `body` makes it full width. */
export function FieldRow({
  entry,
  path,
  value,
  ctx,
  vctx,
  label,
  body,
  notes,
  after,
}: {
  entry: CatalogEntry;
  path: string;
  value: unknown;
  ctx: FieldContext;
  vctx: ValueContext;
  label?: string;
  body?: ReactNode;
  /** Tooltip lines: the code a constant name stands for, the value's provenance. */
  notes?: string[] | undefined;
  /** More beside the value (a range row's second column). */
  after?: ReactNode;
}) {
  const tipId = tipIdFor(ctx, path);
  const shown = label ?? entry.label;
  const stored = storedValue(entry, value, vctx.system, vctx.enums);
  return (
    <div
      className={body ? "field field-wide" : "field"}
      tabIndex={0}
      aria-describedby={tipId}
      aria-keyshortcuts="Shift+F10 C"
      {...fieldDataAttrs(entry, path, value, ctx, vctx, shown)}
    >
      <span className="field-label">
        {shown}
        {entry.dcsKey ? <span className="field-key">{entry.dcsKey}</span> : null}
        {entry.note ? (
          <span className="note-dot" title="Note">
            <span className="visually-hidden">(note)</span>
          </span>
        ) : null}
      </span>
      {body ? null : (
        <span className="field-value">
          <ScalarValue entry={entry} value={value} vctx={vctx} />
          {after}
        </span>
      )}
      <MoreButton label={shown} />
      {body ? <div className="field-body">{body}</div> : null}
      <Description entry={entry} id={tipId} stored={stored} notes={notes} />
    </div>
  );
}
