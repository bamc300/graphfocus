"""Java AST extractor using tree-sitter.

Extracts:
  - Classes and interfaces (with inheritance and implements)
  - Methods (with annotations like @Override, @Transactional)
  - Fields
  - Imports
  - Annotations (Spring: @Service, @Repository, @Controller, @Entity, etc.)
  - Call graph (method calls within method bodies)
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

# Spring / Jakarta annotations that indicate architectural roles
_SPRING_ANNOTATIONS = {
    "Service", "Repository", "Controller", "RestController",
    "Component", "Configuration", "Bean",
    "Entity", "Table", "MappedSuperclass",
    "Transactional", "Autowired", "Inject",
    "RequestMapping", "GetMapping", "PostMapping", "PutMapping", "DeleteMapping",
    "PathVariable", "RequestBody", "RequestParam",
}


class JavaExtractor(LanguageExtractor):
    """Extract Java code structure using tree-sitter AST."""

    @property
    def language_name(self) -> str:
        return "java"

    @property
    def extensions(self) -> set[str]:
        return {".java"}

    def __init__(self) -> None:
        import tree_sitter_java as tsjava
        from tree_sitter import Language, Parser

        self._language = Language(tsjava.language())
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
        package_name: str | None = None

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
                    language="java",
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

        def _get_annotations(node) -> list[str]:
            """Collect annotations from modifiers preceding a declaration.

            For marker annotations (``@Override``) we record just the name.
            For full annotations (``@Table(name="orders")``) we record the
            full text including arguments, with the leading ``@`` stripped,
            so cross-language analysis can recover the table name.
            """
            annotations = []
            for child in node.children:
                if child.type == "modifiers":
                    for mod in child.children:
                        if mod.type == "marker_annotation":
                            name_node = mod.child_by_field_name("name")
                            if name_node:
                                annotations.append(_text(name_node))
                        elif mod.type == "annotation":
                            annotations.append(_text(mod).lstrip("@"))
            return annotations

        def walk(node, parent_nid: str | None = None) -> None:
            nonlocal package_name
            t = node.type

            # ── Package declaration ───────────────────────────────────
            if t == "package_declaration":
                for child in node.children:
                    if child.type == "scoped_identifier" or child.type == "identifier":
                        package_name = _text(child)
                return

            # ── Imports ───────────────────────────────────────────────
            if t == "import_declaration":
                for child in node.children:
                    if child.type in ("scoped_identifier", "identifier"):
                        import_path = _text(child)
                        tgt_nid = make_id(import_path.split(".")[-1])
                        add_edge(file_nid, tgt_nid, "imports", node.start_point[0] + 1)
                return

            # ── Class / Interface / Enum declarations ─────────────────
            if t in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    for child in node.children:
                        walk(child, parent_nid)
                    return

                class_name = _text(name_node)
                class_nid = make_id(stem, class_name)
                line = node.start_point[0] + 1
                kind = {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum"}[t]

                annotations = _get_annotations(node)
                meta = {}
                if annotations:
                    meta["annotations"] = annotations
                    # Detect Spring architectural annotations
                    spring_roles = [a for a in annotations if a in _SPRING_ANNOTATIONS]
                    if spring_roles:
                        meta["spring_roles"] = spring_roles

                add_node(class_nid, class_name, line, kind, **meta)
                add_edge(file_nid, class_nid, "contains", line)

                # Superclass (extends)
                superclass = node.child_by_field_name("superclass")
                if superclass:
                    base_name = _text(superclass)
                    # Handle generic types like "extends BaseEntity<UUID>"
                    if "<" in base_name:
                        base_name = base_name.split("<")[0].strip()
                    base_nid = make_id(base_name)
                    if base_nid not in seen_ids:
                        add_node(base_nid, base_name, line, "class")
                    add_edge(class_nid, base_nid, "extends", line)

                # Interfaces (implements)
                interfaces = node.child_by_field_name("interfaces")
                if interfaces:
                    for child in interfaces.children:
                        if child.type in ("type_identifier", "generic_type"):
                            iface_name = _text(child)
                            if "<" in iface_name:
                                iface_name = iface_name.split("<")[0].strip()
                            iface_nid = make_id(iface_name)
                            if iface_nid not in seen_ids:
                                add_node(iface_nid, iface_name, line, "interface")
                            add_edge(class_nid, iface_nid, "implements", line)

                # Walk class body for methods and fields
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        walk(child, parent_nid=class_nid)
                return

            # ── Methods ───────────────────────────────────────────────
            if t == "method_declaration" or t == "constructor_declaration":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                method_name = _text(name_node)
                line = node.start_point[0] + 1
                method_nid = make_id(parent_nid or stem, method_name) if parent_nid else make_id(stem, method_name)

                annotations = _get_annotations(node)
                meta = {}
                if annotations:
                    meta["annotations"] = annotations

                add_node(method_nid, f"{method_name}()", line, "method", **meta)
                if parent_nid:
                    add_edge(parent_nid, method_nid, "method", line)

                body = node.child_by_field_name("body")
                if body:
                    method_bodies.append((method_nid, body))
                return

            # ── Field declarations ────────────────────────────────────
            if t == "field_declaration" and parent_nid:
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            field_name = _text(name_node)
                            line = node.start_point[0] + 1
                            field_nid = make_id(parent_nid, field_name)
                            add_node(field_nid, field_name, line, "field")
                            add_edge(parent_nid, field_nid, "has_field", line)

            for child in node.children:
                walk(child, parent_nid)

        walk(tree.root_node)

        # ── Call-graph pass ───────────────────────────────────────────
        label_to_nid: dict[str, str] = {}
        for n in nodes:
            normalised = n.label.strip("()").lstrip(".")
            label_to_nid[normalised.lower()] = n.id

        seen_call_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid: str) -> None:
            if node.type in ("method_declaration", "constructor_declaration"):
                return
            if node.type == "method_invocation":
                name_node = node.child_by_field_name("name")
                if name_node:
                    callee_name = _text(name_node).lower()
                    tgt_nid = label_to_nid.get(callee_name)
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
