"""Export graph to JSON format."""

from __future__ import annotations

import json
from pathlib import Path

from graphfocus.extractors.base import Edge, Node


def export_json(
    nodes: list[Node],
    edges: list[Edge],
    output_path: Path,
) -> None:
    """Export nodes and edges to a JSON file.

    Args:
        nodes: List of Node objects
        edges: List of Edge objects
        output_path: Path to write the JSON file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "version": "1.0",
        "generator": "graphfocus",
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "languages": list({n.language for n in nodes if n.language}),
            "kinds": list({n.kind for n in nodes if n.kind}),
        },
    }

    # Always write UTF-8 — node labels may contain arrows (→), Unicode
    # punctuation and non-ASCII identifiers. On Windows write_text()
    # otherwise defaults to cp1252 and crashes.
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
