"""Tests for the Obsidian vault generator."""

from __future__ import annotations

from pathlib import Path

from graphfocus.extractors.base import Edge, Node
from graphfocus.output.obsidian import generate_obsidian_vault


def _graph() -> tuple[list[Node], list[Edge]]:
    nodes = [
        Node(id="mod_a", label="a.py", language="python", kind="module",
             source_file="a.py", source_location="L1"),
        Node(id="mod_a_user", label="User", language="python", kind="class",
             source_file="a.py", source_location="L5"),
        Node(id="schema_users", label="users", language="sql", kind="table",
             source_file="schema.sql", source_location="L1"),
    ]
    edges = [
        Edge(source="mod_a", target="mod_a_user", relation="contains", confidence="EXTRACTED"),
        Edge(source="mod_a_user", target="schema_users", relation="maps_to", confidence="INFERRED"),
    ]
    return nodes, edges


class TestObsidianVault:
    def test_writes_one_note_per_node(self, tmp_path: Path):
        nodes, edges = _graph()
        vault = tmp_path / "vault"
        summary = generate_obsidian_vault(nodes, edges, vault)

        assert summary["notes"] == 3
        assert (vault / "_Index.md").exists()
        # One subdirectory per language
        assert (vault / "python").is_dir()
        assert (vault / "sql").is_dir()
        # User note exists in python/
        user_notes = list((vault / "python").glob("User*.md"))
        assert len(user_notes) == 1

    def test_frontmatter_has_id_and_tags(self, tmp_path: Path):
        nodes, edges = _graph()
        vault = tmp_path / "vault"
        generate_obsidian_vault(nodes, edges, vault)
        user_note = next((vault / "python").glob("User*.md")).read_text()

        assert user_note.startswith("---")
        assert "id: mod_a_user" in user_note
        assert "language: python" in user_note
        assert "kind: class" in user_note
        assert "language/python" in user_note
        assert "kind/class" in user_note

    def test_renders_outgoing_and_incoming_links(self, tmp_path: Path):
        nodes, edges = _graph()
        vault = tmp_path / "vault"
        generate_obsidian_vault(nodes, edges, vault)
        user_note = next((vault / "python").glob("User*.md")).read_text()

        # User → users (outgoing)
        assert "## Outgoing" in user_note
        assert "maps_to" in user_note
        assert "[[users]]" in user_note
        # a.py → User (incoming)
        assert "## Incoming" in user_note
        assert "contains" in user_note

    def test_index_summarises_counts(self, tmp_path: Path):
        nodes, edges = _graph()
        vault = tmp_path / "vault"
        generate_obsidian_vault(nodes, edges, vault)
        index = (vault / "_Index.md").read_text()

        assert "Notes: **3**" in index
        assert "Links: **2**" in index
        assert "python" in index
        assert "sql" in index

    def test_filename_collisions_get_suffix(self, tmp_path: Path):
        # Two nodes share the same label but different ids; both should
        # land in disk without overwriting each other.
        nodes = [
            Node(id="a_user", label="User", language="python", kind="class"),
            Node(id="b_user", label="User", language="python", kind="class"),
        ]
        vault = tmp_path / "vault"
        generate_obsidian_vault(nodes, [], vault)
        files = sorted(p.name for p in (vault / "python").glob("*.md"))
        assert files == ["User.md", "User_2.md"]

    def test_unsafe_chars_stripped_from_filename(self, tmp_path: Path):
        nodes = [
            Node(id="x", label="weird/name:with*chars", language="python", kind="class"),
        ]
        vault = tmp_path / "vault"
        generate_obsidian_vault(nodes, [], vault)
        files = list((vault / "python").glob("*.md"))
        assert len(files) == 1
        assert "/" not in files[0].name
        assert ":" not in files[0].name
        assert "*" not in files[0].name
