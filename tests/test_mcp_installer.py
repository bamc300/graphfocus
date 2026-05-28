"""Tests for the MCP installer.

We don't touch the real filesystem under HOME — every test uses tmp_path
and feeds explicit ``McpTool`` instances pointing at temp files.
"""

from __future__ import annotations

import json
from pathlib import Path

from graphfocus.mcp_installer import (
    InstallResult,
    McpTool,
    install,
    scan,
    uninstall,
)


def _tool(name: str, path: Path) -> McpTool:
    return McpTool(name=name, candidates=[path])


class TestScan:
    def test_reports_missing_config_as_not_installed(self, tmp_path: Path):
        tool = _tool("Fake", tmp_path / "does_not_exist.json")
        [result] = scan([tool])
        assert result.installed is False
        assert result.has_graphfocus is False

    def test_reports_installed_without_graphfocus(self, tmp_path: Path):
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"other": {}}}))
        tool = _tool("Fake", path)
        [result] = scan([tool])
        assert result.installed
        assert not result.has_graphfocus

    def test_reports_existing_graphfocus(self, tmp_path: Path):
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"graphfocus": {"command": "x"}}}))
        tool = _tool("Fake", path)
        [result] = scan([tool])
        assert result.has_graphfocus

    def test_parse_error_is_surfaced(self, tmp_path: Path):
        path = tmp_path / "mcp.json"
        path.write_text("{not valid json")
        tool = _tool("Fake", path)
        [result] = scan([tool])
        assert result.parse_error is not None


class TestInstall:
    def test_creates_new_config_when_missing(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        tool = _tool("Fake", target)
        result: InstallResult = install(
            tool, command="/usr/local/bin/graphfocus", cwd="/proj",
        )
        assert result.action == "added"
        assert target.exists()
        config = json.loads(target.read_text())
        assert config["mcpServers"]["graphfocus"] == {
            "command": "/usr/local/bin/graphfocus",
            "args": ["mcp"],
            "cwd": "/proj",
        }

    def test_merges_into_existing_servers(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text(json.dumps({
            "mcpServers": {"existing": {"command": "echo"}}
        }, indent=2))
        tool = _tool("Fake", target)
        install(tool, command="/bin/graphfocus", cwd="/proj")
        config = json.loads(target.read_text())
        assert "existing" in config["mcpServers"]
        assert "graphfocus" in config["mcpServers"]

    def test_idempotent_without_replace(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text(json.dumps({
            "mcpServers": {"graphfocus": {"command": "old"}},
        }))
        tool = _tool("Fake", target)
        result = install(tool, command="/bin/new", cwd="/proj")
        assert result.action == "already-present"
        # Untouched
        config = json.loads(target.read_text())
        assert config["mcpServers"]["graphfocus"]["command"] == "old"

    def test_replace_overwrites(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text(json.dumps({
            "mcpServers": {"graphfocus": {"command": "old"}},
        }))
        tool = _tool("Fake", target)
        result = install(tool, command="/bin/new", cwd="/proj", replace=True)
        assert result.action == "replaced"
        config = json.loads(target.read_text())
        assert config["mcpServers"]["graphfocus"]["command"] == "/bin/new"

    def test_writes_backup_before_modifying(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text('{"mcpServers": {}}')
        tool = _tool("Fake", target)
        install(tool, command="/bin/g", cwd="/p")
        assert (tmp_path / "mcp.json.bak").exists()

    def test_dry_run_does_not_write(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        tool = _tool("Fake", target)
        result = install(tool, command="/bin/g", cwd="/p", dry_run=True)
        assert result.action == "would-add"
        assert not target.exists()

    def test_respects_custom_servers_key(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        tool = McpTool(name="Zed", candidates=[target],
                       servers_key="context_servers")
        install(tool, command="/bin/g", cwd="/p")
        config = json.loads(target.read_text())
        assert "context_servers" in config
        assert "graphfocus" in config["context_servers"]

    def test_error_on_unparsable_config(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text("not json")
        tool = _tool("Fake", target)
        result = install(tool, command="/bin/g", cwd="/p")
        assert result.action == "error"

    def test_error_when_servers_key_is_not_object(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text('{"mcpServers": "not an object"}')
        tool = _tool("Fake", target)
        result = install(tool, command="/bin/g", cwd="/p")
        assert result.action == "error"


class TestUninstall:
    def test_removes_graphfocus_entry(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text(json.dumps({
            "mcpServers": {
                "graphfocus": {"command": "x"},
                "other": {"command": "y"},
            },
        }))
        tool = _tool("Fake", target)
        result = uninstall(tool)
        assert result.action == "added"  # action name reused to mean "modified"
        config = json.loads(target.read_text())
        assert "graphfocus" not in config["mcpServers"]
        assert "other" in config["mcpServers"]

    def test_noop_when_no_entry(self, tmp_path: Path):
        target = tmp_path / "mcp.json"
        target.write_text('{"mcpServers": {"other": {}}}')
        tool = _tool("Fake", target)
        result = uninstall(tool)
        assert result.action == "already-present"
