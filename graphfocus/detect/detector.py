"""File discovery, type classification, and corpus health checks."""

from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path


class FileType(StrEnum):
    """Classification of a source file."""

    CODE = "code"
    DOCUMENT = "document"
    PAPER = "paper"
    IMAGE = "image"


# ── Extension mappings ────────────────────────────────────────────────────────

CODE_EXTENSIONS: dict[str, str] = {
    # Python
    ".py": "python",
    # Java / Spring Boot / ADF
    ".java": "java",
    ".jsp": "java",
    ".jspx": "java",
    # C#
    ".cs": "csharp",
    # SQL / PL-SQL
    ".sql": "sql",
    ".pls": "plsql",
    ".pks": "plsql",
    ".pkb": "plsql",
    ".pck": "plsql",
    ".fnc": "plsql",
    ".prc": "plsql",
    ".trg": "plsql",
    # JavaScript / TypeScript / React
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    # Vue SFC
    ".vue": "vue",
    # Other languages with dedicated extractors
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".h++": "cpp",
    ".c": "c",
    ".h": "c",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    ".php": "php",
    ".phtml": "php",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    # Config / build
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".properties": "properties",
    ".gradle": "gradle",
    ".pom": "maven",
}

DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc"}
PAPER_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

# ── Directories to always skip ────────────────────────────────────────────────

SKIP_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".pytest_cache",
    ".venv", "venv", "env",
    ".idea", ".vscode",
    "dist", "build", "target",
    "graphfocus-out",
    ".claude",
}

# ── Sensitive file patterns ───────────────────────────────────────────────────

_SENSITIVE_PATTERNS = [
    re.compile(r"(^|[\\/])\.(env|envrc)(\.|$)", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx|cert|crt|der|p8)$", re.IGNORECASE),
    re.compile(r"(credential|secret|passwd|password|token|private_key)", re.IGNORECASE),
    re.compile(r"(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?$"),
    re.compile(r"(\.netrc|\.pgpass|\.htpasswd)$", re.IGNORECASE),
]

# ── Paper detection heuristics ────────────────────────────────────────────────

_PAPER_SIGNALS = [
    re.compile(r"\barxiv\b", re.IGNORECASE),
    re.compile(r"\bdoi\s*:", re.IGNORECASE),
    re.compile(r"\babstract\b", re.IGNORECASE),
    re.compile(r"\bproceedings\b", re.IGNORECASE),
    re.compile(r"\bpreprint\b", re.IGNORECASE),
    re.compile(r"\\cite\{"),
    re.compile(r"\[\d+\]"),
]
_PAPER_SIGNAL_THRESHOLD = 3


def _is_sensitive(path: Path) -> bool:
    """Return True if this file likely contains secrets."""
    name = path.name
    full = str(path)
    return any(p.search(name) or p.search(full) for p in _SENSITIVE_PATTERNS)


def _looks_like_paper(path: Path) -> bool:
    """Heuristic: does this text file read like an academic paper?"""
    try:
        text = path.read_text(errors="ignore")[:3000]
        hits = sum(1 for p in _PAPER_SIGNALS if p.search(text))
        return hits >= _PAPER_SIGNAL_THRESHOLD
    except Exception:
        return False


def classify_file(path: Path) -> FileType | None:
    """Classify a single file by its extension and content heuristics."""
    ext = path.suffix.lower()

    if ext in CODE_EXTENSIONS:
        return FileType.CODE

    if ext in PAPER_EXTENSIONS:
        return FileType.PAPER

    if ext in IMAGE_EXTENSIONS:
        return FileType.IMAGE

    if ext in DOC_EXTENSIONS:
        if _looks_like_paper(path):
            return FileType.PAPER
        return FileType.DOCUMENT

    return None


def detect_files(root: Path) -> dict:
    """Scan a directory tree and classify all supported files.

    Returns a dict with:
        - total_files: int
        - total_words: int (estimated)
        - files: list[dict] with path, type, language, size
        - by_type: dict[str, int] counts per FileType
        - by_language: dict[str, int] counts per language
        - skipped_sensitive: int
    """
    root = root.resolve()
    files: list[dict] = []
    by_type: dict[str, int] = {}
    by_language: dict[str, int] = {}
    total_words = 0
    skipped_sensitive = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            filepath = Path(dirpath) / filename

            # Skip sensitive files
            if _is_sensitive(filepath):
                skipped_sensitive += 1
                continue

            file_type = classify_file(filepath)
            if file_type is None:
                continue

            ext = filepath.suffix.lower()
            language = CODE_EXTENSIONS.get(ext, file_type.value)

            try:
                size = filepath.stat().st_size
            except OSError:
                size = 0

            # Estimate words for text files
            if file_type in (FileType.CODE, FileType.DOCUMENT):
                try:
                    text = filepath.read_text(errors="ignore")
                    total_words += len(text.split())
                except Exception:
                    pass

            rel_path = str(filepath.relative_to(root))
            files.append({
                "path": str(filepath),
                "relative_path": rel_path,
                "type": file_type.value,
                "language": language,
                "extension": ext,
                "size": size,
            })

            by_type[file_type.value] = by_type.get(file_type.value, 0) + 1
            by_language[language] = by_language.get(language, 0) + 1

    return {
        "total_files": len(files),
        "total_words": total_words,
        "files": files,
        "by_type": by_type,
        "by_language": by_language,
        "skipped_sensitive": skipped_sensitive,
    }
