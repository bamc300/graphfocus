"""Regression tests for v0.3.1: every file we write must be UTF-8.

The bug we're guarding against: on Windows, ``Path.write_text(s)``
defaults to ``cp1252`` and crashes when ``s`` contains characters like
``→`` (U+2192) that the cache appears in node labels and metadata.
"""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import Edge, Node
from graphfocus.output.ai_summary import render_ai_summary
from graphfocus.output.json_export import export_json
from graphfocus.output.mermaid_export import write_mermaid
from graphfocus.output.obsidian import generate_obsidian_vault
from graphfocus.output.report import generate_report

# The exact character from the user's traceback.
_ARROW = "→"


def _unicode_nodes() -> list[Node]:
    return [
        Node(id="a", label=f"Foo{_ARROW}Bar", kind="class", language="python",
             source_file="a.py", source_location="L1"),
        Node(id="b", label=f"baz{_ARROW}qux", kind="function", language="python",
             source_file="a.py", source_location="L5"),
    ]


def _unicode_edges() -> list[Edge]:
    return [
        Edge(source="a", target="b", relation="calls", confidence="INFERRED"),
    ]


class TestUtf8Output:
    """Every output writer must keep U+2192 intact regardless of locale."""

    def test_export_json_keeps_unicode(self, tmp_path: Path):
        out = tmp_path / "graph.json"
        export_json(_unicode_nodes(), _unicode_edges(), out)
        text = out.read_bytes().decode("utf-8")
        assert _ARROW in text

    def test_report_keeps_unicode(self, tmp_path: Path):
        out = tmp_path / "REPORT.md"
        generate_report(
            _unicode_nodes(), _unicode_edges(),
            {"total_files": 1, "total_words": 10, "by_type": {"code": 1}},
            out,
        )
        text = out.read_bytes().decode("utf-8")
        assert _ARROW in text

    def test_ai_summary_keeps_unicode(self, tmp_path: Path):
        out = tmp_path / "AI_SUMMARY.md"
        render_ai_summary(_unicode_nodes(), _unicode_edges(), out)
        text = out.read_bytes().decode("utf-8")
        assert _ARROW in text

    def test_mermaid_keeps_unicode(self, tmp_path: Path):
        out = tmp_path / "graph.mmd"
        nodes_dict = [n.to_dict() for n in _unicode_nodes()]
        edges_dict = [e.to_dict() for e in _unicode_edges()]
        write_mermaid(nodes_dict, edges_dict, out)
        text = out.read_bytes().decode("utf-8")
        assert _ARROW in text

    def test_obsidian_keeps_unicode(self, tmp_path: Path):
        vault = tmp_path / "vault"
        generate_obsidian_vault(_unicode_nodes(), _unicode_edges(), vault)
        # All notes plus the index must decode cleanly as UTF-8.
        for md in vault.rglob("*.md"):
            md.read_bytes().decode("utf-8")
