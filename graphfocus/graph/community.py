"""Community detection using Leiden algorithm via graspologic."""

from __future__ import annotations

import logging

import networkx as nx

logger = logging.getLogger(__name__)


def detect_communities(g: nx.DiGraph, resolution: float = 1.0) -> dict[str, int]:
    """Detect communities in the graph using the Leiden algorithm.

    Args:
        g: A NetworkX DiGraph
        resolution: Leiden resolution parameter (higher = more communities)

    Returns:
        Dict mapping node ID -> community number
    """
    if g.number_of_nodes() == 0:
        return {}

    try:
        from graspologic.partition import leiden

        # Leiden needs an undirected graph
        undirected = g.to_undirected()
        partitions = leiden(undirected, resolution=resolution)

        # partitions is a dict: node_id -> community_id
        if isinstance(partitions, dict):
            return partitions

        # Some versions return list of sets
        communities: dict[str, int] = {}
        for idx, community_set in enumerate(partitions):
            for node_id in community_set:
                communities[node_id] = idx
        return communities

    except ImportError:
        logger.warning("graspologic not installed — skipping community detection")
        return {node: 0 for node in g.nodes()}
    except Exception as e:
        logger.warning(f"Community detection failed: {e}")
        return {node: 0 for node in g.nodes()}
