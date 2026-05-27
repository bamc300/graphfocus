"""Tests for the Swift extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.swift_extractor import SwiftExtractor


@pytest.fixture
def extractor() -> SwiftExtractor:
    return SwiftExtractor()


@pytest.fixture
def swift_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "swift" / "UserService.swift"


class TestSwiftExtractor:
    def test_protocol_struct_class_enum(self, extractor, swift_fixture):
        result = extractor.extract(swift_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("UserRepository") == "protocol"
        assert kinds.get("User") == "struct"
        assert kinds.get("UserService") == "class"
        assert kinds.get("Role") == "enum"

    def test_methods_attached_to_type(self, extractor, swift_fixture):
        result = extractor.extract(swift_fixture)
        svc = next(n for n in result.nodes if n.label == "UserService")
        labels = {n.id: n.label for n in result.nodes}
        method_names = {
            labels.get(e.target) for e in result.edges
            if e.relation == "method" and e.source == svc.id
        }
        assert "find()" in method_names
        assert "create()" in method_names
        assert "init()" in method_names

    def test_top_level_function(self, extractor, swift_fixture):
        result = extractor.extract(swift_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "plainHelper()" in labels

    def test_imports(self, extractor, swift_fixture):
        result = extractor.extract(swift_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_no_errors(self, extractor, swift_fixture):
        result = extractor.extract(swift_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, swift_fixture):
        result = extractor.extract(swift_fixture)
        for n in result.nodes:
            assert n.language == "swift"
