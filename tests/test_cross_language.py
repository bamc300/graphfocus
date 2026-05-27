"""Tests for the cross-language linker."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.base import Edge, Node
from graphfocus.extractors.java_extractor import JavaExtractor
from graphfocus.extractors.sql_extractor import SQLExtractor
from graphfocus.graph.cross_language import link_cross_language


def _table(label: str, nid: str | None = None) -> Node:
    return Node(
        id=nid or f"table_{label.lower()}",
        label=label,
        language="sql",
        kind="table",
        source_file="schema.sql",
        source_location="L1",
    )


def _class(label: str, *, language: str = "java", annotations: list[str] | None = None,
           nid: str | None = None) -> Node:
    return Node(
        id=nid or f"cls_{label.lower()}",
        label=label,
        language=language,
        kind="class",
        source_file=f"{label}.{'cs' if language == 'csharp' else 'java'}",
        source_location="L1",
        metadata={"annotations" if language == "java" else "attributes": annotations or []},
    )


class TestLinker:
    def test_explicit_table_annotation_maps_to_table(self):
        nodes = [
            _table("orders"),
            _class("OrderEntity", annotations=["Entity", 'Table(name = "orders")']),
        ]
        new_edges = link_cross_language(nodes, [])
        assert len(new_edges) == 1
        edge = new_edges[0]
        assert edge.source == "cls_orderentity"
        assert edge.target == "table_orders"
        assert edge.relation == "maps_to"
        assert edge.confidence == "EXTRACTED"

    def test_entity_with_name_heuristic_uses_inferred(self):
        nodes = [
            _table("users"),
            _class("User", annotations=["Entity"]),
        ]
        new_edges = link_cross_language(nodes, [])
        assert len(new_edges) == 1
        assert new_edges[0].target == "table_users"
        assert new_edges[0].confidence == "INFERRED"

    def test_no_entity_marker_no_edge(self):
        nodes = [
            _table("users"),
            _class("User", annotations=["Service"]),
        ]
        assert link_cross_language(nodes, []) == []

    def test_no_matching_table_no_edge(self):
        nodes = [
            _table("orders"),
            _class("Customer", annotations=["Entity"]),
        ]
        assert link_cross_language(nodes, []) == []

    def test_csharp_attribute_with_arguments(self):
        nodes = [
            _table("orders"),
            _class("OrderEntity", language="csharp",
                   annotations=['Table("orders")']),
        ]
        new_edges = link_cross_language(nodes, [])
        assert len(new_edges) == 1
        assert new_edges[0].confidence == "EXTRACTED"

    def test_camelcase_to_snake_case(self):
        nodes = [
            _table("order_items"),
            _class("OrderItem", annotations=["Entity"]),
        ]
        new_edges = link_cross_language(nodes, [])
        assert len(new_edges) == 1
        assert new_edges[0].confidence == "INFERRED"

    def test_does_not_duplicate_existing_edge(self):
        nodes = [
            _table("users"),
            _class("User", annotations=["Entity"]),
        ]
        existing = [Edge(source="cls_user", target="table_users", relation="maps_to")]
        assert link_cross_language(nodes, existing) == []

    def test_plsql_table_is_a_valid_target(self):
        nodes = [
            Node(id="emp_table", label="employees", language="plsql", kind="table",
                 source_file="emp.pks", source_location="L1"),
            _class("Employee", annotations=["Entity"]),
        ]
        new_edges = link_cross_language(nodes, [])
        assert len(new_edges) == 1
        assert new_edges[0].target == "emp_table"


class TestEndToEndJavaSQL:
    """Real extractor output → linker → assert edge exists."""

    def test_orderentity_links_to_orders_table(self, fixtures_dir: Path):
        java = JavaExtractor().extract(fixtures_dir / "java" / "OrderEntity.java")
        sql = SQLExtractor().extract(fixtures_dir / "sql" / "schema.sql")

        all_nodes = java.nodes + sql.nodes
        all_edges = java.edges + sql.edges
        new_edges = link_cross_language(all_nodes, all_edges)

        # Look for a maps_to edge from OrderEntity to the orders table.
        maps_to = [e for e in new_edges if e.relation == "maps_to"]
        assert len(maps_to) >= 1, f"no maps_to edges found in {new_edges}"

        # Identify the OrderEntity node id and the orders table id.
        order_entity = next(n for n in all_nodes
                            if n.language == "java" and n.label == "OrderEntity")
        orders_table = next(n for n in all_nodes
                            if n.language == "sql" and n.kind == "table"
                            and n.label == "orders")

        match = [e for e in maps_to
                 if e.source == order_entity.id and e.target == orders_table.id]
        assert len(match) == 1
        # Explicit @Table("orders") → EXTRACTED, not INFERRED.
        assert match[0].confidence == "EXTRACTED"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
