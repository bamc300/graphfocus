"""Graph query endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

_DEFAULT_GRAPH = Path("graphfocus-out/graph.json")


def _load_graph(graph_path: Path = _DEFAULT_GRAPH) -> dict:
    """Load graph from JSON file."""
    if not graph_path.exists():
        raise HTTPException(status_code=404, detail="No graph found. Run analyze first.")
    return json.loads(graph_path.read_text(encoding="utf-8"))


@router.get("/graph")
async def get_graph():
    """Get the full graph."""
    return _load_graph()


@router.get("/graph/nodes")
async def get_nodes(
    language: str | None = Query(None, description="Filter by language"),
    kind: str | None = Query(None, description="Filter by kind"),
):
    """Get nodes with optional filters."""
    data = _load_graph()
    nodes = data.get("nodes", [])

    if language:
        nodes = [n for n in nodes if n.get("language") == language]
    if kind:
        nodes = [n for n in nodes if n.get("kind") == kind]

    return {"nodes": nodes, "total": len(nodes)}


@router.get("/graph/search")
async def search(q: str = Query(..., description="Search query")):
    """Search nodes by label."""
    data = _load_graph()
    q_lower = q.lower()

    matches = [
        n for n in data.get("nodes", [])
        if q_lower in n.get("label", "").lower() or q_lower in n.get("id", "").lower()
    ]

    return {"query": q, "results": matches, "total": len(matches)}


@router.get("/graph/stats")
async def graph_stats():
    """Get graph statistics."""
    data = _load_graph()
    return data.get("stats", {})
