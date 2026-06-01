"""Markdown extractor — turns docs, ADRs and READMEs into nodes too.

This is the first non-code extractor. It treats a Markdown file as a
graph of headings linked by their hierarchy plus the cross-references
they make to other documents.

Extracted:

  * One ``document`` node per file.
  * One ``heading`` node per ``#``/``##``/``###`` heading, with a
    ``contains`` edge from its parent (file or higher-level heading).
  * One ``references`` edge per ``[text](path.md)`` or ``[[wikilink]]``
    that targets a local file. External http(s) links and anchors are
    captured as edges too, but pointing at a synthetic node so the LLM
    can still see what the doc references.
  * Optional ADR slug: if the filename matches ``adr-NNN-*`` the doc
    is tagged with ``kind="adr"`` so architecture-decision-record
    workflows can filter on it.
"""

from __future__ import annotations

import re
from pathlib import Path

from graphfocus.extractors.base import (
    Edge,
    ExtractionResult,
    LanguageExtractor,
    Node,
    make_id,
)

# Matches a setext or ATX heading line.
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)

# [text](path) — non-image, non-empty path.
_LINK_INLINE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Obsidian-style [[wikilink]] or [[wikilink|alias]].
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# ADR file pattern: adr-001-some-title.md or 001-some-title.md
_ADR_FILENAME = re.compile(r"^(?:adr[-_])?(\d{3,4})[-_]", re.IGNORECASE)


class MarkdownExtractor(LanguageExtractor):
    """Treat ``.md`` / ``.markdown`` / ``.mdx`` files as document graphs."""

    @property
    def language_name(self) -> str:
        return "markdown"

    @property
    def extensions(self) -> set[str]:
        return {".md", ".markdown", ".mdx"}

    def extract(self, path: Path) -> ExtractionResult:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ExtractionResult(errors=[f"Read error: {e}"])

        stem = path.stem
        str_path = str(path)
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen: set[str] = set()

        is_adr = bool(_ADR_FILENAME.match(path.name))
        doc_kind = "adr" if is_adr else "document"

        def line_of(idx: int) -> int:
            return source[:idx].count("\n") + 1

        def add_node(nid: str, label: str, line: int, kind: str, **meta) -> None:
            if nid not in seen:
                seen.add(nid)
                nodes.append(Node(
                    id=nid, label=label, file_type="document",
                    source_file=str_path, source_location=f"L{line}",
                    language="markdown", kind=kind,
                    metadata=meta if meta else {},
                ))

        def add_edge(src: str, tgt: str, relation: str, line: int,
                     confidence: str = "EXTRACTED") -> None:
            edges.append(Edge(
                source=src, target=tgt, relation=relation, confidence=confidence,
                source_file=str_path, source_location=f"L{line}",
            ))

        # ── File-level document node ──────────────────────────────────
        file_nid = make_id("doc", stem)
        add_node(file_nid, path.name, 1, doc_kind)

        # ── Headings (build a small hierarchy) ────────────────────────
        # heading_stack: list of (level, nid) for the currently-open headings.
        heading_stack: list[tuple[int, str]] = []
        for match in _HEADING.finditer(source):
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            line = line_of(match.start())

            # Pop deeper-or-equal levels off the stack.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent_nid = heading_stack[-1][1] if heading_stack else file_nid

            heading_nid = make_id(file_nid, f"h{level}", heading_text)
            add_node(heading_nid, heading_text, line, f"heading_h{level}")
            add_edge(parent_nid, heading_nid, "contains", line)
            heading_stack.append((level, heading_nid))

        # ── Inline links [text](url) ─────────────────────────────────
        for match in _LINK_INLINE.finditer(source):
            href = match.group(2)
            line = line_of(match.start())
            if href.startswith(("http://", "https://")):
                # External — point at a synthetic node keyed by host.
                host = href.split("/", 3)[2] if "://" in href else href
                ext_nid = make_id("url", host)
                if ext_nid not in seen:
                    add_node(ext_nid, host, line, "external_url")
                add_edge(file_nid, ext_nid, "references_url", line)
                continue
            if href.startswith("#"):
                # Same-document anchor; skip.
                continue
            # Local reference (relative path or absolute path string).
            target_stem = Path(href).stem
            target_nid = make_id("doc", target_stem)
            add_edge(file_nid, target_nid, "references", line)

        # ── Wikilinks [[Page Title]] ─────────────────────────────────
        for match in _WIKILINK.finditer(source):
            target_label = match.group(1).strip()
            line = line_of(match.start())
            target_nid = make_id("doc", target_label)
            add_edge(file_nid, target_nid, "wikilinks", line)

        return ExtractionResult(nodes=nodes, edges=edges)
