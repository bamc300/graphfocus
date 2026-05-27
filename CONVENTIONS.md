# GraphFocus Development Conventions

## Code Style

- **Python 3.11+** with type hints
- **ruff** for linting and formatting (`make lint`, `make format`)
- Line length: 100 characters
- Use `from __future__ import annotations` for forward references
- Use dataclasses for data containers, not dicts
- Prefer composition over inheritance (except extractors which MUST inherit)

## Naming

| Item | Convention | Example |
|---|---|---|
| Extractor class | `<Language>Extractor` | `JavaExtractor`, `PLSQLExtractor` |
| Extractor file | `<language>_extractor.py` | `java_extractor.py` |
| Test file | `test_<language>_extractor.py` | `test_java_extractor.py` |
| Fixture dir | `tests/fixtures/<language>/` | `tests/fixtures/java/` |
| API route file | `routes/<resource>.py` | `routes/analyze.py` |
| Node kinds | lowercase singular | `class`, `function`, `table`, `procedure` |
| Edge relations | lowercase with underscores | `imports`, `inherits`, `foreign_key` |
| Node IDs | `make_id(stem, name)` | `"userservice_findbyid"` |

## Extractor Conventions

### What to extract per language

| Language | Extract |
|---|---|
| **Python** | modules, classes, functions, methods, imports, inheritance, calls |
| **Java** | packages, classes, interfaces, enums, methods, fields, imports, annotations, inheritance, calls |
| **PL/SQL** | packages (spec+body), procedures, functions, triggers, cursors, table references |
| **C#** | namespaces, classes, interfaces, structs, enums, methods, properties, using, attributes |
| **SQL** | tables, columns, foreign keys, indexes, views, references |

### Edge relation types

| Relation | Meaning | Confidence |
|---|---|---|
| `contains` | Parent contains child (file→class, class→method) | EXTRACTED |
| `imports` / `imports_from` | Import statement | EXTRACTED |
| `using` | C# using directive | EXTRACTED |
| `inherits` / `extends` | Class inheritance | EXTRACTED |
| `implements` | Interface implementation | EXTRACTED |
| `method` | Class has method | EXTRACTED |
| `has_field` / `has_property` | Class has field/property | EXTRACTED |
| `has_column` | Table has column | EXTRACTED |
| `foreign_key` / `references` | FK relationship | EXTRACTED |
| `indexes` | Index on table | EXTRACTED |
| `defines` | File defines table/view | EXTRACTED |
| `triggers_on` | Trigger on table | EXTRACTED |
| `references_table` | Procedure references table | INFERRED |
| `calls` | Function/method call | INFERRED |

### Node kind values

`module`, `file`, `class`, `interface`, `struct`, `enum`, `function`, `method`, `field`, `property`,
`namespace`, `table`, `column`, `view`, `index`, `package_spec`, `package_body`, `procedure`,
`function` (PL/SQL), `trigger`, `cursor`

## Testing Conventions

- Use `pytest` with fixtures from `conftest.py`
- Every extractor needs at minimum:
  - Test it extracts nodes (non-empty result)
  - Test it sets `language` on all nodes
  - Test it produces no errors on valid input
  - Test specific constructs (classes, methods, imports, etc.)
- Test fixtures should be representative but small (~30-50 lines)

## Git Conventions

- Branch naming: `feature/<name>`, `fix/<name>`, `lang/<language>`
- Commit messages: `feat: add Go extractor`, `fix: handle nested classes in Java`
- Always run `make test` before committing
