# GraphFocus

**Turn any folder of code into a queryable knowledge graph.** Multi-language AST extraction with plugin architecture, designed to feed AI coding tools (Claude Desktop, Trae AI, Cursor, Windsurf) with focused, token-efficient context via MCP.

## Why

Most code intelligence tools either parse only one language (so a fullstack Spring Boot + Vue project becomes a black box) or shovel raw files to an LLM until you blow your context window. GraphFocus extracts a **deterministic** knowledge graph via tree-sitter ASTs across **19 languages**, links cross-language references (e.g. `@Entity OrderEntity` ↔ SQL `orders` table), and exposes it to AI tools so the model can ask `find_callers("validate")` instead of grepping the whole repo.

## Features

- **20 extractors** — Python, Java, TypeScript / JavaScript / React, Vue, C#, Go, Kotlin, Rust, Swift, Ruby, PHP, Scala, Lua, C, C++, Dart, R, SQL, PL/SQL, plus **Markdown / ADR** and **OpenAPI / Swagger** specs.
- **Cross-language linker** — Java/C# `@Entity`/`@Table` automatically wired to SQL/PL-SQL tables.
- **Plugin architecture** — add a language by implementing a single interface.
- **Parallel `analyze`** — fans the per-file work across `ProcessPoolExecutor` with a live progress bar; SQLite cache reuses unchanged files and prunes deleted ones.
- **MCP server** with 10 tools — `find_symbol`, `find_semantic`, `get_node`, `get_neighbors`, `find_callers`, `find_path`, `get_context_pack`, `hot_paths`, `cross_language_links`, `list_languages`, `get_stats`. Plug it into any AI IDE (Trae AI, Cursor, Claude Desktop, Windsurf, Continue.dev, Zed, VS Code Cline) with `graphfocus install-mcp`.
- **Outputs** — `graph.json`, WebGL-rendered `graph.html` (Sigma.js, 100k+ nodes), `GRAPH_REPORT.md`, dense `AI_SUMMARY.md` for LLM context, navigable Obsidian vault, Mermaid diagrams, TF-IDF semantic index.
- **Architecture lint** — `.graphfocus.yml` rules (`disallow`, `require`, `max_outgoing`) enforce layering in CI.
- **File watcher** — `graphfocus watch` re-analyzes on every save so the IDE always sees fresh data.
- **FastAPI server** — REST endpoints for non-Python clients.
- **Optional LLM enrichment** — semantic extraction from documents.

## Install

**Requires:** Python 3.11+

```bash
# Core + all 19 extractors
pip install graphfocus

# Add the MCP server for AI tools
pip install "graphfocus[ai]"

# Add the FastAPI server
pip install "graphfocus[api]"

# Everything
pip install "graphfocus[all]"
```

## Quick start

```bash
# Analyze the current directory; --update enables incremental cache;
# --ai writes the dense LLM summary; --obsidian writes a navigable vault.
graphfocus analyze . --update --ai --obsidian

# Output lands in ./graphfocus-out/:
#   graph.json        ← raw data
#   graph.html        ← interactive D3 visualization
#   GRAPH_REPORT.md   ← human report
#   AI_SUMMARY.md     ← LLM-friendly dense map (paste into a chat)
#   obsidian/         ← one .md per node, with wikilinks
#   .cache.db         ← incremental cache
```

## Query the graph from the CLI

```bash
graphfocus find UserService                  # substring search
graphfocus semantic "auth user payment"      # TF-IDF semantic search
graphfocus neighbors userservice_user --depth 2
graphfocus callers validate                  # who calls validate()?
graphfocus languages                         # list active extractors
```

## Other useful commands

| Command | What it does |
|---|---|
| `graphfocus analyze . --update -j 4` | Incremental analyze using 4 parallel workers |
| `graphfocus analyze . --include "src/**" --exclude "**/test_*"` | Limit the scope with globs |
| `graphfocus watch .` | Re-analyze automatically whenever a file changes |
| `graphfocus serve-viz` | Serve `graph.html` locally so WebGL works |
| `graphfocus serve` | Start the FastAPI REST server |
| `graphfocus mcp` | Launch the MCP server (used by AI IDEs) |
| `graphfocus install-mcp` | Auto-wire the MCP server into installed AI IDEs |
| `graphfocus export-mermaid --root <id> --markdown -o diagram.md` | Mermaid subgraph |
| `graphfocus init` | Scaffold `.graphfocus.yml` for the lint engine |
| `graphfocus lint --fail-on-violation` | Run architecture rules; non-zero exit on violations |

## Plug into your AI tool (MCP)

GraphFocus ships an MCP server that exposes the graph to any compatible AI tool. The LLM gains these tools:

