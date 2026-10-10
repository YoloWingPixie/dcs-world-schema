Notes layered on the reference, which the site reads live from the released
SQLite database. They ship with the site (scripts/build-overlays.ts); never edit the data.

- `<series>/_index.md`: intro on the series' browse page.
- `<series>/<id>.md`: note on a record page, named by the record's exact id as `encodeURIComponent(id)` writes it (`BLU-49/B` is `BLU-49%2FB.md`; most ids are their own name). Empty body is fine for aliases only.
- `<series>/_fields/<field path>.md`: note on a field (tooltip, compare header); write `*` as `+`.

Frontmatter: `aliases` (records only; extra search terms) and `seeAlso` (URLs or `{label, href}`).
Unknown frontmatter keys fail the build. Overlays whose record or field is gone from the
data are ignored by the site; `pnpm check:overlays <reference.sqlite>` (and `pnpm test`)
lists them, and names the file a record's id takes when a file is named by its slug.
