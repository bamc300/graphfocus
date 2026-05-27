"""Tests for the Lua extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.lua_extractor import LuaExtractor


@pytest.fixture
def extractor() -> LuaExtractor:
    return LuaExtractor()


@pytest.fixture
def lua_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "lua" / "user_service.lua"


class TestLuaExtractor:
    def test_requires_extracted(self, extractor, lua_fixture):
        result = extractor.extract(lua_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_module_methods(self, extractor, lua_fixture):
        result = extractor.extract(lua_fixture)
        # M.find and M.create become methods of a synthetic "M" module.
        mod = next((n for n in result.nodes if n.label == "M" and n.kind == "module"),
                   None)
        assert mod is not None
        labels = {n.id: n.label for n in result.nodes}
        methods = {
            labels.get(e.target) for e in result.edges
            if e.relation == "method" and e.source == mod.id
        }
        assert "find()" in methods
        assert "create()" in methods

    def test_local_function(self, extractor, lua_fixture):
        result = extractor.extract(lua_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "plain_helper()" in labels
        assert "generate_id()" in labels

    def test_no_errors(self, extractor, lua_fixture):
        result = extractor.extract(lua_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, lua_fixture):
        result = extractor.extract(lua_fixture)
        for n in result.nodes:
            assert n.language == "lua"
