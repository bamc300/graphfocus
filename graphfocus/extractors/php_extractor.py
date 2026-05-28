"""PHP AST extractor using tree-sitter.

Extracts:
  * Namespace declarations
  * ``use`` namespace imports
  * Interfaces, classes (with ``extends`` and ``implements``), traits
  * Methods and top-level functions
  * Properties (declared with visibility modifiers)
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


class PHPExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "php"

    @property
    def extensions(self) -> set[str]:
        return {".php", ".phtml"}

    def __init__(self) -> None:
        import tree_sitter_php as tsphp
        from tree_sitter import Language, Parser
        self._language = Language(tsphp.language_php())
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
                    source_location=f"L{line}", language="php", kind=kind,
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

            if t == "namespace_definition":
                name_node = first(node, ("namespace_name",))
                if name_node is not None:
                    ns = _text(name_node).replace("\\", ".")
                    line = node.start_point[0] + 1
                    nsnid = make_id(ns)
                    add_node(nsnid, ns, line, "namespace")
                    add_edge(file_nid, nsnid, "namespace", line)

            elif t == "namespace_use_declaration":
                # use Foo\Bar\Baz; — emit imports edge to last segment
                for clause in node.children:
                    if clause.type == "namespace_use_clause":
                        qname = first(clause, ("qualified_name",)) or first(clause, ("name",))
                        if qname is not None:
                            last = _text(qname).split("\\")[-1]
                            add_edge(file_nid, make_id(last),
                                     "imports", node.start_point[0] + 1)

            elif t in ("class_declaration", "interface_declaration", "trait_declaration"):
                name_node = first(node, ("name",))
                if name_node is None:
                    return
                cname = _text(name_node)
                line = node.start_point[0] + 1
                kind = {
                    "class_declaration": "class",
                    "interface_declaration": "interface",
                    "trait_declaration": "trait",
                }[t]
                cnid = make_id(stem, cname)
                add_node(cnid, cname, line, kind)
                add_edge(parent_nid or file_nid, cnid, "contains", line)

                # extends / implements clauses
                for child in node.children:
                    if child.type == "base_clause":
                        for sub in child.children:
                            if sub.type in ("name", "qualified_name"):
                                base = _text(sub).split("\\")[-1]
                                bnid = make_id(base)
                                if bnid not in seen:
                                    add_node(bnid, base, line, "class")
                                add_edge(cnid, bnid, "extends", line)
                    elif child.type == "class_interface_clause":
                        for sub in child.children:
                            if sub.type in ("name", "qualified_name"):
                                iface = _text(sub).split("\\")[-1]
                                inid = make_id(iface)
                                if inid not in seen:
                                    add_node(inid, iface, line, "interface")
                                add_edge(cnid, inid, "implements", line)

                body = first(node, ("declaration_list",))
                if body:
                    for child in body.children:
                        walk(child, parent_nid=cnid)
                return

            elif t == "method_declaration":
                name_node = first(node, ("name",))
                if name_node is None:
                    return
                mname = _text(name_node)
                line = node.start_point[0] + 1
                mnid = make_id(parent_nid or stem, mname)
                add_node(mnid, f"{mname}()", line, "method")
                add_edge(parent_nid or file_nid, mnid, "method", line)
                body = first(node, ("compound_statement",))
                if body:
                    method_bodies.append((mnid, body))
                return

            elif t == "function_definition":
                name_node = first(node, ("name",))
                if name_node is None:
                    return
                fname = _text(name_node)
                line = node.start_point[0] + 1
                fnid = make_id(stem, fname)
                add_node(fnid, f"{fname}()", line, "function")
                add_edge(file_nid, fnid, "contains", line)
                body = first(node, ("compound_statement",))
                if body:
                    method_bodies.append((fnid, body))
                return

            elif t == "property_declaration" and parent_nid:
                for child in node.children:
                    if child.type == "property_element":
                        var = first(child, ("variable_name",))
                        if var is not None:
                            pname = _text(var).lstrip("$")
                            line = node.start_point[0] + 1
                            pnid = make_id(parent_nid, pname)
                            add_node(pnid, pname, line, "property")
                            add_edge(parent_nid, pnid, "has_property", line)

            for child in node.children:
                walk(child, parent_nid=parent_nid)

        walk(tree.root_node)

        # Call graph
        label_to_nid = {n.label.strip("()").lstrip(".").lower(): n.id for n in nodes}
        seen_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid):
            if node.type in ("function_definition", "method_declaration"):
                return
            if node.type in ("function_call_expression", "member_call_expression",
                             "scoped_call_expression"):
                # Find the callee name.
                callee: str | None = None
                name_node = node.child_by_field_name("name") or node.child_by_field_name("function")
                if name_node is not None:
                    callee = _text(name_node).lstrip("$")
                if not callee:
                    nm = first(node, ("name",))
                    if nm is not None:
                        callee = _text(nm)
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
