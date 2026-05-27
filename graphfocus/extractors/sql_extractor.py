"""SQL DDL extractor using regex-based parsing.

Extracts:
  - CREATE TABLE statements (columns, types, constraints)
  - Foreign key relationships
  - CREATE INDEX
  - CREATE VIEW (with table references)
  - ALTER TABLE (add column, add constraint)

Works with standard SQL, PostgreSQL, MySQL, and Oracle DDL syntax.
Also handles .sql files that contain DML (SELECT, INSERT, etc.) to
extract table references.
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

# ── Regex patterns for SQL DDL ────────────────────────────────────────────────

_CREATE_TABLE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+(?:\.\w+)?)\s*\(",
    re.IGNORECASE,
)

_COLUMN_DEF = re.compile(
    r"^\s+(\w+)\s+(\w+(?:\(\d+(?:,\s*\d+)?\))?)",
    re.MULTILINE,
)

_FK_INLINE = re.compile(
    r"REFERENCES\s+(\w+(?:\.\w+)?)\s*\((\w+)\)",
    re.IGNORECASE,
)

_FK_CONSTRAINT = re.compile(
    r"FOREIGN\s+KEY\s*\((\w+(?:\s*,\s*\w+)*)\)\s+REFERENCES\s+(\w+(?:\.\w+)?)\s*\((\w+(?:\s*,\s*\w+)*)\)",
    re.IGNORECASE,
)

_CREATE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_CREATE_VIEW = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+(\w+(?:\.\w+)?)\s+AS\s+(.*?)(?:;|$)",
    re.IGNORECASE | re.DOTALL,
)

_TABLE_REF = re.compile(
    r"(?:FROM|JOIN|INTO|UPDATE)\s+(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+(\w+(?:\.\w+)?)",
    re.IGNORECASE,
)

_PRIMARY_KEY = re.compile(
    r"PRIMARY\s+KEY\s*\(([^)]+)\)",
    re.IGNORECASE,
)

# SQL keywords to skip when they appear as table names
_SQL_KEYWORDS = {
    "set", "dual", "user", "date", "level", "rownum", "value", "values",
    "select", "insert", "update", "delete", "where", "order", "group",
    "having", "limit", "offset", "as", "on", "and", "or", "not",
    "null", "true", "false", "default", "constraint", "check",
}


class SQLExtractor(LanguageExtractor):
    """Extract SQL schema structure using regex-based parsing.

    Handles DDL (CREATE TABLE, views, indexes) and extracts
    table relationships from foreign keys.
    """

    @property
    def language_name(self) -> str:
        return "sql"

    @property
    def extensions(self) -> set[str]:
        return {".sql"}

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

        def add_node(nid: str, label: str, line: int, kind: str, **meta) -> None:
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append(Node(
                    id=nid,
                    label=label,
                    file_type="code",
                    source_file=str_path,
                    source_location=f"L{line}",
                    language="sql",
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

        # File-level node
        file_nid = make_id(stem)
        add_node(file_nid, path.name, 1, "file")

        # ── CREATE TABLE ──────────────────────────────────────────────
        for match in _CREATE_TABLE.finditer(source):
            table_name = match.group(1)
            if table_name.lower() in _SQL_KEYWORDS:
                continue
            line = source[:match.start()].count("\n") + 1
            table_nid = make_id(table_name)
            add_node(table_nid, table_name, line, "table")
            add_edge(file_nid, table_nid, "defines", line)

            # Find the matching closing paren for this CREATE TABLE
            start_paren = match.end() - 1
            depth = 1
            end_paren = start_paren + 1
            while end_paren < len(source) and depth > 0:
                if source[end_paren] == "(":
                    depth += 1
                elif source[end_paren] == ")":
                    depth -= 1
                end_paren += 1
            table_body = source[start_paren:end_paren]

            # Extract columns
            for col_match in _COLUMN_DEF.finditer(table_body):
                col_name = col_match.group(1)
                col_type = col_match.group(2)
                if col_name.upper() in ("PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK", "INDEX", "LIKE"):
                    continue
                col_nid = make_id(table_name, col_name)
                col_line = line + table_body[:col_match.start()].count("\n")
                add_node(col_nid, f"{table_name}.{col_name}", col_line, "column", data_type=col_type)
                add_edge(table_nid, col_nid, "has_column", col_line)

            # Extract FK references within table body
            for fk_match in _FK_INLINE.finditer(table_body):
                ref_table = fk_match.group(1)
                ref_nid = make_id(ref_table)
                if ref_nid not in seen_ids:
                    add_node(ref_nid, ref_table, line, "table")
                add_edge(table_nid, ref_nid, "references", line)

            for fk_match in _FK_CONSTRAINT.finditer(table_body):
                ref_table = fk_match.group(2)
                ref_nid = make_id(ref_table)
                if ref_nid not in seen_ids:
                    add_node(ref_nid, ref_table, line, "table")
                add_edge(table_nid, ref_nid, "foreign_key", line)

        # ── CREATE INDEX ──────────────────────────────────────────────
        for match in _CREATE_INDEX.finditer(source):
            index_name = match.group(1)
            table_name = match.group(2)
            line = source[:match.start()].count("\n") + 1
            index_nid = make_id(index_name)
            table_nid = make_id(table_name)
            add_node(index_nid, index_name, line, "index")
            if table_nid not in seen_ids:
                add_node(table_nid, table_name, line, "table")
            add_edge(index_nid, table_nid, "indexes", line)

        # ── CREATE VIEW ───────────────────────────────────────────────
        for match in _CREATE_VIEW.finditer(source):
            view_name = match.group(1)
            view_body = match.group(2)
            line = source[:match.start()].count("\n") + 1
            view_nid = make_id(view_name)
            add_node(view_nid, view_name, line, "view")
            add_edge(file_nid, view_nid, "defines", line)

            # Extract table references from view body
            for ref_match in _TABLE_REF.finditer(view_body):
                ref_table = ref_match.group(1)
                if ref_table.lower() in _SQL_KEYWORDS:
                    continue
                ref_nid = make_id(ref_table)
                if ref_nid not in seen_ids:
                    add_node(ref_nid, ref_table, line, "table")
                add_edge(view_nid, ref_nid, "references", line, confidence="EXTRACTED")

        # ── ALTER TABLE ───────────────────────────────────────────────
        for match in _ALTER_TABLE.finditer(source):
            table_name = match.group(1)
            table_nid = make_id(table_name)
            line = source[:match.start()].count("\n") + 1
            if table_nid not in seen_ids:
                add_node(table_nid, table_name, line, "table")

            # Look for FK constraints in ALTER TABLE
            alter_end = source.find(";", match.end())
            if alter_end == -1:
                alter_end = len(source)
            alter_body = source[match.end():alter_end]
            for fk_match in _FK_CONSTRAINT.finditer(alter_body):
                ref_table = fk_match.group(2)
                ref_nid = make_id(ref_table)
                if ref_nid not in seen_ids:
                    add_node(ref_nid, ref_table, line, "table")
                add_edge(table_nid, ref_nid, "foreign_key", line)

        return ExtractionResult(nodes=nodes, edges=edges)
