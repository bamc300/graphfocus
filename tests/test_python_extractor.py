"""Tests for the Python AST extractor."""

import pytest

from graphfocus.extractors.python_extractor import PythonExtractor


@pytest.fixture
def extractor():
    return PythonExtractor()


class TestPythonExtractor:
    def test_extract_classes(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)

        node_labels = [n.label for n in result.nodes]
        assert "BaseModel" in node_labels
        assert "User" in node_labels
        assert "AdminUser" in node_labels

    def test_extract_functions(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)

        node_labels = [n.label for n in result.nodes]
        assert "validate_email()" in node_labels
        assert "create_user()" in node_labels

    def test_extract_methods(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)

        node_labels = [n.label for n in result.nodes]
        assert ".greet()" in node_labels
        assert ".save()" in node_labels

    def test_extract_inheritance(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)

        inherits_edges = [e for e in result.edges if e.relation == "inherits"]
        assert len(inherits_edges) >= 2  # User->BaseModel, AdminUser->User

    def test_extract_imports(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)

        import_edges = [e for e in result.edges if "import" in e.relation]
        assert len(import_edges) >= 2  # os, pathlib

    def test_extract_call_graph(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)

        call_edges = [e for e in result.edges if e.relation == "calls"]
        # save() calls validate_email(), create_user() calls validate_email()
        assert len(call_edges) >= 1

    def test_node_has_language(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)
        for node in result.nodes:
            assert node.language == "python"

    def test_node_has_kind(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)
        kinds = {n.kind for n in result.nodes}
        assert "class" in kinds
        assert "function" in kinds
        assert "module" in kinds

    def test_no_errors(self, extractor, python_fixture):
        result = extractor.extract(python_fixture)
        assert len(result.errors) == 0
