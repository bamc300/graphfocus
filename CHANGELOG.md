# Changelog

All notable changes to GraphFocus are documented here. This project uses
[Semantic Versioning](https://semver.org/). PyPI releases are produced
automatically by the `publish.yml` workflow on every `vX.Y.Z` tag.

## [0.3.1] — 2026-06-02

### Fixed
- **Windows crash on `analyze`**: every output writer (`graph.json`,
  `GRAPH_REPORT.md`) and every source reader (SQL / PL-SQL extractors,
  detector heuristics, FastAPI graph route) now forces
  ``encoding="utf-8"`` explicitly. Without this, ``Path.write_text``
  defaults to ``cp1252`` on Windows and crashes the moment a label
  contains a non-Latin-1 character such as ``→`` (U+2192):
  ``UnicodeEncodeError: 'charmap' codec can't encode character
  '\\u2192' ...``. The other writers (Obsidian, AI summary, Mermaid,
  HTML viz, semantic index, MCP installer) already passed the encoding.

### Added
- ``tests/test_unicode_io.py`` — a regression suite that re-runs every
  output writer with a node whose label contains ``→`` and asserts the
  resulting file decodes cleanly as UTF-8.

## [0.3.0] — 2026-06-02

### Added
- **`graphfocus diff old.json new.json`** — compare two graph snapshots
  and print added / removed / changed nodes and edges, with a `--json`
  mode that's friendly for CI consumption.
- **Minimap** in `graph.html` — fixed in the bottom-right corner of the
  viz, painted from the same pre-computed positions. Click to recentre
  the camera; the viewport rectangle tracks the camera live.
- **Keyboard shortcuts** in the viz: `/` focuses the search, `f` fits
  the camera, `r` resets filters, `1`/`2`/`3` switch the Color-by
  mode (language/kind/community), `Esc` clears.
- **FastAPI bearer-token auth** — set `GRAPHFOCUS_API_TOKEN` in the
  environment and every `/api/*` request requires the matching
  `Authorization: Bearer …` header. Unset = open server (backward
  compatible with 0.2.x deployments).

## [0.2.5] — 2026-06-02

### Added
- **Parallel `analyze`** — fans the per-file extraction across a
  `ProcessPoolExecutor` when the project has 100+ pending files.
  Falls back to a sequential loop for small projects (where pool
  startup is more expensive than the work itself). New `-j/--jobs` flag.
- **`--include` and `--exclude` glob filters** for `analyze` to narrow
  the scan to a subdirectory or skip generated code without touching
  the detector.
- **Live progress bar** during `analyze` via `rich.progress` (silent
  in non-TTY output).
- **`graphfocus init`** — scaffolds a starter `.graphfocus.yml`
  ready for the lint engine.
- **Cache prune** — `analyze --update` now deletes entries for files
  that no longer exist on disk, so the graph never carries stale
  nodes from deleted source.

### Changed
- Removed the unimplemented `graphfocus query` and `graphfocus path`
  stubs that printed "coming soon". Use `graphfocus semantic` for
  natural-language queries and the MCP tool `find_path` for paths.
- Internal extraction loop moved out of `cli.py` into
  `graphfocus/pipeline.py` so it can be reused by future commands.

## [0.2.4] — 2026-05-29

### Added
- Architecture lint engine: `graphfocus lint` reads `.graphfocus.yml`
  rules (`disallow`, `require`, `max_outgoing` / `max_incoming`) and
  reports violations. `--fail-on-violation` makes it CI-friendly.

## [0.2.3] — 2026-05-29

### Added
- OpenAPI / Swagger extractor — `.yaml`, `.yml`, `.json` files that
  contain a spec become subgraphs of `api` / `endpoint` / `schema` /
  `property` nodes with `accepts` / `returns` / `references` edges.

## [0.2.2] — 2026-05-29

### Added
- `graphfocus export-mermaid` — renders the graph (or a filtered
  subgraph) as a Mermaid `flowchart` that embeds in GitHub, GitLab,
  Notion, Obsidian and most static site generators.

## [0.2.1] — 2026-05-29

### Added
- TF-IDF semantic search — `graphfocus semantic <query>` and MCP tool
  `find_semantic`. Dependency-free; CamelCase / snake_case splitting
  with a tiny plural/singular fold for friendlier queries.

## [0.2.0] — 2026-05-29

### Added
- **`get_context_pack`** MCP tool — bundles symbol + callers + callees
  + neighbors + community siblings into one round-trip.
- **`hot_paths`** MCP tool — ranks central nodes by degree.
- **Markdown / ADR extractor** — `.md`/`.markdown`/`.mdx` files
  become document graphs (headings, wikilinks, references).
- **`graphfocus watch`** — file watcher that re-runs `analyze --update`
  on every change.

## [0.1.5] — 2026-05-28

### Fixed
- HTML viz used to fail under `file://` (browsers refuse WebGL and
  CDN scripts for local files). The wheel now ships `sigma.min.js`
  and `graphology.umd.min.js` next to `graph.html`, and the new
  `graphfocus serve-viz` command runs a tiny local HTTP server with
  the right scope.

## [0.1.4] — 2026-05-28

### Added
- `graphfocus install-mcp` — scans the machine for Claude Desktop,
  Cursor, Windsurf, Trae AI, Continue.dev, Zed and VS Code (Cline),
  and offers to wire the graphfocus MCP server into each one's
  configuration. Backs up the original file before editing.

## [0.1.3] — 2026-05-28

### Added
- WebGL viz: Sigma.js v3 + graphology rendering scaling to 100k+
  nodes. Layout is pre-computed in Python with `igraph`, so the
  browser only renders.

## [0.1.2] — 2026-05-27

### Added
- "Color by" selector in `graph.html`: Language / Kind / Community.

## [0.1.1] — 2026-05-27

### Fixed
- Replaced `graspologic` with `igraph` for community detection so
  `pip install "graphfocus[all]"` succeeds on Python 3.14.

## [0.1.0] — 2026-05-27

Initial public release.
- 19 language extractors (tree-sitter for Python, Java, C#, Go,
  Kotlin, Rust, TypeScript, Swift, Ruby, PHP, C, C++, Scala, Lua,
  plus Vue SFCs; regex for SQL, PL/SQL, Dart, R).
- Cross-language linker connecting Java/C# `@Entity` to SQL/PL-SQL
  tables.
- Outputs: `graph.json`, interactive HTML, Markdown report, Obsidian
  vault, dense AI summary.
- MCP server with 8 tools for AI integration.
- FastAPI REST server.
- SQLite cache for incremental `--update` runs.
