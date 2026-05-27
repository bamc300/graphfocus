"""Tests for the TypeScript / JavaScript / React extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.typescript_extractor import TypeScriptExtractor


@pytest.fixture
def extractor() -> TypeScriptExtractor:
    return TypeScriptExtractor()


@pytest.fixture
def tsx_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "typescript" / "UserList.tsx"


class TestTypeScriptExtractor:
    def test_extracts_interface(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("User") == "interface"

    def test_extracts_type_alias(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("UserListProps") == "type"

    def test_named_function_returning_jsx_is_component(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        comp = next(n for n in result.nodes if n.label == "UserList()")
        assert comp.kind == "component"

    def test_arrow_function_returning_jsx_is_component(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        badge = next(n for n in result.nodes if n.label == "UserBadge()")
        assert badge.kind == "component"

    def test_class_extending_react_component_is_component(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        dash = next(n for n in result.nodes if n.label == "UserDashboard")
        assert dash.kind == "component"

    def test_plain_function_is_not_component(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        helper = next(n for n in result.nodes if n.label == "plainHelper()")
        assert helper.kind == "function"

    def test_imports_are_extracted(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        import_edges = [e for e in result.edges if e.relation == "imports"]
        # react + ./api
        assert len(import_edges) >= 2

    def test_no_errors(self, extractor, tsx_fixture):
        result = extractor.extract(tsx_fixture)
        assert not result.errors

    def test_language_label_for_ts(self, extractor, tmp_path):
        ts = tmp_path / "util.ts"
        ts.write_text("export function add(a: number, b: number) { return a + b; }\n")
        result = extractor.extract(ts)
        for n in result.nodes:
            assert n.language == "typescript"

    def test_language_label_for_js(self, extractor, tmp_path):
        js = tmp_path / "util.js"
        js.write_text("export function add(a, b) { return a + b; }\n")
        result = extractor.extract(js)
        for n in result.nodes:
            assert n.language == "javascript"
