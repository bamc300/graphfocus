"""TypeScript / JavaScript / React extractor using tree-sitter.

Handles ``.ts``, ``.tsx``, ``.js``, ``.jsx``. We use the **tsx** grammar
from ``tree-sitter-typescript`` because it is a strict superset that
parses all four file types — including JSX, which is what React uses.

Extracts:
  * Classes (with ``extends`` and ``implements``)
  * Interfaces and type aliases
  * Named functions and methods
  * Arrow functions / function expressions bound to ``const``/``let``
  * React components — any function that returns JSX is tagged
    ``kind="component"`` instead of ``kind="function"``
  * Class components — classes whose superclass is ``Component`` or
    ``React.Component`` are tagged ``kind="component"``
  * Decorators (``@Component``, ``@Injectable``, …) captured in metadata
  * Imports
  * Call graph (function/method calls within bodies)
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


# Node types that mark a piece of JSX inside the AST.
_JSX_NODE_TYPES = {
    "jsx_element",
    "jsx_self_closing_element",
    "jsx_fragment",
}

# Superclass names that turn a class into a React component.
_REACT_CLASS_BASES = {"Component", "PureComponent", "React.Component", "React.PureComponent"}


class TypeScriptExtractor(LanguageExtractor):
    """Extract TypeScript/JavaScript/React structure via tree-sitter."""

    @property
    def language_name(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> set[str]:
        return {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

    def __init__(self) -> None:
        import tree_sitter_typescript as tsts
        from tree_sitter import Language, Parser

        # `tsx` is a strict superset; one grammar covers all four file types.
        self._language = Language(tsts.language_tsx())
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

        # Sub-language label: .jsx and .tsx are React; .js and .ts are plain.
        language_label = "typescript"
        ext = path.suffix.lower()
        if ext in (".js", ".mjs", ".cjs"):
            language_label = "javascript"

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
                    language=language_label,
                    kind=kind,
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

        def _has_jsx(node) -> bool:
            """Return True if anywhere inside ``node`` we see a JSX element."""
            if node is None:
                return False
            stack = [node]
            while stack:
                cur = stack.pop()
                if cur.type in _JSX_NODE_TYPES:
                    return True
                stack.extend(cur.children)
            return False

        def _decorator_names(node) -> list[str]:
            """Collect decorator names that precede ``node`` (Angular, NestJS…)."""
            decs: list[str] = []
            for child in node.children:
                if child.type == "decorator":
                    # decorator → "@name" or "@name(arg)"; pull rightmost identifier
                    name = _text(child).lstrip("@")
                    decs.append(name)
            return decs

        def walk(node, parent_class_nid: str | None = None) -> None:
            t = node.type

            # ── Imports ───────────────────────────────────────────────
            if t == "import_statement":
                src_node = node.child_by_field_name("source")
                if src_node is not None:
                    module = _text(src_node).strip("\"'`")
                    add_edge(file_nid, make_id(module.split("/")[-1]),
                             "imports", node.start_point[0] + 1)
                return

            # ── Class declaration ─────────────────────────────────────
            if t == "class_declaration":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                class_name = _text(name_node)
                line = node.start_point[0] + 1
                class_nid = make_id(stem, class_name)

                decorators = _decorator_names(node)
                meta = {"decorators": decorators} if decorators else {}

                # Heritage (extends / implements)
                kind = "class"
                heritage = node.child_by_field_name("body")  # find class_heritage sibling
                # In TS the heritage lives as a child of class_declaration directly.
                base_names: list[str] = []
                impl_names: list[str] = []
                for child in node.children:
                    if child.type == "class_heritage":
                        for sub in child.children:
                            if sub.type == "extends_clause":
                                for grand in sub.children:
                                    if grand.type in ("identifier", "type_identifier",
                                                      "member_expression", "nested_type_identifier"):
                                        base_names.append(_text(grand))
                            elif sub.type == "implements_clause":
                                for grand in sub.children:
                                    if grand.type in ("type_identifier", "identifier",
                                                      "generic_type"):
                                        name = _text(grand)
                                        if "<" in name:
                                            name = name.split("<")[0]
                                        impl_names.append(name)

                if any(b in _REACT_CLASS_BASES or b.endswith(".Component")
                       or b.endswith(".PureComponent") for b in base_names):
                    kind = "component"

                add_node(class_nid, class_name, line, kind, **meta)
                add_edge(file_nid, class_nid, "contains", line)
                for base in base_names:
                    base_nid = make_id(base.split(".")[-1])
                    if base_nid not in seen_ids:
                        add_node(base_nid, base, line, "class")
                    add_edge(class_nid, base_nid, "extends", line)
                for iface in impl_names:
                    iface_nid = make_id(iface)
                    if iface_nid not in seen_ids:
                        add_node(iface_nid, iface, line, "interface")
                    add_edge(class_nid, iface_nid, "implements", line)

                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        walk(child, parent_class_nid=class_nid)
                return

            # ── Interface ─────────────────────────────────────────────
            if t == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    iname = _text(name_node)
                    line = node.start_point[0] + 1
                    iid = make_id(stem, iname)
                    add_node(iid, iname, line, "interface")
                    add_edge(file_nid, iid, "contains", line)
                return

            # ── Type alias ────────────────────────────────────────────
            if t == "type_alias_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    tname = _text(name_node)
                    line = node.start_point[0] + 1
                    tid = make_id(stem, tname)
                    add_node(tid, tname, line, "type")
                    add_edge(file_nid, tid, "contains", line)
                return

            # ── Function declaration ──────────────────────────────────
            if t == "function_declaration":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                fname = _text(name_node)
                line = node.start_point[0] + 1
                fnid = make_id(stem, fname)
                body = node.child_by_field_name("body")
                kind = "component" if _has_jsx(body) else "function"
                add_node(fnid, f"{fname}()", line, kind)
                add_edge(file_nid, fnid, "contains", line)
                if body:
                    function_bodies.append((fnid, body))
                return

            # ── Method definition (inside a class) ────────────────────
            if t == "method_definition" and parent_class_nid:
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                mname = _text(name_node)
                line = node.start_point[0] + 1
                mnid = make_id(parent_class_nid, mname)
                add_node(mnid, f"{mname}()", line, "method")
                add_edge(parent_class_nid, mnid, "method", line)
                body = node.child_by_field_name("body")
                if body:
                    function_bodies.append((mnid, body))
                return

            # ── const/let foo = (…) => … ; const Foo = function(){…} ─
            if t in ("lexical_declaration", "variable_declaration"):
                for child in node.children:
                    if child.type != "variable_declarator":
                        continue
                    name_node = child.child_by_field_name("name")
                    value_node = child.child_by_field_name("value")
                    if not (name_node and value_node):
                        continue
                    if value_node.type not in ("arrow_function", "function_expression"):
                        continue
                    fname = _text(name_node)
                    line = node.start_point[0] + 1
                    fnid = make_id(stem, fname)
                    body = value_node.child_by_field_name("body")
                    kind = "component" if _has_jsx(value_node) else "function"
                    add_node(fnid, f"{fname}()", line, kind)
                    add_edge(file_nid, fnid, "contains", line)
                    if body:
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
            if node.type in ("function_declaration", "method_definition",
                             "function_expression", "arrow_function"):
                return
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                callee_name: str | None = None
                if fn is not None:
                    if fn.type == "identifier":
                        callee_name = _text(fn)
                    elif fn.type == "member_expression":
                        prop = fn.child_by_field_name("property")
                        if prop is not None:
                            callee_name = _text(prop)
                if callee_name:
                    tgt = label_to_nid.get(callee_name.lower())
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
