"""Tests for the parallel extraction pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.cache.sqlite_cache import ExtractionCache
from graphfocus.extractors.registry import ExtractorRegistry
from graphfocus.pipeline import run_extraction


@pytest.fixture
def fixtures_root() -> Path:
    return Path(__file__).parent / "fixtures"


def _detection(*files: Path) -> list[dict]:
    """Build a minimal detection["files"] payload from a list of paths."""
    return [
        {"path": str(p), "relative_path": p.name, "type": "code",
         "language": "python", "extension": p.suffix, "size": p.stat().st_size}
        for p in files
    ]


class TestRunExtraction:
    def test_sequential_extracts_nodes(self, fixtures_root: Path):
        py = fixtures_root / "python" / "sample_module.py"
        registry = ExtractorRegistry()
        payload, hits = run_extraction(
            _detection(py), registry, cache=None, console=None, workers=1,
        )
        assert hits == 0
        assert any(n["label"] == "User" for n in payload["nodes"])

    def test_cache_hit_skips_worker(self, tmp_path: Path, fixtures_root: Path):
        py = fixtures_root / "python" / "sample_module.py"
        cache = ExtractionCache(tmp_path / "cache.db")

        registry = ExtractorRegistry()
        # First pass: cache miss, populates the DB.
        payload1, hits1 = run_extraction(
            _detection(py), registry, cache=cache, console=None, workers=1,
        )
        assert hits1 == 0
        # Second pass on the same file: every node served from cache.
        payload2, hits2 = run_extraction(
            _detection(py), registry, cache=cache, console=None, workers=1,
        )
        assert hits2 == 1
        assert payload1["nodes"] == payload2["nodes"]

    def test_unknown_extension_is_skipped(self, tmp_path: Path):
        unknown = tmp_path / "thing.xyz"
        unknown.write_text("nope")
        registry = ExtractorRegistry()
        payload, hits = run_extraction(
            _detection(unknown), registry, cache=None, console=None, workers=1,
        )
        assert payload["nodes"] == []
        assert hits == 0

    def test_parallel_path_matches_sequential(self, fixtures_root: Path):
        """Force the parallel branch by passing >= threshold files."""
        py = fixtures_root / "python" / "sample_module.py"
        # Repeat the same path so we exceed _PARALLEL_THRESHOLD but each
        # worker still does real extraction (same node ids → dedup
        # happens in the merger, not here).
        big = _detection(*([py] * 120))
        registry = ExtractorRegistry()
        payload, _ = run_extraction(
            big, registry, cache=None, console=None, workers=2,
        )
        # 120 invocations of the same file → 120× the node count of one pass.
        single, _ = run_extraction(
            _detection(py), registry, cache=None, console=None, workers=1,
        )
        assert len(payload["nodes"]) == len(single["nodes"]) * 120


class TestPruneMissing:
    def test_removes_only_absent_files(self, tmp_path: Path):
        cache = ExtractionCache(tmp_path / "cache.db")
        kept = tmp_path / "kept.py"
        kept.write_text("# kept")
        gone = tmp_path / "gone.py"
        gone.write_text("# gone")

        cache.save(kept, [], [], "python")
        cache.save(gone, [], [], "python")
        assert cache.stats()["entries"] == 2

        # Simulate deletion: only 'kept' is present in this run.
        removed = cache.prune_missing({str(kept)})
        assert removed == 1
        assert cache.stats()["entries"] == 1

    def test_noop_when_all_present(self, tmp_path: Path):
        cache = ExtractionCache(tmp_path / "cache.db")
        f = tmp_path / "a.py"
        f.write_text("# a")
        cache.save(f, [], [], "python")
        assert cache.prune_missing({str(f)}) == 0
