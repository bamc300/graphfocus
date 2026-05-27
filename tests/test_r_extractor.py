"""Tests for the R extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.r_extractor import RExtractor


@pytest.fixture
def extractor() -> RExtractor:
    return RExtractor()


@pytest.fixture
def r_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "r" / "analysis.R"


class TestRExtractor:
    def test_functions(self, extractor, r_fixture):
        result = extractor.extract(r_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "add()" in labels
        assert "greet()" in labels
        assert "plot_data()" in labels

    def test_library_imports(self, extractor, r_fixture):
        result = extractor.extract(r_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        # dplyr, ggplot2, magrittr, utils
        assert len(imports) >= 4

    def test_source_call_is_import(self, extractor, r_fixture):
        result = extractor.extract(r_fixture)
        from graphfocus.extractors.base import make_id
        utils_target = make_id("utils")
        targets = {e.target for e in result.edges if e.relation == "imports"}
        assert utils_target in targets

    def test_no_errors(self, extractor, r_fixture):
        result = extractor.extract(r_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, r_fixture):
        result = extractor.extract(r_fixture)
        for n in result.nodes:
            assert n.language == "r"
