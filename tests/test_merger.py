"""Tests for the graph merger."""

from graphfocus.extractors.base import Edge, ExtractionResult, Node
from graphfocus.graph.merger import merge_extractions


class TestMergeExtractions:
    def test_merge_deduplicates_nodes(self):
        r1 = ExtractionResult(
            nodes=[Node(id="a", label="A"), Node(id="b", label="B")],
            edges=[],
        )
        r2 = ExtractionResult(
            nodes=[Node(id="b", label="B"), Node(id="c", label="C")],
            edges=[],
        )

        merged = merge_extractions([r1, r2])
        assert len(merged.nodes) == 3

    def test_merge_keeps_all_edges(self):
        r1 = ExtractionResult(
            nodes=[Node(id="a", label="A"), Node(id="b", label="B")],
            edges=[Edge(source="a", target="b", relation="calls")],
        )
        r2 = ExtractionResult(
            nodes=[Node(id="b", label="B"), Node(id="c", label="C")],
            edges=[Edge(source="b", target="c", relation="imports")],
        )

        merged = merge_extractions([r1, r2])
        assert len(merged.edges) == 2

    def test_merge_collects_errors(self):
        r1 = ExtractionResult(errors=["error1"])
        r2 = ExtractionResult(errors=["error2"])

        merged = merge_extractions([r1, r2])
        assert len(merged.errors) == 2

    def test_merge_empty_list(self):
        merged = merge_extractions([])
        assert len(merged.nodes) == 0
        assert len(merged.edges) == 0
