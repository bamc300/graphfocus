"""Lightweight TF-IDF semantic index for nodes.

Goal: let the LLM ask ``find_semantic("authentication logic")`` and get
back the nodes most likely to be about authentication — even when their
labels don't contain the word "auth".

We could plug in sentence-transformers for true semantic embeddings,
but that drags ~500 MB of torch into the package and isn't worth it
for typical codebase queries. Instead we use **TF-IDF over tokenised
labels**, which is:

  * dependency-free (pure Python stdlib);
  * fast — building the index for 100k nodes takes well under a second;
  * deterministic — same input always gives the same scores;
  * good enough to beat substring matching on synonym and morphology.

The index gets persisted next to ``graph.json`` as ``semantic.json``
and is loaded on-demand by both the CLI and the MCP server.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

# Split CamelCase, snake_case, dots, slashes, parens, punctuation.
_SPLITTER = re.compile(
    r"(?<=[a-z])(?=[A-Z])|"          # camelCase boundary
    r"(?<=[A-Z])(?=[A-Z][a-z])|"     # XMLParser → XML/Parser
    r"[\s._\-/()\[\]{}:;,!?]+",      # punctuation/whitespace
)


def _singularise(token: str) -> str:
    """Return the singular form of a simple English plural, else the token."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and token[-3] not in "aeiou":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(*texts: str | None) -> list[str]:
    """Break ``texts`` into normalised tokens used by the index.

    Each surface form is kept and, if it looks like a simple English
    plural, its singular form is added too. That way a query for
    ``user`` matches a table named ``users`` and vice versa.
    """
    out: list[str] = []
    for t in texts:
        if not t:
            continue
        for piece in _SPLITTER.split(str(t)):
            piece = piece.strip().lower()
            if not piece or len(piece) <= 1 or piece.isdigit():
                continue
            out.append(piece)
            singular = _singularise(piece)
            if singular != piece and len(singular) > 1:
                out.append(singular)
    return out


def _doc_tokens(node: dict) -> list[str]:
    """All tokens that describe a node — label, id, kind, language, file stem."""
    file_stem = ""
    if node.get("source_file"):
        file_stem = Path(node["source_file"]).stem
    return tokenize(
        node.get("label"),
        node.get("id"),
        node.get("kind"),
        node.get("language"),
        file_stem,
    )


def build_index(nodes: list[dict]) -> dict:
    """Compute a TF-IDF index over the node corpus.

    Returns a JSON-serialisable dict with three sections::

        {
          "idf":    {token: inverse_document_frequency},
          "vectors": [
              {"id": node_id, "tokens": {token: tf}, "norm": float},
              ...
          ]
        }

    ``vectors`` is a parallel list (one entry per node) carrying each
    node's term-frequency map and its precomputed L2 norm so queries
    don't recompute it on every call.
    """
    if not nodes:
        return {"idf": {}, "vectors": []}

    # Document frequency: how many nodes contain each token.
    df: Counter[str] = Counter()
    per_doc: list[Counter[str]] = []
    for n in nodes:
        tokens = _doc_tokens(n)
        counts = Counter(tokens)
        per_doc.append(counts)
        for token in counts:
            df[token] += 1

    n_docs = len(nodes)
    idf = {
        token: math.log((n_docs + 1) / (count + 1)) + 1.0
        for token, count in df.items()
    }

    vectors: list[dict] = []
    for n, counts in zip(nodes, per_doc, strict=True):
        # tf-idf weights for this doc.
        weighted = {tok: tf * idf.get(tok, 0.0) for tok, tf in counts.items()}
        # Drop zeros to keep the index compact.
        weighted = {t: w for t, w in weighted.items() if w > 0}
        norm = math.sqrt(sum(w * w for w in weighted.values())) or 1.0
        vectors.append({"id": n["id"], "tokens": weighted, "norm": norm})

    return {"idf": idf, "vectors": vectors}


def save_index(index: dict, path: Path) -> None:
    """Persist the index as JSON next to the graph file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def load_index(path: Path) -> dict | None:
    """Return the saved index, or None if it's missing or empty."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not data.get("vectors"):
        return None
    return data


def search(
    index: dict,
    query: str,
    limit: int = 10,
    min_score: float = 0.01,
) -> list[tuple[str, float]]:
    """Return ``[(node_id, score), …]`` for the top matches against ``query``.

    Scores are cosine similarity in TF-IDF space, in ``[0, 1]``.
    """
    idf = index.get("idf", {})
    vectors = index.get("vectors", [])
    if not vectors:
        return []

    q_tokens = tokenize(query)
    if not q_tokens:
        return []

    q_counts = Counter(q_tokens)
    q_weighted = {tok: tf * idf.get(tok, 0.0) for tok, tf in q_counts.items()}
    q_weighted = {t: w for t, w in q_weighted.items() if w > 0}
    if not q_weighted:
        return []
    q_norm = math.sqrt(sum(w * w for w in q_weighted.values())) or 1.0

    # Score each document by inverted-index walk: only docs that share at
    # least one token with the query contribute. We materialise the
    # inverted index lazily here — for the typical analyze size that's
    # ~milliseconds; the alternative would be to persist it explicitly.
    inverted: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for i, doc in enumerate(vectors):
        for tok, w in doc["tokens"].items():
            if tok in q_weighted:
                inverted[tok].append((i, w))

    scores: dict[int, float] = defaultdict(float)
    for tok, qw in q_weighted.items():
        for i, w in inverted.get(tok, []):
            scores[i] += qw * w

    results: list[tuple[str, float]] = []
    for i, raw in scores.items():
        norm = vectors[i]["norm"] * q_norm
        sim = raw / norm if norm else 0.0
        if sim >= min_score:
            results.append((vectors[i]["id"], sim))

    results.sort(key=lambda kv: -kv[1])
    return results[:limit]


def filter_by(
    matches: Iterable[tuple[str, float]],
    nodes_by_id: dict[str, dict],
    *,
    language: str | None = None,
    kind: str | None = None,
) -> list[tuple[str, float]]:
    """Filter a search result by language and/or kind."""
    out: list[tuple[str, float]] = []
    for nid, score in matches:
        node = nodes_by_id.get(nid)
        if node is None:
            continue
        if language and node.get("language") != language:
            continue
        if kind and node.get("kind") != kind:
            continue
        out.append((nid, score))
    return out
