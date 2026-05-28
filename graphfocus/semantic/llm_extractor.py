"""LLM-based semantic extractor for documents, images, and enrichment.

Uses Claude or OpenAI to extract entities and relationships from files
that AST parsers cannot handle (PDFs, images, markdown docs, etc.).

This module is optional — GraphFocus works without it for code analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path

from graphfocus.extractors.base import ExtractionResult

logger = logging.getLogger(__name__)


class LLMExtractor:
    """Extract semantic entities and relationships using an LLM.

    Supports:
      - Anthropic Claude (via anthropic SDK)
      - OpenAI GPT-4 (via openai SDK)

    Usage:
        extractor = LLMExtractor(provider="anthropic")
        result = extractor.extract_file(Path("research_paper.md"))
    """

    def __init__(self, provider: str = "anthropic", model: str | None = None) -> None:
        self.provider = provider
        self.model = model or self._default_model()
        self._client = None

    def _default_model(self) -> str:
        if self.provider == "anthropic":
            return "claude-sonnet-4-20250514"
        return "gpt-4o"

    def _get_client(self):
        """Lazy-initialize the API client."""
        if self._client is not None:
            return self._client

        if self.provider == "anthropic":
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except ImportError as err:
                raise ImportError(
                    "Install anthropic: pip install 'graphfocus[semantic]'"
                ) from err
        elif self.provider == "openai":
            try:
                import openai
                self._client = openai.OpenAI()
            except ImportError as err:
                raise ImportError(
                    "Install openai: pip install 'graphfocus[semantic]'"
                ) from err
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        return self._client

    def extract_file(self, path: Path) -> ExtractionResult:
        """Extract entities and relationships from a document file.

        Args:
            path: Path to the file to analyze

        Returns:
            ExtractionResult with nodes and edges
        """
        # TODO: Implement LLM-based extraction
        logger.info(f"LLM extraction not yet implemented for: {path}")
        return ExtractionResult()

    def extract_text(self, text: str, source_file: str = "") -> ExtractionResult:
        """Extract entities from raw text content.

        Args:
            text: The text content to analyze
            source_file: Optional source file path for attribution

        Returns:
            ExtractionResult with nodes and edges
        """
        # TODO: Implement LLM-based text extraction
        logger.info("LLM text extraction not yet implemented")
        return ExtractionResult()
