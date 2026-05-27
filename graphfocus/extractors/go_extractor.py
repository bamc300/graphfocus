"""Go AST extractor using tree-sitter.

Extracts:
  * Package declaration (one node per file)
  * Imports
  * Struct and interface type declarations
  * Top-level functions
  * Methods (functions with a receiver) — wired to their receiver type
  * Call graph (calls within function bodies)
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


class GoExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "go"

    @property
    def extensions(self) -> set[str]:
        return {".go"}

    def __init__(self) -> None:
        import tree_sitter_go as tsgo
        from tree_sitter import Language, Parser

        self._language = Language(tsgo.language())
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
        seen_ids: set[str] = set()
        function_bodies: list[tuple[str, object]] = []

        def _text(node) -> str:
            return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

        def add_node(nid: str, label: str, line: int, kind: str, **meta) -> None:
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append(Node(
                    id=nid, label=label, file_type="code",
                    source_file=str_path, source_location=f"L{line}",
                    language="go", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src: str, tgt: str, relation: str, line: int,
                     confidence: str = "EXTRACTED") -> None:
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        for node in tree.root_node.children:
            t = node.type

            # Package clause
            if t == "package_clause":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    # tree-sitter-go: package_identifier is the 2nd child
                    for child in node.children:
                        if child.type == "package_identifier":
                            name_node = child
                            break
                if name_node:
                    pkg_name = _text(name_node)
                    pkg_nid = make_id("pkg", pkg_name)
                    add_node(pkg_nid, pkg_name, node.start_point[0] + 1, "package")
                    add_edge(file_nid, pkg_nid, "package", node.start_point[0] + 1)

            # Imports — can be a single spec or wrapped in import_spec_list.
            elif t == "import_declaration":
                specs = list(_iter(node, "import_spec"))
                for spec_list in _iter(node, "import_spec_list"):
                    specs.extend(_iter(spec_list, "import_spec"))
                for spec in specs:
                    path_node = spec.child_by_field_name("path")
                    if path_node is None:
                        for child in spec.children:
                            if child.type == "interpreted_string_literal":
                                path_node = child
                                break
                    if path_node is not None:
                        module = _text(path_node).strip("\"'`")
                        add_edge(file_nid, make_id(module.split("/")[-1]),
                                 "imports", node.start_point[0] + 1)

            # type Foo struct {…} / type Foo interface {…}
            elif t == "type_declaration":
                for spec in _iter(node, "type_spec"):
                    name_node = spec.child_by_field_name("name")
                    type_node = spec.child_by_field_name("type")
                    if not (name_node and type_node):
                        continue
                    tname = _text(name_node)
                    line = spec.start_point[0] + 1
                    if type_node.type == "struct_type":
                        kind = "struct"
                    elif type_node.type == "interface_type":
                        kind = "interface"
                    else:
                        kind = "type"
                    nid = make_id(stem, tname)
                    add_node(nid, tname, line, kind)
                    add_edge(file_nid, nid, "contains", line)

                    # Struct fields
                    if type_node.type == "struct_type":
                        for field_list in _iter(type_node, "field_declaration_list"):
                            for fdecl in _iter(field_list, "field_declaration"):
                                # Each field_declaration can declare multiple names.
                                for ident in fdecl.children:
                                    if ident.type == "field_identifier":
                                        fname = _text(ident)
                                        fnid = make_id(nid, fname)
                                        add_node(fnid, fname, line, "field")
                                        add_edge(nid, fnid, "has_field", line)

            # Top-level function
            elif t == "function_declaration":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    continue
                fname = _text(name_node)
                line = node.start_point[0] + 1
                fnid = make_id(stem, fname)
                add_node(fnid, f"{fname}()", line, "function")
                add_edge(file_nid, fnid, "contains", line)
                body = node.child_by_field_name("body")
                if body:
                    function_bodies.append((fnid, body))

            # Method declaration: func (r *Receiver) Foo() {…}
            elif t == "method_declaration":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    continue
                mname = _text(name_node)
                line = node.start_point[0] + 1
                # Identify receiver type
                receiver = node.child_by_field_name("receiver")
                rcv_type: str | None = None
                if receiver is not None:
                    for child in receiver.children:
                        if child.type == "parameter_declaration":
                            type_node = child.child_by_field_name("type")
                            if type_node is not None:
                                raw = _text(type_node).lstrip("*")
                                rcv_type = raw.split(".")[-1]
                                break
                parent_nid = make_id(stem, rcv_type) if rcv_type else file_nid
                if rcv_type and parent_nid not in seen_ids:
                    add_node(parent_nid, rcv_type, line, "struct")
                mnid = make_id(parent_nid, mname)
                add_node(mnid, f"{mname}()", line, "method")
                add_edge(parent_nid, mnid, "method", line)
                body = node.child_by_field_name("body")
                if body:
                    function_bodies.append((mnid, body))

        # ── Call-graph pass ───────────────────────────────────────────
        label_to_nid: dict[str, str] = {}
        for n in nodes:
            normalised = n.label.strip("()").lstrip(".")
            label_to_nid[normalised.lower()] = n.id

        seen_call_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid: str) -> None:
            if node.type in ("function_declaration", "method_declaration"):
                return
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                callee: str | None = None
                if fn is not None:
                    if fn.type == "identifier":
                        callee = _text(fn)
                    elif fn.type == "selector_expression":
                        field = fn.child_by_field_name("field")
                        if field is not None:
                            callee = _text(field)
                if callee:
                    tgt = label_to_nid.get(callee.lower())
                    if tgt and tgt != caller_nid:
                        pair = (caller_nid, tgt)
                        if pair not in seen_call_pairs:
                            seen_call_pairs.add(pair)
                            edges.append(Edge(
                                source=caller_nid, target=tgt,
                                relation="calls", confidence="INFERRED",
                                source_file=str_path,
                                source_location=f"L{node.start_point[0] + 1}",
                                weight=0.8,
                            ))
            for child in node.children:
                walk_calls(child, caller_nid)

        for caller_nid, body_node in function_bodies:
            walk_calls(body_node, caller_nid)

        return ExtractionResult(nodes=nodes, edges=edges)


def _iter(node, type_name: str):
    """Yield direct children of ``node`` matching ``type_name``."""
    for child in node.children:
        if child.type == type_name:
            yield child
