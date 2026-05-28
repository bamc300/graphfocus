"""GraphFocus configuration and constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ── Default output directory ──────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = "graphfocus-out"

# ── Cache settings ────────────────────────────────────────────────────────────
DEFAULT_CACHE_DB = "graphfocus-out/.cache.db"

# ── Corpus thresholds ─────────────────────────────────────────────────────────
CORPUS_WARN_THRESHOLD = 50_000       # words - below this, warn "you may not need a graph"
CORPUS_UPPER_THRESHOLD = 500_000     # words - above this, warn about token cost
FILE_COUNT_UPPER = 200               # files - above this, warn about token cost


@dataclass(frozen=True)
class GraphFocusConfig:
    """Immutable configuration for a GraphFocus run."""

    input_path: Path
    output_dir: Path = field(default_factory=lambda: Path(DEFAULT_OUTPUT_DIR))
    mode: str = "normal"             # "normal" | "deep"
    update: bool = False             # incremental update
    skip_semantic: bool = False      # skip LLM extraction
    skip_viz: bool = False           # skip HTML visualization
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    def __post_init__(self) -> None:
        # Ensure input_path is resolved
        object.__setattr__(self, "input_path", self.input_path.resolve())
        object.__setattr__(self, "output_dir", self.output_dir.resolve())
