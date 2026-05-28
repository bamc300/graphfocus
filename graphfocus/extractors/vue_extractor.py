"""Vue Single-File Component extractor.

A ``.vue`` file is not a language of its own: it is a wrapper that holds
up to three blocks — ``<template>``, ``<script>``, ``<style>``. This
extractor:

  1. Treats the file itself as a node with ``kind="component"``.
  2. Extracts the ``<script>`` block and delegates parsing to the
     TypeScript/JavaScript extractor (since the script is plain TS or
     JS, with optional ``lang="ts"``). The resulting nodes are rewritten
     to point back at the ``.vue`` file with correctly offset line
     numbers.
  3. Scans the ``<template>`` block with a regex to find child component
     usages (``<UserCard />``, ``<user-card>``) and emits ``uses``
     edges from the parent component to each referenced component.

No tree-sitter grammar is required for ``.vue``; the regex + script
delegation pattern is enough for the relationships we care about.
"""

from __future__ import annotations

import contextlib
import re
import tempfile
from pathlib import Path

from graphfocus.extractors.base import (
    Edge,
    ExtractionResult,
    LanguageExtractor,
    Node,
    make_id,
)
from graphfocus.extractors.typescript_extractor import TypeScriptExtractor

# Match a single <script ...>...</script> block. Re-runs to support
# Vue's optional separate <script setup> alongside a normal <script>.
_SCRIPT_BLOCK = re.compile(
    r"<script\b([^>]*)>(.*?)</script\s*>",
    re.DOTALL | re.IGNORECASE,
)

# `lang="ts"` on a script tag.
_LANG_TS = re.compile(r"""lang\s*=\s*["']ts["']""", re.IGNORECASE)

# Match opening tags whose name starts with an uppercase letter (PascalCase
# components like <UserCard>) or contains a hyphen (kebab-case components
# like <user-card>). HTML-native tags (lowercase, no hyphen) are skipped.
_TEMPLATE_TAG = re.compile(r"<([A-Za-z][\w-]*)\b")

# Tags that are always native HTML or Vue built-ins — never user components.
_HTML_TAGS = {
    "html", "head", "body", "div", "span", "p", "a", "img", "ul", "ol", "li",
    "table", "tr", "td", "th", "thead", "tbody", "form", "input", "label",
    "button", "select", "option", "textarea", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "nav", "main", "aside", "br", "hr",
    "i", "b", "u", "em", "strong", "small", "code", "pre", "blockquote",
    "template", "script", "style", "slot", "transition", "transition-group",
    "keep-alive", "teleport", "suspense", "component",
}


class VueExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "vue"

    @property
    def extensions(self) -> set[str]:
        return {".vue"}

    def __init__(self) -> None:
        # The script extractor lazily loads tree-sitter-typescript.
        self._script_extractor: TypeScriptExtractor | None = None

    def _scripts(self) -> TypeScriptExtractor:
        if self._script_extractor is None:
            self._script_extractor = TypeScriptExtractor()
        return self._script_extractor

    def extract(self, path: Path) -> ExtractionResult:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ExtractionResult(errors=[f"Read error: {e}"])

        stem = path.stem
        str_path = str(path)
        nodes: list[Node] = []
        edges: list[Edge] = []
        errors: list[str] = []

        # 1. Component node for the file itself.
        component_nid = make_id("vue", stem)
        nodes.append(Node(
            id=component_nid,
            label=stem,
            file_type="code",
            source_file=str_path,
            source_location="L1",
            language="vue",
            kind="component",
        ))

        # 2. Script block(s).
        for match in _SCRIPT_BLOCK.finditer(source):
            attrs, body = match.group(1), match.group(2)
            is_ts = bool(_LANG_TS.search(attrs))
            script_offset = source[: match.start(2)].count("\n")

            try:
                script_nodes, script_edges, script_errors = self._extract_script(
                    body, is_ts=is_ts, path=path,
                )
            except Exception as e:  # pragma: no cover — defensive
                errors.append(f"Script parse error: {e}")
                continue

            errors.extend(script_errors)

            # Rewrite source_file / source_location to point at the .vue file.
            for n in script_nodes:
                n.source_file = str_path
                n.source_location = _offset_location(n.source_location, script_offset)
                # Skip the synthetic "file" node from the script — we already
                # have a component node for the .vue file.
                if n.kind == "file":
                    continue
                nodes.append(n)
                edges.append(Edge(
                    source=component_nid, target=n.id, relation="contains",
                    confidence="EXTRACTED",
                    source_file=str_path,
                    source_location=n.source_location,
                ))
            for e in script_edges:
                e.source_file = str_path
                e.source_location = _offset_location(e.source_location, script_offset)
                # Drop edges that came from the synthetic script "file" node.
                # We replace them with edges from the component node.
                if e.source.endswith(stem) and e.source.startswith("file"):
                    e.source = component_nid
                edges.append(e)

        # 3. <template> child-component references.
        template_match = re.search(
            r"<template\b[^>]*>(.*?)</template\s*>", source, re.DOTALL | re.IGNORECASE,
        )
        if template_match:
            template_body = template_match.group(1)
            template_line = source[: template_match.start()].count("\n") + 1
            seen_refs: set[str] = set()
            for tag_match in _TEMPLATE_TAG.finditer(template_body):
                name = tag_match.group(1)
                if name.lower() in _HTML_TAGS:
                    continue
                # Only Vue components: PascalCase or kebab-case with hyphen.
                if not (name[:1].isupper() or "-" in name):
                    continue
                if name in seen_refs:
                    continue
                seen_refs.add(name)
                target_nid = make_id("vue", name.replace("-", ""))
                edges.append(Edge(
                    source=component_nid, target=target_nid,
                    relation="uses",
                    confidence="EXTRACTED",
                    source_file=str_path,
                    source_location=f"L{template_line}",
                ))

        return ExtractionResult(nodes=nodes, edges=edges, errors=errors)

    def _extract_script(self, body: str, *, is_ts: bool, path: Path):
        """Parse a ``<script>`` body via the TypeScript extractor.

        We write the body to a temp file because the TypeScript extractor
        reads from disk. Returns (nodes, edges, errors).
        """
        suffix = ".ts" if is_ts else ".js"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=suffix, delete=False,
        ) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        try:
            result = self._scripts().extract(tmp_path)
            # The script extractor used the temp filename as stem; rewrite
            # to use the .vue stem so IDs collide cleanly across the file.
            for n in result.nodes:
                n.source_file = str(path)
            return result.nodes, result.edges, result.errors
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def _offset_location(loc: str | None, offset: int) -> str | None:
    """Shift a ``"L42"`` location by ``offset`` lines."""
    if not loc:
        return loc
    if not loc.startswith("L"):
        return loc
    try:
        return f"L{int(loc[1:]) + offset}"
    except ValueError:
        return loc
