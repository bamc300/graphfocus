"""Tests for the Go extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.go_extractor import GoExtractor


@pytest.fixture
def extractor() -> GoExtractor:
    return GoExtractor()


@pytest.fixture
def go_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "go" / "user_service.go"


class TestGoExtractor:
    def test_extracts_package(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        pkgs = [n for n in result.nodes if n.kind == "package"]
        assert any(n.label == "userservice" for n in pkgs)

    def test_extracts_struct_and_interface(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("User") == "struct"
        assert kinds.get("Service") == "struct"
        assert kinds.get("Repository") == "interface"

    def test_extracts_struct_fields(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        labels = [n.label for n in result.nodes if n.kind == "field"]
        assert "ID" in labels
        assert "Name" in labels
        assert "Email" in labels

    def test_extracts_top_level_function(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        labels = [n.label for n in result.nodes if n.kind == "function"]
        assert "NewService()" in labels
        assert "plainHelper()" in labels

    def test_methods_attached_to_receiver(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        method_edges = [e for e in result.edges if e.relation == "method"]
        # Service.Get and Service.Create should be attached to the Service struct.
        service = next(n for n in result.nodes if n.label == "Service" and n.kind == "struct")
        attached = [e for e in method_edges if e.source == service.id]
        method_names = {
            next(n.label for n in result.nodes if n.id == e.target)
            for e in attached
        }
        assert "Get()" in method_names
        assert "Create()" in method_names

    def test_imports_are_extracted(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        # context, errors, fmt
        assert len(imports) >= 3

    def test_no_errors(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, go_fixture):
        result = extractor.extract(go_fixture)
        for n in result.nodes:
            assert n.language == "go"
