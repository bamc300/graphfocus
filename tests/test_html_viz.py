"""Tests for the interactive HTML visualization generator.

Since v0.1.3 ``generate_html`` writes **two** files next to each other:
``graph.html`` (the UI shell) and ``graph-data.js`` (the data assigned to
``window.__GRAPHFOCUS_DATA__``). The HTML loads the data via a regular
``<script src="./graph-data.js">`` tag so it works straight from the
file system, no web server required.
"""

from __future__ import annotations

import json
import re

from graphfocus.extractors.base import Edge, Node
from graphfocus.output.html_viz import generate_html


def _sample_graph() -> tuple[list[Node], list[Edge]]:
    nodes = [
        Node(id="mod_a", label="a.py", language="python", kind="module",
             source_file="a.py", source_location="L1"),
        Node(id="mod_a_user", label="User", language="python", kind="class",
             source_file="a.py", source_location="L5"),
        Node(id="schema_users", label="users", language="sql", kind="table",
             source_file="schema.sql", source_location="L3"),
    ]
    edges = [
        Edge(source="mod_a", target="mod_a_user", relation="contains",
             confidence="EXTRACTED"),
        Edge(source="mod_a_user", target="schema_users", relation="references",
             confidence="INFERRED"),
        # Ghost target gets dropped at render time, not at extraction.
        Edge(source="mod_a_user", target="ghost", relation="calls",
             confidence="AMBIGUOUS"),
    ]
    return nodes, edges


def _read_payload(html_path):
    """Extract the JSON payload that lives in graph-data.js."""
    data_path = html_path.with_name("graph-data.js")
    raw = data_path.read_text(encoding="utf-8")
    match = re.match(r"window\.__GRAPHFOCUS_DATA__\s*=\s*(\{.*\});\s*$", raw, re.DOTALL)
    assert match, f"graph-data.js did not match expected shape: {raw[:120]!r}"
    return json.loads(match.group(1))


class TestHTMLViz:
    def test_writes_both_files(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out)
        assert out.exists() and out.stat().st_size > 0
        assert (tmp_path / "graph-data.js").exists()

    def test_html_references_data_file_and_libraries(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out)
        text = out.read_text(encoding="utf-8")
        assert "<!doctype html>" in text.lower()
        assert "graph-data.js" in text
        assert "sigma" in text
        assert "graphology" in text

    def test_data_file_is_valid_json_payload(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out, title="demo")
        payload = _read_payload(out)
        assert payload["title"] == "demo"
        assert len(payload["nodes"]) == 3
        assert {n["id"] for n in payload["nodes"]} == {
            "mod_a", "mod_a_user", "schema_users",
        }
        assert "python" in payload["languages"]
        assert "sql" in payload["languages"]
        assert set(payload["confidences"]) == {"EXTRACTED", "INFERRED", "AMBIGUOUS"}

    def test_nodes_have_precomputed_xy(self, tmp_path):
        """The whole point of v0.1.3 — the browser must not run layout."""
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out)
        payload = _read_payload(out)
        for n in payload["nodes"]:
            assert isinstance(n["x"], (int, float))
            assert isinstance(n["y"], (int, float))
            assert 0 <= n["x"] <= 1000
            assert 0 <= n["y"] <= 1000

    def test_color_by_selector_in_html(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out)
        text = out.read_text(encoding="utf-8")
        assert 'id="color-mode"' in text
        for opt in ("Language", "Kind", "Community"):
            assert f">{opt}<" in text

    def test_communities_propagate_to_payload(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        communities = {"mod_a": 0, "mod_a_user": 0, "schema_users": 1}
        generate_html(nodes, edges, out, communities=communities)
        payload = _read_payload(out)
        assert payload["community_count"] == 2
        by_id = {n["id"]: n for n in payload["nodes"]}
        assert by_id["mod_a"]["community"] == 0
        assert by_id["schema_users"]["community"] == 1