| Tool | What it does |
|---|---|
| `find_symbol` | Search nodes by label/id, filter by language or kind |
| `get_node` | Full info on one node + its incoming/outgoing edges |
| `get_neighbors` | Walk N hops out from a node |
| `find_callers` | Who calls this function/method |
| `find_path` | Shortest path between two nodes |
| `list_languages` | What's in the graph |
| `get_stats` | Counts by kind and relation |
| `cross_language_links` | Only edges that cross languages |

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "graphfocus": {
      "command": "graphfocus",
      "args": ["mcp"],
      "cwd": "/absolute/path/to/your/project"
    }
  }
}
```

### Trae AI / Cursor / Windsurf / Continue.dev

In the tool's MCP config (`.cursor/mcp.json`, Trae settings, etc.):

```json
{
  "mcpServers": {
    "graphfocus": {
      "command": "graphfocus",
      "args": ["mcp"]
    }
  }
}
```

Restart the AI tool and ask things like *"who calls `validateUser`?"* — the model invokes `find_callers` and gets back a 200-byte JSON answer instead of grepping the whole codebase.

### HTTP transport

For tools that prefer HTTP+SSE over stdio:

```bash
graphfocus mcp --http --port 8765
```

## Token efficiency comparison

For a mid-sized Spring Boot project:

| Approach | Tokens sent to LLM |
|---|---|
| Raw source files | 30–100K |
| Full `graph.json` | 15–40K |
| `AI_SUMMARY.md` + a few Obsidian notes | **1–3K** |
| MCP `find_callers("X")` round-trip | **200–800** per question |

## Supported languages

| Language | Parser | Extracts |
|---|---|---|
| Python | tree-sitter | classes, functions, imports, calls, inheritance |
| Java | tree-sitter | classes, interfaces, methods, Spring annotations |
| TypeScript / JavaScript / React | tree-sitter (tsx) | classes, interfaces, type aliases, components |
| Vue | regex + delegated TS parser | component node, `<script>` symbols, child component refs in `<template>` |
| C# | tree-sitter | classes, methods, namespaces, attributes |
| Go | tree-sitter | structs, interfaces, methods (attached to receiver) |
| Kotlin | tree-sitter | classes, data classes, objects, Spring annotations |
| Rust | tree-sitter | structs, enums, traits, `impl Trait for Type` |
| Swift | tree-sitter | protocols, structs, classes, methods |
| Ruby | tree-sitter | modules, classes, methods, requires |
| PHP | tree-sitter | namespaces, interfaces, classes, methods |
| Scala | tree-sitter | traits, classes, case classes, objects |
| Lua | tree-sitter | functions, module methods (`M.foo`), requires |
| C | tree-sitter | structs, typedefs, functions, includes |
| C++ | tree-sitter | namespaces, classes, out-of-class methods |
| Dart | regex | classes, mixins, abstract classes, methods |
| R | regex | functions, library/source imports |
| SQL | regex (dialect-agnostic) | tables, columns, FKs, views, indexes |
| PL/SQL | regex | packages, procedures, functions, triggers |

## Architecture

```
Input files
   ↓
Detector  →  Registry  →  19 Extractors (per language)
                              ↓
                       Merger (dedup nodes)
                              ↓
                       Cross-language linker
                       (Java @Entity ↔ SQL table)
                              ↓
                Outputs:
                  • graph.json
                  • graph.html (D3 force-directed)
                  • GRAPH_REPORT.md
                  • AI_SUMMARY.md (dense for LLM)
                  • obsidian/  (one .md per node)
                              ↓
                MCP server / FastAPI / Query CLI
                              ↓
                Any AI tool over MCP
```

## Adding a new language

```python
from graphfocus.extractors.base import LanguageExtractor, ExtractionResult

class MyLanguageExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "mylanguage"

    @property
    def extensions(self) -> set[str]:
        return {".ml", ".mli"}

    def extract(self, path: Path) -> ExtractionResult:
        # Your extraction logic using tree-sitter or regex
        ...
```

Register the class in [graphfocus/extractors/registry.py](graphfocus/extractors/registry.py) and add a test + fixture. See [CONVENTIONS.md](CONVENTIONS.md) for details.

## Development

```bash
make dev      # install with all extras
make test     # run pytest
make lint     # ruff check
make format   # ruff format
make serve    # start the FastAPI server
```

## Release

Publishing to PyPI is automated via GitHub Actions and PyPI Trusted Publishing — no API tokens are stored in this repo.

**One-time setup on pypi.org** (project owner only):
1. Log in to https://pypi.org and go to the project (after the first manual upload, or use a pending publisher).
2. *Manage → Publishing → Add a new publisher* → fill in:
   - Owner: `bamc300`
   - Repository name: `graphfocus`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

**Each release**:
```bash
# 1. bump the version in pyproject.toml
# 2. commit + tag
git commit -am "chore: bump version to 0.2.0"
git tag v0.2.0
git push && git push --tags
# 3. the publish.yml workflow runs automatically and uploads to PyPI
```

## License

MIT
