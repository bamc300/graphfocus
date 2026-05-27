"""C# AST extractor using tree-sitter.

Extracts:
  - Namespaces
  - Classes, interfaces, structs, enums (with inheritance)
  - Methods and properties
  - Fields
  - Using directives (imports)
  - Attributes ([ApiController], [HttpGet], etc.)
  - Call graph
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


class CSharpExtractor(LanguageExtractor):
    """Extract C# code structure using tree-sitter AST."""

    @property
    def language_name(self) -> str:
        return "csharp"

    @property
    def extensions(self) -> set[str]:
        return {".cs"}

    def __init__(self) -> None:
        import tree_sitter_c_sharp as tscsharp
        from tree_sitter import Language, Parser

        self._language = Language(tscsharp.language())
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
        method_bodies: list[tuple[str, object]] = []

        def _text(node) -> str:
            return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

        def add_node(nid: str, label: str, line: int, kind: str, **meta) -> None:
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append(Node(
                    id=nid,
                    label=label,
                    file_type="code",
                    source_file=str_path,
                    source_location=f"L{line}",
                    language="csharp",
                    kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src: str, tgt: str, relation: str, line: int, confidence: str = "EXTRACTED") -> None:
            edges.append(Edge(
                source=src,
                target=tgt,
                relation=relation,
                confidence=confidence,
                source_file=str_path,
                source_location=f"L{line}",
            ))

        # File-level node
        file_nid = make_id(stem)
        add_node(file_nid, path.name, 1, "file")

        def _get_attributes(node) -> list[str]:
            """Extract attributes from attribute lists.

            If the attribute has arguments (``[Table("orders")]``) the full
            text is captured so cross-language analysis can recover the
            table name. Bare attributes (``[ApiController]``) keep just
            their name.
            """
            attrs = []
            for child in node.children:
                if child.type == "attribute_list":
                    for attr in child.children:
                        if attr.type == "attribute":
                            arg_list = attr.child_by_field_name("arguments")
                            if arg_list is not None:
                                attrs.append(_text(attr))
                            else:
                                name_node = attr.child_by_field_name("name")
                                if name_node:
                                    attrs.append(_text(name_node))
            return attrs

        def walk(node, parent_nid: str | None = None, namespace: str = "") -> None:
            t = node.type

            # ── Using directives (imports) ────────────────────────────
            if t == "using_directive":
                for child in node.children:
                    if child.type in ("qualified_name", "identifier", "name"):
                        import_name = _text(child)
                        tgt_nid = make_id(import_name.split(".")[-1])
                        add_edge(file_nid, tgt_nid, "using", node.start_point[0] + 1)
                return

            # ── Namespace ─────────────────────────────────────────────
            if t in ("namespace_declaration", "file_scoped_namespace_declaration"):
                name_node = node.child_by_field_name("name")
                ns_name = _text(name_node) if name_node else ""
                ns_nid = make_id(ns_name)
                line = node.start_point[0] + 1
                add_node(ns_nid, ns_name, line, "namespace")
                add_edge(file_nid, ns_nid, "contains", line)

                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        walk(child, parent_nid=ns_nid, namespace=ns_name)
                else:
                    # file-scoped namespace — rest of file is the body
                    for child in node.children:
                        if child.type not in ("namespace", "name", ";"):
                            walk(child, parent_nid=ns_nid, namespace=ns_name)
                return

            # ── Class / Interface / Struct / Enum ─────────────────────
            if t in ("class_declaration", "interface_declaration", "struct_declaration", "enum_declaration"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    for child in node.children:
                        walk(child, parent_nid, namespace)
                    return

                type_name = _text(name_node)
                type_nid = make_id(namespace, type_name) if namespace else make_id(stem, type_name)
                line = node.start_point[0] + 1
                kind_map = {
                    "class_declaration": "class",
                    "interface_declaration": "interface",
                    "struct_declaration": "struct",
                    "enum_declaration": "enum",
                }
                kind = kind_map[t]

                attributes = _get_attributes(node)
                meta = {}
                if attributes:
                    meta["attributes"] = attributes

                add_node(type_nid, type_name, line, kind, **meta)
                container = parent_nid or file_nid
                add_edge(container, type_nid, "contains", line)

                # Base types (extends / implements)
                bases = node.child_by_field_name("bases")
                if bases:
                    for child in bases.children:
                        if child.type in ("identifier", "generic_name", "qualified_name"):
                            base_name = _text(child)
                            if "<" in base_name:
                                base_name = base_name.split("<")[0]
                            base_nid = make_id(base_name)
                            if base_nid not in seen_ids:
                                add_node(base_nid, base_name, line, "class")
                            relation = "implements" if kind == "class" and base_name.startswith("I") else "extends"
                            add_edge(type_nid, base_nid, relation, line)

                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        walk(child, parent_nid=type_nid, namespace=namespace)
                return

            # ── Methods ───────────────────────────────────────────────
            if t == "method_declaration":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                method_name = _text(name_node)
                line = node.start_point[0] + 1
                method_nid = make_id(parent_nid or stem, method_name)

                attributes = _get_attributes(node)
                meta = {}
                if attributes:
                    meta["attributes"] = attributes

                add_node(method_nid, f"{method_name}()", line, "method", **meta)
                if parent_nid:
                    add_edge(parent_nid, method_nid, "method", line)

                body = node.child_by_field_name("body")
                if body:
                    method_bodies.append((method_nid, body))
                return

            # ── Properties ────────────────────────────────────────────
            if t == "property_declaration" and parent_nid:
                name_node = node.child_by_field_name("name")
                if name_node:
                    prop_name = _text(name_node)
                    line = node.start_point[0] + 1
                    prop_nid = make_id(parent_nid, prop_name)
                    add_node(prop_nid, prop_name, line, "property")
                    add_edge(parent_nid, prop_nid, "has_property", line)
                return

            for child in node.children:
                walk(child, parent_nid, namespace)

        walk(tree.root_node)

        # ── Call-graph pass ───────────────────────────────────────────
        label_to_nid: dict[str, str] = {}
        for n in nodes:
            normalised = n.label.strip("()").lstrip(".")
            label_to_nid[normalised.lower()] = n.id

        seen_call_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid: str) -> None:
            if node.type == "method_declaration":
                return
            if node.type == "invocation_expression":
                func_node = node.child_by_field_name("function")
                if func_node:
                    # Get rightmost identifier (method name)
                    if func_node.type == "member_access_expression":
                        name_node = func_node.child_by_field_name("name")
                        if name_node:
                            callee = _text(name_node).lower()
                    elif func_node.type == "identifier":
                        callee = _text(func_node).lower()
                    else:
                        callee = None

                    if callee:
                        tgt_nid = label_to_nid.get(callee)
                        if tgt_nid and tgt_nid != caller_nid:
                            pair = (caller_nid, tgt_nid)
                            if pair not in seen_call_pairs:
                                seen_call_pairs.add(pair)
                                edges.append(Edge(
                                    source=caller_nid,
                                    target=tgt_nid,
                                    relation="calls",
                                    confidence="INFERRED",
                                    source_file=str_path,
                                    source_location=f"L{node.start_point[0] + 1}",
                                    weight=0.8,
                                ))
            for child in node.children:
                walk_calls(child, caller_nid)

        for caller_nid, body_node in method_bodies:
            walk_calls(body_node, caller_nid)

        return ExtractionResult(nodes=nodes, edges=edges)
