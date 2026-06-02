"""Tests for the architecture-lint engine."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # noqa: F841

from graphfocus.lint import Rule, evaluate, load_rules  # noqa: E402


def _g():
    nodes = [
        {"id": "ui_button", "label": "Button", "language": "typescript", "kind": "component"},
        {"id": "ui_form", "label": "Form", "language": "typescript", "kind": "component"},
        {"id": "users_tbl", "label": "users", "language": "sql", "kind": "table"},
        {"id": "user_svc", "label": "UserService", "language": "java", "kind": "class"},
        {"id": "user_repo", "label": "UserRepo", "language": "java", "kind": "class"},
        {"id": "auth_filter", "label": "AuthFilter", "language": "java", "kind": "class"},
    ]
    edges = [
        # Bad: UI talks to SQL directly.
        {"source": "ui_button", "target": "users_tbl", "relation": "queries"},
        {"source": "user_svc", "target": "user_repo", "relation": "calls"},
        {"source": "user_svc", "target": "users_tbl", "relation": "maps_to"},
        # Fan-out test: ui_form has many outgoing.
        *[
            {"source": "ui_form", "target": f"x{i}", "relation": "calls"}
            for i in range(15)
        ],
    ]
    # Materialise the x{i} targets so they exist.
    for i in range(15):
        nodes.append({"id": f"x{i}", "label": f"X{i}", "language": "java",
                      "kind": "class"})
    return nodes, edges


class TestDisallow:
    def test_disallow_ui_to_sql(self):
        nodes, edges = _g()
        rule = Rule(
            name="ui-not-sql",
            disallow={"from": {"language": "typescript"},
                      "to": {"language": "sql"}},
        )
        violations = evaluate([rule], nodes, edges)
        assert len(violations) == 1
        assert violations[0].source_id == "ui_button"
        assert violations[0].target_id == "users_tbl"

    def test_disallow_no_false_positive(self):
        nodes, edges = _g()
        rule = Rule(
            name="java-not-html",
            disallow={"from": {"language": "java"},
                      "to": {"language": "html"}},
        )
        assert evaluate([rule], nodes, edges) == []


class TestRequire:
    def test_auth_must_only_talk_to_repos_or_auth(self):
        nodes, edges = _g()
        # AuthFilter has no edges yet — add one bad and one good.
        edges = list(edges) + [
            {"source": "auth_filter", "target": "user_svc", "relation": "calls"},  # bad
        ]
        rule = Rule(
            name="auth-isolation",
            require={
                "from": {"name_match": "Auth"},
                "to_any_of": [
                    {"name_match": "Repo"},
                    {"name_match": "Auth"},
                ],
            },
        )
        violations = evaluate([rule], nodes, edges)
        # The auth→svc edge violates; the rule emits one per bad target.
        bad_targets = {v.target_id for v in violations
                       if v.source_id == "auth_filter"}
        assert "user_svc" in bad_targets


class TestMaxFanOut:
    def test_max_outgoing_flags_god_class(self):
        nodes, edges = _g()
        rule = Rule(
            name="no-god",
            max_outgoing=10,
            scope={"kind": "component"},
        )
        violations = evaluate([rule], nodes, edges)
        offending = [v for v in violations if v.source_id == "ui_form"]
        assert offending
        assert "15" in offending[0].message

    def test_max_outgoing_respects_scope(self):
        nodes, edges = _g()
        rule = Rule(
            name="no-god-classes-only",
            max_outgoing=1,
            scope={"kind": "class"},   # ui_form is a component, excluded
        )
        violations = evaluate([rule], nodes, edges)
        for v in violations:
            assert v.source_id != "ui_form"


class TestLoadRules:
    def test_round_trip_from_yaml(self, tmp_path: Path):
        rules_yaml = """
rules:
  - name: ui-not-sql
    disallow:
      from: {language: typescript}
      to: {language: sql}
  - name: no-god-class
    max_outgoing: 30
    scope: {kind: class}
"""
        p = tmp_path / ".graphfocus.yml"
        p.write_text(rules_yaml)
        rules = load_rules(p)
        assert len(rules) == 2
        assert rules[0].name == "ui-not-sql"
        assert rules[1].max_outgoing == 30
