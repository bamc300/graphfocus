"""Tests for the TF-IDF semantic index."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.semantic_index import (
    build_index,
    filter_by,
    load_index,
    save_index,
    search,
    tokenize,
)


class TestTokenize:
    def test_splits_camel_case(self):
        assert "user" in tokenize("UserService")
        assert "service" in tokenize("UserService")

    def test_splits_snake_case(self):
        toks = tokenize("validate_email")
        assert "validate" in toks
        assert "email" in toks

    def test_lowercases(self):
        toks = tokenize("HTTPServer")
        assert all(t == t.lower() for t in toks)

    def test_drops_single_char_and_digits(self):
        toks = tokenize("a b 123 cd")
        assert "a" not in toks
        assert "b" not in toks
        assert "123" not in toks
        assert "cd" in toks


class TestBuildIndex:
    def test_empty_corpus(self):
        idx = build_index([])
        assert idx == {"idf": {}, "vectors": []}

    def test_indexes_each_node(self):
        nodes = [
            {"id": "a", "label": "UserService", "kind": "class", "language": "java"},
            {"id": "b", "label": "PaymentRepo", "kind": "class", "language": "java"},
        ]
        idx = build_index(nodes)
        assert len(idx["vectors"]) == 2
        assert {v["id"] for v in idx["vectors"]} == {"a", "b"}
        assert "user" in idx["idf"]
        assert "payment" in idx["idf"]


class TestSearch:
    @pytest.fixture
    def index(self):
        nodes = [
            {"id": "uc", "label": "UserController", "kind": "class", "language": "java"},
            {"id": "us", "label": "UserService", "kind": "class", "language": "java"},
            {"id": "ur", "label": "UserRepository", "kind": "interface",
             "language": "java"},
            {"id": "pc", "label": "PaymentController", "kind": "class",
             "language": "java"},
            {"id": "auth", "label": "AuthenticationFilter", "kind": "class",
             "language": "java"},
            {"id": "table", "label": "users", "kind": "table", "language": "sql"},
        ]
        return nodes, build_index(nodes)

    def test_finds_exact_token(self, index):
        nodes, idx = index
        results = search(idx, "user")
        ids = [r[0] for r in results]
        # All four user-containing nodes should rank highly.
        assert {"uc", "us", "ur", "table"}.issubset(set(ids))

    def test_ranks_by_relevance(self, index):
        nodes, idx = index
        results = search(idx, "payment")
        # The PaymentController must be the top match (only one with "payment").
        assert results[0][0] == "pc"

    def test_multi_token_query(self, index):
        nodes, idx = index
        results = search(idx, "user controller")
        ids = [r[0] for r in results]
        # UserController has both query tokens → top.
        assert ids[0] == "uc"

    def test_filter_by_language(self, index):
        nodes, idx = index
        nodes_by_id = {n["id"]: n for n in nodes}
        results = search(idx, "user")
        filtered = filter_by(results, nodes_by_id, language="sql")
        assert all(nodes_by_id[i]["language"] == "sql" for i, _ in filtered)

    def test_no_match_returns_empty(self, index):
        nodes, idx = index
        assert search(idx, "xyzzy_no_such_token") == []


class TestPersistence:
    def test_round_trip(self, tmp_path: Path):
        nodes = [
            {"id": "a", "label": "Foo", "kind": "class", "language": "python"},
            {"id": "b", "label": "Bar", "kind": "function", "language": "python"},
        ]
        idx = build_index(nodes)
        path = tmp_path / "semantic.json"
        save_index(idx, path)
        loaded = load_index(path)
        assert loaded is not None
        assert len(loaded["vectors"]) == 2

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert load_index(tmp_path / "does_not_exist.json") is None

    def test_load_empty_returns_none(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text('{"idf":{},"vectors":[]}')
        assert load_index(path) is None
