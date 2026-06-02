"""CLI entry point for GraphFocus."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from graphfocus import __version__
from graphfocus.config import GraphFocusConfig
from graphfocus.detect.detector import detect_files
from graphfocus.extractors.registry import ExtractorRegistry

console = Console()


@click.group()
@click.version_option(__version__, prog_name="graphfocus")
def main() -> None:
    """GraphFocus — Turn any folder of code into a queryable knowledge graph."""


@main.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--mode", type=click.Choice(["normal", "deep"]), default="normal", help="Extraction depth")
@click.option("--update", is_flag=True, help="Incremental update, only process changed files")
@click.option("--no-viz", is_flag=True, help="Skip HTML visualization")
@click.option("--no-semantic", is_flag=True, help="Skip LLM semantic extraction")
@click.option("--obsidian", is_flag=True, help="Also export an Obsidian vault")
@click.option("--ai", "ai_summary", is_flag=True,
              help="Also write AI_SUMMARY.md (dense Markdown for LLM context)")
@click.option("--output", "-o", type=click.Path(), default="graphfocus-out", help="Output directory")
def analyze(
    path: str,
    mode: str,
    update: bool,
    no_viz: bool,
    no_semantic: bool,
    obsidian: bool,
    ai_summary: bool,
    output: str,
) -> None:
    """Analyze a directory and build a knowledge graph."""
    config = GraphFocusConfig(
        input_path=Path(path),
        output_dir=Path(output),
        mode=mode,
        update=update,
        skip_viz=no_viz,
        skip_semantic=no_semantic,
    )

    console.print(f"\n[bold blue]GraphFocus v{__version__}[/]")
    console.print(f"Analyzing: [cyan]{config.input_path}[/]\n")

    # Step 1: Detect files
    detection = detect_files(config.input_path)
    _print_detection_summary(detection)

    if detection["total_files"] == 0:
        console.print("[yellow]No supported files found. Nothing to do.[/]")
        return

    # Step 2: Extract with AST (optionally using the SQLite cache)
    registry = ExtractorRegistry()
    all_nodes = []
    all_edges = []
    cache = None
    cache_hits = 0
    if config.update:
        from graphfocus.cache.sqlite_cache import ExtractionCache

        cache_db = config.output_dir / ".cache.db"
        cache = ExtractionCache(cache_db)

    from graphfocus.extractors.base import Edge as _Edge  # noqa: E402
    from graphfocus.extractors.base import Node as _Node

    for file_info in detection["files"]:
        file_path = Path(file_info["path"])
        extractor = registry.get_extractor(file_path.suffix)
        if extractor is None:
            continue

        cached = cache.get_cached(file_path) if cache else None
        if cached is not None:
            all_nodes.extend(_Node.from_dict(n) for n in cached["nodes"])
            all_edges.extend(_Edge.from_dict(e) for e in cached["edges"])
            cache_hits += 1
            continue

        result = extractor.extract(file_path)
        all_nodes.extend(result.nodes)
        all_edges.extend(result.edges)
        if cache:
            cache.save(
                file_path,
                [n.to_dict() for n in result.nodes],
                [e.to_dict() for e in result.edges],
                extractor.language_name,
            )
        if result.errors:
            for err in result.errors:
                console.print(f"  [yellow]⚠ {file_path.name}: {err}[/]")

    if cache:
        cache.close()
        if cache_hits:
            console.print(f"[dim]Cache: {cache_hits} files reused from previous run[/]")

    console.print(f"\n[green]✓ Extracted {len(all_nodes)} nodes and {len(all_edges)} edges[/]")

    # Step 2b: Cross-language linking (Java/C# @Entity ↔ SQL/PL-SQL tables, etc.)
    from graphfocus.graph.cross_language import link_cross_language

    cross_edges = link_cross_language(all_nodes, all_edges)
    if cross_edges:
        all_edges.extend(cross_edges)
        console.print(f"[green]✓ Linked {len(cross_edges)} cross-language edges[/]")

    # Step 2c: Community detection (Leiden via igraph if installed).
    # If igraph is missing this returns {node: 0 for all}, so callers stay
    # consistent — the viz just won't have distinct community colors.
    from graphfocus.graph.builder import build_graph
    from graphfocus.graph.community import detect_communities

    nx_graph = build_graph(all_nodes, all_edges)
    communities = detect_communities(nx_graph)
    distinct = len(set(communities.values()))
    if distinct > 1:
        console.print(f"[green]✓ Detected {distinct} communities[/]")

    # Step 3: Output
    config.output_dir.mkdir(parents=True, exist_ok=True)

    from graphfocus.output.json_export import export_json

    export_json(all_nodes, all_edges, config.output_dir / "graph.json")
    console.print(f"[green]✓ Graph saved to {config.output_dir / 'graph.json'}[/]")

    # Step 3b: TF-IDF semantic index for find_semantic queries.
    from graphfocus.semantic_index import build_index, save_index

    index = build_index([n.to_dict() for n in all_nodes])
    save_index(index, config.output_dir / "semantic.json")
    console.print(
        f"[green]✓ Semantic index ({len(index['idf'])} tokens, "
        f"{len(index['vectors'])} docs)[/]"
    )

    from graphfocus.output.report import generate_report

    generate_report(all_nodes, all_edges, detection, config.output_dir / "GRAPH_REPORT.md")
    console.print(f"[green]✓ Report saved to {config.output_dir / 'GRAPH_REPORT.md'}[/]")

    if not config.skip_viz:
        from graphfocus.output.html_viz import generate_html

        html_path = config.output_dir / "graph.html"
        generate_html(
            all_nodes, all_edges, html_path,
            communities=communities,
            title=config.input_path.name,
        )
        console.print(f"[green]✓ Interactive viz saved to {html_path}[/]")

    if obsidian:
        from graphfocus.output.obsidian import generate_obsidian_vault

        vault_dir = config.output_dir / "obsidian"
        summary = generate_obsidian_vault(all_nodes, all_edges, vault_dir)
        console.print(
            f"[green]✓ Obsidian vault: {summary['notes']} notes, "
            f"{summary['links']} links at {vault_dir}[/]"
        )

    if ai_summary:
        from graphfocus.output.ai_summary import render_ai_summary

        ai_path = config.output_dir / "AI_SUMMARY.md"
        bytes_written = render_ai_summary(all_nodes, all_edges, ai_path)
        kb = bytes_written / 1024
        console.print(
            f"[green]✓ AI summary saved to {ai_path} ({kb:.1f} KB)[/]"
        )


@main.command()
def languages() -> None:
    """List all supported languages and their extractors."""
    registry = ExtractorRegistry()

    table = Table(title="Supported Languages", show_header=True, header_style="bold magenta")
    table.add_column("Language", style="cyan")
    table.add_column("Extensions", style="green")
    table.add_column("Status", style="yellow")

    for ext_info in registry.list_languages():
        table.add_row(
            ext_info["name"],
            ", ".join(ext_info["extensions"]),
            ext_info["status"],
        )

    console.print(table)


@main.command()
@click.argument("question")
def query(question: str) -> None:
    """Query the knowledge graph with a natural language question."""
    graph_path = Path("graphfocus-out/graph.json")
    if not graph_path.exists():
        console.print("[red]No graph found. Run 'graphfocus analyze' first.[/]")
        return

    console.print(f"[yellow]Query support coming soon. Question: {question}[/]")


@main.command()
@click.argument("source")
@click.argument("target")
def path(source: str, target: str) -> None:
    """Find shortest path between two concepts in the graph."""
    console.print(f"[yellow]Path finding coming soon: {source} → {target}[/]")


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option("--ai", "ai_summary", is_flag=True,
              help="Also refresh AI_SUMMARY.md on every change")
@click.option("--obsidian", is_flag=True, help="Also refresh the Obsidian vault")
@click.option("--no-viz", is_flag=True, help="Skip HTML viz regeneration")
@click.option("--debounce", default=0.8, type=float,
              help="Seconds to wait after the last change before re-analyzing")
@click.option("--output", "-o", type=click.Path(), default="graphfocus-out")
def watch(path: str, ai_summary: bool, obsidian: bool, no_viz: bool,
          debounce: float, output: str) -> None:
    """Re-analyze PATH automatically whenever a source file changes.

    Uses the SQLite cache so only changed files are re-extracted — typical
    incremental cycles complete in under a second. Press Ctrl+C to stop.
    """
    try:
        from watchfiles import watch as _watch
    except ImportError:
        console.print(
            "[red]watchfiles not installed. "
            "Run: pip install 'graphfocus[api]'[/]"
        )
        return

    import subprocess

    watched = Path(path).resolve()
    out_dir = Path(output).resolve()

    def _run_analyze() -> None:
        args = [
            "graphfocus", "analyze", str(watched),
            "--update", "--no-semantic", "-o", str(out_dir),
        ]
        if ai_summary:
            args.append("--ai")
        if obsidian:
            args.append("--obsidian")
        if no_viz:
            args.append("--no-viz")
        try:
            subprocess.run(args, check=False)
        except FileNotFoundError:
            # Fallback for when 'graphfocus' isn't on PATH (e.g. inside venv).
            import sys as _sys
            subprocess.run([_sys.executable, "-m", "graphfocus", *args[1:]],
                           check=False)

    console.print(f"[bold]Watching[/] [cyan]{watched}[/] — Ctrl+C to stop\n")
    console.print("[dim]Running first analysis…[/]")
    _run_analyze()
    console.print("\n[bold green]Ready. Listening for changes…[/]\n")

    # Translate `debounce` seconds → milliseconds for watchfiles.
    step_ms = max(50, int(debounce * 1000))

    # Ignore paths inside the output directory so we don't loop forever.
    def _filter(_change, p: str) -> bool:  # noqa: ARG001
        try:
            Path(p).resolve().relative_to(out_dir)
            return False
        except ValueError:
            return True

    try:
        for changes in _watch(
            watched,
            step=step_ms,
            watch_filter=_filter,
            recursive=True,
            rust_timeout=0,
        ):
            files = sorted({Path(p).name for _, p in changes})[:5]
            console.print(f"[dim]Detected change in: {', '.join(files)} …[/]")
            _run_analyze()
            console.print("[bold green]Ready.[/]\n")
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")


@main.command(name="serve-viz")
@click.option("--port", "-p", default=8765, type=int,
              help="Local port to serve on (default: 8765)")
@click.option("--no-open", is_flag=True,
              help="Don't auto-open the browser")
@click.option("--output", "-o", type=click.Path(),
              default="graphfocus-out",
              help="Directory containing graph.html (default: graphfocus-out)")
def serve_viz(port: int, no_open: bool, output: str) -> None:
    """Serve the generated graph.html locally and open it in the browser.

    Opening graph.html directly from disk (file://) fails in most modern
    browsers because they refuse to create a WebGL context for local
    files and block cross-origin script loads. This command runs a tiny
    HTTP server scoped to the output directory so the page works.
    """
    import http.server
    import socketserver
    import threading
    import webbrowser

    out_dir = Path(output).resolve()
    html_file = out_dir / "graph.html"
    if not html_file.exists():
        console.print(f"[red]No graph.html at {html_file}.[/]")
        console.print("[yellow]Run 'graphfocus analyze .' first.[/]")
        return

    # Bind to localhost only so we don't expose the graph on the network.
    handler = http.server.SimpleHTTPRequestHandler

    class _Handler(handler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out_dir), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A002, ARG002
            # Silence the per-request access log; let stdout stay clean.
            return

    try:
        server = socketserver.TCPServer(("127.0.0.1", port), _Handler)
    except OSError as e:
        console.print(f"[red]Could not bind 127.0.0.1:{port} — {e}[/]")
        console.print("[yellow]Try a different --port[/]")
        return

    url = f"http://127.0.0.1:{port}/graph.html"
    console.print(f"[bold green]Serving GraphFocus viz at {url}[/]")
    console.print(f"[dim]Directory: {out_dir}[/]")
    console.print("[dim]Press Ctrl+C to stop.[/]\n")

    if not no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")
    finally:
        server.server_close()


@main.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to")
def serve(host: str, port: int) -> None:
    """Start the FastAPI server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]FastAPI not installed. Run: pip install 'graphfocus[api]'[/]")
        return

    console.print(f"[bold blue]Starting GraphFocus API server on {host}:{port}[/]")
    uvicorn.run("graphfocus.api.app:app", host=host, port=port, reload=True)


