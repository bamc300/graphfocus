"""Tests for the Rust extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.rust_extractor import RustExtractor


@pytest.fixture
def extractor() -> RustExtractor:
    return RustExtractor()


@pytest.fixture
def rs_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "rust" / "user_service.rs"


class TestRustExtractor:
    def test_struct_trait_enum(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("User") == "struct"
        assert kinds.get("InMemoryRepo") == "struct"
        assert kinds.get("Repository") == "trait"
        assert kinds.get("Role") == "enum"

    def test_struct_fields(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        field_labels = [n.label for n in result.nodes if n.kind == "field"]
        assert "id" in field_labels
        assert "name" in field_labels

    def test_trait_implementation_edge(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        impls = [e for e in result.edges if e.relation == "implements"]
        labels = {n.id: n.label for n in result.nodes}
        edges_labelled = {(labels.get(e.source), labels.get(e.target)) for e in impls}
        assert ("InMemoryRepo", "Repository") in edges_labelled

    def test_methods_attached_to_impl_target(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        repo = next(n for n in result.nodes if n.label == "InMemoryRepo")
        labels = {n.id: n.label for n in result.nodes}
        method_names = {
            labels.get(e.target)
            for e in result.edges
            if e.relation == "method" and e.source == repo.id
        }
        assert "new()" in method_names
        assert "find()" in method_names
        assert "save()" in method_names

    def test_top_level_function(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "plain_helper()" in labels

    def test_use_declaration_imports(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 1

    def test_no_errors(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, rs_fixture):
        result = extractor.extract(rs_fixture)
        for n in result.nodes:
            assert n.language == "rust"
