"""Tests for the PHP extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.php_extractor import PHPExtractor


@pytest.fixture
def extractor() -> PHPExtractor:
    return PHPExtractor()


@pytest.fixture
def php_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "php" / "UserService.php"


class TestPHPExtractor:
    def test_namespace_and_imports(self, extractor, php_fixture):
        result = extractor.extract(php_fixture)
        labels = {n.label for n in result.nodes if n.kind == "namespace"}
        assert any("App" in lbl and "Service" in lbl for lbl in labels)
        imports = [e for e in result.edges if e.relation == "imports"]
        assert len(imports) >= 2

    def test_classes_interfaces(self, extractor, php_fixture):
        result = extractor.extract(php_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        assert kinds.get("UserRepository") == "interface"
        assert kinds.get("BaseService") == "class"
        assert kinds.get("UserService") == "class"

    def test_extends_and_implements(self, extractor, php_fixture):
        result = extractor.extract(php_fixture)
        extends = [e for e in result.edges if e.relation == "extends"]
        implements = [e for e in result.edges if e.relation == "implements"]
        assert len(extends) >= 1
        assert len(implements) >= 1

    def test_methods_and_functions(self, extractor, php_fixture):
        result = extractor.extract(php_fixture)
        labels = {n.label for n in result.nodes}
        assert "find()" in labels
        assert "save()" in labels
        assert "plainHelper()" in labels

    def test_no_errors(self, extractor, php_fixture):
        result = extractor.extract(php_fixture)
        assert not result.errors

    def test_language_attribution(self, extractor, php_fixture):
        result = extractor.extract(php_fixture)
        for n in result.nodes:
            assert n.language == "php"
