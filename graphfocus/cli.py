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

    from graphfocus.extractors.base import Edge as _Edge, Node as _Node  # noqa: E402

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

    # Step 3: Output
    config.output_dir.mkdir(parents=True, exist_ok=True)

    from graphfocus.output.json_export import export_json

    export_json(all_nodes, all_edges, config.output_dir / "graph.json")
    console.print(f"[green]✓ Graph saved to {config.output_dir / 'graph.json'}[/]")

    from graphfocus.output.report import generate_report

    generate_report(all_nodes, all_edges, detection, config.output_dir / "GRAPH_REPORT.md")
    console.print(f"[green]✓ Report saved to {config.output_dir / 'GRAPH_REPORT.md'}[/]")

    if not config.skip_viz:
        from graphfocus.output.html_viz import generate_html

        html_path = config.output_dir / "graph.html"
        generate_html(all_nodes, all_edges, html_path, title=config.input_path.name)
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
        from graphfocus.mcp_server import run_stdio, run_http
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
