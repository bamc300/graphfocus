"""SQLite-based extraction cache for incremental updates.

Stores file hashes and their extraction results. On subsequent runs,
only files that changed (different SHA256) are re-extracted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from graphfocus.config import DEFAULT_CACHE_DB


def _hash_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class ExtractionCache:
    """SQLite-backed cache for file extraction results."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_CACHE_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_cache (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                nodes_json TEXT NOT NULL,
                edges_json TEXT NOT NULL,
                language TEXT,
                extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def is_cached(self, path: Path) -> bool:
        """Check if a file has a valid cache entry (same hash)."""
        current_hash = _hash_file(path)
        row = self._conn.execute(
            "SELECT file_hash FROM file_cache WHERE file_path = ?",
            (str(path),),
        ).fetchone()
        return row is not None and row[0] == current_hash

    def get_cached(self, path: Path) -> dict | None:
        """Get cached extraction result for a file.

        Returns dict with 'nodes' and 'edges' or None if not cached.
        """
        current_hash = _hash_file(path)
        row = self._conn.execute(
            "SELECT file_hash, nodes_json, edges_json FROM file_cache WHERE file_path = ?",
            (str(path),),
        ).fetchone()

        if row is None or row[0] != current_hash:
            return None

        return {
            "nodes": json.loads(row[1]),
            "edges": json.loads(row[2]),
        }

    def save(self, path: Path, nodes: list[dict], edges: list[dict], language: str = "") -> None:
        """Save extraction result to cache."""
        file_hash = _hash_file(path)
        self._conn.execute(
            """INSERT OR REPLACE INTO file_cache (file_path, file_hash, nodes_json, edges_json, language)
               VALUES (?, ?, ?, ?, ?)""",
            (str(path), file_hash, json.dumps(nodes), json.dumps(edges), language),
        )
        self._conn.commit()

    def clear(self) -> int:
        """Clear all cache entries. Returns number of entries cleared."""
        cursor = self._conn.execute("SELECT COUNT(*) FROM file_cache")
        count = cursor.fetchone()[0]
        self._conn.execute("DELETE FROM file_cache")
        self._conn.commit()
        return count

    def prune_missing(self, present: set[str]) -> int:
        """Delete cache entries whose ``file_path`` is not in ``present``.

        Call this after every analyze run with the set of paths that are
        still on disk; otherwise nodes from deleted files survive in the
        cache and leak back into future graphs.

        Returns the number of stale entries that were removed.
        """
        cursor = self._conn.execute("SELECT file_path FROM file_cache")
        cached_paths = {row[0] for row in cursor.fetchall()}
        stale = cached_paths - present
        if not stale:
            return 0
        # SQLite has a parameter cap (~999); chunk if needed.
        removed = 0
        for chunk_start in range(0, len(stale), 500):
            chunk = list(stale)[chunk_start:chunk_start + 500]
            placeholders = ",".join("?" * len(chunk))
            self._conn.execute(
                f"DELETE FROM file_cache WHERE file_path IN ({placeholders})",
                chunk,
            )
            removed += len(chunk)
        self._conn.commit()
        return removed

    def stats(self) -> dict:
        """Get cache statistics."""
        cursor = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(nodes_json) + LENGTH(edges_json)), 0) FROM file_cache"
        )
        count, total_bytes = cursor.fetchone()
        return {
            "entries": count,
            "total_bytes": total_bytes,
        }

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
