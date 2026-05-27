"""Tests for the SQLite-backed extraction cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.cache.sqlite_cache import ExtractionCache
from graphfocus.extractors.base import Edge, Node


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "sample.py"
    p.write_text("class Foo:\n    pass\n")
    return p


@pytest.fixture
def cache(tmp_path: Path) -> ExtractionCache:
    db = tmp_path / "cache.db"
    return ExtractionCache(db)


class TestExtractionCache:
    def test_round_trip(self, cache: ExtractionCache, sample_file: Path):
        cache.save(
            sample_file,
            [Node(id="foo", label="Foo", kind="class", language="python").to_dict()],
            [Edge(source="foo", target="bar", relation="calls").to_dict()],
            language="python",
        )

        loaded = cache.get_cached(sample_file)
        assert loaded is not None
        assert len(loaded["nodes"]) == 1
        assert loaded["nodes"][0]["id"] == "foo"
        assert len(loaded["edges"]) == 1
        assert loaded["edges"][0]["relation"] == "calls"

    def test_miss_when_file_changes(self, cache: ExtractionCache, sample_file: Path):
        cache.save(sample_file, [], [], "python")
        assert cache.is_cached(sample_file)

        sample_file.write_text("class Foo:\n    def bar(self): pass\n")
        assert not cache.is_cached(sample_file)
        assert cache.get_cached(sample_file) is None

    def test_get_cached_returns_none_for_unknown(self, cache: ExtractionCache, tmp_path: Path):
        unknown = tmp_path / "never_saved.py"
        unknown.write_text("pass")
        assert cache.get_cached(unknown) is None

    def test_node_from_dict_round_trip(self):
        original = Node(
            id="x", label="X", kind="class", language="python",
            source_file="a.py", source_location="L7",
            metadata={"annotations": ["Override"]},
        )
        restored = Node.from_dict(original.to_dict())
        assert restored == original

    def test_edge_from_dict_round_trip(self):
        original = Edge(
            source="a", target="b", relation="calls", confidence="INFERRED",
            source_file="a.py", source_location="L9", weight=0.7,
        )
        restored = Edge.from_dict(original.to_dict())
        assert restored == original

    def test_clear_empties_cache(self, cache: ExtractionCache, sample_file: Path):
        cache.save(sample_file, [], [], "python")
        assert cache.stats()["entries"] == 1
        removed = cache.clear()
        assert removed == 1
        assert cache.stats()["entries"] == 0
