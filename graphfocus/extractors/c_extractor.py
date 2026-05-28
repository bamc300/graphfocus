"""C AST extractor using tree-sitter.

Extracts:
  * ``#include`` directives (both ``<system>`` and ``"local"``)
  * Structs declared via ``typedef struct {…} Name;``
  * Standalone ``struct Name {…}`` declarations
  * Function definitions
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


class CExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "c"

    @property
    def extensions(self) -> set[str]:
        return {".c", ".h"}

    def __init__(self) -> None:
        import tree_sitter_c as tsc
        from tree_sitter import Language, Parser
        self._language = Language(tsc.language())
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
                    source_location=f"L{line}", language="c", kind=kind,
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
            """Recursively descend a (possibly nested) function_declarator
            until we find the identifier — handles pointers, attributes, etc."""
            if declarator is None:
                return None, None
            ident = first(declarator, ("identifier", "field_identifier"))
            if ident is not None:
                return _text(ident), declarator
            inner = first(declarator, ("function_declarator", "pointer_declarator"))
            if inner is not None:
                return _function_name(inner)
            return None, None

        def _find_field_identifier(node):
            """Descend through array_declarator / pointer_declarator wrappers
            until a field_identifier is found."""
            stack = [node]
            while stack:
                cur = stack.pop()
                if cur.type == "field_identifier":
                    return cur
                stack.extend(cur.children)
            return None

        def _struct_fields(field_list, struct_nid, base_line):
            for fdecl in field_list.children:
                if fdecl.type != "field_declaration":
                    continue
                # field_declaration may wrap the identifier in array_declarator,
                # pointer_declarator, etc. Walk children depth-first.
                for ch in fdecl.children:
                    if ch.type == "primitive_type" or ch.type == "type_identifier":
                        continue
                    ident = _find_field_identifier(ch) if ch.type != "field_identifier" else ch
                    if ident is None:
                        continue
                    fname = _text(ident)
                    line = fdecl.start_point[0] + 1
                    fnid = make_id(struct_nid, fname)
                    add_node(fnid, fname, line, "field")
                    add_edge(struct_nid, fnid, "has_field", line)
                    break  # one field per field_declaration in typical code

        for node in tree.root_node.children:
            t = node.type
            line = node.start_point[0] + 1

            # #include <…>  /  #include "…"
            if t == "preproc_include":
                target_node = first(node, ("system_lib_string", "string_literal"))
                if target_node is not None:
                    raw = _text(target_node).strip('<>"')
                    last = raw.split("/")[-1].rsplit(".", 1)[0]
                    add_edge(file_nid, make_id(last), "imports", line)
                continue

            # typedef struct {…} Name;
            if t == "type_definition":
                struct = first(node, ("struct_specifier", "union_specifier", "enum_specifier"))
                name_node = None
                # Find the last type_identifier in the typedef (skipping inner).
                for child in node.children:
                    if child.type == "type_identifier":
                        name_node = child
                if name_node is not None:
                    sname = _text(name_node)
                    snid = make_id(stem, sname)
                    kind = "enum" if struct and struct.type == "enum_specifier" else "struct"
                    add_node(snid, sname, line, kind)
                    add_edge(file_nid, snid, "contains", line)
                    if struct is not None:
                        flist = first(struct, ("field_declaration_list",))
                        if flist is not None:
                            _struct_fields(flist, snid, line)
                continue

            # struct Foo {…};
            if t == "struct_specifier":
                name_node = first(node, ("type_identifier",))
                if name_node is not None:
                    sname = _text(name_node)
                    snid = make_id(stem, sname)
                    add_node(snid, sname, line, "struct")
                    add_edge(file_nid, snid, "contains", line)
                    flist = first(node, ("field_declaration_list",))
                    if flist is not None:
                        _struct_fields(flist, snid, line)
                continue

            if t == "function_definition":
                declarator = first(node, ("function_declarator", "pointer_declarator"))
                fname, _ = _function_name(declarator)
                if not fname:
                    continue
                fnid = make_id(stem, fname)
                add_node(fnid, f"{fname}()", line, "function")
                add_edge(file_nid, fnid, "contains", line)
                body = first(node, ("compound_statement",))
                if body:
                    function_bodies.append((fnid, body))
                continue

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
