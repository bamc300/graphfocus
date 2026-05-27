"""Obsidian vault generator.

Writes one Markdown file per node into ``<output>/obsidian/<language>/``
with YAML frontmatter and wikilinks for every relationship, plus a
top-level ``_Index.md`` summarising the graph.

The resulting directory can be opened directly as an Obsidian vault: each
``[[NodeLabel]]`` link resolves to the matching note thanks to Obsidian's
shortest-path link resolution.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from graphfocus.extractors.base import Edge, Node


_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._\- ]+")


def generate_obsidian_vault(
    nodes: list[Node],
    edges: list[Edge],
    output_dir: Path,
) -> dict:
    """Write an Obsidian-compatible vault.

    Args:
        nodes: nodes to write (one note per node)
        edges: edges (rendered as wikilinks inside each note)
        output_dir: target directory; created if missing. The vault is
            placed at ``output_dir`` directly — no extra ``/obsidian``
            subdir is appended, so callers can choose where to put it.

    Returns:
        Summary dict ``{"notes": int, "links": int}``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build lookup: node id → unique filename slug.
    slugs = _assign_slugs(nodes)
    by_id: dict[str, Node] = {n.id: n for n in nodes}

    # Group outgoing and incoming edges per node for easy rendering.
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    incoming: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        if e.source in by_id:
            outgoing[e.source].append(e)
        if e.target in by_id:
            incoming[e.target].append(e)

    written = 0
    for node in nodes:
        lang_dir = output_dir / (node.language or "unknown")
        lang_dir.mkdir(parents=True, exist_ok=True)
        path = lang_dir / f"{slugs[node.id]}.md"
        path.write_text(
            _render_note(node, slugs, by_id, outgoing[node.id], incoming[node.id]),
            encoding="utf-8",
        )
        written += 1

    index_path = output_dir / "_Index.md"
    index_path.write_text(_render_index(nodes, edges), encoding="utf-8")

    return {"notes": written, "links": sum(len(v) for v in outgoing.values())}


# ── internals ───────────────────────────────────────────────────────────────


def _assign_slugs(nodes: list[Node]) -> dict[str, str]:
    """Return a stable, collision-free filename per node id."""
    used: set[str] = set()
    out: dict[str, str] = {}
    for n in nodes:
        base = _slug(n.label) or _slug(n.id) or "node"
        candidate = base
        i = 2
        while candidate.lower() in used:
            candidate = f"{base}_{i}"
            i += 1
        used.add(candidate.lower())
        out[n.id] = candidate
    return out


def _slug(text: str) -> str:
    """Strip characters that would break an Obsidian filename."""
    cleaned = _SAFE_FILENAME.sub("", text).strip().rstrip(".")
    return cleaned[:80]


def _render_note(
    node: Node,
    slugs: dict[str, str],
    by_id: dict[str, Node],
    outs: list[Edge],
    ins: list[Edge],
) -> str:
    lang = node.language or "unknown"
    kind = node.kind or "unknown"

    tags = [f"language/{lang}", f"kind/{kind}"]
    fm = ["---"]
    fm.append(f"id: {node.id}")
    fm.append(f"label: {_yaml_str(node.label)}")
    fm.append(f"language: {lang}")
    fm.append(f"kind: {kind}")
    if node.source_file:
        fm.append(f"source_file: {_yaml_str(node.source_file)}")
    if node.source_location:
        fm.append(f"source_location: {node.source_location}")
    fm.append("tags:")
    for t in tags:
        fm.append(f"  - {t}")
    fm.append("---")

    body = [f"# {node.label}", ""]
    if node.source_file:
        loc = f":{node.source_location}" if node.source_location else ""
        body.append(f"**Source:** `{node.source_file}{loc}`")
        body.append("")

    if outs:
        body.append("## Outgoing")
        body.append("")
        for e in outs:
            tgt = by_id.get(e.target)
            link = f"[[{slugs[e.target]}]]" if tgt else f"`{e.target}`"
            body.append(f"- `{e.relation}` → {link}  _({e.confidence})_")
        body.append("")

    if ins:
        body.append("## Incoming")
        body.append("")
        for e in ins:
            src = by_id.get(e.source)
            link = f"[[{slugs[e.source]}]]" if src else f"`{e.source}`"
            body.append(f"- {link} `{e.relation}` →  _({e.confidence})_")
        body.append("")

    return "\n".join(fm + [""] + body)


def _render_index(nodes: list[Node], edges: list[Edge]) -> str:
    lang_counts: dict[str, int] = defaultdict(int)
    kind_counts: dict[str, int] = defaultdict(int)
    for n in nodes:
        lang_counts[n.language or "unknown"] += 1
        kind_counts[n.kind or "unknown"] += 1

    lines = [
        "# GraphFocus Vault",
        "",
        f"- Notes: **{len(nodes)}**",
        f"- Links: **{len(edges)}**",
        "",
        "## By language",
        "",
    ]
    for lang, c in sorted(lang_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{lang}`: {c}")
    lines += ["", "## By kind", ""]
    for kind, c in sorted(kind_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{kind}`: {c}")
    return "\n".join(lines) + "\n"


def _yaml_str(value: str) -> str:
    """Quote a YAML scalar containing colons, quotes or hashes."""
    if any(ch in value for ch in ':#"\n'):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value
