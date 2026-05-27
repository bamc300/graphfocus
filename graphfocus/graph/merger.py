"""Merge and deduplicate extraction results from multiple extractors."""

from __future__ import annotations

from graphfocus.extractors.base import Edge, ExtractionResult, Node


def merge_extractions(results: list[ExtractionResult]) -> ExtractionResult:
    """Merge multiple ExtractionResults, deduplicating nodes by ID.

    Edges are kept as-is (duplicates are allowed since they may represent
    different relationships between the same nodes).

    Args:
        results: List of ExtractionResult objects to merge

    Returns:
        A single merged ExtractionResult
    """
    seen_node_ids: set[str] = set()
    merged_nodes: list[Node] = []
    merged_edges: list[Edge] = []
    merged_errors: list[str] = []

    for result in results:
        for node in result.nodes:
            if node.id not in seen_node_ids:
                seen_node_ids.add(node.id)
                merged_nodes.append(node)

        merged_edges.extend(result.edges)
        merged_errors.extend(result.errors)

    # Remove edges pointing to nonexistent nodes (optional strictness)
    valid_edges = [
        e for e in merged_edges
        if e.source in seen_node_ids or e.target in seen_node_ids
    ]

    return ExtractionResult(
        nodes=merged_nodes,
        edges=valid_edges,
        errors=merged_errors,
    )
