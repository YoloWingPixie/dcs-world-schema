# Shared site contracts

## Global search (`engine.ts`, `client.ts`)

The palette (Ctrl K), the home search box and `/search` search every row of the database's
`search` table (reference records and Lua API symbols) in memory:

- `scripts/split-sqlite.ts` (`nameIndex`) writes the rows to a content-hashed file next to the
  database parts, named by `names` in `/data/reference.json`: `[series, id, name, subtitle,
  keywords]`, keywords trimmed to the words the name's own terms do not cover.
- `client.ts` `loadSearch` fetches it on first use (the search button prefetches it on hover
  or focus), joins the overlays' record aliases and API notes, and indexes it with MiniSearch
  (`engine.ts` `buildNameIndex`). `useGlobalSearch` then answers each keystroke at once.
- `engine.ts` `searchNames` ranks (prefix words, AND; the words run together; typos only when
  nothing matches) and groups the hits: one group per series, the Lua API as its own; an
  exact name, id or alias comes first.

## Reference data (`../db/`)

The browser queries the released `.sqlite` over HTTP range requests (`db/browser.ts`,
sql.js-httpvfs); `db/reference.ts` reads records, browse rows and field values from it with
any `Query` (node:sqlite in tests). The model (series, schema types, reference paths) comes
from a static file `split-sqlite.ts` writes (`model` in reference.json; `modelFrom`). Record URLs are `/<series>/<id>/`,
served by the shell in `app/not-found.tsx`; link to them with `RefLink` / `openHref`
(`components/ref-link.tsx`) and `recordHref` (`../series.ts`).

## Navigation (`../nav.ts`)

`NAV_SECTIONS` drives the header links and which paths are Next.js pages (`PAGE_ROOTS`):
append `{ id, label, href, kind, match?, prefetch?, className?, compare? }` (`kind`: `page`
or `shell`; `match`: path prefixes, default `[href]`).

## Markdown (`../markdown.ts`, `components/Markdown.tsx`)

`parseFrontmatter(text, { file, allowed })` (throws on unknown keys), `renderMarkdown(md)`
(raw HTML escaped) and `markdownToText(md)` for indexes. Render with `<Markdown html />`
(client; pass `handWritten` to mark overlay content), also from a server component with
`html={renderMarkdown(source)}`. Internal links are site-relative; the component adds basePath.

## Units (`../units.ts`)

`useUnitSystem()` (`../unit-system.ts`, client) returns `"metric" | "imperial"`;
`convertValue` / `formatPlain(value, entry, system)` (`../units.ts`) convert for display only;
pass the catalog entry (its unit, name and resolved conversions) or a bare unit string; radians (`rad`, `rad/s`) show as degrees in both systems, and `formatStored` gives the stored
value whenever the display converts. Units come from field-name suffixes (`unitFor(name)`), and a
suffixed record field passes its unit to unsuffixed members (`slewRateRadS.yaw`).
