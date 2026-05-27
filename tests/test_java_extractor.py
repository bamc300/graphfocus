"""Tests for the Java AST extractor."""

import pytest

from graphfocus.extractors.java_extractor import JavaExtractor


@pytest.fixture
def extractor():
    return JavaExtractor()


class TestJavaExtractor:
    def test_extract_class(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)

        node_labels = [n.label for n in result.nodes]
        assert "UserService" in node_labels

    def test_extract_methods(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)

        node_labels = [n.label for n in result.nodes]
        assert "findById()" in node_labels
        assert "create()" in node_labels
        assert "update()" in node_labels

    def test_extract_spring_annotations(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)

        # Find the UserService node
        service_nodes = [n for n in result.nodes if n.label == "UserService"]
        assert len(service_nodes) == 1
        assert "Service" in service_nodes[0].metadata.get("annotations", [])

    def test_extract_imports(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)

        import_edges = [e for e in result.edges if e.relation == "imports"]
        assert len(import_edges) >= 3

    def test_extract_fields(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)

        field_nodes = [n for n in result.nodes if n.kind == "field"]
        assert len(field_nodes) >= 1

    def test_node_has_java_language(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)
        code_nodes = [n for n in result.nodes if n.kind != "file"]
        for node in code_nodes:
            assert node.language == "java"

    def test_no_errors(self, extractor, java_fixture):
        result = extractor.extract(java_fixture)
        assert len(result.errors) == 0
