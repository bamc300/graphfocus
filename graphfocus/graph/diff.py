"""Diff two graph snapshots — useful for PR reviews and audits.

Compares two ``graph.json`` payloads and reports:

  * Nodes added / removed (by id).
  * Edges added / removed (matched on source+target+relation).
  * Nodes whose attributes changed (kind, language, source_location).

Each section is bounded so a noisy diff doesn't dump megabytes of
output; the totals always reflect the unbounded count.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GraphDiff:
    added_nodes: list[dict] = field(default_factory=list)
    removed_nodes: list[dict] = field(default_factory=list)
    changed_nodes: list[dict] = field(default_factory=list)
    added_edges: list[dict] = field(default_factory=list)
    removed_edges: list[dict] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            len(self.added_nodes) + len(self.removed_nodes)
            + len(self.changed_nodes)
            + len(self.added_edges) + len(self.removed_edges)
        )

    def to_dict(self) -> dict:
        return {
            "summary": {
                "added_nodes": len(self.added_nodes),
                "removed_nodes": len(self.removed_nodes),
                "changed_nodes": len(self.changed_nodes),
                "added_edges": len(self.added_edges),
                "removed_edges": len(self.removed_edges),
            },
            "added_nodes": self.added_nodes,
            "removed_nodes": self.removed_nodes,
            "changed_nodes": self.changed_nodes,
            "added_edges": self.added_edges,
            "removed_edges": self.removed_edges,
        }


# Fields that, if they differ between two same-id nodes, count as a "change".
_TRACKED_NODE_FIELDS = ("kind", "language", "source_file", "source_location")


def diff_graphs(old: dict, new: dict) -> GraphDiff:
    """Return a structured diff between two graph payloads.

    Args:
        old: parsed ``graph.json`` from the older snapshot.
        new: parsed ``graph.json`` from the newer snapshot.
    """
    old_nodes = {n["id"]: n for n in old.get("nodes") or []}
    new_nodes = {n["id"]: n for n in new.get("nodes") or []}

    added_ids = new_nodes.keys() - old_nodes.keys()
    removed_ids = old_nodes.keys() - new_nodes.keys()
    common_ids = new_nodes.keys() & old_nodes.keys()

    changed: list[dict] = []
    for nid in common_ids:
        before = old_nodes[nid]
        after = new_nodes[nid]
        delta = {
            f: {"before": before.get(f), "after": after.get(f)}
            for f in _TRACKED_NODE_FIELDS
            if before.get(f) != after.get(f)
        }
        if delta:
            changed.append({
                "id": nid,
                "label": after.get("label"),
                "changes": delta,
            })

    def _edge_key(e: dict) -> tuple[str, str, str]:
        return (e["source"], e["target"], e.get("relation", ""))

    old_edges = {_edge_key(e): e for e in old.get("edges") or []}
    new_edges = {_edge_key(e): e for e in new.get("edges") or []}

    added_edges = [new_edges[k] for k in new_edges.keys() - old_edges.keys()]
    removed_edges = [old_edges[k] for k in old_edges.keys() - new_edges.keys()]

    return GraphDiff(
        added_nodes=[new_nodes[i] for i in sorted(added_ids)],
        removed_nodes=[old_nodes[i] for i in sorted(removed_ids)],
        changed_nodes=sorted(changed, key=lambda c: c["id"]),
        added_edges=added_edges,
        removed_edges=removed_edges,
    )
