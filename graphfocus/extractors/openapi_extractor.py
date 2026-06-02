"""OpenAPI / Swagger extractor.

Parses ``.yaml`` / ``.yml`` / ``.json`` files that look like OpenAPI 3.x
or Swagger 2.x specs and turns them into graph nodes:

  * One ``api`` node per spec file.
  * One ``endpoint`` node per ``paths.{path}.{method}`` operation,
    labelled ``GET /users/{id}`` and tagged with the operation tag.
  * One ``schema`` node per ``components.schemas.{Name}`` (3.x) or
    ``definitions.{Name}`` (2.x).
  * ``returns`` edges from operations to schemas referenced in responses.
  * ``accepts`` edges from operations to schemas referenced in request
    bodies / parameters.
  * ``has_property`` edges from schemas to their declared properties.
  * ``references`` edges between schemas when one ``$ref``s another.

The extractor uses ``yaml`` when available and falls back to ``json``
for ``.json`` files so the optional dep is only required for YAML.
"""

from __future__ import annotations

import json as _json
import logging
import re
from pathlib import Path

from graphfocus.extractors.base import (
    Edge,
    ExtractionResult,
    LanguageExtractor,
    Node,
    make_id,
)

logger = logging.getLogger(__name__)


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
_REF_NAME = re.compile(r"#/(?:components/schemas|definitions)/([^/]+)$")


class OpenAPIExtractor(LanguageExtractor):
    @property
    def language_name(self) -> str:
        return "openapi"

    @property
    def extensions(self) -> set[str]:
        # We claim .yaml/.yml/.json because OpenAPI specs live in those.
        # The extract() method sniffs the content and returns an empty
        # ExtractionResult when the file isn't a spec, so plain config
        # YAMLs/JSONs are silently skipped.
        return {".yaml", ".yml", ".json", ".openapi", ".openapi.json"}

    def can_handle(self, path: Path) -> bool:
        # Accept the dedicated .openapi* suffixes outright. For generic
        # .yaml / .yml / .json files we sniff the first KB to look for an
        # 'openapi:' or 'swagger:' top-level key.
        if path.suffix.lower() in self.extensions:
            return True
        if path.suffix.lower() not in (".yaml", ".yml", ".json"):
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:1024]
        except Exception:
            return False
        lower = head.lower()
        return ("openapi:" in lower
                or "swagger:" in lower
                or '"openapi"' in lower
                or '"swagger"' in lower)

    def extract(self, path: Path) -> ExtractionResult:
        spec = self._load(path)
        if spec is None:
            return ExtractionResult()
        if not isinstance(spec, dict):
            return ExtractionResult()
        if "openapi" not in spec and "swagger" not in spec:
            return ExtractionResult()

        stem = path.stem
        str_path = str(path)
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen: set[str] = set()

        def add_node(nid: str, label: str, kind: str, **meta) -> None:
            if nid in seen:
                return
            seen.add(nid)
            nodes.append(Node(
                id=nid, label=label, file_type="code",
                source_file=str_path, source_location="L1",
                language="openapi", kind=kind,
                metadata=meta if meta else {},
            ))

        def add_edge(src: str, tgt: str, relation: str,
                     confidence: str = "EXTRACTED") -> None:
            edges.append(Edge(
                source=src, target=tgt, relation=relation,
                confidence=confidence, source_file=str_path,
                source_location="L1",
            ))

        # ── API node ──────────────────────────────────────────────────
        api_nid = make_id("api", stem)
        info = spec.get("info") or {}
        title = info.get("title") or path.name
        version = info.get("version") or ""
        add_node(api_nid, f"{title} {version}".strip(), "api")

        # ── Schemas ───────────────────────────────────────────────────
        schemas = (
            (spec.get("components") or {}).get("schemas")  # 3.x
            or spec.get("definitions")                      # 2.x
            or {}
        )
        for schema_name, schema_def in (schemas or {}).items():
            schema_nid = make_id("schema", schema_name)
            add_node(schema_nid, schema_name, "schema")
            add_edge(api_nid, schema_nid, "contains")

            if not isinstance(schema_def, dict):
                continue
            props = schema_def.get("properties") or {}
            for prop_name, prop_def in props.items():
                prop_nid = make_id(schema_nid, prop_name)
                ptype = (
                    prop_def.get("type") if isinstance(prop_def, dict) else None
                ) or "any"
                add_node(prop_nid, prop_name, "property", data_type=ptype)
                add_edge(schema_nid, prop_nid, "has_property")

                # If the property is a $ref to another schema, link it.
                ref_target = _resolve_ref(prop_def)
                if ref_target:
                    ref_nid = make_id("schema", ref_target)
                    if ref_nid not in seen:
                        add_node(ref_nid, ref_target, "schema")
                    add_edge(schema_nid, ref_nid, "references")

        # ── Operations / endpoints ────────────────────────────────────
        for raw_path, item in (spec.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            for method, op in item.items():
                if method.lower() not in _HTTP_METHODS:
                    continue
                if not isinstance(op, dict):
                    continue
                label = f"{method.upper()} {raw_path}"
                op_nid = make_id("op", method, raw_path)
                tags = op.get("tags") or []
                meta = {}
                if tags:
                    meta["tags"] = list(tags)
                summary = op.get("summary")
                if summary:
                    meta["summary"] = summary
                add_node(op_nid, label, "endpoint", **meta)
                add_edge(api_nid, op_nid, "exposes")

                # request body / parameters → accepts
                for ref in _refs_in(op.get("requestBody")):
                    target_nid = make_id("schema", ref)
                    if target_nid not in seen:
                        add_node(target_nid, ref, "schema")
                    add_edge(op_nid, target_nid, "accepts")
                for param in op.get("parameters") or []:
                    for ref in _refs_in(param):
                        target_nid = make_id("schema", ref)
                        if target_nid not in seen:
                            add_node(target_nid, ref, "schema")
                        add_edge(op_nid, target_nid, "accepts")

                # responses → returns
                for _status, resp in (op.get("responses") or {}).items():
                    for ref in _refs_in(resp):
                        target_nid = make_id("schema", ref)
                        if target_nid not in seen:
                            add_node(target_nid, ref, "schema")
                        add_edge(op_nid, target_nid, "returns")

        return ExtractionResult(nodes=nodes, edges=edges)

    def _load(self, path: Path) -> dict | None:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            try:
                return _json.loads(text)
            except _json.JSONDecodeError:
                return None
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            # YAML support is provided by uvicorn's pyyaml dep when [api]
            # is installed. Without it, .yaml/.yml specs can't be parsed
            # — just bail out silently.
            logger.debug("PyYAML not installed; cannot parse %s", path)
            return None
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError:
            return None


# ── helpers ────────────────────────────────────────────────────────────

def _resolve_ref(value) -> str | None:
    """Return the bare schema name if ``value`` is a $ref dict."""
    if isinstance(value, dict) and "$ref" in value:
        m = _REF_NAME.search(value["$ref"])
        if m:
            return m.group(1)
    return None


def _refs_in(value) -> list[str]:
    """Recursively collect all schema names referenced inside ``value``."""
    out: list[str] = []
    if isinstance(value, dict):
        ref = _resolve_ref(value)
        if ref:
            out.append(ref)
        for v in value.values():
            out.extend(_refs_in(v))
    elif isinstance(value, list):
        for item in value:
            out.extend(_refs_in(item))
    return out
