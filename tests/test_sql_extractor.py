"""Tests for the SQL DDL extractor."""

import pytest

from graphfocus.extractors.sql_extractor import SQLExtractor


@pytest.fixture
def extractor():
    return SQLExtractor()


class TestSQLExtractor:
    def test_extract_tables(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)

        table_nodes = [n for n in result.nodes if n.kind == "table"]
        table_names = [n.label.lower() for n in table_nodes]
        assert "users" in table_names
        assert "orders" in table_names
        assert "order_items" in table_names

    def test_extract_columns(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)

        col_nodes = [n for n in result.nodes if n.kind == "column"]
        assert len(col_nodes) > 0

    def test_extract_foreign_keys(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)

        fk_edges = [e for e in result.edges if e.relation == "foreign_key"]
        assert len(fk_edges) >= 2  # orders->users, order_items->orders

    def test_extract_indexes(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)

        index_nodes = [n for n in result.nodes if n.kind == "index"]
        assert len(index_nodes) >= 1

    def test_extract_views(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)

        view_nodes = [n for n in result.nodes if n.kind == "view"]
        assert len(view_nodes) >= 1

    def test_node_has_sql_language(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)
        for node in result.nodes:
            assert node.language == "sql"

    def test_no_errors(self, extractor, sql_fixture):
        result = extractor.extract(sql_fixture)
        assert len(result.errors) == 0
