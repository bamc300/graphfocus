"""Tests for the Ruby extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.ruby_extractor import RubyExtractor


@pytest.fixture
def extractor() -> RubyExtractor:
    return RubyExtractor()


@pytest.fixture
def rb_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "ruby" / "user_service.rb"


class TestRubyExtractor:
    def test_extracts_module(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("Users") == "module"

    def test_extracts_classes(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("BaseService") == "class"
        assert kinds.get("UserService") == "class"

    def test_extracts_inheritance(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        inherits = [e for e in result.edges if e.relation == "inherits"]
        assert len(inherits) >= 1

    def test_extracts_methods(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        labels = {n.label for n in result.nodes if n.kind in ("method", "function")}
        assert "find()" in labels
        assert "create()" in labels
        assert "validate()" in labels
        assert "helper()" in labels

    def test_extracts_requires(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_no_errors(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, rb_fixture):
        result = extractor.extract(rb_fixture)
        for n in result.nodes:
            assert n.language == "ruby"
