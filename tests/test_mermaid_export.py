"""Tests for the Mermaid exporter."""

from __future__ import annotations

from pathlib import Path

from graphfocus.output.mermaid_export import render_mermaid, write_mermaid


def _sample():
    nodes = [
        {"id": "a", "label": "UserService", "language": "java",
         "kind": "class", "community": 0},
        {"id": "b", "label": "findById()", "language": "java",
         "kind": "method", "community": 0},
        {"id": "c", "label": "users", "language": "sql",
         "kind": "table", "community": 1},
        {"id": "d", "label": "PaymentService", "language": "java",
         "kind": "class", "community": 2},
    ]
    edges = [
        {"source": "a", "target": "b", "relation": "method"},
        {"source": "a", "target": "c", "relation": "maps_to"},
        {"source": "d", "target": "c", "relation": "references"},
    ]
    return nodes, edges


class TestRender:
    def test_renders_flowchart_header(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges)
        assert body.startswith("flowchart LR")

    def test_includes_nodes_and_edges(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges)
        assert '"UserService"' in body
        assert '"findById()"' in body
        assert "-->|method|" in body
        assert "-->|maps_to|" in body

    def test_direction_option(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges, direction="TB")
        assert body.startswith("flowchart TB")

    def test_language_filter(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges, language="sql")
        assert '"users"' in body
        assert "UserService" not in body

    def test_kind_filter(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges, kind="class")
        assert "UserService" in body
        assert "PaymentService" in body
        assert "findById" not in body

    def test_community_filter(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges, community=2)
        assert "PaymentService" in body
        assert "UserService" not in body

    def test_roots_includes_neighbors(self):
        nodes, edges = _sample()
        body = render_mermaid(nodes, edges, roots=["a"])
        # a + its neighbors via edges: a, b, c
        assert "UserService" in body
        assert "findById" in body
        assert '"users"' in body
        # d is unrelated to a → must not appear
        assert "PaymentService" not in body

    def test_max_nodes_caps_output(self):
        # 5 nodes, max 2 → only top-2 by degree.
        nodes = [{"id": str(i), "label": f"n{i}", "language": "py",
                  "kind": "class"} for i in range(5)]
        edges = [{"source": "0", "target": str(i), "relation": "calls"}
                 for i in range(1, 5)]  # node 0 has degree 4
        body = render_mermaid(nodes, edges, max_nodes=2)
        # Node "0" (highest degree) must be present.
        assert '"n0"' in body

    def test_sanitises_unsafe_ids(self):
        nodes = [{"id": "foo.bar/baz", "label": "X", "language": "py",
                  "kind": "class"}]
        body = render_mermaid(nodes, [])
        assert "foo.bar/baz" not in body  # raw id should be replaced
        assert '"X"' in body

    def test_escapes_label_quotes(self):
        nodes = [{"id": "a", "label": 'has "quote"', "language": "py",
                  "kind": "class"}]
        body = render_mermaid(nodes, [])
        assert '"has \'quote\'"' in body


class TestWrite:
    def test_writes_mmd_file(self, tmp_path: Path):
        nodes, edges = _sample()
        out = tmp_path / "g.mmd"
        size = write_mermaid(nodes, edges, out)
        assert out.exists()
        assert size > 0
        assert out.read_text().startswith("flowchart")

    def test_markdown_wrap(self, tmp_path: Path):
        nodes, edges = _sample()
        out = tmp_path / "g.md"
        write_mermaid(nodes, edges, out, embed_in_markdown=True)
        text = out.read_text()
        assert text.startswith("```mermaid\n")
        assert text.endswith("```\n")