@main.command(name="export-mermaid")
@click.option("--graph", "graph_path", type=click.Path(exists=False),
              default="graphfocus-out/graph.json")
@click.option("--output", "-o", type=click.Path(),
              default="graphfocus-out/graph.mmd",
              help="File to write (.mmd or .md)")
@click.option("--direction", type=click.Choice(["LR", "RL", "TB", "BT"]),
              default="LR")
@click.option("--max-nodes", default=150, type=int)
@click.option("--language", default=None)
@click.option("--kind", default=None)
@click.option("--community", type=int, default=None)
@click.option("--root", "roots", multiple=True,
              help="Filter to these node ids and their neighbors (repeatable)")
@click.option("--markdown", is_flag=True,
              help="Wrap output in a ```mermaid fenced block")
def export_mermaid(graph_path: str, output: str, direction: str,
                   max_nodes: int, language: str | None, kind: str | None,
                   community: int | None, roots: tuple[str, ...],
                   markdown: bool) -> None:
    """Export the graph as a Mermaid diagram for embedding in docs.

    Useful for READMEs, ADRs and design docs. By default writes the
    full graph (capped at --max-nodes by degree). Pass --language,
    --kind, --community or --root to narrow the scope.
    """
    import json as _json

    from graphfocus.output.mermaid_export import write_mermaid

    g = Path(graph_path)
    if not g.exists():
        console.print(f"[red]No graph at {g}. Run 'graphfocus analyze' first.[/]")
        return
    data = _json.loads(g.read_text(encoding="utf-8"))

    out = Path(output)
    size = write_mermaid(
        data.get("nodes", []),
        data.get("edges", []),
        out,
        direction=direction,
        max_nodes=max_nodes,
        language=language,
        kind=kind,
        community=community,
        roots=list(roots) if roots else None,
        embed_in_markdown=markdown or out.suffix == ".md",
    )
    kb = size / 1024
    console.print(f"[green]✓ Mermaid diagram saved to {out} ({kb:.1f} KB)[/]")


