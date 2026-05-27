"""Tests for the Kotlin extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.kotlin_extractor import KotlinExtractor


@pytest.fixture
def extractor() -> KotlinExtractor:
    return KotlinExtractor()


@pytest.fixture
def kt_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "kotlin" / "UserService.kt"


class TestKotlinExtractor:
    def test_distinguishes_interface_class_object_data_class(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("UserRepository") == "interface"
        assert kinds.get("UserService") == "class"
        assert kinds.get("User") == "data_class"
        assert kinds.get("Constants") == "object"

    def test_spring_annotations_captured_on_class(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        svc = next(n for n in result.nodes if n.label == "UserService")
        assert "Service" in svc.metadata.get("annotations", [])
        assert "Service" in svc.metadata.get("spring_roles", [])

    def test_transactional_annotation_on_method(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        create = next(n for n in result.nodes if n.label == "create()")
        assert "Transactional" in create.metadata.get("annotations", [])

    def test_top_level_function(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        labels = {n.label for n in result.nodes if n.kind == "function"}
        assert "topLevelHelper()" in labels

    def test_methods_attached_to_parent_class(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        svc = next(n for n in result.nodes if n.label == "UserService")
        method_targets = {
            next(n.label for n in result.nodes if n.id == e.target)
            for e in result.edges
            if e.relation == "method" and e.source == svc.id
        }
        assert "create()" in method_targets
        assert "find()" in method_targets

    def test_imports_extracted(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_no_errors(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, kt_fixture):
        result = extractor.extract(kt_fixture)
        for n in result.nodes:
            assert n.language == "kotlin"
