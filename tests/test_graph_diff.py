"""Tests for the graph snapshot diff."""

from __future__ import annotations

from graphfocus.graph.diff import diff_graphs


def _graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


class TestDiffNodes:
    def test_added_and_removed(self):
        old = _graph(
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            [],
        )
        new = _graph(
            [{"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
            [],
        )
        d = diff_graphs(old, new)
        assert [n["id"] for n in d.added_nodes] == ["c"]
        assert [n["id"] for n in d.removed_nodes] == ["a"]

    def test_changed_node_tracked_fields(self):
        old = _graph([{"id": "x", "label": "X", "kind": "class",
                       "source_location": "L10"}], [])
        new = _graph([{"id": "x", "label": "X", "kind": "class",
                       "source_location": "L20"}], [])
        d = diff_graphs(old, new)
        assert len(d.changed_nodes) == 1
        change = d.changed_nodes[0]
        assert change["id"] == "x"
        assert "source_location" in change["changes"]
        assert change["changes"]["source_location"]["before"] == "L10"
        assert change["changes"]["source_location"]["after"] == "L20"


class TestDiffEdges:
    def test_edge_identity_uses_source_target_relation(self):
        old = _graph(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "relation": "calls"}],
        )
        new = _graph(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "relation": "calls"},
             {"source": "a", "target": "b", "relation": "extends"}],
        )
        d = diff_graphs(old, new)
        assert d.added_edges == [
            {"source": "a", "target": "b", "relation": "extends"},
        ]
        assert d.removed_edges == []


class TestTotals:
    def test_no_change_means_empty_diff(self):
        g = _graph(
            [{"id": "a", "label": "A"}],
            [{"source": "a", "target": "a", "relation": "self"}],
        )
        d = diff_graphs(g, g)
        assert d.total_changes == 0

    def test_to_dict_summary_matches_lists(self):
        old = _graph([{"id": "a", "label": "A"}], [])
        new = _graph(
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            [{"source": "a", "target": "b", "relation": "calls"}],
        )
        d = diff_graphs(old, new).to_dict()
        assert d["summary"]["added_nodes"] == 1
        assert d["summary"]["added_edges"] == 1
        assert d["summary"]["removed_nodes"] == 0
