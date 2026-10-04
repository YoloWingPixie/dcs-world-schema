# Lua API overlays

Hand-written notes layered on the Lua API docs, which the site reads from the reference database. One file per symbol, named by its path: `Unit.md`, `Unit.getByName.md`, `trigger.action.outText.md`, `DcsTask.Task.Orbit.md`.
Optional frontmatter: `summary`, `description` (replace the schema's), `seeAlso` (list of symbol paths), `deprecated` (true or a message), `since`, and `symbol` / `section` (`mission`, `hooks`, `export`, `server`, `types`) when the file name cannot say it.
The Markdown body (Notes, Examples in ```lua fences, Caveats) renders below the generated entry, marked as hand-written, and is searchable.
`pnpm build:api` compiles them to `public/overlays/api.json` and fails only on unknown frontmatter keys or bad Markdown. Overlays whose symbol is gone are ignored by the site; `pnpm check:overlays <reference.sqlite>` lists them.
