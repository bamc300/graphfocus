"""Build a NetworkX graph from extraction results."""

from __future__ import annotations

import networkx as nx

from graphfocus.extractors.base import Edge, Node


def build_graph(nodes: list[Node], edges: list[Edge]) -> nx.DiGraph:
    """Build a directed NetworkX graph from extracted nodes and edges.

    Args:
        nodes: List of Node objects from extractors
        edges: List of Edge objects from extractors

    Returns:
        A NetworkX DiGraph with node and edge attributes
    """
    g = nx.DiGraph()

    for node in nodes:
        g.add_node(
            node.id,
            label=node.label,
            file_type=node.file_type,
            source_file=node.source_file,
            source_location=node.source_location,
            language=node.language,
            kind=node.kind,
            **node.metadata,
        )

    for edge in edges:
        g.add_edge(
            edge.source,
            edge.target,
            relation=edge.relation,
            confidence=edge.confidence,
            source_file=edge.source_file,
            source_location=edge.source_location,
            weight=edge.weight,
            **edge.metadata,
        )

    return g


def graph_stats(g: nx.DiGraph) -> dict:
    """Compute summary statistics for a graph."""
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "density": nx.density(g),
        "components": nx.number_weakly_connected_components(g),
        "languages": set(
            data.get("language", "unknown")
            for _, data in g.nodes(data=True)
            if data.get("language")
        ),
        "kinds": set(
            data.get("kind", "unknown")
            for _, data in g.nodes(data=True)
            if data.get("kind")
        ),
    }
