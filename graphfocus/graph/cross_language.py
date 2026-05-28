"""Cross-language relationship detection.

After every extractor has run and the per-file results are merged, this
module looks across the combined node set and infers edges that no single
extractor could see on its own — for example:

  * A Java class annotated ``@Entity`` / ``@Table("orders")`` referencing
    a table defined in ``schema.sql``.
  * A C# class annotated ``[Table("orders")]`` referencing the same table.
  * A class whose name matches a known table by simple singular/plural
    heuristics (``User`` ↔ ``users``) — emitted with lower confidence.

The linker is conservative: it only emits a new edge when both endpoints
already exist as nodes. It never creates ghost targets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from graphfocus.extractors.base import Edge, Node

# Annotations / attributes that mean "this class maps to a DB table".
_ENTITY_MARKERS = {"Entity", "Table", "MappedSuperclass"}

# Languages whose nodes can be the *source* of a cross-language ORM edge.
_ORM_SOURCE_LANGUAGES = {"java", "csharp"}

# Languages whose nodes are valid table *targets*.
_TABLE_LANGUAGES = {"sql", "plsql"}


def link_cross_language(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
) -> list[Edge]:
    """Return the list of *new* edges discovered by cross-language analysis.

    The returned edges are additive — callers concatenate them to the
    existing edge list. Existing nodes/edges are never modified.
    """
    nodes = list(nodes)
    edges = list(edges)

    table_index = _build_table_index(nodes)
    if not table_index:
        return []

    existing_edges: set[tuple[str, str, str]] = {
        (e.source, e.target, e.relation) for e in edges
    }
    new_edges: list[Edge] = []

    for node in nodes:
        if node.language not in _ORM_SOURCE_LANGUAGES:
            continue
        if node.kind not in ("class", "interface", "struct"):
            continue
        markers = _entity_markers(node)
        if not markers:
            continue

        explicit_table = _explicit_table_name(node)
        if explicit_table is not None:
            table_nid = table_index.get(explicit_table.lower())
            if table_nid:
                _maybe_add(new_edges, existing_edges, node, table_nid,
                           relation="maps_to", confidence="EXTRACTED")
                continue

        # Fall back to name-based heuristics (singular/plural).
        for candidate in _name_candidates(node.label):
            table_nid = table_index.get(candidate.lower())
            if table_nid:
                _maybe_add(new_edges, existing_edges, node, table_nid,
                           relation="maps_to", confidence="INFERRED")
                break

    return new_edges


# ── internals ───────────────────────────────────────────────────────────────


def _build_table_index(nodes: list[Node]) -> dict[str, str]:
    """Map lowercased table name → node id."""
    out: dict[str, str] = {}
    for n in nodes:
        if n.language in _TABLE_LANGUAGES and n.kind == "table":
            out[n.label.lower()] = n.id
    return out


def _entity_markers(node: Node) -> list[str]:
    """Return the entity-related annotations/attributes on this node, if any."""
    meta = node.metadata or {}
    found: list[str] = []
    for key in ("annotations", "attributes"):
        for ann in meta.get(key, []) or []:
            base = _strip_args(ann)
            if base in _ENTITY_MARKERS:
                found.append(ann)
    return found


def _explicit_table_name(node: Node) -> str | None:
    """Extract the table name from ``@Table("name")`` or ``[Table("name")]``.

    Tree-sitter usually strips the argument list from the annotation name,
    so by default we won't have it. We still handle the case where an
    extractor preserved it in metadata or the raw annotation string.
    """
    meta = node.metadata or {}
    for key in ("annotations", "attributes"):
        for ann in meta.get(key, []) or []:
            m = re.search(r'Table\s*\(\s*(?:name\s*=\s*)?"([^"]+)"', ann)
            if m:
                return m.group(1)
    raw = meta.get("table_name")
    return raw if isinstance(raw, str) else None


def _name_candidates(label: str) -> list[str]:
    """Generate plausible table names from a class label."""
    if not label:
        return []
    # Strip trailing parens / decorations the extractor may have added.
    name = label.strip().rstrip("()").lstrip(".")
    # CamelCase → snake_case
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    candidates = {name.lower(), snake}
    for base in list(candidates):
        candidates.add(base + "s")           # User -> users
        if base.endswith("y"):
            candidates.add(base[:-1] + "ies")  # Category -> categories
        if base.endswith("s"):
            candidates.add(base[:-1])        # Users -> user
    return list(candidates)


def _strip_args(annotation: str) -> str:
    """``@Table(name="x")`` → ``Table``."""
    return re.sub(r"\(.*\)$", "", annotation).strip()


def _maybe_add(
    new_edges: list[Edge],
    existing: set[tuple[str, str, str]],
    src: Node,
    tgt_id: str,
    *,
    relation: str,
    confidence: str,
) -> None:
    key = (src.id, tgt_id, relation)
    if key in existing:
        return
    existing.add(key)
    new_edges.append(Edge(
        source=src.id,
        target=tgt_id,
        relation=relation,
        confidence=confidence,
        source_file=src.source_file,
        source_location=src.source_location,
        weight=0.7,
    ))
