"""Tests for the PL/SQL extractor."""

import pytest

from graphfocus.extractors.plsql_extractor import PLSQLExtractor


@pytest.fixture
def extractor():
    return PLSQLExtractor()


class TestPLSQLExtractor:
    def test_extract_package(self, extractor, plsql_fixture):
        result = extractor.extract(plsql_fixture)

        pkg_nodes = [n for n in result.nodes if n.kind == "package_spec"]
        assert len(pkg_nodes) >= 1
        assert any("pkg_users" in n.label.lower() for n in pkg_nodes)

    def test_extract_procedures(self, extractor, plsql_fixture):
        result = extractor.extract(plsql_fixture)

        proc_nodes = [n for n in result.nodes if n.kind == "procedure"]
        proc_names = [n.label for n in proc_nodes]
        assert any("create_user" in name.lower() for name in proc_names)
        assert any("update_user_status" in name.lower() for name in proc_names)

    def test_extract_functions(self, extractor, plsql_fixture):
        result = extractor.extract(plsql_fixture)

        func_nodes = [n for n in result.nodes if n.kind == "function"]
        assert len(func_nodes) >= 1
        assert any("get_user_by_id" in n.label.lower() for n in func_nodes)

    def test_node_has_plsql_language(self, extractor, plsql_fixture):
        result = extractor.extract(plsql_fixture)
        for node in result.nodes:
            assert node.language == "plsql"

    def test_no_errors(self, extractor, plsql_fixture):
        result = extractor.extract(plsql_fixture)
        assert len(result.errors) == 0
