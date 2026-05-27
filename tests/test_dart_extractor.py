"""Tests for the Dart extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.dart_extractor import DartExtractor


@pytest.fixture
def extractor() -> DartExtractor:
    return DartExtractor()


@pytest.fixture
def dart_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "dart" / "user_service.dart"


class TestDartExtractor:
    def test_classes_and_abstract(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("Repository") == "abstract_class"
        assert kinds.get("HttpRepository") == "class"
        assert kinds.get("UserService") == "class"

    def test_implements_edges(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        impl = [e for e in result.edges if e.relation == "implements"]
        assert len(impl) >= 1

    def test_mixin(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("Loggable") == "mixin"

    def test_imports(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_methods_attached_to_class(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        http = next(n for n in result.nodes if n.label == "HttpRepository")
        labels = {n.id: n.label for n in result.nodes}
        method_names = {
            labels.get(e.target) for e in result.edges
            if e.relation == "method" and e.source == http.id
        }
        assert "find()" in method_names
        assert "save()" in method_names

    def test_top_level_function(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "helper()" in labels

    def test_no_errors(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, dart_fixture):
        result = extractor.extract(dart_fixture)
        for n in result.nodes:
            assert n.language == "dart"
