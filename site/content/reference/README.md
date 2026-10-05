Notes layered on the reference, which the site reads live from the released
SQLite database. They ship with the site (scripts/build-overlays.ts); never edit the data.

- `<series>/_index.md`: intro on the series' browse page.
- `<series>/<id or slug>.md`: note on a record page (empty body is fine for aliases only).
- `<series>/_fields/<field path>.md`: note on a field (tooltip, compare header); write `*` as `+`.

Frontmatter: `aliases` (records only; extra search terms) and `seeAlso` (URLs or `{label, href}`).
Unknown frontmatter keys fail the build. Overlays whose record or field is gone from the
data are ignored by the site; `pnpm check:overlays <reference.sqlite>` lists them.
