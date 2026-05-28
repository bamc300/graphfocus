"""Community detection using the Leiden algorithm via igraph.

We use ``igraph`` (the C implementation with Python bindings) because it
publishes manylinux + macOS wheels for every supported Python version,
including 3.14 — unlike ``graspologic``, which lags behind. The fallback
when ``igraph`` is not installed is a single community containing every
node, so callers never crash on missing optional dependencies.
"""

from __future__ import annotations

import logging

import networkx as nx

logger = logging.getLogger(__name__)


def detect_communities(g: nx.DiGraph, resolution: float = 1.0) -> dict[str, int]:
    """Detect communities in the graph using the Leiden algorithm.

    Args:
        g: A NetworkX DiGraph (it will be treated as undirected for clustering).
        resolution: Leiden resolution parameter (higher → more, smaller
            communities; lower → fewer, larger).

    Returns:
        Dict mapping NetworkX node ID → integer community id (0-indexed).
        Returns ``{node: 0 for node in g}`` when igraph is unavailable.
    """
    if g.number_of_nodes() == 0:
        return {}

    try:
        import igraph as ig
    except ImportError:
        logger.warning(
            "igraph not installed — skipping community detection. "
            "Install with: pip install 'graphfocus[community]'"
        )
        return {node: 0 for node in g.nodes()}

    try:
        # Build an undirected igraph Graph from the NetworkX one. We map
        # NetworkX node ids to igraph integer vertex indices and remember
        # the inverse so we can hand back the user's original ids.
        nodes = list(g.nodes())
        index_of = {nid: i for i, nid in enumerate(nodes)}

        undirected = g.to_undirected()
        edges = [
            (index_of[u], index_of[v])
            for u, v in undirected.edges()
            if u in index_of and v in index_of
        ]

        h = ig.Graph(n=len(nodes), edges=edges, directed=False)
        partition = h.community_leiden(
            objective_function="modularity",
            resolution=resolution,
        )

        communities: dict[str, int] = {}
        for community_id, vertex_indices in enumerate(partition):
            for vidx in vertex_indices:
                communities[nodes[vidx]] = community_id
        return communities

    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"Community detection failed: {e}")
        return {node: 0 for node in g.nodes()}
