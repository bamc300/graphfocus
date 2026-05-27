"""Rust AST extractor using tree-sitter.

Extracts:
  * ``use`` declarations (imports)
  * Structs (with public fields)
  * Enums
  * Traits (with their method signatures)
  * Inherent ``impl`` blocks — methods are attached to the struct/enum
  * Trait ``impl Trait for Type`` blocks — an ``implements`` edge connects
    the type to the trait, plus the methods are attached to the type
  * Top-level functions
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


class RustExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "rust"

    @property
    def extensions(self) -> set[str]:
        return {".rs"}

    def __init__(self) -> None:
        import tree_sitter_rust as tsrs
        from tree_sitter import Language, Parser

        self._language = Language(tsrs.language())
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
                    language="rust", kind=kind,
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

        def _last_identifier(node) -> str | None:
            """For `a::b::c`, return `c`. Recurses through scoped_identifier."""
            if node is None:
                return None
            if node.type == "scoped_identifier":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    return _text(name_node)
                # Fallback: last identifier child
                for child in reversed(node.children):
                    if child.type == "identifier":
                        return _text(child)
            if node.type in ("identifier", "type_identifier"):
                return _text(node)
            return None

        for node in tree.root_node.children:
            t = node.type
            line = node.start_point[0] + 1

            # use std::collections::HashMap;
            if t == "use_declaration":
                # The argument can be scoped_identifier, scoped_use_list,
                # use_as_clause, etc. Grab the rightmost identifier we can find.
                arg = None
                for child in node.children:
                    if child.type not in ("use", ";"):
                        arg = child
                        break
                last = _last_identifier(arg) if arg is not None else None
                if last:
                    add_edge(file_nid, make_id(last), "imports", line)
                continue

            # struct Foo { … }
            if t == "struct_item":
                name_node = _first_child(node, ("type_identifier",))
                if not name_node:
                    continue
                sname = _text(name_node)
                snid = make_id(stem, sname)
                add_node(snid, sname, line, "struct")
                add_edge(file_nid, snid, "contains", line)

                fields = _first_child(node, ("field_declaration_list",))
                if fields is not None:
                    for fdecl in fields.children:
                        if fdecl.type != "field_declaration":
                            continue
                        fname_node = _first_child(fdecl, ("field_identifier",))
                        if fname_node is None:
                            continue
                        fname = _text(fname_node)
                        fnid = make_id(snid, fname)
                        add_node(fnid, fname, fdecl.start_point[0] + 1, "field")
                        add_edge(snid, fnid, "has_field", fdecl.start_point[0] + 1)
                continue

            # enum Foo { … }
            if t == "enum_item":
                name_node = _first_child(node, ("type_identifier",))
                if name_node:
                    ename = _text(name_node)
                    enid = make_id(stem, ename)
                    add_node(enid, ename, line, "enum")
                    add_edge(file_nid, enid, "contains", line)
                continue

            # trait Foo { … }
            if t == "trait_item":
                name_node = _first_child(node, ("type_identifier",))
                if not name_node:
                    continue
                tname = _text(name_node)
                tnid = make_id(stem, tname)
                add_node(tnid, tname, line, "trait")
                add_edge(file_nid, tnid, "contains", line)

                decls = _first_child(node, ("declaration_list",))
                if decls is not None:
                    for child in decls.children:
                        if child.type in ("function_signature_item", "function_item"):
                            ident = _first_child(child, ("identifier",))
                            if ident is None:
                                continue
                            mname = _text(ident)
                            mline = child.start_point[0] + 1
                            mnid = make_id(tnid, mname)
                            add_node(mnid, f"{mname}()", mline, "method")
                            add_edge(tnid, mnid, "method", mline)
                            body = _first_child(child, ("block",))
                            if body is not None:
                                function_bodies.append((mnid, body))
                continue

            # impl Type { … }   OR   impl Trait for Type { … }
            if t == "impl_item":
                trait_name_node = node.child_by_field_name("trait")
                type_name_node = node.child_by_field_name("type")
                # Fallbacks for grammars that don't expose field names here.
                type_ids = [c for c in node.children if c.type == "type_identifier"]
                if trait_name_node is None and type_name_node is None:
                    # Either single (inherent impl) or two (trait impl) type_identifiers.
                    if len(type_ids) == 1:
                        type_name_node = type_ids[0]
                    elif len(type_ids) >= 2:
                        trait_name_node = type_ids[0]
                        type_name_node = type_ids[1]
                if type_name_node is None:
                    continue
                type_name = _text(type_name_node)
                parent_nid = make_id(stem, type_name)
                # Ensure the struct/enum exists.
                if parent_nid not in seen_ids:
                    add_node(parent_nid, type_name, line, "struct")

                if trait_name_node is not None:
                    trait_name = _text(trait_name_node)
                    trait_nid = make_id(stem, trait_name)
                    if trait_nid not in seen_ids:
                        # The trait may have been declared in another file.
                        trait_nid_alt = make_id(trait_name)
                        if trait_nid_alt not in seen_ids:
                            add_node(trait_nid_alt, trait_name, line, "trait")
                        trait_nid = trait_nid_alt
                    add_edge(parent_nid, trait_nid, "implements", line)

                decls = _first_child(node, ("declaration_list",))
                if decls is not None:
                    for child in decls.children:
                        if child.type != "function_item":
                            continue
                        ident = _first_child(child, ("identifier",))
                        if ident is None:
                            continue
                        mname = _text(ident)
                        mline = child.start_point[0] + 1
                        mnid = make_id(parent_nid, mname)
                        add_node(mnid, f"{mname}()", mline, "method")
                        add_edge(parent_nid, mnid, "method", mline)
                        body = _first_child(child, ("block",))
                        if body is not None:
                            function_bodies.append((mnid, body))
                continue

            # Top-level function
            if t == "function_item":
                ident = _first_child(node, ("identifier",))
                if ident is None:
                    continue
                fname = _text(ident)
                fnid = make_id(stem, fname)
                add_node(fnid, f"{fname}()", line, "function")
                add_edge(file_nid, fnid, "contains", line)
                body = _first_child(node, ("block",))
                if body is not None:
                    function_bodies.append((fnid, body))
                continue

        # ── Call-graph pass ───────────────────────────────────────────
        label_to_nid: dict[str, str] = {}
        for n in nodes:
            normalised = n.label.strip("()").lstrip(".")
            label_to_nid[normalised.lower()] = n.id

        seen_call_pairs: set[tuple[str, str]] = set()

        def walk_calls(node, caller_nid: str) -> None:
            if node.type in ("function_item", "function_signature_item"):
                return
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                callee: str | None = None
                if fn is not None:
                    if fn.type == "identifier":
                        callee = _text(fn)
                    elif fn.type == "field_expression":
                        field = fn.child_by_field_name("field")
                        if field is not None:
                            callee = _text(field)
                    elif fn.type == "scoped_identifier":
                        callee = _last_identifier(fn)
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
