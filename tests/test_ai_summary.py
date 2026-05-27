"""Tests for the LLM-friendly Markdown summary."""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import Edge, Node
from graphfocus.output.ai_summary import render_ai_summary


def _graph():
    nodes = [
        Node(id="mod_a", label="main.py", language="python", kind="file",
             source_file="main.py", source_location="L1"),
        Node(id="mod_a_user", label="UserService", language="python", kind="class",
             source_file="main.py", source_location="L5",
             metadata={"decorators": ["dataclass"]}),
        Node(id="mod_a_user_create", label="create()", language="python", kind="method",
             source_file="main.py", source_location="L10"),
        Node(id="mod_a_save", label="save()", language="python", kind="function",
             source_file="main.py", source_location="L20"),
        Node(id="java_user", label="OrderEntity", language="java", kind="class",
             source_file="OrderEntity.java", source_location="L1",
             metadata={"annotations": ["Entity", 'Table("orders")']}),
        Node(id="sql_orders", label="orders", language="sql", kind="table",
             source_file="schema.sql", source_location="L3"),
    ]
    edges = [
        Edge(source="mod_a", target="mod_a_user", relation="contains"),
        Edge(source="mod_a_user", target="mod_a_user_create", relation="method"),
        Edge(source="mod_a_user_create", target="mod_a_save", relation="calls",
             confidence="INFERRED"),
        Edge(source="java_user", target="sql_orders", relation="maps_to",
             confidence="EXTRACTED"),
    ]
    return nodes, edges


class TestAISummary:
    def test_writes_file(self, tmp_path: Path):
        nodes, edges = _graph()
        out = tmp_path / "AI_SUMMARY.md"
        size = render_ai_summary(nodes, edges, out)
        assert out.exists()
        assert size > 0

    def test_cross_language_section_present(self, tmp_path: Path):
        nodes, edges = _graph()
        out = tmp_path / "AI_SUMMARY.md"
        render_ai_summary(nodes, edges, out)
        text = out.read_text()
        assert "Cross-language links" in text
        assert "OrderEntity" in text
        assert "orders" in text
        assert "maps_to" in text

    def test_classes_and_methods_appear_under_language(self, tmp_path: Path):
        nodes, edges = _graph()
        out = tmp_path / "AI_SUMMARY.md"
        render_ai_summary(nodes, edges, out)
        text = out.read_text()
        # Per-language section
        assert "## python" in text
        # Class line
        assert "UserService [class]" in text
        # Method indented under it
        assert "create()" in text

    def test_call_arrows_render(self, tmp_path: Path):
        nodes, edges = _graph()
        out = tmp_path / "AI_SUMMARY.md"
        render_ai_summary(nodes, edges, out)
        text = out.read_text()
        # create() calls save()
        assert "→ save" in text

    def test_annotations_inline(self, tmp_path: Path):
        nodes, edges = _graph()
        out = tmp_path / "AI_SUMMARY.md"
        render_ai_summary(nodes, edges, out)
        text = out.read_text()
        # OrderEntity has @Entity annotation
        assert "@Entity" in text

    def test_compact_size_for_small_graph(self, tmp_path: Path):
        nodes, edges = _graph()
        out = tmp_path / "AI_SUMMARY.md"
        size = render_ai_summary(nodes, edges, out)
        # The 6-node sample should fit in a tweet-sized window.
        assert size < 2000
