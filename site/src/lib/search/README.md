# Shared site contracts

## Global search sources (`sources.ts`)

The palette (Ctrl K) merges every entry of `SEARCH_SOURCES`. A source is:

```ts
{ id, label, indexUrl, options, docToResult, weight?, priority? }   // types.ts
```

- `indexUrl`: site path without basePath (`/data/search/api.json`), fetched lazily the first
  time the palette opens; lower `priority` loads first.
- The file is `serializeIndex(options, docs)` (engine.ts) written at build time; `options`
  are the MiniSearch options used to build it and must be the same object at runtime.
- `docToResult(stored)` maps a stored document (its `storeFields` + `id`) to
  `{ key, title, subtitle?, detail?, href }`; `href` is a site path without basePath.
- `id`/`label` become the group heading and the filter chip. Results are grouped per source
  and groups are ordered by their best score times `weight`.

To add one, export a `SearchSource` from your own module and append it to `SEARCH_SOURCES`.

`SEARCH_PROVIDERS` holds searches that run their own query per keystroke instead of a
prebuilt index: `{ id, label, search(query, limitPerGroup) => Promise<SourceHits[]>, warm? }`.
The reference is one (`reference-sources.ts`): FTS5 over the SQLite database, one group per
series. Groups from sources and providers are merged and ranked together.

## Reference data (`../db/`)

The browser queries the released `.sqlite` over HTTP range requests (`db/browser.ts`,
sql.js-httpvfs); `db/reference.ts` reads the model, records, browse rows, field values and
search from it with any `Query` (node:sqlite in tests). Record URLs are `/<series>/<id>/`,
served by the shell in `app/not-found.tsx`; link to them with `RefLink` / `openHref`
(`components/ref-link.tsx`) and `recordHref` (`../series.ts`).

## Navigation (`../nav.ts`)

`NAV_SECTIONS` drives the header links and the home page sections: append
`{ id, label, href, description, match? }` (`match`: path prefixes, default `[href]`).

## Markdown (`../markdown.ts`, `components/Markdown.tsx`)

`parseFrontmatter(text, { file, allowed })` (throws on unknown keys), `renderMarkdown(md)`
(raw HTML escaped) and `markdownToText(md)` for indexes. Render with `<Markdown html />`
(client; pass `handWritten` to mark overlay content) or `<MarkdownSource source />` from a
server component. Internal links are site-relative; the component adds basePath.

## Units (`../units.ts`)

`useUnitSystem()` (`../unit-system.ts`, client) returns `"metric" | "imperial"`;
`convertValue` / `formatPlain(value, unit, system, fieldName)` (`../units.ts`) convert for display
only. Units come from field-name suffixes (`unitFor(name)`).
