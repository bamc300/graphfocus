"""Extractor registry — auto-discovers and manages all language extractors."""

from __future__ import annotations

import logging

from graphfocus.extractors.base import LanguageExtractor

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """Registry that discovers and provides language extractors.

    Usage:
        registry = ExtractorRegistry()
        extractor = registry.get_extractor(".java")
        if extractor:
            result = extractor.extract(Path("MyClass.java"))
    """

    def __init__(self) -> None:
        self._extractors: dict[str, LanguageExtractor] = {}
        self._by_extension: dict[str, LanguageExtractor] = {}
        self._discover()

    def _discover(self) -> None:
        """Auto-discover all available extractors by importing them."""
        extractor_classes: list[type[LanguageExtractor]] = []

        # Import each extractor module — they register themselves
        try:
            from graphfocus.extractors.python_extractor import PythonExtractor

            extractor_classes.append(PythonExtractor)
        except ImportError as e:
            logger.debug(f"Python extractor not available: {e}")

        try:
            from graphfocus.extractors.java_extractor import JavaExtractor

            extractor_classes.append(JavaExtractor)
        except ImportError as e:
            logger.debug(f"Java extractor not available: {e}")

        try:
            from graphfocus.extractors.plsql_extractor import PLSQLExtractor

            extractor_classes.append(PLSQLExtractor)
        except ImportError as e:
            logger.debug(f"PL/SQL extractor not available: {e}")

        try:
            from graphfocus.extractors.csharp_extractor import CSharpExtractor

            extractor_classes.append(CSharpExtractor)
        except ImportError as e:
            logger.debug(f"C# extractor not available: {e}")

        try:
            from graphfocus.extractors.sql_extractor import SQLExtractor

            extractor_classes.append(SQLExtractor)
        except ImportError as e:
            logger.debug(f"SQL extractor not available: {e}")

        try:
            from graphfocus.extractors.typescript_extractor import TypeScriptExtractor

            extractor_classes.append(TypeScriptExtractor)
        except ImportError as e:
            logger.debug(f"TypeScript extractor not available: {e}")

        try:
            from graphfocus.extractors.go_extractor import GoExtractor

            extractor_classes.append(GoExtractor)
        except ImportError as e:
            logger.debug(f"Go extractor not available: {e}")

        try:
            from graphfocus.extractors.kotlin_extractor import KotlinExtractor

            extractor_classes.append(KotlinExtractor)
        except ImportError as e:
            logger.debug(f"Kotlin extractor not available: {e}")

        try:
            from graphfocus.extractors.rust_extractor import RustExtractor

            extractor_classes.append(RustExtractor)
        except ImportError as e:
            logger.debug(f"Rust extractor not available: {e}")

        try:
            from graphfocus.extractors.vue_extractor import VueExtractor

            extractor_classes.append(VueExtractor)
        except ImportError as e:
            logger.debug(f"Vue extractor not available: {e}")

        try:
            from graphfocus.extractors.ruby_extractor import RubyExtractor

            extractor_classes.append(RubyExtractor)
        except ImportError as e:
            logger.debug(f"Ruby extractor not available: {e}")

        try:
            from graphfocus.extractors.php_extractor import PHPExtractor

            extractor_classes.append(PHPExtractor)
        except ImportError as e:
            logger.debug(f"PHP extractor not available: {e}")

        try:
            from graphfocus.extractors.swift_extractor import SwiftExtractor

            extractor_classes.append(SwiftExtractor)
        except ImportError as e:
            logger.debug(f"Swift extractor not available: {e}")

        try:
            from graphfocus.extractors.c_extractor import CExtractor

            extractor_classes.append(CExtractor)
        except ImportError as e:
            logger.debug(f"C extractor not available: {e}")

        try:
            from graphfocus.extractors.cpp_extractor import CppExtractor

            extractor_classes.append(CppExtractor)
        except ImportError as e:
            logger.debug(f"C++ extractor not available: {e}")

        try:
            from graphfocus.extractors.scala_extractor import ScalaExtractor

            extractor_classes.append(ScalaExtractor)
        except ImportError as e:
            logger.debug(f"Scala extractor not available: {e}")

        try:
            from graphfocus.extractors.lua_extractor import LuaExtractor

            extractor_classes.append(LuaExtractor)
        except ImportError as e:
            logger.debug(f"Lua extractor not available: {e}")

        try:
            from graphfocus.extractors.dart_extractor import DartExtractor

            extractor_classes.append(DartExtractor)
        except ImportError as e:
            logger.debug(f"Dart extractor not available: {e}")

        try:
            from graphfocus.extractors.r_extractor import RExtractor

            extractor_classes.append(RExtractor)
        except ImportError as e:
            logger.debug(f"R extractor not available: {e}")

        try:
            from graphfocus.extractors.markdown_extractor import MarkdownExtractor

            extractor_classes.append(MarkdownExtractor)
        except ImportError as e:
            logger.debug(f"Markdown extractor not available: {e}")

        try:
            from graphfocus.extractors.openapi_extractor import OpenAPIExtractor

            extractor_classes.append(OpenAPIExtractor)
        except ImportError as e:
            logger.debug(f"OpenAPI extractor not available: {e}")

        # Instantiate and register
        for cls in extractor_classes:
            try:
                instance = cls()
                self._extractors[instance.language_name] = instance
                for ext in instance.extensions:
                    self._by_extension[ext] = instance
                logger.debug(f"Registered extractor: {instance}")
            except Exception as e:
                logger.warning(f"Failed to instantiate {cls.__name__}: {e}")

    def get_extractor(self, extension: str) -> LanguageExtractor | None:
        """Get the extractor for a given file extension.

        Args:
            extension: File extension including dot (e.g., ".java")

        Returns:
            The appropriate LanguageExtractor or None if no extractor is available
        """
        return self._by_extension.get(extension.lower())

    def get_by_language(self, language: str) -> LanguageExtractor | None:
        """Get extractor by language name (e.g., 'java')."""
        return self._extractors.get(language.lower())

    def list_languages(self) -> list[dict]:
        """List all registered languages with their info."""
        result = []
        for name, extractor in sorted(self._extractors.items()):
            result.append({
                "name": name,
                "extensions": sorted(extractor.extensions),
                "status": "✅ active",
                "class": extractor.__class__.__name__,
            })
        return result

    def supported_extensions(self) -> set[str]:
        """Return all file extensions that have an extractor."""
        return set(self._by_extension.keys())

    def __repr__(self) -> str:
        langs = ", ".join(sorted(self._extractors.keys()))
        return f"ExtractorRegistry(languages=[{langs}])"