@main.command(name="install-mcp")
@click.option("--scan", is_flag=True, help="Only scan; don't modify any file")
@click.option("--yes", "-y", "auto_yes", is_flag=True, help="Skip the confirmation prompt")
@click.option("--replace", is_flag=True,
              help="Overwrite an existing graphfocus entry if present")
@click.option("--cwd", "project_cwd", type=click.Path(file_okay=False), default=None,
              help="Project directory the MCP server should default to "
                   "(default: current dir)")
@click.option("--uninstall", is_flag=True,
              help="Remove the graphfocus entry from every detected tool")
def install_mcp(scan: bool, auto_yes: bool, replace: bool,
                project_cwd: str | None, uninstall: bool) -> None:
    """Detect installed AI IDEs (Trae AI, Cursor, Claude Desktop, …) and
    wire up the GraphFocus MCP server in each one's configuration.

    Run this from the root of the project you want the IDEs to query. The
    command shows what was detected, what it would change, and asks for
    confirmation before touching any file. Existing entries are preserved;
    each modified config gets a .bak backup next to it.
    """
    import shutil as _shutil
    import sys as _sys

    from graphfocus.mcp_installer import (
        install as _install,
    )
    from graphfocus.mcp_installer import (
        scan as _scan_tools,
    )
    from graphfocus.mcp_installer import (
        uninstall as _uninstall,
    )

    binary = _shutil.which("graphfocus") or _sys.executable
    cwd_abs = str(Path(project_cwd or ".").resolve())

    console.print("\n[bold]GraphFocus MCP installer[/]")
    console.print(f"  graphfocus binary: [dim]{binary}[/]")
    console.print(f"  project cwd:       [dim]{cwd_abs}[/]\n")
    console.print("Scanning known MCP-compatible AI tools…\n")

    results = _scan_tools()
    targets = []  # list of McpTool to act on

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Tool", style="cyan")
    table.add_column("Status")
    table.add_column("Config path", style="dim", overflow="fold")
    for r in results:
        if r.parse_error:
            status = "[red]parse error[/]"
        elif not r.installed:
            status = "[dim]not installed[/]"
        elif r.has_graphfocus:
            status = "[yellow]graphfocus present[/]"
            if not uninstall:
                pass  # keep as targets only if --replace
        else:
            status = "[green]ready to add[/]"

        path_str = str(r.tool.existing_path or r.tool.install_path or "—")
        table.add_row(r.tool.name, status, path_str)

        if uninstall:
            if r.installed and r.has_graphfocus:
                targets.append(r.tool)
        else:
            if not r.installed:
                continue
            if r.parse_error:
                continue
            if r.has_graphfocus and not replace:
                continue
            targets.append(r.tool)
    console.print(table)

    if scan:
        console.print("\n[dim]--scan: no changes made.[/]")
        return

    if not targets:
        console.print(
            "\n[yellow]Nothing to do — every detected tool already has the "
            "graphfocus entry, or no tools were found.[/]\n"
            "Pass [bold]--replace[/] to overwrite existing entries, or "
            "[bold]--uninstall[/] to remove them."
        )
        return

    action_word = "remove" if uninstall else "add"
    console.print(
        f"\nWill {action_word} the graphfocus entry in [bold]{len(targets)}[/] tool(s):"
    )
    for t in targets:
        console.print(f"  • {t.name} → [dim]{t.install_path}[/]")

    if not auto_yes and not click.confirm("\nProceed?", default=True):
        console.print("[yellow]Cancelled.[/]")
        return

    console.print()
    for tool in targets:
        if uninstall:
            res = _uninstall(tool)
        else:
            res = _install(tool, command=binary, cwd=cwd_abs, replace=replace)
        if res.action in ("added", "replaced"):
            console.print(f"  [green]✓[/] {res.tool_name}: {res.action} ({res.path})")
        elif res.action == "error":
            console.print(f"  [red]✗[/] {res.tool_name}: {res.detail}")
        else:
            console.print(f"  [dim]·[/] {res.tool_name}: {res.detail}")

    console.print(
        "\n[bold]Done.[/] Restart your AI tool(s) so they pick up the new "
        "MCP server."
    )


