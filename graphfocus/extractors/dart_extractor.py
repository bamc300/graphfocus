"""Dart extractor using regex.

No standalone tree-sitter-dart wheel is published on PyPI, so we use the
same regex-based approach we already use for PL/SQL.  Extracts:

  * ``import`` and ``part``/``part of`` directives
  * Classes (with ``extends`` and ``implements``) and ``abstract class``
  * Mixins
  * Methods inside class bodies and top-level functions
"""

from __future__ import annotations

import re
from pathlib import Path

from graphfocus.extractors.base import (
    Edge, ExtractionResult, LanguageExtractor, Node, make_id,
)


# ── Patterns ──────────────────────────────────────────────────────────────────

_IMPORT = re.compile(
    r"""^\s*import\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# `class Foo`, `abstract class Foo`, `class Foo extends Bar implements Baz, Qux`
_CLASS = re.compile(
    r"""^\s*(abstract\s+)?class\s+(\w+)
        (?:\s+extends\s+([\w<>,\s]+?))?
        (?:\s+implements\s+([\w<>,\s]+?))?
        \s*\{""",
    re.MULTILINE | re.VERBOSE,
)

_MIXIN = re.compile(r"""^\s*mixin\s+(\w+)""", re.MULTILINE)

# Top-level function: returnType name(params) { … }  /  expression-body
# Skip lines starting with `class`, `enum`, etc.
_FUNCTION = re.compile(
    r"""^\s*(?:Future<[^>]+>|[\w<>,\s\?]+?)\s+(\w+)\s*\([^)]*\)\s*(?:async\s*)?(?:\{|=>)""",
    re.MULTILINE,
)

_DART_KEYWORDS = {
    "if", "for", "while", "switch", "return", "do", "try", "catch",
    "import", "library", "part", "class", "enum", "mixin", "extension",
}


class DartExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "dart"

    @property
    def extensions(self) -> set[str]:
        return {".dart"}

    def extract(self, path: Path) -> ExtractionResult:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ExtractionResult(errors=[f"Read error: {e}"])

        stem = path.stem
        str_path = str(path)
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen: set[str] = set()

        def line_of(idx: int) -> int:
            return source[:idx].count("\n") + 1

        def add_node(nid, label, line, kind, **meta):
            if nid not in seen:
                seen.add(nid)
                nodes.append(Node(
                    id=nid, label=label, file_type="code", source_file=str_path,
                    source_location=f"L{line}", language="dart", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src, tgt, relation, line, confidence="EXTRACTED"):
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        # Imports
        for m in _IMPORT.finditer(source):
            module = m.group(1)
            last = module.split("/")[-1].rsplit(".", 1)[0]
            add_edge(file_nid, make_id(last), "imports", line_of(m.start()))

        # Classes — also record their body spans for nested method extraction.
        class_spans: list[tuple[int, int, str]] = []  # (body_start, body_end, class_nid)
        for m in _CLASS.finditer(source):
            is_abstract = bool(m.group(1))
            cname = m.group(2)
            extends_chain = m.group(3) or ""
            implements_chain = m.group(4) or ""
            line = line_of(m.start())
            cnid = make_id(stem, cname)
            kind = "abstract_class" if is_abstract else "class"
            add_node(cnid, cname, line, kind)
            add_edge(file_nid, cnid, "contains", line)

            for base in _split_types(extends_chain):
                # Prefer an existing in-file node so kinds stay consistent.
                local = make_id(stem, base)
                if local in seen:
                    bnid = local
                else:
                    bnid = make_id(base)
                    if bnid not in seen:
                        add_node(bnid, base, line, "class")
                add_edge(cnid, bnid, "extends", line)
            for iface in _split_types(implements_chain):
                local = make_id(stem, iface)
                if local in seen:
                    inid = local
                else:
                    inid = make_id(iface)
                    if inid not in seen:
                        add_node(inid, iface, line, "interface")
                add_edge(cnid, inid, "implements", line)

            # Find matching closing brace for the class body.
            body_start = source.index("{", m.start())
            body_end = _matching_brace(source, body_start)
            if body_end > body_start:
                class_spans.append((body_start + 1, body_end, cnid))

        # Mixins (simple — no body extraction).
        for m in _MIXIN.finditer(source):
            mname = m.group(1)
            mnid = make_id(stem, mname)
            add_node(mnid, mname, line_of(m.start()), "mixin")
            add_edge(file_nid, mnid, "contains", line_of(m.start()))

        # Methods inside class bodies + top-level functions.
        # We scan _FUNCTION across the whole source and route each match
        # by checking which (if any) class span contains it.
        for m in _FUNCTION.finditer(source):
            fname = m.group(1)
            if fname in _DART_KEYWORDS:
                continue
            line = line_of(m.start())
            position = m.start()

            # Determine if this function lives inside a class body.
            container_nid = None
            for start, end, cnid in class_spans:
                if start <= position < end:
                    container_nid = cnid
                    break

            if container_nid is not None:
                fnid = make_id(container_nid, fname)
                if fnid in seen:
                    continue
                add_node(fnid, f"{fname}()", line, "method")
                add_edge(container_nid, fnid, "method", line)
            else:
                fnid = make_id(stem, fname)
                if fnid in seen:
                    continue
                add_node(fnid, f"{fname}()", line, "function")
                add_edge(file_nid, fnid, "contains", line)

        return ExtractionResult(nodes=nodes, edges=edges)


def _split_types(chain: str) -> list[str]:
    """Split ``Foo, Bar<X>, Baz`` into ``["Foo", "Bar", "Baz"]``."""
    out: list[str] = []
    for part in chain.split(","):
        name = part.strip().split("<")[0].strip()
        if name:
            out.append(name)
    return out


def _matching_brace(source: str, start: int) -> int:
    """Return the index of the ``}`` that closes the ``{`` at ``source[start]``.

    Naive — doesn't account for braces inside strings/comments, which is
    fine for our purposes since we only use this for class body bounds.
    """
    depth = 1
    i = start + 1
    while i < len(source) and depth > 0:
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else len(source)
