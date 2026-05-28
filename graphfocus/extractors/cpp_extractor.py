"""C++ AST extractor using tree-sitter.

Extracts:
  * ``#include`` directives
  * Namespaces
  * Classes / structs (with their methods declared inline)
  * Out-of-class method definitions (``Class::method`` qualified name)
  * Top-level functions
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


class CppExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "cpp"

    @property
    def extensions(self) -> set[str]:
        return {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h++"}

    def __init__(self) -> None:
        import tree_sitter_cpp as tscpp
        from tree_sitter import Language, Parser
        self._language = Language(tscpp.language())
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
                    source_location=f"L{line}", language="cpp", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src, tgt, relation, line, confidence="EXTRACTED"):
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        file_nid = make_id("file", stem)
        add_node(file_nid, path.name, 1, "file")

        def _function_name(declarator):
            """Return (name, parent_type_or_None) from a function_declarator.

            For ``Class::method`` we get parent_type = "Class".
            """
            if declarator is None:
                return None, None
            # Peel wrappers.
            while declarator.type in ("pointer_declarator", "reference_declarator"):
                inner = first(declarator,
                              ("function_declarator", "pointer_declarator",
                               "reference_declarator"))
                if inner is None:
                    return None, None
                declarator = inner
            # qualified_identifier means out-of-class definition.
            for child in declarator.children:
                if child.type == "qualified_identifier":
                    scope_node = child.child_by_field_name("scope")
                    name_node = child.child_by_field_name("name")
                    if scope_node is not None and name_node is not None:
                        return _text(name_node), _text(scope_node)
                if child.type == "identifier" or child.type == "field_identifier":
                    return _text(child), None
                if child.type == "destructor_name":
                    return _text(child), None
            return None, None

        def walk(node, parent_nid=None, parent_is_type=False):
            """Walk the AST.

            ``parent_is_type`` is True when we're inside a class/struct body —
            functions there are methods. False when we're at file scope or
            inside a namespace, where functions stay top-level.
            """
            t = node.type
            line = node.start_point[0] + 1

            if t == "preproc_include":
                target = first(node, ("system_lib_string", "string_literal"))
                if target is not None:
                    raw = _text(target).strip('<>"')
                    last = raw.split("/")[-1].rsplit(".", 1)[0]
                    add_edge(file_nid, make_id(last), "imports", line)
                return

            if t == "namespace_definition":
                name_node = first(node, ("namespace_identifier", "identifier"))
                if name_node is not None:
                    nname = _text(name_node)
                    nnid = make_id(nname)
                    add_node(nnid, nname, line, "namespace")
                    add_edge(parent_nid or file_nid, nnid, "contains", line)
                    body = first(node, ("declaration_list",))
                    if body:
                        for child in body.children:
                            walk(child, parent_nid=nnid, parent_is_type=False)
                return

            if t in ("class_specifier", "struct_specifier"):
                name_node = first(node, ("type_identifier",))
                if name_node is None:
                    return
                cname = _text(name_node)
                cnid = make_id(stem, cname)
                kind = "class" if t == "class_specifier" else "struct"
                add_node(cnid, cname, line, kind)
                add_edge(parent_nid or file_nid, cnid, "contains", line)

                # Base classes
                base_clause = first(node, ("base_class_clause",))
                if base_clause is not None:
                    for sub in base_clause.children:
                        if sub.type in ("type_identifier", "qualified_identifier"):
                            base = _text(sub).split("::")[-1]
                            bnid = make_id(base)
                            if bnid not in seen:
                                add_node(bnid, base, line, "class")
                            add_edge(cnid, bnid, "inherits", line)

                body = first(node, ("field_declaration_list",))
                if body:
                    for child in body.children:
                        walk(child, parent_nid=cnid, parent_is_type=True)
                return

            if t == "function_definition":
                declarator = first(node, ("function_declarator", "pointer_declarator",
                                          "reference_declarator"))
                fname, scope = _function_name(declarator)
                if not fname:
                    return
                if scope:
                    # Out-of-class definition: attach to the class node.
                    type_nid = make_id(stem, scope)
                    if type_nid not in seen:
                        add_node(type_nid, scope, line, "class")
                    fnid = make_id(type_nid, fname)
                    add_node(fnid, f"{fname}()", line, "method")
                    add_edge(type_nid, fnid, "method", line)
                elif parent_is_type:
                    fnid = make_id(parent_nid, fname)
                    add_node(fnid, f"{fname}()", line, "method")
                    add_edge(parent_nid, fnid, "method", line)
                else:
                    fnid = make_id(stem, fname)
                    add_node(fnid, f"{fname}()", line, "function")
                    add_edge(parent_nid or file_nid, fnid, "contains", line)
                body = first(node, ("compound_statement",))
                if body:
                    function_bodies.append((fnid, body))
                return

            # Inline method declaration inside class body: `field_declaration`
            # whose declarator is a function_declarator.
            if t == "field_declaration" and parent_is_type and parent_nid:
                declarator = first(node, ("function_declarator",))
                if declarator is not None:
                    fname, _ = _function_name(declarator)
                    if fname:
                        fnid = make_id(parent_nid, fname)
                        add_node(fnid, f"{fname}()", line, "method")
                        add_edge(parent_nid, fnid, "method", line)

            for child in node.children:
                walk(child, parent_nid=parent_nid, parent_is_type=parent_is_type)

        walk(tree.root_node)

        # Call graph
        label_to_nid = {n.label.strip("()").lstrip(".").lower(): n.id for n in nodes}
        seen_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid):
            if node.type == "function_definition":
                return
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                callee = None
                if fn is not None:
                    if fn.type == "identifier":
                        callee = _text(fn)
                    elif fn.type == "field_expression":
                        field = fn.child_by_field_name("field")
                        if field is not None:
                            callee = _text(field)
                    elif fn.type == "qualified_identifier":
                        name = fn.child_by_field_name("name")
                        if name is not None:
                            callee = _text(name)
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