@main.command()
@click.option("--graph", "graph_path", type=click.Path(exists=False),
              help="Path to graph.json (defaults to ./graphfocus-out/graph.json "
                   "or $GRAPHFOCUS_GRAPH)")
@click.option("--http", "use_http", is_flag=True,
              help="Run over HTTP+SSE instead of stdio (for Cursor, web clients)")
@click.option("--host", default="127.0.0.1", help="HTTP host (with --http)")
@click.option("--port", default=8765, type=int, help="HTTP port (with --http)")
def mcp(graph_path: str | None, use_http: bool, host: str, port: int) -> None:
    """Run an MCP server exposing the knowledge graph to AI tools.

    Connect from Claude Desktop, Trae AI, Cursor, Windsurf, etc. See the
    README for the JSON snippet to add to each client's config.
    """
    try:
        from graphfocus.mcp_server import run_http, run_stdio
    except ImportError:
        console.print("[red]MCP SDK not installed. Run: pip install 'graphfocus[ai]'[/]")
        return

    path = Path(graph_path) if graph_path else None
    if use_http:
        console.print(f"[bold blue]GraphFocus MCP server (HTTP) on {host}:{port}[/]")
        run_http(path, host=host, port=port)
    else:
        # Stdio mode: no rich output — the protocol uses stdout.
        run_stdio(path)


