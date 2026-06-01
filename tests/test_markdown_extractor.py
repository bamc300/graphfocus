"""Tests for the Markdown / ADR extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.base import make_id
from graphfocus.extractors.markdown_extractor import MarkdownExtractor


@pytest.fixture
def extractor() -> MarkdownExtractor:
    return MarkdownExtractor()


@pytest.fixture
def md_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "markdown" / "adr-001-use-graphfocus.md"


class TestMarkdownExtractor:
    def test_file_is_classified_as_adr(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        doc = next(n for n in result.nodes if n.kind == "adr")
        assert doc is not None
        assert doc.label.endswith(".md")

    def test_extracts_heading_hierarchy(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        labels_by_kind: dict[str, list[str]] = {}
        for n in result.nodes:
            labels_by_kind.setdefault(n.kind or "?", []).append(n.label)
        assert "ADR 001 — Use GraphFocus for code intelligence" in labels_by_kind["heading_h1"]
        assert "Status" in labels_by_kind["heading_h2"]
        assert "Consequences" in labels_by_kind["heading_h3"]

    def test_subheading_is_contained_by_its_parent(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        by_label = {n.label: n for n in result.nodes}
        decision = by_label["Decision"]
        consequences = by_label["Consequences"]
        contains = [(e.source, e.target) for e in result.edges if e.relation == "contains"]
        assert (decision.id, consequences.id) in contains

    def test_inline_links_become_references_edges(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        refs = [e for e in result.edges if e.relation == "references"]
        target_ids = {e.target for e in refs}
        assert make_id("doc", "README") in target_ids

    def test_wikilinks_become_wikilinks_edges(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        wikis = [e for e in result.edges if e.relation == "wikilinks"]
        target_ids = {e.target for e in wikis}
        assert make_id("doc", "Architecture") in target_ids
        assert make_id("doc", "Visualization") in target_ids

    def test_external_urls_become_references_url(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        ext = [e for e in result.edges if e.relation == "references_url"]
        assert len(ext) >= 1

    def test_language_attribution(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        for n in result.nodes:
            assert n.language == "markdown"

    def test_no_errors(self, extractor, md_fixture):
        result = extractor.extract(md_fixture)
        assert not result.errors

    def test_plain_doc_is_kind_document(self, extractor, tmp_path: Path):
        md = tmp_path / "README.md"
        md.write_text("# Hello\n\nSome text [link](other.md).\n")
        result = extractor.extract(md)
        doc = next(n for n in result.nodes if n.kind == "document")
        assert doc.label == "README.md"
