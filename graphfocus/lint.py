"""Architecture lint — assert rules about the graph and report violations.

Rule file (``.graphfocus.yml`` at the project root, or passed via
``--rules``)::

    rules:
      # Forbid edges from any UI node to any DB node.
      - name: ui-must-not-touch-db
        disallow:
          from:
            language: typescript
          to:
            language: sql

      # Force the auth layer to only talk to itself or to repo classes.
      - name: auth-only-talks-to-repos
        require:
          from:
            kind: class
            name_match: "Auth"
          to_any_of:
            - kind: class
              name_match: "Repo"
            - kind: class
              name_match: "Auth"

      # Cap fan-out (max outgoing edges per node).
      - name: no-god-classes
        max_outgoing: 30
        scope:
          kind: class

A rule fires when ALL of the conditions in its ``disallow`` block match
an edge, OR when a ``require`` block describes an obligation the graph
does not meet, OR when ``max_outgoing`` is exceeded. Each violation has
a ``rule`` name, a ``message``, and the offending nodes/edge.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Violation:
    rule: str
    message: str
    source_id: str | None = None
    target_id: str | None = None
    relation: str | None = None
    location: str | None = None


@dataclass
class Selector:
    """A filter that matches a subset of nodes.

    Empty selector → matches everything. Combining keys is AND.
    """
    language: str | None = None
    kind: str | None = None
    name_match: str | None = None        # regex on label or id
    id_match: str | None = None          # regex on id only

    _label_re: re.Pattern | None = field(default=None, init=False, repr=False)
    _id_re: re.Pattern | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if self.name_match:
            self._label_re = re.compile(self.name_match, re.IGNORECASE)
        if self.id_match:
            self._id_re = re.compile(self.id_match, re.IGNORECASE)

    def matches(self, node: dict) -> bool:
        if self.language and node.get("language") != self.language:
            return False
        if self.kind and node.get("kind") != self.kind:
            return False
        if self._label_re and not self._label_re.search(
            node.get("label") or "",
        ) and not self._label_re.search(node.get("id") or ""):
            return False
        return not (self._id_re and not self._id_re.search(node.get("id") or ""))


@dataclass
class Rule:
    name: str
    disallow: dict | None = None     # {"from": {...}, "to": {...}}
    require: dict | None = None      # {"from": {...}, "to_any_of": [{...}]}
    max_outgoing: int | None = None
    max_incoming: int | None = None
    scope: dict | None = None        # selector for nodes the rule applies to


def load_rules(path: Path) -> list[Rule]:
    """Parse a YAML rules file into ``Rule`` objects."""
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError(
            "PyYAML required for lint rules — pip install 'graphfocus[api]'",
        ) from e
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules: list[Rule] = []
    for item in raw.get("rules", []):
        rules.append(Rule(
            name=item.get("name") or "unnamed",
            disallow=item.get("disallow"),
            require=item.get("require"),
            max_outgoing=item.get("max_outgoing"),
            max_incoming=item.get("max_incoming"),
            scope=item.get("scope"),
        ))
    return rules


def _selector(d: dict | None) -> Selector:
    d = d or {}
    return Selector(
        language=d.get("language"),
        kind=d.get("kind"),
        name_match=d.get("name_match"),
        id_match=d.get("id_match"),
    )


def evaluate(
    rules: list[Rule],
    nodes: list[dict],
    edges: list[dict],
) -> list[Violation]:
    """Apply every rule to the graph; return all violations."""
    by_id = {n["id"]: n for n in nodes}
    out_edges: dict[str, list[dict]] = defaultdict(list)
    in_edges: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        out_edges[e["source"]].append(e)
        in_edges[e["target"]].append(e)

    violations: list[Violation] = []

    for rule in rules:
        # ── disallow: edge X with from-match and to-match ────────
        if rule.disallow:
            from_sel = _selector(rule.disallow.get("from"))
            to_sel = _selector(rule.disallow.get("to"))
            for e in edges:
                s = by_id.get(e["source"])
                t = by_id.get(e["target"])
                if s and t and from_sel.matches(s) and to_sel.matches(t):
                    violations.append(Violation(
                        rule=rule.name,
                        message=(
                            f"forbidden edge {s.get('label')} "
                            f"-[{e['relation']}]-> {t.get('label')}"
                        ),
                        source_id=e["source"],
                        target_id=e["target"],
                        relation=e["relation"],
                        location=s.get("source_file"),
                    ))

        # ── require: every from-node must have at least one to-node ─
        if rule.require:
            from_sel = _selector(rule.require.get("from"))
            allowed = [
                _selector(d) for d in (rule.require.get("to_any_of") or [])
            ] or [_selector(rule.require.get("to"))]

            for n in nodes:
                if not from_sel.matches(n):
                    continue
                # Walk outgoing edges; require at least one points to an
                # allowed target. If the node has no outgoing edges, that
                # already breaks the obligation.
                ok = False
                for e in out_edges.get(n["id"], []):
                    t = by_id.get(e["target"])
                    if not t:
                        continue
                    if any(sel.matches(t) for sel in allowed):
                        ok = True
                        break
                # Detect strictly forbidden talks: any outgoing edge to
                # something NOT in the allowed set is a violation.
                for e in out_edges.get(n["id"], []):
                    t = by_id.get(e["target"])
                    if t and not any(sel.matches(t) for sel in allowed):
                        violations.append(Violation(
                            rule=rule.name,
                            message=(
                                f"{n.get('label')} talks to "
                                f"{t.get('label')} ({t.get('kind')}/"
                                f"{t.get('language')}) but rule allows only "
                                f"the listed shapes"
                            ),
                            source_id=n["id"],
                            target_id=e["target"],
                            relation=e["relation"],
                            location=n.get("source_file"),
                        ))
                if not ok and out_edges.get(n["id"]):
                    # Already emitted per-edge violations above.
                    continue

        # ── max_outgoing / max_incoming ───────────────────────────
        scope = _selector(rule.scope) if rule.scope else None
        if rule.max_outgoing is not None:
            for n in nodes:
                if scope and not scope.matches(n):
                    continue
                count = len(out_edges.get(n["id"], []))
                if count > rule.max_outgoing:
                    violations.append(Violation(
                        rule=rule.name,
                        message=(
                            f"{n.get('label')} has {count} outgoing edges "
                            f"(limit {rule.max_outgoing})"
                        ),
                        source_id=n["id"],
                        location=n.get("source_file"),
                    ))
        if rule.max_incoming is not None:
            for n in nodes:
                if scope and not scope.matches(n):
                    continue
                count = len(in_edges.get(n["id"], []))
                if count > rule.max_incoming:
                    violations.append(Violation(
                        rule=rule.name,
                        message=(
                            f"{n.get('label')} has {count} incoming edges "
                            f"(limit {rule.max_incoming})"
                        ),
                        source_id=n["id"],
                        location=n.get("source_file"),
                    ))

    return violations
