"""R extractor using regex.

R doesn't have native classes in the OO sense (S3/S4 exist but are
loosely typed). The useful structure to extract is:

  * ``library(pkg)`` / ``require(pkg)`` / ``requireNamespace("pkg")``
    as imports
  * ``source("file.R")`` as imports
  * Top-level function assignments: ``name <- function(args) {…}`` or
    ``name = function(args) {…}``
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

# library(dplyr), require(magrittr), requireNamespace("foo")
_LIBRARY = re.compile(
    r"""(?:library|require|requireNamespace)\s*\(\s*['"]?([\w.]+)['"]?\s*\)""",
)

# source("utils.R")
_SOURCE = re.compile(r"""source\s*\(\s*['"]([^'"]+)['"]""")

# Top-level: <name> <- function(...) ...   or   <name> = function(...) ...
_FUNCTION_ASSIGN = re.compile(
    r"""^[ \t]*([a-zA-Z_][\w.]*)\s*(?:<-|=)\s*function\s*\(""",
    re.MULTILINE,
)


class RExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "r"

    @property
    def extensions(self) -> set[str]:
        return {".r", ".R"}

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
                    source_location=f"L{line}", language="r", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src, tgt, relation, line, confidence="EXTRACTED"):
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        for m in _LIBRARY.finditer(source):
            pkg = m.group(1)
            add_edge(file_nid, make_id(pkg), "imports", line_of(m.start()))

        for m in _SOURCE.finditer(source):
            target = m.group(1).split("/")[-1].rsplit(".", 1)[0]
            add_edge(file_nid, make_id(target), "imports", line_of(m.start()))

        for m in _FUNCTION_ASSIGN.finditer(source):
            fname = m.group(1)
            line = line_of(m.start())
            fnid = make_id(stem, fname)
            add_node(fnid, f"{fname}()", line, "function")
            add_edge(file_nid, fnid, "contains", line)

        return ExtractionResult(nodes=nodes, edges=edges)
