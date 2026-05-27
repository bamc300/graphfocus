"""Tests for the C extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.c_extractor import CExtractor


@pytest.fixture
def extractor() -> CExtractor:
    return CExtractor()


@pytest.fixture
def c_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "c" / "user.c"


class TestCExtractor:
    def test_struct_typedef_and_plain(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("User") == "struct"
        assert kinds.get("Point") == "struct"

    def test_struct_fields(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        field_labels = [n.label for n in result.nodes if n.kind == "field"]
        assert "id" in field_labels
        assert "name" in field_labels
        assert "x" in field_labels
        assert "y" in field_labels

    def test_includes_extracted(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        # stdio, stdlib, user
        assert len(imports) >= 3

    def test_functions(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "find_user()" in labels
        assert "create_user()" in labels
        assert "main()" in labels

    def test_call_graph(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        calls = [e for e in result.edges if e.relation == "calls"]
        assert len(calls) >= 2  # main calls find_user and create_user

    def test_no_errors(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, c_fixture):
        result = extractor.extract(c_fixture)
        for n in result.nodes:
            assert n.language == "c"
