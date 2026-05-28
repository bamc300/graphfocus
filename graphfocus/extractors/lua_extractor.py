"""Lua AST extractor using tree-sitter.

Lua doesn't have a native class concept; idiomatic code uses tables and
``function Module.method(…)``. We extract:

  * ``require("foo")`` calls as imports
  * Top-level ``function name(…)`` and ``local function name(…)``
  * Module-style methods ``function Mod.method(…)`` — the ``Mod`` is
    recorded as a synthetic module node and the method is attached to it
  * Call graph
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


class LuaExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "lua"

    @property
    def extensions(self) -> set[str]:
        return {".lua"}

    def __init__(self) -> None:
        import tree_sitter_lua as tslua
        from tree_sitter import Language, Parser
        self._language = Language(tslua.language())
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
        function_bodies: list[tuple[str, object]] = []

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
                    source_location=f"L{line}", language="lua", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src, tgt, relation, line, confidence="EXTRACTED"):
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        # Pass 1: discover requires anywhere in the tree.
        def find_requires(node):
            if node.type == "function_call":
                callee = first(node, ("identifier",))
                if callee is not None and _text(callee) == "require":
                    args = first(node, ("arguments",)) or node
                    for sub in args.children:
                        if sub.type == "string":
                            content = first(sub, ("string_content",))
                            module = _text(content if content else sub).strip("\"'")
                            add_edge(file_nid, make_id(module.split("/")[-1]),
                                     "imports", node.start_point[0] + 1)
            for child in node.children:
                find_requires(child)

        find_requires(tree.root_node)

        # Pass 2: top-level function declarations.
        for child in tree.root_node.children:
            if child.type != "function_declaration":
                continue
            line = child.start_point[0] + 1

            # `function Mod.method(...)` — name is a dot_index_expression.
            name_node = None
            container_name = None
            for sub in child.children:
                if sub.type == "identifier":
                    name_node = sub
                    break
                if sub.type == "dot_index_expression":
                    # children: identifier (container) . identifier (method)
                    idents = [c for c in sub.children if c.type == "identifier"]
                    if len(idents) >= 2:
                        container_name = _text(idents[0])
                        name_node = idents[-1]
                    break

            if name_node is None:
                continue
            fname = _text(name_node)

            if container_name:
                container_nid = make_id(stem, container_name)
                if container_nid not in seen:
                    add_node(container_nid, container_name, line, "module")
                    add_edge(file_nid, container_nid, "contains", line)
                fnid = make_id(container_nid, fname)
                add_node(fnid, f"{fname}()", line, "method")
                add_edge(container_nid, fnid, "method", line)
            else:
                fnid = make_id(stem, fname)
                add_node(fnid, f"{fname}()", line, "function")
                add_edge(file_nid, fnid, "contains", line)

            body = first(child, ("block",))
            if body:
                function_bodies.append((fnid, body))

        # Call graph
        label_to_nid = {n.label.strip("()").lstrip(".").lower(): n.id for n in nodes}
        seen_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid):
            if node.type == "function_declaration":
                return
            if node.type == "function_call":
                callee = None
                # Either identifier or dot_index_expression
                if node.children:
                    head = node.children[0]
                    if head.type == "identifier":
                        callee = _text(head)
                    elif head.type == "dot_index_expression":
                        idents = [c for c in head.children if c.type == "identifier"]
                        if idents:
                            callee = _text(idents[-1])
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

        for caller_nid, body in function_bodies:
            walk_calls(body, caller_nid)

        return ExtractionResult(nodes=nodes, edges=edges)
