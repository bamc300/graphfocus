"""PL/SQL extractor using tree-sitter or regex fallback.

Extracts:
  - Package specifications and bodies
  - Procedures and functions (standalone and within packages)
  - Triggers
  - Cursors
  - Table references (from DML: SELECT, INSERT, UPDATE, DELETE)
  - Exception handlers
  - Variable declarations with types

Note: tree-sitter-sql handles standard SQL. For PL/SQL-specific constructs
(packages, procedures, triggers), we use a regex-based fallback parser
since tree-sitter-plsql grammar availability varies.
"""

from __future__ import annotations

import re
from pathlib import Path

from graphfocus.extractors.base import (
    Edge,
    ExtractionResult,
    LanguageExtractor,
    Node,
    make_id,
)

# ── Regex patterns for PL/SQL constructs ──────────────────────────────────────

_PACKAGE_SPEC = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\s+(?:BODY\s+)?(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_PROCEDURE = re.compile(
    r"(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?PROCEDURE\s+(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_FUNCTION = re.compile(
    r"(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?FUNCTION\s+(\w+(?:\.\w+)?)\s*(?:\([^)]*\))?\s*RETURN\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)

_TRIGGER = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(\w+(?:\.\w+)?)\s+"
    r"(?:BEFORE|AFTER|INSTEAD\s+OF)\s+(?:INSERT|UPDATE|DELETE)(?:\s+OR\s+(?:INSERT|UPDATE|DELETE))*"
    r"\s+ON\s+(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_CURSOR = re.compile(
    r"CURSOR\s+(\w+)\s+IS\s+SELECT\b",
    re.IGNORECASE,
)

_TABLE_REF = re.compile(
    r"(?:FROM|JOIN|INTO|UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_VARIABLE_DECL = re.compile(
    r"(\w+)\s+(\w+(?:\.\w+)?(?:%(?:TYPE|ROWTYPE))?)\s*(?::=|;)",
    re.IGNORECASE,
)

_EXCEPTION_HANDLER = re.compile(
    r"WHEN\s+(\w+)\s+THEN",
    re.IGNORECASE,
)

_PROCEDURE_CALL = re.compile(
    r"(?:EXECUTE\s+IMMEDIATE|EXEC\s+)?\b(\w+(?:\.\w+)?)\s*\(",
    re.IGNORECASE,
)

# Tables to skip (common SQL keywords that look like table names)
_SKIP_TABLES = {"dual", "user", "date", "level", "rownum", "sysdate", "systimestamp"}


class PLSQLExtractor(LanguageExtractor):
    """Extract PL/SQL code structure using regex-based parsing.

    Handles Oracle PL/SQL constructs: packages, procedures, functions,
    triggers, cursors, and table references.
    """

    @property
    def language_name(self) -> str:
        return "plsql"

    @property
    def extensions(self) -> set[str]:
        return {".pls", ".pks", ".pkb", ".pck", ".fnc", ".prc", ".trg"}

    def extract(self, path: Path) -> ExtractionResult:
        try:
            source = path.read_text(errors="ignore")
        except Exception as e:
            return ExtractionResult(errors=[f"Read error: {e}"])

        stem = path.stem
        str_path = str(path)
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen_ids: set[str] = set()
        referenced_tables: set[str] = set()

        def add_node(nid: str, label: str, line: int, kind: str, **meta) -> None:
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append(Node(
                    id=nid,
                    label=label,
                    file_type="code",
                    source_file=str_path,
                    source_location=f"L{line}",
                    language="plsql",
                    kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src: str, tgt: str, relation: str, line: int = 0, confidence: str = "EXTRACTED") -> None:
            edges.append(Edge(
                source=src,
                target=tgt,
                relation=relation,
                confidence=confidence,
                source_file=str_path,
                source_location=f"L{line}" if line else None,
            ))

        # File-level node — prefixed so it can never collide with a same-named symbol
        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        # ── Packages ──────────────────────────────────────────────────
        for match in _PACKAGE_SPEC.finditer(source):
            pkg_name = match.group(1)
            line = source[:match.start()].count("\n") + 1
            is_body = "BODY" in match.group(0).upper()
            kind = "package_body" if is_body else "package_spec"
            pkg_nid = make_id(pkg_name)
            add_node(pkg_nid, pkg_name, line, kind)
            add_edge(file_nid, pkg_nid, "contains", line)

        # ── Procedures ────────────────────────────────────────────────
        for match in _PROCEDURE.finditer(source):
            proc_name = match.group(1)
            line = source[:match.start()].count("\n") + 1
            proc_nid = make_id(proc_name)
            add_node(proc_nid, f"{proc_name}()", line, "procedure")
            add_edge(file_nid, proc_nid, "contains", line)

        # ── Functions ─────────────────────────────────────────────────
        for match in _FUNCTION.finditer(source):
            func_name = match.group(1)
            return_type = match.group(2)
            line = source[:match.start()].count("\n") + 1
            func_nid = make_id(func_name)
            add_node(func_nid, f"{func_name}()", line, "function", return_type=return_type)
            add_edge(file_nid, func_nid, "contains", line)

        # ── Triggers ──────────────────────────────────────────────────
        for match in _TRIGGER.finditer(source):
            trigger_name = match.group(1)
            table_name = match.group(2)
            line = source[:match.start()].count("\n") + 1
            trigger_nid = make_id(trigger_name)
            table_nid = make_id(table_name)
            add_node(trigger_nid, trigger_name, line, "trigger")
            add_edge(file_nid, trigger_nid, "contains", line)
            if table_nid not in seen_ids:
                add_node(table_nid, table_name, line, "table")
            add_edge(trigger_nid, table_nid, "triggers_on", line)
            referenced_tables.add(table_name.lower())

        # ── Cursors ───────────────────────────────────────────────────
        for match in _CURSOR.finditer(source):
            cursor_name = match.group(1)
            line = source[:match.start()].count("\n") + 1
            cursor_nid = make_id(cursor_name)
            add_node(cursor_nid, cursor_name, line, "cursor")
            add_edge(file_nid, cursor_nid, "contains", line)

        # ── Table references ──────────────────────────────────────────
        for match in _TABLE_REF.finditer(source):
            table_name = match.group(1)
            if table_name.lower() in _SKIP_TABLES:
                continue
            line = source[:match.start()].count("\n") + 1
            table_nid = make_id(table_name)
            if table_nid not in seen_ids:
                add_node(table_nid, table_name, line, "table")
            referenced_tables.add(table_name.lower())

        # Connect procedures/functions to tables they reference
        for proc_node in [n for n in nodes if n.kind in ("procedure", "function")]:
            for table_name in referenced_tables:
                table_nid = make_id(table_name)
                if table_nid in seen_ids:
                    add_edge(proc_node.id, table_nid, "references_table", confidence="INFERRED")

        return ExtractionResult(nodes=nodes, edges=edges)
