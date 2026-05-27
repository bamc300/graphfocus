# GraphFocus — Agent Configuration

> This file provides context for AI coding agents (Trae AI, Cursor, Windsurf, Codex, and others).

## Project Overview

GraphFocus is a **multi-language code knowledge graph generator**. It analyzes codebases using AST parsing (tree-sitter) and produces queryable knowledge graphs with community detection.

**Tech stack:** Python 3.11+, tree-sitter, NetworkX, graspologic, Click, FastAPI

## Architecture

```
graphfocus/
├── extractors/      ← Plugin system: one extractor per language (19 total)
│   ├── base.py      ← LanguageExtractor ABC + Node/Edge dataclasses
│   ├── registry.py  ← Auto-discovery of available extractors
│   └── <lang>_extractor.py  ← python, java, csharp, sql, plsql, typescript,
│                              vue, go, kotlin, rust, ruby, php, swift,
│                              c, cpp, scala, lua, dart, r
├── detect/          ← File classification + sensitive-file filter
├── graph/           ← NetworkX builder, merger, cross-language linker, Leiden
├── cache/           ← SQLite cache for incremental --update
├── output/          ← JSON, HTML viz, Markdown report, Obsidian, AI_SUMMARY
├── api/             ← FastAPI REST API
├── semantic/        ← Optional LLM extraction
├── mcp_server.py    ← MCP server for AI tool integration
├── cli.py           ← Click CLI
└── config.py        ← Configuration
```

## Key Rules

1. **Extractors use the plugin pattern** — inherit from `LanguageExtractor`, implement `language_name`, `extensions`, `extract()`
2. **Use `make_id()` for node IDs** — never generate IDs manually
3. **Every node needs `language` and `kind`** — e.g., language="java", kind="class"
4. **Every edge needs `confidence`** — EXTRACTED, INFERRED, or AMBIGUOUS
5. **Tree-sitter extractors must fail gracefully** if the grammar is missing
6. **Tests follow the pattern** `tests/test_<language>_extractor.py` with fixtures in `tests/fixtures/<language>/`

## Development

```bash
make dev          # Install with all deps
make test         # Run tests
make lint         # Lint with ruff
make format       # Format with ruff
make serve        # Start FastAPI server
```

## Adding a New Language

1. Create `graphfocus/extractors/<lang>_extractor.py`
2. Register in `registry.py`
3. Add extension in `detect/detector.py`
4. Create test fixture + tests
5. Add tree-sitter dependency to `pyproject.toml` (or use regex for languages
   without a grammar wheel, like SQL/PL/SQL/Dart/R)
