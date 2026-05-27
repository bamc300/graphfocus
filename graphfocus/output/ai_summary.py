"""Ultra-compact Markdown summary aimed at LLM context windows.

The goal is to give an AI assistant a complete bird's-eye view of the
codebase in a single ~5KB file it can paste into its system prompt or
load on demand. Verbose details live in graph.json — this is a *map*.

Format (one section per language, one block per file):

    # GraphFocus AI Summary

    ## Cross-language links
    - OrderEntity (java) -[maps_to]-> orders (sql)

    ## java
    ### UserService.java
    UserService [class] L9 @Service
      .create() [method] L22 @Transactional → User.save
      .find() [method] L17 → User.findByIdAndIsDeletedIsFalse

The format is greppable, line-oriented, and dense.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from graphfocus.extractors.base import Edge, Node


def render_ai_summary(
    nodes: list[Node],
    edges: list[Edge],
    output_path: Path,
    *,
    max_calls_per_method: int = 4,
) -> int:
    """Write a dense LLM-friendly summary. Returns the file size in bytes."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    by_id: dict[str, Node] = {n.id: n for n in nodes}
    out_edges: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        out_edges[e.source].append(e)

    # Group nodes by language → file
    grouped: dict[str, dict[str, list[Node]]] = defaultdict(lambda: defaultdict(list))
    for n in nodes:
        lang = n.language or "unknown"
        file = n.source_file or "unknown"
        grouped[lang][file].append(n)

    lines: list[str] = ["# GraphFocus AI Summary", ""]

    # ── Cross-language links section ─────────────────────────────────
    cross: list[tuple[Node, Node, Edge]] = []
    for e in edges:
        s = by_id.get(e.source)
        t = by_id.get(e.target)
        if s and t and s.language and t.language and s.language != t.language:
            cross.append((s, t, e))
    if cross:
        lines.append("## Cross-language links")
        for s, t, e in cross[:50]:
            lines.append(
                f"- {s.label} ({s.language}) -[{e.relation}]-> "
                f"{t.label} ({t.language})"
            )
        lines.append("")

    # ── Stats ────────────────────────────────────────────────────────
    lines.append("## Stats")
    lang_counts = {lang: sum(len(v) for v in files.values())
                   for lang, files in grouped.items()}
    for lang, count in sorted(lang_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {lang}: {count} nodes")
    lines.append("")

    # ── Per-language sections ────────────────────────────────────────
    for lang in sorted(grouped):
        if lang == "unknown":
            continue
        lines.append(f"## {lang}")
        for file in sorted(grouped[lang]):
            stem = file.rsplit("/", 1)[-1]
            lines.append(f"### {stem}")
            file_nodes = grouped[lang][file]
            # Render container nodes (class, interface, struct, …) first,
            # then orphan functions/methods.
            containers = [n for n in file_nodes
                          if n.kind in ("class", "interface", "struct", "trait",
                                        "protocol", "object", "enum",
                                        "case_class", "data_class", "component",
                                        "abstract_class", "mixin", "package",
                                        "namespace", "module")]
            top_level = [n for n in file_nodes
                         if n.kind in ("function",)]

            for c in containers:
                meta = _summarise_meta(c)
                lines.append(f"{c.label} [{c.kind}] {c.source_location or ''}{meta}")
                # Members: methods/fields/properties from outgoing edges.
                for e in out_edges.get(c.id, []):
                    tgt = by_id.get(e.target)
                    if tgt is None:
                        continue
                    if tgt.kind in ("method", "function"):
                        calls = _short_calls(out_edges, by_id, tgt.id,
                                             max_calls_per_method)
                        meta = _summarise_meta(tgt)
                        lines.append(
                            f"  .{tgt.label} [{tgt.kind}] "
                            f"{tgt.source_location or ''}{meta}{calls}"
                        )
            for f in top_level:
                calls = _short_calls(out_edges, by_id, f.id, max_calls_per_method)
                lines.append(
                    f"{f.label} [function] {f.source_location or ''}{calls}"
                )
            lines.append("")
        lines.append("")

    text = "\n".join(lines)
    output_path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _summarise_meta(node: Node) -> str:
    """Render decorators/annotations inline, compactly."""
    if not node.metadata:
        return ""
    parts: list[str] = []
    for key in ("annotations", "attributes", "decorators", "spring_roles"):
        vals = node.metadata.get(key)
        if vals:
            parts.extend(f"@{v}" for v in vals[:3])
            break
    if not parts:
        return ""
    return " " + " ".join(parts)


def _short_calls(out_edges, by_id, src_id, limit) -> str:
    """Render a few outgoing call targets inline: ' → save, find'."""
    callees: list[str] = []
    for e in out_edges.get(src_id, []):
        if e.relation != "calls":
            continue
        tgt = by_id.get(e.target)
        if tgt is None:
            continue
        callees.append(tgt.label.strip("()").lstrip("."))
        if len(callees) >= limit:
            break
    return " → " + ", ".join(callees) if callees else ""
