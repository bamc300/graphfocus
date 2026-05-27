"""Tests for the extractor registry."""

from graphfocus.extractors.registry import ExtractorRegistry


class TestExtractorRegistry:
    def test_registry_discovers_extractors(self):
        registry = ExtractorRegistry()
        languages = registry.list_languages()
        # At minimum we should have Python, PL/SQL, and SQL (which don't need tree-sitter)
        names = [lang["name"] for lang in languages]
        assert "plsql" in names
        assert "sql" in names

    def test_get_extractor_by_extension(self):
        registry = ExtractorRegistry()
        # PL/SQL and SQL extractors don't need tree-sitter
        assert registry.get_extractor(".pks") is not None
        assert registry.get_extractor(".sql") is not None

    def test_get_extractor_unknown_extension(self):
        registry = ExtractorRegistry()
        assert registry.get_extractor(".xyz") is None

    def test_supported_extensions(self):
        registry = ExtractorRegistry()
        exts = registry.supported_extensions()
        assert ".pks" in exts
        assert ".sql" in exts

    def test_list_languages_format(self):
        registry = ExtractorRegistry()
        for lang in registry.list_languages():
            assert "name" in lang
            assert "extensions" in lang
            assert "status" in lang
