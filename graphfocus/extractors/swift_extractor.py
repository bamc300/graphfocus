"""Swift AST extractor using tree-sitter.

Extracts:
  * ``import`` declarations
  * Protocols (``protocol``)
  * Classes, structs, enums (the grammar uses ``class_declaration`` for
    all three — the first keyword child distinguishes them)
  * Functions, methods and ``init`` declarations
  * Properties (``let``/``var`` inside type bodies)
"""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import (
    Edge, ExtractionResult, LanguageExtractor, Node, make_id,
)


_TYPE_KEYWORDS = ("class", "struct", "enum", "actor")


class SwiftExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "swift"

    @property
    def extensions(self) -> set[str]:
        return {".swift"}

    def __init__(self) -> None:
        import tree_sitter_swift as tssw
        from tree_sitter import Language, Parser
        self._language = Language(tssw.language())
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
                    source_location=f"L{line}", language="swift", kind=kind,
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

            if t == "import_declaration":
                ident = first(node, ("identifier",))
                if ident is not None:
                    sub = first(ident, ("simple_identifier",)) or ident
                    name = _text(sub)
                    add_edge(file_nid, make_id(name), "imports", node.start_point[0] + 1)
                return

            if t == "protocol_declaration":
                name_node = first(node, ("type_identifier",))
                if name_node is None:
                    return
                pname = _text(name_node)
                line = node.start_point[0] + 1
                pnid = make_id(stem, pname)
                add_node(pnid, pname, line, "protocol")
                add_edge(file_nid, pnid, "contains", line)
                body = first(node, ("protocol_body",))
                if body:
                    for child in body.children:
                        walk(child, parent_nid=pnid)
                return

            if t == "class_declaration":
                # First keyword distinguishes class / struct / enum / actor.
                kw = next((c.type for c in node.children if c.type in _TYPE_KEYWORDS), "class")
                name_node = first(node, ("type_identifier",))
                if name_node is None:
                    return
                cname = _text(name_node)
                line = node.start_point[0] + 1
                cnid = make_id(stem, cname)
                kind = {"class": "class", "struct": "struct", "enum": "enum", "actor": "actor"}[kw]
                add_node(cnid, cname, line, kind)
                add_edge(parent_nid or file_nid, cnid, "contains", line)
                body = first(node, ("class_body", "enum_class_body", "actor_body"))
                if body:
                    for child in body.children:
                        walk(child, parent_nid=cnid)
                return

            if t in ("function_declaration", "protocol_function_declaration"):
                name_node = first(node, ("simple_identifier",))
                if name_node is None:
                    return
                fname = _text(name_node)
                line = node.start_point[0] + 1
                if parent_nid:
                    fnid = make_id(parent_nid, fname)
                    add_node(fnid, f"{fname}()", line, "method")
                    add_edge(parent_nid, fnid, "method", line)
                else:
                    fnid = make_id(stem, fname)
                    add_node(fnid, f"{fname}()", line, "function")
                    add_edge(file_nid, fnid, "contains", line)
                return

            if t == "init_declaration" and parent_nid:
                line = node.start_point[0] + 1
                inid = make_id(parent_nid, "init")
                add_node(inid, "init()", line, "method")
                add_edge(parent_nid, inid, "method", line)
                return

            if t == "property_declaration" and parent_nid:
                pat = first(node, ("pattern",))
                if pat is not None:
                    pname = _text(pat)
                    line = node.start_point[0] + 1
                    pnid = make_id(parent_nid, pname)
                    add_node(pnid, pname, line, "property")
                    add_edge(parent_nid, pnid, "has_property", line)

            for child in node.children:
                walk(child, parent_nid=parent_nid)

        walk(tree.root_node)

        return ExtractionResult(nodes=nodes, edges=edges)
