"""Ruby AST extractor using tree-sitter.

Extracts:
  * Modules (``module Users``)
  * Classes (with superclass via ``<``)
  * Methods (``def x``) and singleton/class methods (``def self.x``)
  * ``require`` / ``require_relative`` as imports
  * Call graph
"""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import (
    Edge, ExtractionResult, LanguageExtractor, Node, make_id,
)


class RubyExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "ruby"

    @property
    def extensions(self) -> set[str]:
        return {".rb"}

    def __init__(self) -> None:
        import tree_sitter_ruby as tsrb
        from tree_sitter import Language, Parser
        self._language = Language(tsrb.language())
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
        method_bodies: list[tuple[str, object]] = []

        def _text(n) -> str:
            return source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")

        def add_node(nid, label, line, kind, **meta):
            if nid not in seen:
                seen.add(nid)
                nodes.append(Node(
                    id=nid, label=label, file_type="code", source_file=str_path,
                    source_location=f"L{line}", language="ruby", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src, tgt, relation, line, confidence="EXTRACTED"):
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        def first(node, types):
            for ch in node.children:
                if ch.type in types:
                    return ch
            return None

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        def walk(node, parent_nid=None):
            t = node.type

            if t == "module":
                name_node = first(node, ("constant",))
                if name_node is None:
                    return
                mname = _text(name_node)
                line = node.start_point[0] + 1
                mnid = make_id(stem, mname)
                add_node(mnid, mname, line, "module")
                add_edge(parent_nid or file_nid, mnid, "contains", line)
                body = first(node, ("body_statement",))
                if body:
                    for child in body.children:
                        walk(child, parent_nid=mnid)
                return

            if t == "class":
                name_node = first(node, ("constant",))
                if name_node is None:
                    return
                cname = _text(name_node)
                line = node.start_point[0] + 1
                cnid = make_id(stem, cname)
                add_node(cnid, cname, line, "class")
                add_edge(parent_nid or file_nid, cnid, "contains", line)
                # Superclass: in `class Foo < Bar`, after the `<` token comes a constant.
                superclass = first(node, ("superclass",))
                if superclass is not None:
                    base_node = first(superclass, ("constant", "scope_resolution"))
                    if base_node is not None:
                        bname = _text(base_node).split("::")[-1]
                        bnid = make_id(bname)
                        if bnid not in seen:
                            add_node(bnid, bname, line, "class")
                        add_edge(cnid, bnid, "inherits", line)
                body = first(node, ("body_statement",))
                if body:
                    for child in body.children:
                        walk(child, parent_nid=cnid)
                return

            if t in ("method", "singleton_method"):
                name_node = first(node, ("identifier", "constant", "operator"))
                if name_node is None:
                    return
                mname = _text(name_node)
                line = node.start_point[0] + 1
                kind = "method" if parent_nid else "function"
                mnid = make_id(parent_nid or stem, mname)
                add_node(mnid, f"{mname}()", line, kind)
                relation = "method" if parent_nid else "contains"
                add_edge(parent_nid or file_nid, mnid, relation, line)
                body = first(node, ("body_statement",))
                if body:
                    method_bodies.append((mnid, body))
                return

            # require / require_relative
            if t == "call":
                receiver = first(node, ("identifier",))
                if receiver is not None and _text(receiver) in ("require", "require_relative"):
                    args = first(node, ("argument_list",))
                    if args is not None:
                        for arg in args.children:
                            if arg.type == "string":
                                content = first(arg, ("string_content",))
                                if content is not None:
                                    module = _text(content).split("/")[-1]
                                    add_edge(file_nid, make_id(module),
                                             "imports", node.start_point[0] + 1)

            for child in node.children:
                walk(child, parent_nid=parent_nid)

        walk(tree.root_node)

        # Call graph
        label_to_nid = {n.label.strip("()").lstrip("."): n.id for n in nodes}
        label_to_nid = {k.lower(): v for k, v in label_to_nid.items()}
        seen_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid):
            if node.type in ("method", "singleton_method"):
                return
            if node.type == "call":
                # method_call: receiver.method or just identifier
                method_node = node.child_by_field_name("method")
                callee = _text(method_node) if method_node is not None else None
                if callee is None:
                    ident = first(node, ("identifier",))
                    if ident is not None:
                        callee = _text(ident)
                if callee:
                    tgt = label_to_nid.get(callee.lower())
                    if tgt and tgt != caller_nid:
                        pair = (caller_nid, tgt)
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            edges.append(Edge(
                                source=caller_nid, target=tgt, relation="calls",
                                confidence="INFERRED", source_file=str_path,
                                source_location=f"L{node.start_point[0] + 1}",
                                weight=0.8,
                            ))
            for child in node.children:
                walk_calls(child, caller_nid)

        for caller_nid, body in method_bodies:
            walk_calls(body, caller_nid)

        return ExtractionResult(nodes=nodes, edges=edges)
