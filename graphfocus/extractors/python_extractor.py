"""Python AST extractor using tree-sitter.

Extracts:
  - Classes (with inheritance)
  - Functions / methods
  - Imports (import and from...import)
  - Call graph (function calls within function bodies)
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


class PythonExtractor(LanguageExtractor):
    """Extract Python code structure using tree-sitter AST."""

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def extensions(self) -> set[str]:
        return {".py"}

    def __init__(self) -> None:
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        self._language = Language(tspython.language())
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

        def add_node(nid: str, label: str, line: int, kind: str) -> None:
            if nid not in seen_ids:
                seen_ids.add(nid)
                nodes.append(Node(
                    id=nid,
                    label=label,
                    file_type="code",
                    source_file=str_path,
                    source_location=f"L{line}",
                    language="python",
                    kind=kind,
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
        add_node(file_nid, path.name, 1, "module")

        def walk(node, parent_class_nid: str | None = None) -> None:
            t = node.type

            # ── Imports ───────────────────────────────────────────────
            if t == "import_statement":
                for child in node.children:
                    if child.type in ("dotted_name", "aliased_import"):
                        raw = source[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                        module_name = raw.split(" as ")[0].strip().lstrip(".")
                        tgt_nid = make_id(module_name)
                        add_edge(file_nid, tgt_nid, "imports", node.start_point[0] + 1)
                return

            if t == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                if module_node:
                    raw = source[module_node.start_byte:module_node.end_byte].decode("utf-8", errors="replace").lstrip(".")
                    tgt_nid = make_id(raw)
                    add_edge(file_nid, tgt_nid, "imports_from", node.start_point[0] + 1)
                return

            # ── Classes ───────────────────────────────────────────────
            if t == "class_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                class_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                class_nid = make_id(stem, class_name)
                line = node.start_point[0] + 1
                add_node(class_nid, class_name, line, "class")
                add_edge(file_nid, class_nid, "contains", line)

                # Inheritance
                args = node.child_by_field_name("superclasses")
                if args:
                    for arg in args.children:
                        if arg.type == "identifier":
                            base = source[arg.start_byte:arg.end_byte].decode("utf-8", errors="replace")
                            base_nid = make_id(stem, base)
                            if base_nid not in seen_ids:
                                base_nid = make_id(base)
                                if base_nid not in seen_ids:
                                    add_node(base_nid, base, line, "class")
                            add_edge(class_nid, base_nid, "inherits", line)

                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        walk(child, parent_class_nid=class_nid)
                return

            # ── Functions / Methods ───────────────────────────────────
            if t == "function_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                func_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                line = node.start_point[0] + 1

                if parent_class_nid:
                    func_nid = make_id(parent_class_nid, func_name)
                    add_node(func_nid, f".{func_name}()", line, "method")
                    add_edge(parent_class_nid, func_nid, "method", line)
                else:
                    func_nid = make_id(stem, func_name)
                    add_node(func_nid, f"{func_name}()", line, "function")
                    add_edge(file_nid, func_nid, "contains", line)

                body = node.child_by_field_name("body")
                if body:
                    function_bodies.append((func_nid, body))
                return

            # ── Decorators ────────────────────────────────────────────
            if t == "decorator":
                # Capture decorator names for annotation tracking
                pass

            for child in node.children:
                walk(child, parent_class_nid=None)

        walk(tree.root_node)

        # ── Call-graph pass ───────────────────────────────────────────
        label_to_nid: dict[str, str] = {}
        for n in nodes:
            normalised = n.label.strip("().").lstrip(".")
            label_to_nid[normalised.lower()] = n.id

        seen_call_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid: str) -> None:
            if node.type == "function_definition":
                return
            if node.type == "call":
                func_node = node.child_by_field_name("function")
                callee_name: str | None = None
                if func_node:
                    if func_node.type == "identifier":
                        callee_name = source[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="replace")
                    elif func_node.type == "attribute":
                        attr = func_node.child_by_field_name("attribute")
                        if attr:
                            callee_name = source[attr.start_byte:attr.end_byte].decode("utf-8", errors="replace")
                if callee_name:
                    tgt_nid = label_to_nid.get(callee_name.lower())
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

        for caller_nid, body_node in function_bodies:
            walk_calls(body_node, caller_nid)

        return ExtractionResult(nodes=nodes, edges=edges)