@main.command()
@click.argument("query")
@click.option("--limit", default=10, type=int)
@click.option("--language", default=None)
@click.option("--kind", default=None)
@click.option("--graph", "graph_path", type=click.Path(exists=False),
              default="graphfocus-out/graph.json")
def find(query: str, limit: int, language: str | None, kind: str | None,
         graph_path: str) -> None:
    """Search the graph for nodes whose label or id contains QUERY."""
    from graphfocus.mcp_server import GraphStore

    store = GraphStore(Path(graph_path))
    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        return

    q = query.lower()
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Label", style="cyan")
    table.add_column("Kind")
    table.add_column("Language", style="green")
    table.add_column("ID", style="dim")
    table.add_column("Source", style="dim")

    found = 0
    for n in store.nodes:
        if language and n.get("language") != language:
            continue
        if kind and n.get("kind") != kind:
            continue
        if q in n["label"].lower() or q in n["id"].lower():
            loc = n.get("source_location")
            src = n.get("source_file", "")
            if src and loc:
                src = f"{src}:{loc}"
            table.add_row(n["label"], str(n.get("kind") or "-"),
                          str(n.get("language") or "-"), n["id"], src)
            found += 1
            if found >= limit:
                break
    if found == 0:
        console.print(f"[yellow]No matches for '{query}'[/]")
    else:
        console.print(table)


@main.command()
@click.argument("node_id")
@click.option("--depth", default=1, type=int)
@click.option("--direction", type=click.Choice(["in", "out", "both"]), default="both")
@click.option("--graph", "graph_path", type=click.Path(exists=False),
              default="graphfocus-out/graph.json")
def neighbors(node_id: str, depth: int, direction: str, graph_path: str) -> None:
    """List nodes connected to NODE_ID up to DEPTH hops away."""
    from collections import deque

    from graphfocus.mcp_server import GraphStore

    store = GraphStore(Path(graph_path))
    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        return

    if store.by_id(node_id) is None:
        console.print(f"[red]Node not found: {node_id}[/]")
        return

    visited = {node_id}
    frontier = deque([(node_id, 0)])
    while frontier:
        current, level = frontier.popleft()
        if level >= depth:
            continue
        edges = []
        if direction in ("out", "both"):
            edges.extend(store.outgoing(current))
        if direction in ("in", "both"):
            edges.extend(store.incoming(current))
        for e in edges:
            other = e["target"] if e["source"] == current else e["source"]
            if other not in visited:
                visited.add(other)
                frontier.append((other, level + 1))

    visited.discard(node_id)
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Label", style="cyan")
    table.add_column("Kind")
    table.add_column("Language", style="green")
    table.add_column("ID", style="dim")
    for nid in sorted(visited):
        n = store.by_id(nid)
        if n is None:
            continue
        table.add_row(n["label"], str(n.get("kind") or "-"),
                      str(n.get("language") or "-"), n["id"])
    console.print(table)


