"""Graph building, merging, and community detection."""

from graphfocus.graph.builder import build_graph
from graphfocus.graph.community import detect_communities
from graphfocus.graph.merger import merge_extractions

__all__ = ["build_graph", "merge_extractions", "detect_communities"]
