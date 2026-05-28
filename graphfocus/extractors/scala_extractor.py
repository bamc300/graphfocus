"""Scala AST extractor using tree-sitter.

Extracts:
  * Package and import declarations
  * Traits, classes (incl. case classes), objects
  * Functions (``def``)
  * Vals
"""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import (
    Edge,
    ExtractionResult,
    LanguageExtractor,
    Node,
    make_id,
)


class ScalaExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "scala"

    @property
    def extensions(self) -> set[str]:
        return {".scala", ".sc"}

    def __init__(self) -> None:
        import tree_sitter_scala as tssc
        from tree_sitter import Language, Parser
        self._language = Language(tssc.language())
        self._parser = Parser(self._language)

    def extract(self, path: Path) -> ExtractionResult:
        try:
            source = path.read_bytes()
            tree = self._parser.parse(source)
        except Exception as e:
            return ExtractionResult(errors=[f"Parse error: {e}"])

        stem = path.stem
        str_path = str(path)
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen: set[str] = set()

        def _text(n) -> str:
            return source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")

        def first(node, types):
            for ch in node.children:
                if ch.type in types:
                    return ch
            return None

        def add_node(nid, label, line, kind, **meta):
            if nid not in seen:
                seen.add(nid)
                nodes.append(Node(
                    id=nid, label=label, file_type="code", source_file=str_path,
                    source_location=f"L{line}", language="scala", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src, tgt, relation, line, confidence="EXTRACTED"):
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        def walk(node, parent_nid=None):
            t = node.type
            line = node.start_point[0] + 1

            if t == "import_declaration":
                # Pull the rightmost identifier in the dotted path.
                last_ident = None
                for child in node.children:
                    if child.type == "identifier":
                        last_ident = child
                if last_ident is not None:
                    add_edge(file_nid, make_id(_text(last_ident)),
                             "imports", line)
                return

            if t == "trait_definition":
                name_node = first(node, ("identifier",))
                if name_node is not None:
                    name = _text(name_node)
                    nid = make_id(stem, name)
                    add_node(nid, name, line, "trait")
                    add_edge(parent_nid or file_nid, nid, "contains", line)
                    body = first(node, ("template_body",))
                    if body:
                        for child in body.children:
                            walk(child, parent_nid=nid)
                return

            if t == "class_definition":
                # `case class X` has a `case` keyword child.
                is_case = any(c.type == "case" for c in node.children)
                name_node = first(node, ("identifier",))
                if name_node is not None:
                    name = _text(name_node)
                    nid = make_id(stem, name)
                    add_node(nid, name, line, "case_class" if is_case else "class")
                    add_edge(parent_nid or file_nid, nid, "contains", line)
                    body = first(node, ("template_body",))
                    if body:
                        for child in body.children:
                            walk(child, parent_nid=nid)
                return

            if t == "object_definition":
                name_node = first(node, ("identifier",))
                if name_node is not None:
                    name = _text(name_node)
                    nid = make_id(stem, name)
                    add_node(nid, name, line, "object")
                    add_edge(parent_nid or file_nid, nid, "contains", line)
                    body = first(node, ("template_body",))
                    if body:
                        for child in body.children:
                            walk(child, parent_nid=nid)
                return

            if t in ("function_definition", "function_declaration"):
                name_node = first(node, ("identifier",))
                if name_node is None:
                    return
                fname = _text(name_node)
                kind = "method" if parent_nid else "function"
                if parent_nid:
                    fnid = make_id(parent_nid, fname)
                    relation = "method"
                    container = parent_nid
                else:
                    fnid = make_id(stem, fname)
                    relation = "contains"
                    container = file_nid
                add_node(fnid, f"{fname}()", line, kind)
                add_edge(container, fnid, relation, line)
                return

            if t == "val_definition" and parent_nid:
                name_node = first(node, ("identifier",))
                if name_node is not None:
                    vname = _text(name_node)
                    vnid = make_id(parent_nid, vname)
                    add_node(vnid, vname, line, "val")
                    add_edge(parent_nid, vnid, "has_val", line)

            for child in node.children:
                walk(child, parent_nid=parent_nid)

        walk(tree.root_node)

        return ExtractionResult(nodes=nodes, edges=edges)
