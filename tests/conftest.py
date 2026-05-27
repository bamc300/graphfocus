"""Shared test fixtures for GraphFocus tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def python_fixture() -> Path:
    return FIXTURES_DIR / "python" / "sample_module.py"


@pytest.fixture
def java_fixture() -> Path:
    return FIXTURES_DIR / "java" / "UserService.java"


@pytest.fixture
def plsql_fixture() -> Path:
    return FIXTURES_DIR / "plsql" / "pkg_users.pks"


@pytest.fixture
def csharp_fixture() -> Path:
    return FIXTURES_DIR / "csharp" / "UserController.cs"


@pytest.fixture
def sql_fixture() -> Path:
    return FIXTURES_DIR / "sql" / "schema.sql"
