"use client";

import Link from "next/link";
import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { setNavHint } from "@/lib/nav-hints";
import { useGlobalSearch, warmSearch } from "@/lib/search/client";
import type { SearchResultItem } from "@/lib/search/types";
import { SearchIcon } from "@/ui/icons";

const PER_GROUP = 4;
const PER_SOURCE = 50;

type Props = {
  label: string;
  placeholder?: string;
  autoFocus?: boolean;
  /** Palette: the list is always open; inline: it opens while typing. */
  variant: "palette" | "inline" | "page";
  initialQuery?: string;
  onPick: (item: SearchResultItem) => void;
  onEscape?: () => void;
  onQueryChange?: (q: string) => void;
  emptyHint?: ReactNode;
  footer?: ReactNode;
};

type Row = SearchResultItem & { source: string; sourceLabel: string };

/**
 * The global search: every registered source (lib/search/sources.ts), grouped by source,
 * with source filter chips and arrow-key navigation across groups.
 */
export function GlobalSearch({
  label,
  placeholder = "Search",
  autoFocus,
  variant,
  initialQuery = "",
  onPick,
  onEscape,
  onQueryChange,
  emptyHint,
  footer,
}: Props) {
  const [query, setQuery] = useState(initialQuery);
  const [filter, setFilter] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(variant !== "inline");
  const [enabled, setEnabled] = useState(variant !== "inline" || Boolean(autoFocus));
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useGlobalSearch(query, { enabled, limit: PER_SOURCE });

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);
  useEffect(() => setQuery(initialQuery), [initialQuery]);

  const visibleGroups = useMemo(() => {
    const groups = filter ? results.groups.filter((g) => g.source.id === filter) : results.groups;
    const per = filter || variant === "page" ? PER_SOURCE : PER_GROUP;
    return groups.map((g) => ({ ...g, results: g.results.slice(0, per) }));
  }, [results.groups, filter, variant]);

  const rows: Row[] = useMemo(
    () =>
      visibleGroups.flatMap((g) =>
        g.results.map((r) => ({ ...r, source: g.source.id, sourceLabel: g.source.label })),
      ),
    [visibleGroups],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset the cursor when the list changes
  useEffect(() => setActive(0), [query, filter]);

  const pick = (row: Row | undefined) => {
    if (!row) return;
    setNavHint(row.href, { name: row.title, ...(row.subtitle ? { meta: row.subtitle } : {}) });
    onPick(row);
    if (variant === "inline") setOpen(false);
  };

  const chipIds = results.groups.map((g) => g.source.id);
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(rows.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(rows[active]);
    } else if (event.key === "Escape") {
      if (filter) {
        event.stopPropagation();
        setFilter(null);
      } else if (query) {
        event.stopPropagation();
        setQuery("");
        onQueryChange?.("");
      } else {
        if (variant === "inline") setOpen(false);
        onEscape?.();
      }
    } else if ((event.key === "ArrowRight" || event.key === "ArrowLeft") && event.altKey) {
      // Alt+arrows step through the source chips.
      event.preventDefault();
      const order = [null, ...chipIds];
      const i = order.indexOf(filter);
      const next = order[(i + (event.key === "ArrowRight" ? 1 : -1) + order.length) % order.length];
      setFilter(next ?? null);
    }
  };

  const q = query.trim();
  const showList = open && (q !== "" || variant !== "inline");
  const activeId = rows[active] ? `${listId}-${active}` : undefined;
  let rowIndex = -1;

  return (
    <div className={`combo gsearch gsearch-${variant}`}>
      <div className="combo-field">
        <SearchIcon />
        <input
          ref={inputRef}
          className="combo-input"
          role="combobox"
          aria-label={label}
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={showList ? activeId : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={query}
          onFocus={() => {
            setEnabled(true);
            setOpen(true);
          }}
          onPointerEnter={() => warmSearch()}
          onBlur={() => variant === "inline" && window.setTimeout(() => setOpen(false), 150)}
          onChange={(event) => {
            setQuery(event.target.value);
            onQueryChange?.(event.target.value);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      {showList ? (
        <div className="combo-popup">
          {q && results.groups.length > 0 ? (
            // biome-ignore lint/a11y/useSemanticElements: a toolbar of toggle chips
            <div className="gsearch-chips" role="group" aria-label="Filter results">
              <button
                type="button"
                className="gchip"
                aria-pressed={filter === null}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => setFilter(null)}
              >
                All
              </button>
              {results.groups.map((g) => (
                <button
                  type="button"
                  key={g.source.id}
                  className="gchip"
                  aria-pressed={filter === g.source.id}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => setFilter(filter === g.source.id ? null : g.source.id)}
                >
                  {g.source.label}
                  <span className="gchip-count">
                    {g.results.length >= PER_SOURCE ? `${PER_SOURCE}+` : g.results.length}
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <div className="results" id={listId} role="listbox" aria-label={`${label} results`}>
            {visibleGroups.map((g) => (
              // biome-ignore lint/a11y/useSemanticElements: an option group inside a listbox
              <div role="group" aria-labelledby={`${listId}-g-${g.source.id}`} key={g.source.id}>
                <div className="result-group" id={`${listId}-g-${g.source.id}`}>
                  <span>{g.source.label}</span>
                  {!filter && g.results.length >= PER_GROUP ? (
                    <button
                      type="button"
                      className="result-group-more"
                      tabIndex={-1}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => setFilter(g.source.id)}
                    >
                      More {g.source.label.toLowerCase()}
                    </button>
                  ) : null}
                </div>
                {g.results.map((r) => {
                  rowIndex += 1;
                  const i = rowIndex;
                  return (
                    // biome-ignore lint/a11y/useKeyWithClickEvents: keyboard is handled on the input
                    <div
                      key={`${g.source.id}:${r.key}`}
                      id={`${listId}-${i}`}
                      role="option"
                      tabIndex={-1}
                      aria-selected={i === active}
                      aria-label={[r.title, r.subtitle, g.source.label, r.detail]
                        .filter(Boolean)
                        .join(", ")}
                      className="result"
                      data-source={g.source.id}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseMove={() => setActive(i)}
                      onClick={() => pick(rows[i])}
                    >
                      <span className="result-name">{r.title}</span>
                      <span className="result-meta">{r.subtitle ?? ""}</span>
                      <span className="result-id">{r.detail ?? ""}</span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          {q && results.loading.length && !results.ready ? (
            <div className="results-empty">Loading…</div>
          ) : null}
          {q && results.ready && rows.length === 0 && results.loading.length === 0 ? (
            <div className="results-empty">No results for “{query}”.</div>
          ) : null}
          {q && results.loading.length > 0 && results.ready ? (
            <div className="results-loading" aria-live="polite">
              Loading…
            </div>
          ) : null}
          {results.failed.length ? (
            <div className="results-empty">
              Failed to load: {results.failed.map((s) => s.label).join(", ")}.
            </div>
          ) : null}
          {!q && emptyHint ? emptyHint : null}
          {q && variant !== "page" ? (
            <div className="results-all">
              <Link href={`/search/?q=${encodeURIComponent(q)}`} onClick={() => onEscape?.()}>
                All results for “{q}”
              </Link>
            </div>
          ) : null}
          {footer}
        </div>
      ) : null}
    </div>
  );
}
