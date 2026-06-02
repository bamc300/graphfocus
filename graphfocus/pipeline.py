"""Extraction pipeline — fans the per-file work across worker processes.

For projects under a few hundred files the overhead of spinning up
``ProcessPoolExecutor`` outweighs the gain, so we fall back to a plain
sequential loop. Above that threshold the workers parse files in
parallel and the main process just collects results, deduplicates,
and writes to the cache.

The cache is touched only from the main process — SQLite connections
don't share well across processes, and workers don't need read access
because the main process already filtered out cache hits.

A ``rich`` progress bar shows live progress on TTYs and stays silent
inside CI.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from graphfocus.extractors.registry import ExtractorRegistry

if TYPE_CHECKING:
    from rich.console import Console

    from graphfocus.cache.sqlite_cache import ExtractionCache


# Threshold below which sequential extraction wins — pool startup costs ~200ms
# on macOS / Linux, plus per-task pickling overhead. We benchmarked the
# break-even around 100 files.
_PARALLEL_THRESHOLD = 100


def _extract_one(path_str: str) -> dict:
    """Worker entry point — must be importable from a child process.

    Loads the registry inside the worker (each process has its own
    instance of every extractor; that's fine because they hold parser
    state, not shared state) and returns plain dicts so the result
    survives ``pickle``.
    """
    path = Path(path_str)
    registry = _get_worker_registry()
    extractor = registry.get_extractor(path.suffix)
    if extractor is None:
        return {"path": path_str, "nodes": [], "edges": [],
                "errors": [], "language": None}
    result = extractor.extract(path)
    return {
        "path": path_str,
        "nodes": [n.to_dict() for n in result.nodes],
        "edges": [e.to_dict() for e in result.edges],
        "errors": list(result.errors),
        "language": extractor.language_name,
    }


_WORKER_REGISTRY: ExtractorRegistry | None = None


def _get_worker_registry() -> ExtractorRegistry:
    """Lazy-construct one registry per worker process."""
    global _WORKER_REGISTRY
    if _WORKER_REGISTRY is None:
        _WORKER_REGISTRY = ExtractorRegistry()
    return _WORKER_REGISTRY


def run_extraction(
    files: list[dict],
    registry: ExtractorRegistry,
    *,
    cache: ExtractionCache | None = None,
    console: Console | None = None,
    workers: int = 0,
) -> tuple[dict, int]:
    """Extract every file's nodes and edges, in parallel when worth it.

    Args:
        files: detection["files"] from ``detect_files``.
        registry: extractor registry used in the main process for cache
            hits and for resolving which extension is supported.
        cache: optional SQLite cache. Hits are served without touching
            the worker pool; misses are saved after the worker returns.
        console: ``rich`` Console for the progress bar. None = silent.
        workers: 0 = ``os.cpu_count()``; 1 = sequential.

    Returns ``({"nodes": [...], "edges": [...]}, cache_hits)``.
    """
    nodes_out: list[dict] = []
    edges_out: list[dict] = []
    cache_hits = 0

    # ── 1. Filter to supported files; serve cache hits inline ────────
    pending: list[str] = []
    cached_paths_with_errors: list[tuple[str, list[str]]] = []

    for fi in files:
        file_path = Path(fi["path"])
        if registry.get_extractor(file_path.suffix) is None:
            continue
        cached = cache.get_cached(file_path) if cache else None
        if cached is not None:
            nodes_out.extend(cached["nodes"])
            edges_out.extend(cached["edges"])
            cache_hits += 1
            continue
        pending.append(str(file_path))

    if not pending:
        return {"nodes": nodes_out, "edges": edges_out}, cache_hits

    # ── 2. Resolve worker count ──────────────────────────────────────
    if workers <= 0:
        workers = max(1, os.cpu_count() or 1)
    use_parallel = workers > 1 and len(pending) >= _PARALLEL_THRESHOLD

    # ── 3. Run extraction with a progress bar ────────────────────────
    progress = None
    task_id = None
    if console is not None:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        progress.start()
        label = f"Extracting ({workers} workers)" if use_parallel else "Extracting"
        task_id = progress.add_task(label, total=len(pending))

    def _consume(result: dict) -> None:
        nonlocal nodes_out, edges_out
        nodes_out.extend(result["nodes"])
        edges_out.extend(result["edges"])
        if cache and result["language"]:
            cache.save(
                Path(result["path"]),
                result["nodes"],
                result["edges"],
                result["language"],
            )
        if result["errors"] and console is not None:
            for err in result["errors"]:
                console.print(
                    f"  [yellow]⚠ {Path(result['path']).name}: {err}[/]"
                )

    try:
        if use_parallel:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_extract_one, p): p for p in pending
                }
                for fut in as_completed(futures):
                    _consume(fut.result())
                    if progress and task_id is not None:
                        progress.advance(task_id)
        else:
            for p in pending:
                _consume(_extract_one(p))
                if progress and task_id is not None:
                    progress.advance(task_id)
    finally:
        if progress is not None:
            progress.stop()

    # Forward any cached errors collected up front (none today but the
    # placeholder keeps the contract clean).
    for _, _errs in cached_paths_with_errors:  # pragma: no cover
        pass

    return {"nodes": nodes_out, "edges": edges_out}, cache_hits