@main.command()
@click.argument("query")
@click.option("--limit", default=10, type=int)
@click.option("--language", default=None)
@click.option("--kind", default=None)
@click.option("--graph", "graph_path", type=click.Path(exists=False),
              default="graphfocus-out/graph.json")
def semantic(query: str, limit: int, language: str | None,
             kind: str | None, graph_path: str) -> None:
    """TF-IDF semantic search over node labels and metadata.

    Unlike 'graphfocus find' (substring), this scores nodes by how
    similar their tokens are to the query in TF-IDF space, so a query
    like 'auth user' returns nodes about authentication and users even
    when their labels are spelled differently.
    """
    from graphfocus.mcp_server import GraphStore
    from graphfocus.semantic_index import filter_by, load_index, search

    g_path = Path(graph_path)
    store = GraphStore(g_path)
    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        return

    index_path = g_path.with_name("semantic.json")
    index = load_index(index_path)
    if index is None:
        console.print(
            f"[red]No semantic index at {index_path}.[/]\n"
            "[yellow]Run 'graphfocus analyze .' once to build it.[/]"
        )
        return

    matches = search(index, query, limit=limit * 3)
    nodes_by_id = {n["id"]: n for n in store.nodes}
    matches = filter_by(matches, nodes_by_id, language=language, kind=kind)[:limit]

    if not matches:
        console.print(f"[yellow]No matches for '{query}'[/]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Score", style="dim", justify="right")
    table.add_column("Label", style="cyan")
    table.add_column("Kind")
    table.add_column("Language", style="green")
    table.add_column("Source", style="dim", overflow="fold")
    for nid, score in matches:
        n = nodes_by_id[nid]
        src = n.get("source_file", "") or ""
        loc = n.get("source_location") or ""
        if src and loc:
            src = f"{src}:{loc}"
        table.add_row(
            f"{score:.2f}", n["label"], str(n.get("kind") or "-"),
            str(n.get("language") or "-"), src,
        )
    console.print(table)


@main.command()
@click.argument("symbol")
@click.option("--graph", "graph_path", type=click.Path(exists=False),
              default="graphfocus-out/graph.json")
def callers(symbol: str, graph_path: str) -> None:
    """Show every node that calls SYMBOL (function, method)."""
    from graphfocus.mcp_server import GraphStore

    store = GraphStore(Path(graph_path))
    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/]")
        return

    q = symbol.lower().strip("()")
    targets = []
    for n in store.nodes:
        if n["id"] == symbol:
            targets = [n]
            break
        label = n["label"].lower().strip("()").lstrip(".")
        if label == q:
            targets.append(n)
    if not targets:
        console.print(f"[yellow]No symbol found matching '{symbol}'[/]")
        return

    for t in targets:
        console.print(f"\n[bold]Callers of {t['label']} ({t['id']}):[/]")
        incoming_calls = [e for e in store.incoming(t["id"])
                          if e["relation"] == "calls"]
        if not incoming_calls:
            console.print("  [dim](none)[/]")
            continue
        for e in incoming_calls:
            caller = store.by_id(e["source"])
            label = caller["label"] if caller else e["source"]
            loc = caller.get("source_location") if caller else ""
            file = caller.get("source_file", "") if caller else ""
            extra = f" [dim]{file}{':' + loc if loc else ''}[/]" if file else ""
            console.print(f"  - {label}{extra}")


def _print_detection_summary(detection: dict) -> None:
    """Print a clean summary of detected files."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Category", style="dim")
    table.add_column("Count", justify="right", style="bold")

    by_type = detection.get("by_type", {})
    for file_type, count in by_type.items():
        table.add_row(f"  {file_type}:", str(count))

    console.print(f"[bold]Corpus:[/] {detection['total_files']} files · ~{detection['total_words']:,} words")
    console.print(table)

    if detection.get("skipped_sensitive", 0) > 0:
        console.print(f"  [dim]({detection['skipped_sensitive']} sensitive files skipped)[/]")
