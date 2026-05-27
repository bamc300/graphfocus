"""Kotlin AST extractor using tree-sitter.

Extracts:
  * Package
  * Imports
  * Classes / interfaces / objects / data classes
  * Functions and methods
  * Annotations on classes and functions (incl. Spring: ``@Service``,
    ``@Transactional``, ``@Component``, ``@RestController`` …)
  * Call graph (calls within function bodies)

The grammar from ``tree-sitter-kotlin`` does not expose field names on
most nodes, so we look up children by ``type`` and pick the first
matching identifier.
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


_SPRING_ANNOTATIONS = {
    "Service", "Repository", "Controller", "RestController",
    "Component", "Configuration", "Bean",
    "Entity", "Table", "MappedSuperclass",
    "Transactional", "Autowired", "Inject",
    "RequestMapping", "GetMapping", "PostMapping", "PutMapping", "DeleteMapping",
}


class KotlinExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "kotlin"

    @property
    def extensions(self) -> set[str]:
        return {".kt", ".kts"}

    def __init__(self) -> None:
        import tree_sitter_kotlin as tskt
        from tree_sitter import Language, Parser

        self._language = Language(tskt.language())
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

        def _first_child(node, types: tuple[str, ...]):
            for child in node.children:
                if child.type in types:
                    return child
            return None

        def add_node(nid: str, label: str, line: int, kind: str, **meta) -> None:
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append(Node(
                    id=nid, label=label, file_type="code",
                    source_file=str_path, source_location=f"L{line}",
                    language="kotlin", kind=kind,
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

        def _annotation_names(node) -> list[str]:
            """Pull annotation names from a ``modifiers`` child of ``node``."""
            names: list[str] = []
            for child in node.children:
                if child.type != "modifiers":
                    continue
                for mod in child.children:
                    if mod.type != "annotation":
                        continue
                    user_type = _first_child(mod, ("user_type", "constructor_invocation"))
                    if user_type is not None:
                        # Pull the identifier (drop generics / args).
                        ident = _first_child(user_type, ("type_identifier", "identifier",
                                                         "simple_identifier"))
                        if ident is not None:
                            names.append(_text(ident))
                        else:
                            names.append(_text(user_type).strip("@"))
            return names

        def _is_interface(node) -> bool:
            return _first_child(node, ("interface",)) is not None

        def _is_object(node) -> bool:
            return _first_child(node, ("object",)) is not None

        def _is_data_class(node) -> bool:
            modifiers = _first_child(node, ("modifiers",))
            if not modifiers:
                return False
            for child in modifiers.children:
                if child.type == "class_modifier":
                    if any(c.type == "data" for c in child.children):
                        return True
            return False

        def _identifier_name(node) -> str | None:
            ident = _first_child(node, ("identifier", "type_identifier", "simple_identifier"))
            return _text(ident) if ident is not None else None

        def walk(node, parent_class_nid: str | None = None) -> None:
            t = node.type

            if t == "package_header":
                # Captured but not stored as a node (just for context).
                return

            if t == "import":
                qid = _first_child(node, ("qualified_identifier", "identifier"))
                if qid is not None:
                    raw = _text(qid)
                    last = raw.split(".")[-1]
                    add_edge(file_nid, make_id(last), "imports", node.start_point[0] + 1)
                return

            if t in ("class_declaration", "object_declaration"):
                name = _identifier_name(node)
                if not name:
                    return
                line = node.start_point[0] + 1
                if t == "object_declaration" or _is_object(node):
                    kind = "object"
                elif _is_interface(node):
                    kind = "interface"
                elif _is_data_class(node):
                    kind = "data_class"
                else:
                    kind = "class"

                annotations = _annotation_names(node)
                meta: dict = {}
                if annotations:
                    meta["annotations"] = annotations
                    spring = [a for a in annotations if a in _SPRING_ANNOTATIONS]
                    if spring:
                        meta["spring_roles"] = spring

                class_nid = make_id(stem, name)
                add_node(class_nid, name, line, kind, **meta)
                add_edge(file_nid, class_nid, "contains", line)

                # Descend into the body for nested fn/class declarations.
                body = _first_child(node, ("class_body", "enum_class_body"))
                if body is not None:
                    for child in body.children:
                        walk(child, parent_class_nid=class_nid)
                return

            if t == "function_declaration":
                name = _identifier_name(node)
                if not name:
                    return
                line = node.start_point[0] + 1
                annotations = _annotation_names(node)
                meta = {"annotations": annotations} if annotations else {}

                if parent_class_nid:
                    fnid = make_id(parent_class_nid, name)
                    add_node(fnid, f"{name}()", line, "method", **meta)
                    add_edge(parent_class_nid, fnid, "method", line)
                else:
                    fnid = make_id(stem, name)
                    add_node(fnid, f"{name}()", line, "function", **meta)
                    add_edge(file_nid, fnid, "contains", line)

                body = _first_child(node, ("function_body",))
                if body is not None:
                    function_bodies.append((fnid, body))
                return

            for child in node.children:
                walk(child, parent_class_nid=parent_class_nid)

        walk(tree.root_node)

        # ── Call-graph pass ───────────────────────────────────────────
        label_to_nid: dict[str, str] = {}
        for n in nodes:
            normalised = n.label.strip("()").lstrip(".")
            label_to_nid[normalised.lower()] = n.id

        seen_call_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid: str) -> None:
            if node.type == "function_declaration":
                return
            if node.type == "call_expression":
                callee: str | None = None
                # Pattern 1: direct identifier call — `foo(...)`
                first = node.children[0] if node.children else None
                if first is not None:
                    if first.type in ("identifier", "simple_identifier"):
                        callee = _text(first)
                    elif first.type == "navigation_expression":
                        # repo.findById(...) → grab the rightmost identifier.
                        for sub in reversed(first.children):
                            if sub.type in ("identifier", "simple_identifier",
                                            "navigation_suffix"):
                                if sub.type == "navigation_suffix":
                                    ident = _first_child(sub, ("identifier",
                                                               "simple_identifier"))
                                    if ident is not None:
                                        callee = _text(ident)
                                else:
                                    callee = _text(sub)
                                break
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
