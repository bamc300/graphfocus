"""Tests for the C++ extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.cpp_extractor import CppExtractor


@pytest.fixture
def extractor() -> CppExtractor:
    return CppExtractor()


@pytest.fixture
def cpp_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "cpp" / "user_service.cpp"


class TestCppExtractor:
    def test_namespace(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("app") == "namespace"

    def test_classes(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("User") == "class"
        assert kinds.get("BaseService") == "class"
        assert kinds.get("UserService") == "class"

    def test_inheritance(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        inherits = [e for e in result.edges if e.relation == "inherits"]
        assert len(inherits) >= 1

    def test_out_of_class_methods_attach_to_class(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        svc = next(n for n in result.nodes if n.label == "UserService")
        labels = {n.id: n.label for n in result.nodes}
        method_names = {
            labels.get(e.target) for e in result.edges
            if e.relation == "method" and e.source == svc.id
        }
        assert "find()" in method_names
        assert "create()" in method_names

    def test_top_level_function(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "helper()" in labels

    def test_includes(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_no_errors(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, cpp_fixture):
        result = extractor.extract(cpp_fixture)
        for n in result.nodes:
            assert n.language == "cpp"
