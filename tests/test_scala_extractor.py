"""Tests for the Scala extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.scala_extractor import ScalaExtractor


@pytest.fixture
def extractor() -> ScalaExtractor:
    return ScalaExtractor()


@pytest.fixture
def sc_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "scala" / "UserService.scala"


class TestScalaExtractor:
    def test_trait_class_case_class_object(self, extractor, sc_fixture):
        result = extractor.extract(sc_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("UserRepository") == "trait"
        assert kinds.get("User") == "case_class"
        assert kinds.get("UserService") == "class"
        assert kinds.get("Constants") == "object"

    def test_methods_attached_to_class(self, extractor, sc_fixture):
        result = extractor.extract(sc_fixture)
        svc = next(n for n in result.nodes if n.label == "UserService")
        labels = {n.id: n.label for n in result.nodes}
        method_names = {
            labels.get(e.target) for e in result.edges
            if e.relation == "method" and e.source == svc.id
        }
        assert "find()" in method_names
        assert "create()" in method_names

    def test_object_holds_helper(self, extractor, sc_fixture):
        result = extractor.extract(sc_fixture)
        const = next(n for n in result.nodes if n.label == "Constants")
        labels = {n.id: n.label for n in result.nodes}
        nested = {
            labels.get(e.target) for e in result.edges
            if e.source == const.id
        }
        assert "helper()" in nested
        assert "PAGE_SIZE" in nested

    def test_imports(self, extractor, sc_fixture):
        result = extractor.extract(sc_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_no_errors(self, extractor, sc_fixture):
        result = extractor.extract(sc_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, sc_fixture):
        result = extractor.extract(sc_fixture)
        for n in result.nodes:
            assert n.language == "scala"
