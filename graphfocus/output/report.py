"""Generate Markdown analysis report."""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import Edge, Node


def generate_report(
    nodes: list[Node],
    edges: list[Edge],
    detection: dict,
    output_path: Path,
) -> None:
    """Generate a GRAPH_REPORT.md with analysis summary.

    Args:
        nodes: List of extracted Node objects
        edges: List of extracted Edge objects
        detection: Detection result dict from detect_files()
        output_path: Path to write the report
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Compute statistics
    languages = {}
    kinds = {}
    for n in nodes:
        lang = n.language or "unknown"
        languages[lang] = languages.get(lang, 0) + 1
        kind = n.kind or "unknown"
        kinds[kind] = kinds.get(kind, 0) + 1

    relations = {}
    confidence_counts = {"EXTRACTED": 0, "INFERRED": 0, "AMBIGUOUS": 0}
    for e in edges:
        relations[e.relation] = relations.get(e.relation, 0) + 1
        confidence_counts[e.confidence] = confidence_counts.get(e.confidence, 0) + 1

    # Find "god nodes" — nodes with the most connections
    connection_count: dict[str, int] = {}
    for e in edges:
        connection_count[e.source] = connection_count.get(e.source, 0) + 1
        connection_count[e.target] = connection_count.get(e.target, 0) + 1
    god_nodes = sorted(connection_count.items(), key=lambda x: x[1], reverse=True)[:10]

    # Build report
    lines = [
        "# GraphFocus Report",
        "",
        "## Corpus Summary",
        "",
        f"- **Total files analyzed:** {detection.get('total_files', 0)}",
        f"- **Estimated words:** {detection.get('total_words', 0):,}",
        f"- **Sensitive files skipped:** {detection.get('skipped_sensitive', 0)}",
        "",
        "### Files by type",
        "",
    ]

    for file_type, count in sorted(detection.get("by_type", {}).items()):
        lines.append(f"- {file_type}: {count}")

    lines.extend([
        "",
        "## Graph Summary",
        "",
        f"- **Nodes:** {len(nodes)}",
        f"- **Edges:** {len(edges)}",
        "",
        "### By language",
        "",
    ])

    for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {lang}: {count}")

    lines.extend([
        "",
        "### By kind",
        "",
    ])

    for kind, count in sorted(kinds.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {kind}: {count}")

    lines.extend([
        "",
        "### Edge types",
        "",
    ])

    for rel, count in sorted(relations.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {rel}: {count}")

    lines.extend([
        "",
        "### Confidence",
        "",
        f"- EXTRACTED: {confidence_counts['EXTRACTED']}",
        f"- INFERRED: {confidence_counts['INFERRED']}",
        f"- AMBIGUOUS: {confidence_counts['AMBIGUOUS']}",
        "",
        "## God Nodes (most connected)",
        "",
    ])

    node_labels = {n.id: n.label for n in nodes}
    for nid, count in god_nodes:
        label = node_labels.get(nid, nid)
        lines.append(f"- **{label}** ({nid}): {count} connections")

    lines.append("")

    output_path.write_text("\n".join(lines))
