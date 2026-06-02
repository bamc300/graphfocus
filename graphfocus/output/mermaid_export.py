"""Export the knowledge graph (or a filtered subgraph) as Mermaid.

Mermaid renders inside GitHub, GitLab, Notion, Obsidian and most static
site generators, so this is the cheapest way to embed a GraphFocus
diagram in a README or design doc.

For huge graphs we cap the node count and pick by degree so the diagram
stays readable. The user can pass filters (language, kind, community
or a list of root nodes) to narrow the export.
"""

from __future__ import annotations

import re
from pathlib import Path

_MMD_ID = re.compile(r"[^A-Za-z0-9_]+")


def _safe(s: str) -> str:
    """Mermaid node ids are restricted; sanitise to [A-Za-z0-9_]."""
    cleaned = _MMD_ID.sub("_", s)
    if cleaned and cleaned[0].isdigit():
        cleaned = "n_" + cleaned
    return cleaned or "n"


def _label(node: dict) -> str:
    """Escape a label for Mermaid (quotes, brackets, pipes)."""
    label = node.get("label", node["id"])
    return label.replace("\"", "'").replace("|", "/").replace("[", "(").replace("]", ")")


def render_mermaid(
    nodes: list[dict],
    edges: list[dict],
    *,
    direction: str = "LR",
    max_nodes: int = 150,
    language: str | None = None,
    kind: str | None = None,
    community: int | None = None,
    roots: list[str] | None = None,
) -> str:
    """Render the graph as a Mermaid ``flowchart`` block.

    Args:
        nodes: raw node dicts (e.g. from ``graph.json``).
        edges: raw edge dicts.
        direction: Mermaid layout — ``LR``, ``RL``, ``TB``, ``BT``.
        max_nodes: cap on rendered nodes. Picks the top-N by degree.
        language: only include nodes from this language.
        kind: only include nodes of this kind.
        community: only include nodes from this Leiden community.
        roots: only include these node ids and their immediate neighbors.

    Returns:
        A string ready to write to a ``.mmd`` file or paste into
        Markdown inside a ```` ```mermaid ```` block.
    """
    by_id = {n["id"]: n for n in nodes}

    # ── Filter ────────────────────────────────────────────────────────
    selected: set[str] = set()
    if roots:
        seed = {r for r in roots if r in by_id}
        selected.update(seed)
        # Add only one-hop neighbors of the seed (don't expand transitively).
        for e in edges:
            if e["source"] in seed:
                selected.add(e["target"])
            elif e["target"] in seed:
                selected.add(e["source"])
    else:
        for n in nodes:
            if language and n.get("language") != language:
                continue
            if kind and n.get("kind") != kind:
                continue
            if community is not None and n.get("community") != community:
                continue
            selected.add(n["id"])

    # ── Cap by degree ────────────────────────────────────────────────
    degree: dict[str, int] = {}
    for e in edges:
        if e["source"] in selected:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
        if e["target"] in selected:
            degree[e["target"]] = degree.get(e["target"], 0) + 1

    if len(selected) > max_nodes:
        ranked = sorted(selected, key=lambda i: -degree.get(i, 0))
        selected = set(ranked[:max_nodes])

    # ── Render ───────────────────────────────────────────────────────
    out: list[str] = [f"flowchart {direction}"]
    for nid in sorted(selected):
        n = by_id.get(nid)
        if not n:
            continue
        out.append(f'  {_safe(nid)}["{_label(n)}"]')

    for e in edges:
        s, t = e["source"], e["target"]
        if s not in selected or t not in selected:
            continue
        rel = e.get("relation", "")
        out.append(f'  {_safe(s)} -->|{rel}| {_safe(t)}')

    return "\n".join(out) + "\n"


def write_mermaid(
    nodes: list[dict],
    edges: list[dict],
    output_path: Path,
    *,
    embed_in_markdown: bool = False,
    **kwargs,
) -> int:
    """Render and write to disk. Returns bytes written.

    If ``embed_in_markdown`` is True, wrap the diagram inside a
    fenced ```` ```mermaid ```` block so the file is a valid ``.md``.
    """
    body = render_mermaid(nodes, edges, **kwargs)
    if embed_in_markdown:
        body = f"```mermaid\n{body}```\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")
    return len(body.encode("utf-8"))
