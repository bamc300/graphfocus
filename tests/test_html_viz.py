"""Tests for the interactive HTML visualization generator."""

from __future__ import annotations

import json

from graphfocus.extractors.base import Edge, Node
from graphfocus.output.html_viz import generate_html


def _sample_graph() -> tuple[list[Node], list[Edge]]:
    nodes = [
        Node(id="mod_a", label="a.py", language="python", kind="module", source_file="a.py", source_location="L1"),
        Node(id="mod_a_user", label="User", language="python", kind="class", source_file="a.py", source_location="L5"),
        Node(id="schema_users", label="users", language="sql", kind="table", source_file="schema.sql", source_location="L3"),
    ]
    edges = [
        Edge(source="mod_a", target="mod_a_user", relation="contains", confidence="EXTRACTED"),
        Edge(source="mod_a_user", target="schema_users", relation="references", confidence="INFERRED"),
        Edge(source="mod_a_user", target="ghost", relation="calls", confidence="AMBIGUOUS"),  # ghost target stripped
    ]
    return nodes, edges


class TestHTMLViz:
    def test_writes_file(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_contains_html_skeleton(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out)
        text = out.read_text(encoding="utf-8")
        assert "<!doctype html>" in text.lower()
        assert "d3.v7.min.js" in text
        assert 'id="graph-data"' in text

    def test_embeds_valid_json_payload(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        generate_html(nodes, edges, out, title="demo")
        text = out.read_text(encoding="utf-8")

        # Extract the inline JSON payload and validate it.
        start = text.index('id="graph-data" type="application/json">')
        start = text.index(">", start) + 1
        end = text.index("</script>", start)
        payload = json.loads(text[start:end])

        assert payload["title"] == "demo"
        assert len(payload["nodes"]) == 3
        assert {n["id"] for n in payload["nodes"]} == {"mod_a", "mod_a_user", "schema_users"}
        assert "python" in payload["languages"]
        assert "sql" in payload["languages"]
        assert set(payload["confidences"]) == {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
        # Node carries its language color and degree.
        user_node = next(n for n in payload["nodes"] if n["id"] == "mod_a_user")
        assert user_node["color"].startswith("#")
        assert user_node["degree"] >= 1

    def test_unused_kwargs_accepted(self, tmp_path):
        nodes, edges = _sample_graph()
        out = tmp_path / "viz.html"
        # communities is optional; passing it should not fail.
        generate_html(nodes, edges, out, communities={"mod_a": 0, "mod_a_user": 1})
        assert out.exists()
