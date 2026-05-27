"""Abstract base class for all language extractors.

Every language extractor must inherit from LanguageExtractor and implement:
  - language_name (property): e.g. "python", "java"
  - extensions (property): e.g. {".py"}, {".java"}
  - extract(path) -> ExtractionResult

The ExtractionResult contains nodes and edges in a standardized format
that the graph builder can merge across languages.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    """A node in the knowledge graph."""

    id: str
    label: str
    file_type: str = "code"
    source_file: str = ""
    source_location: str | None = None
    language: str | None = None
    kind: str | None = None  # class, function, method, interface, table, procedure, etc.
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "label": self.label,
            "file_type": self.file_type,
            "source_file": self.source_file,
            "source_location": self.source_location,
            "language": self.language,
            "kind": self.kind,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Node:
        return cls(
            id=d["id"],
            label=d["label"],
            file_type=d.get("file_type", "code"),
            source_file=d.get("source_file", ""),
            source_location=d.get("source_location"),
            language=d.get("language"),
            kind=d.get("kind"),
            metadata=d.get("metadata") or {},
        )


@dataclass
class Edge:
    """An edge (relationship) in the knowledge graph."""

    source: str
    target: str
    relation: str  # imports, calls, inherits, implements, references, contains, etc.
    confidence: str = "EXTRACTED"  # EXTRACTED | INFERRED | AMBIGUOUS
    source_file: str = ""
    source_location: str | None = None
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "confidence": self.confidence,
            "source_file": self.source_file,
            "source_location": self.source_location,
            "weight": self.weight,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Edge:
        return cls(
            source=d["source"],
            target=d["target"],
            relation=d["relation"],
            confidence=d.get("confidence", "EXTRACTED"),
            source_file=d.get("source_file", ""),
            source_location=d.get("source_location"),
            weight=d.get("weight", 1.0),
            metadata=d.get("metadata") or {},
        )


@dataclass
class ExtractionResult:
    """Result of extracting entities and relationships from a file."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def merge(self, other: ExtractionResult) -> ExtractionResult:
        """Merge another extraction result into this one."""
        return ExtractionResult(
            nodes=self.nodes + other.nodes,
            edges=self.edges + other.edges,
            errors=self.errors + other.errors,
        )


def make_id(*parts: str) -> str:
    """Build a stable, deterministic node ID from name parts.

    Examples:
        make_id("my_module", "MyClass") -> "my_module_myclass"
        make_id("utils.py", "parse_data") -> "utils_parse_data"
    """
    combined = "_".join(p.strip("_.") for p in parts if p)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", combined)
    return cleaned.strip("_").lower()


class LanguageExtractor(ABC):
    """Abstract base class for all language extractors.

    To add a new language:
    1. Create a new file: graphfocus/extractors/<language>_extractor.py
    2. Define a class that inherits from LanguageExtractor
    3. Implement language_name, extensions, and extract()
    4. The registry will auto-discover it on import

    Example:
        class GoExtractor(LanguageExtractor):
            @property
            def language_name(self) -> str:
                return "go"

            @property
            def extensions(self) -> set[str]:
                return {".go"}

            def extract(self, path: Path) -> ExtractionResult:
                # Parse using tree-sitter-go
                ...
    """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Human-readable name of the language (e.g., 'python', 'java')."""
        ...

    @property
    @abstractmethod
    def extensions(self) -> set[str]:
        """Set of file extensions this extractor handles (e.g., {'.py'})."""
        ...

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        """Extract nodes and edges from a single file.

        Args:
            path: Path to the source file

        Returns:
            ExtractionResult with nodes, edges, and any errors
        """
        ...

    def can_handle(self, path: Path) -> bool:
        """Check if this extractor can handle the given file."""
        return path.suffix.lower() in self.extensions

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(language={self.language_name!r})"
