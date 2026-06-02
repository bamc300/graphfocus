"""Tests for the OpenAPI / Swagger extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

# PyYAML ships transitively via uvicorn[standard] (watchfiles, etc.).
# Skip cleanly if it's somehow missing in the test environment.
yaml = pytest.importorskip("yaml")  # noqa: F841

from graphfocus.extractors.openapi_extractor import OpenAPIExtractor  # noqa: E402


@pytest.fixture
def extractor() -> OpenAPIExtractor:
    return OpenAPIExtractor()


@pytest.fixture
def spec_path() -> Path:
    return Path(__file__).parent / "fixtures" / "openapi" / "users-api.yaml"


class TestOpenAPIExtractor:
    def test_api_node_created(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        api = [n for n in result.nodes if n.kind == "api"]
        assert len(api) == 1
        assert "Users API" in api[0].label

    def test_endpoints_extracted_with_method_and_path(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        labels = {n.label for n in result.nodes if n.kind == "endpoint"}
        assert "GET /users" in labels
        assert "POST /users" in labels
        assert "GET /users/{id}" in labels

    def test_schemas_extracted(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        labels = {n.label for n in result.nodes if n.kind == "schema"}
        assert {"User", "Address", "Error"}.issubset(labels)

    def test_schema_properties_extracted(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        props = {n.label for n in result.nodes if n.kind == "property"}
        assert "name" in props
        assert "city" in props

    def test_responses_become_returns_edges(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        labels = {n.id: n.label for n in result.nodes}
        returns = [
            (labels.get(e.source), labels.get(e.target))
            for e in result.edges
            if e.relation == "returns"
        ]
        # GET /users returns User; GET /users/{id} returns User and Error
        assert ("GET /users", "User") in returns
        assert ("GET /users/{id}", "Error") in returns

    def test_request_body_becomes_accepts_edge(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        labels = {n.id: n.label for n in result.nodes}
        accepts = [
            (labels.get(e.source), labels.get(e.target))
            for e in result.edges
            if e.relation == "accepts"
        ]
        assert ("POST /users", "User") in accepts

    def test_schema_references_other_schema(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        labels = {n.id: n.label for n in result.nodes}
        refs = [
            (labels.get(e.source), labels.get(e.target))
            for e in result.edges
            if e.relation == "references"
        ]
        # User.address → Address
        assert ("User", "Address") in refs

    def test_tags_captured_on_endpoint(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        ep = next(n for n in result.nodes if n.label == "GET /users")
        assert "users" in (ep.metadata.get("tags") or [])

    def test_no_errors(self, extractor, spec_path):
        result = extractor.extract(spec_path)
        assert not result.errors

    def test_non_openapi_yaml_returns_empty(self, extractor, tmp_path: Path):
        p = tmp_path / "config.yaml"
        p.write_text("database:\n  host: localhost\n  port: 5432\n")
        result = extractor.extract(p)
        assert result.nodes == []
        assert result.edges == []
