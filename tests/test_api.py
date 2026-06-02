"""Integration tests for the FastAPI server.

Uses fastapi.testclient.TestClient so the app runs in-process; no port is
opened. We monkeypatch the cwd so each test's outputs land in tmp_path.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graphfocus.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_project(tmp_path: Path, fixtures_dir: Path) -> Path:
    """A minimal project copied into tmp_path that the API can analyze."""
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(fixtures_dir / "python" / "sample_module.py", project / "sample.py")
    shutil.copy(fixtures_dir / "sql" / "schema.sql", project / "schema.sql")
    return project


class TestHealth:
    def test_health_returns_languages(self, client: TestClient):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "python" in body["languages"]
        assert "sql" in body["languages"]


class TestBearerAuth:
    """v0.3.0 — when GRAPHFOCUS_API_TOKEN is set every /api/* call needs it."""

    def test_unauthenticated_blocked_when_token_set(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("GRAPHFOCUS_API_TOKEN", "secret")
        r = client.get("/api/health")
        assert r.status_code == 401
        assert "Bearer" in r.headers.get("WWW-Authenticate", "")

    def test_wrong_token_forbidden(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("GRAPHFOCUS_API_TOKEN", "secret")
        r = client.get("/api/health", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 403

    def test_correct_token_passes(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("GRAPHFOCUS_API_TOKEN", "secret")
        r = client.get("/api/health", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200

    def test_no_token_means_open(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("GRAPHFOCUS_API_TOKEN", raising=False)
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_root_endpoint_reports_auth_state(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("GRAPHFOCUS_API_TOKEN", "secret")
        r = client.get("/")
        body = r.json()
        assert body["auth_required"] is True


class TestAnalyzeEndpoint:
    def test_404_when_path_missing(self, client: TestClient, tmp_path: Path):
        r = client.post("/api/analyze", json={"path": str(tmp_path / "does_not_exist")})
        assert r.status_code == 404

    def test_400_when_path_is_file(self, client: TestClient, sample_project: Path):
        target = sample_project / "sample.py"
        r = client.post("/api/analyze", json={"path": str(target)})
        assert r.status_code == 400

    def test_analyze_returns_counts(
        self,
        client: TestClient,
        sample_project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # The API writes output to graphfocus-out/ in the current working dir.
        # Redirect that to tmp_path so we don't touch the repo.
        monkeypatch.chdir(tmp_path)

        r = client.post("/api/analyze", json={"path": str(sample_project)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_files"] >= 2
        assert body["total_nodes"] >= 1
        assert body["total_edges"] >= 0
        assert "python" in body["by_language"]
        assert "sql" in body["by_language"]


class TestGraphEndpoints:
    def test_graph_404_when_no_graph_yet(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        r = client.get("/api/graph")
        assert r.status_code == 404

    def test_graph_endpoints_after_analyze(
        self,
        client: TestClient,
        sample_project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        # Run analyze first so graph.json exists in cwd/graphfocus-out/.
        r = client.post("/api/analyze", json={"path": str(sample_project)})
        assert r.status_code == 200

        graph_json = tmp_path / "graphfocus-out" / "graph.json"
        assert graph_json.exists()

        # GET /api/graph
        r = client.get("/api/graph")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data and "edges" in data

        # GET /api/graph/nodes?language=sql
        r = client.get("/api/graph/nodes", params={"language": "sql"})
        assert r.status_code == 200
        body = r.json()
        assert all(n["language"] == "sql" for n in body["nodes"])

        # GET /api/graph/search?q=user
        r = client.get("/api/graph/search", params={"q": "user"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert all("user" in (n["label"] + n["id"]).lower() for n in results)

        # GET /api/graph/stats — written by export_json
        r = client.get("/api/graph/stats")
        assert r.status_code == 200
        stats = r.json()
        assert stats.get("total_nodes", 0) >= 1


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
