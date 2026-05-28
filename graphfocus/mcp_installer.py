"""Auto-detect installed AI IDEs and inject the GraphFocus MCP server.

The goal is to spare users from hunting down each tool's config file. We
keep a small registry of well-known MCP clients with their canonical
config paths per OS, scan the disk to see which are present, and offer
to add (or remove) a ``graphfocus`` entry under their ``mcpServers``
object — keeping any existing entries intact and writing a ``.bak``
backup before touching anything.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Standard JSON shape every supported IDE uses:
#   {"mcpServers": {"graphfocus": {"command": "...", "args": [...], ...}}}


@dataclass
class McpTool:
    """A known MCP-compatible IDE and the candidate paths for its config."""

    name: str
    candidates: list[Path] = field(default_factory=list)
    servers_key: str = "mcpServers"

    @property
    def existing_path(self) -> Path | None:
        """The first candidate that actually exists on disk, or None."""
        for p in self.candidates:
            if p.exists():
                return p
        return None

    @property
    def install_path(self) -> Path | None:
        """Where to write — the existing config if any, else the first
        candidate path so we can create a new file there."""
        return self.existing_path or (self.candidates[0] if self.candidates else None)


def known_tools() -> list[McpTool]:
    """Return the list of known MCP clients with OS-specific config paths."""
    system = platform.system()
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", "")) if system == "Windows" else None
    userprofile = (
        Path(os.environ.get("USERPROFILE", str(home))) if system == "Windows" else home
    )

    tools: list[McpTool] = []

    # ── Claude Desktop ────────────────────────────────────────────────
    if system == "Darwin":
        tools.append(McpTool(
            name="Claude Desktop",
            candidates=[
                home / "Library/Application Support/Claude/claude_desktop_config.json",
            ],
        ))
    elif system == "Windows" and appdata:
        tools.append(McpTool(
            name="Claude Desktop",
            candidates=[appdata / "Claude/claude_desktop_config.json"],
        ))

    # ── Cursor (global, then project-local) ───────────────────────────
    tools.append(McpTool(
        name="Cursor",
        candidates=[
            home / ".cursor/mcp.json",
            Path.cwd() / ".cursor/mcp.json",
        ],
    ))

    # ── Windsurf ──────────────────────────────────────────────────────
    if system in ("Darwin", "Linux"):
        tools.append(McpTool(
            name="Windsurf",
            candidates=[home / ".codeium/windsurf/mcp_config.json"],
        ))
    elif system == "Windows":
        tools.append(McpTool(
            name="Windsurf",
            candidates=[userprofile / ".codeium/windsurf/mcp_config.json"],
        ))

    # ── Trae AI ───────────────────────────────────────────────────────
    if system == "Darwin":
        tools.append(McpTool(
            name="Trae AI",
            candidates=[
                home / "Library/Application Support/Trae/User/mcp.json",
                home / "Library/Application Support/Trae CN/User/mcp.json",
                home / ".trae/mcp.json",
            ],
        ))
    elif system == "Windows" and appdata:
        tools.append(McpTool(
            name="Trae AI",
            candidates=[
                appdata / "Trae/User/mcp.json",
                appdata / "Trae CN/User/mcp.json",
            ],
        ))
    elif system == "Linux":
        tools.append(McpTool(
            name="Trae AI",
            candidates=[home / ".config/Trae/User/mcp.json"],
        ))

    # ── Continue.dev ──────────────────────────────────────────────────
    tools.append(McpTool(
        name="Continue.dev",
        candidates=[home / ".continue/config.json"],
    ))

    # ── Zed (experimental MCP support) ────────────────────────────────
    if system == "Darwin" or system == "Linux":
        tools.append(McpTool(
            name="Zed",
            candidates=[home / ".config/zed/settings.json"],
            servers_key="context_servers",
        ))

    # ── VS Code (Cline / Saoudrizwan.claude-dev extension) ────────────
    if system == "Darwin":
        tools.append(McpTool(
            name="VS Code (Cline)",
            candidates=[
                home / "Library/Application Support/Code/User/globalStorage/"
                       "saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
            ],
        ))

    return tools


@dataclass
class ScanResult:
    tool: McpTool
    installed: bool                                       # config file exists
    has_graphfocus: bool = False                          # graphfocus entry already present
    parse_error: str | None = None                        # JSON couldn't be read


def scan(tools: list[McpTool] | None = None) -> list[ScanResult]:
    """Inspect every candidate file and report state."""
    results: list[ScanResult] = []
    for tool in tools if tools is not None else known_tools():
        path = tool.existing_path
        if path is None:
            results.append(ScanResult(tool=tool, installed=False))
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            has = "graphfocus" in (config.get(tool.servers_key) or {})
            results.append(ScanResult(tool=tool, installed=True, has_graphfocus=has))
        except (json.JSONDecodeError, OSError) as e:
            results.append(ScanResult(tool=tool, installed=True, parse_error=str(e)))
    return results


@dataclass
class InstallResult:
    tool_name: str
    path: Path
    action: Literal["added", "already-present", "replaced", "error", "would-add"]
    detail: str = ""


def install(
    tool: McpTool,
    *,
    command: str,
    cwd: str,
    dry_run: bool = False,
    replace: bool = False,
) -> InstallResult:
    """Merge a ``graphfocus`` entry into the tool's MCP config.

    Args:
        tool: McpTool to target.
        command: Absolute path to the ``graphfocus`` executable.
        cwd: Absolute path of the project the server should default to.
        dry_run: If True, don't write; just report what would happen.
        replace: If True, overwrite an existing graphfocus entry.

    Returns an InstallResult describing the outcome. We always back up
    the original file as ``<path>.bak`` before writing.
    """
    path = tool.install_path
    if path is None:
        return InstallResult(
            tool_name=tool.name, path=Path(""), action="error",
            detail="no candidate path available for this OS",
        )

    # Load (or initialise) the JSON.
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return InstallResult(
                tool_name=tool.name, path=path, action="error",
                detail=f"could not parse existing config: {e}",
            )
        if not isinstance(config, dict):
            return InstallResult(
                tool_name=tool.name, path=path, action="error",
                detail="config root is not an object",
            )
    else:
        config = {}

    servers = config.setdefault(tool.servers_key, {})
    if not isinstance(servers, dict):
        return InstallResult(
            tool_name=tool.name, path=path, action="error",
            detail=f"'{tool.servers_key}' field is not an object",
        )

    new_entry = {
        "command": command,
        "args": ["mcp"],
        "cwd": cwd,
    }

    if "graphfocus" in servers and not replace:
        return InstallResult(
            tool_name=tool.name, path=path, action="already-present",
            detail="graphfocus entry already exists (pass --replace to overwrite)",
        )

    action: Literal["added", "replaced", "would-add"] = (
        "replaced" if "graphfocus" in servers else "added"
    )
    servers["graphfocus"] = new_entry
    config[tool.servers_key] = servers

    if dry_run:
        return InstallResult(
            tool_name=tool.name, path=path, action="would-add",
            detail=json.dumps(new_entry),
        )

    # Backup and write atomically (write to .tmp then rename).
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

    return InstallResult(tool_name=tool.name, path=path, action=action)


def uninstall(tool: McpTool, *, dry_run: bool = False) -> InstallResult:
    """Remove the ``graphfocus`` entry from a tool's MCP config, if present."""
    path = tool.existing_path
    if path is None:
        return InstallResult(
            tool_name=tool.name, path=Path(""), action="error",
            detail="no config file found",
        )
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return InstallResult(
            tool_name=tool.name, path=path, action="error",
            detail=f"could not parse config: {e}",
        )
    servers = config.get(tool.servers_key) or {}
    if "graphfocus" not in servers:
        return InstallResult(
            tool_name=tool.name, path=path, action="already-present",
            detail="no graphfocus entry to remove",
        )
    if dry_run:
        return InstallResult(
            tool_name=tool.name, path=path, action="would-add",
            detail="would remove graphfocus entry",
        )
    del servers["graphfocus"]
    config[tool.servers_key] = servers
    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return InstallResult(tool_name=tool.name, path=path, action="added",
                         detail="graphfocus entry removed")
