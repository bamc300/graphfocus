# GraphFocus

**Turn any folder of code into a queryable knowledge graph.** Multi-language AST extraction with plugin architecture, designed to feed AI coding tools (Claude Desktop, Trae AI, Cursor, Windsurf) with focused, token-efficient context via MCP.

## Why

Most code intelligence tools either parse only one language (so a fullstack Spring Boot + Vue project becomes a black box) or shovel raw files to an LLM until you blow your context window. GraphFocus extracts a **deterministic** knowledge graph via tree-sitter ASTs across **19 languages**, links cross-language references (e.g. `@Entity OrderEntity` ↔ SQL `orders` table), and exposes it to AI tools so the model can ask `find_callers("validate")` instead of grepping the whole repo.

## Features

- 🌳 **19 languages with dedicated extractors** — Python, Java, TypeScript/JavaScript/React, Vue, C#, Go, Kotlin, Rust, Swift, Ruby, PHP, Scala, Lua, C, C++, Dart, R, SQL, PL/SQL
- 🔌 **Plugin architecture** — Add new languages by implementing a single interface
- 🔗 **Cross-language linker** — Java/C# `@Entity`/`@Table` automatically wired to SQL/PL-SQL tables
- 🤖 **MCP server** — Plug into any MCP-compatible AI tool (Trae, Cursor, Claude Desktop…) so the LLM queries the graph directly
- 📁 **Multiple outputs** — Interactive HTML viz, JSON, Markdown report, Obsidian vault, **AI_SUMMARY.md** (dense LLM context)
- ⚡ **Smart caching** — SQLite-based, only re-processes changed files
- 🚀 **FastAPI server** — REST endpoints to query the graph from any tool
- 🧠 **Optional LLM enrichment** — Use Claude/GPT to extract semantic relationships from docs and images

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
graphfocus find UserService                  # search by label or id
graphfocus neighbors userservice_user 2      # explore neighborhood
graphfocus callers validate                  # who calls validate()?
graphfocus languages                         # list active extractors
```

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

## License

MIT
