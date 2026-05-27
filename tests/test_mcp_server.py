"""Tests for the GraphFocus MCP server.

We exercise the tools by calling them through ``FastMCP.call_tool`` so we
verify the same code path an MCP client would hit, just in-process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphfocus.mcp_server import GraphStore, build_server


def _write_sample_graph(path: Path) -> None:
    """Write a minimal graph.json with a handful of cross-language nodes."""
    payload = {
        "nodes": [
            {"id": "py_main", "label": "main.py", "kind": "file", "language": "python",
             "source_file": "main.py", "source_location": "L1"},
            {"id": "py_validate", "label": "validate()", "kind": "function",
             "language": "python", "source_file": "main.py", "source_location": "L5"},
            {"id": "py_handler", "label": "handler()", "kind": "function",
             "language": "python", "source_file": "main.py", "source_location": "L20"},
            {"id": "java_user", "label": "User", "kind": "class", "language": "java",
             "source_file": "User.java", "source_location": "L1"},
            {"id": "sql_users", "label": "users", "kind": "table", "language": "sql",
             "source_file": "schema.sql", "source_location": "L1"},
        ],
        "edges": [
            {"source": "py_handler", "target": "py_validate", "relation": "calls",
             "confidence": "INFERRED"},
            {"source": "py_main", "target": "py_handler", "relation": "contains",
             "confidence": "EXTRACTED"},
            {"source": "java_user", "target": "sql_users", "relation": "maps_to",
             "confidence": "EXTRACTED"},
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def graph_path(tmp_path: Path) -> Path:
    p = tmp_path / "graph.json"
    _write_sample_graph(p)
    return p


@pytest.fixture
def store(graph_path: Path) -> GraphStore:
    s = GraphStore(graph_path)
    s.ensure_loaded()
    return s


class TestGraphStore:
    def test_loads_nodes_and_edges(self, store: GraphStore):
        assert len(store.nodes) == 5
        assert len(store.edges) == 3

    def test_outgoing_and_incoming_indexed(self, store: GraphStore):
        out = store.outgoing("py_handler")
        assert any(e["target"] == "py_validate" for e in out)
        inc = store.incoming("py_validate")
        assert any(e["source"] == "py_handler" for e in inc)

    def test_reload_on_mtime_change(self, graph_path: Path, store: GraphStore):
        # First load already done by fixture.
        assert len(store.nodes) == 5
        # Bump the file: add a new node and bump mtime.
        new = {
            "nodes": [{"id": "new", "label": "extra", "kind": "class",
                       "language": "go", "source_file": "x.go", "source_location": "L1"}],
            "edges": [],
        }
        graph_path.write_text(json.dumps(new), encoding="utf-8")
        # Force a mtime advance on systems with coarse mtime resolution.
        import os, time
        new_time = graph_path.stat().st_mtime + 2
        os.utime(graph_path, (new_time, new_time))
        store.ensure_loaded()
        assert len(store.nodes) == 1
        assert store.nodes[0]["label"] == "extra"


class TestMCPTools:
    """Call the registered FastMCP tools end-to-end via call_tool()."""

    @pytest.fixture
    def server(self, graph_path: Path):
        return build_server(graph_path)

    @pytest.mark.asyncio
    async def test_find_symbol_matches_label(self, server):
        result = await server.call_tool("find_symbol", {"query": "validate"})
        structured = json.loads(result[0].text)
        assert structured["total"] >= 1
        assert any(r["id"] == "py_validate" for r in structured["results"])

    @pytest.mark.asyncio
    async def test_find_symbol_filters_by_language(self, server):
        result = await server.call_tool(
            "find_symbol", {"query": "user", "language": "sql"},
        )
        structured = json.loads(result[0].text)
        assert all(r["language"] == "sql" for r in structured["results"])

    @pytest.mark.asyncio
    async def test_get_node_returns_neighbors(self, server):
        result = await server.call_tool("get_node", {"node_id": "py_handler"})
        structured = json.loads(result[0].text)
        assert structured["node"]["id"] == "py_handler"
        out_targets = {e["target"] for e in structured["outgoing"]}
        assert "py_validate" in out_targets
        in_sources = {e["source"] for e in structured["incoming"]}
        assert "py_main" in in_sources

    @pytest.mark.asyncio
    async def test_get_node_missing(self, server):
        result = await server.call_tool("get_node", {"node_id": "nope"})
        structured = json.loads(result[0].text)
        assert "error" in structured

    @pytest.mark.asyncio
    async def test_get_neighbors_two_hops(self, server):
        result = await server.call_tool(
            "get_neighbors", {"node_id": "py_main", "depth": 2},
        )
        structured = json.loads(result[0].text)
        ids = {n["id"] for n in structured["nodes"]}
        # main → handler (depth 1) → validate (depth 2)
        assert "py_handler" in ids
        assert "py_validate" in ids

    @pytest.mark.asyncio
    async def test_find_callers(self, server):
        result = await server.call_tool("find_callers", {"symbol": "validate"})
        structured = json.loads(result[0].text)
        assert len(structured["matches"]) >= 1
        callers = structured["matches"][0]["callers"]
        assert any(c["caller"]["id"] == "py_handler" for c in callers)

    @pytest.mark.asyncio
    async def test_find_path(self, server):
        result = await server.call_tool(
            "find_path", {"source": "py_main", "target": "py_validate"},
        )
        structured = json.loads(result[0].text)
        assert structured["length"] == 2
        chain = [n["id"] for n in structured["path_nodes"]]
        assert chain[0] == "py_main"
        assert chain[-1] == "py_validate"

    @pytest.mark.asyncio
    async def test_list_languages(self, server):
        result = await server.call_tool("list_languages", {})
        structured = json.loads(result[0].text)
        langs = {item["language"] for item in structured["languages"]}
        assert {"python", "java", "sql"}.issubset(langs)

    @pytest.mark.asyncio
    async def test_get_stats(self, server):
        result = await server.call_tool("get_stats", {})
        structured = json.loads(result[0].text)
        assert structured["total_nodes"] == 5
        assert structured["total_edges"] == 3
        assert "calls" in structured["by_relation"]

    @pytest.mark.asyncio
    async def test_cross_language_links(self, server):
        result = await server.call_tool("cross_language_links", {})
        structured = json.loads(result[0].text)
        # The java_user → sql_users maps_to edge crosses languages.
        assert structured["total"] >= 1
        edge = next(e for e in structured["edges"]
                    if e["source"] == "java_user")
        assert edge["target_language"] == "sql"
        assert edge["source_language"] == "java"
