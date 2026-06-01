"""MCP server for GraphFocus.

Exposes the knowledge graph to any MCP-compatible AI tool (Claude Desktop,
Cursor, Trae AI, Windsurf, …) as a set of tools the LLM can call directly.

Why a server instead of just reading files?

  * Token efficiency — the LLM asks targeted questions ("who calls X?")
    and receives focused JSON instead of loading the whole graph
  * Universal — MCP is supported by every modern AI coding tool
  * Live data — the LLM always queries the current graph on disk

Run with::

    graphfocus mcp           # stdio (Claude Desktop / Trae AI)
    graphfocus mcp --http    # http+sse (Cursor, Windsurf, custom clients)
"""

from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_DEFAULT_GRAPH_PATH = Path("graphfocus-out/graph.json")


class GraphStore:
    """Lazy loader and indexer for ``graph.json``.

    Every tool call calls ``ensure_loaded()``, which re-reads the file
    if its mtime changed. That way users can re-run ``graphfocus analyze``
    and the MCP server picks up the new graph automatically.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._mtime: float = 0.0
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._outgoing: dict[str, list[dict]] = defaultdict(list)
        self._incoming: dict[str, list[dict]] = defaultdict(list)

    def ensure_loaded(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(
                f"No graph at {self.path}. Run 'graphfocus analyze' first."
            )
        mtime = self.path.stat().st_mtime
        if mtime == self._mtime and self._nodes:
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._nodes = data.get("nodes", [])
        self._edges = data.get("edges", [])
        self._by_id = {n["id"]: n for n in self._nodes}
        self._outgoing = defaultdict(list)
        self._incoming = defaultdict(list)
        for e in self._edges:
            self._outgoing[e["source"]].append(e)
            self._incoming[e["target"]].append(e)
        self._mtime = mtime

    @property
    def nodes(self) -> list[dict]:
        return self._nodes

    @property
    def edges(self) -> list[dict]:
        return self._edges

    def by_id(self, nid: str) -> dict | None:
        return self._by_id.get(nid)

    def outgoing(self, nid: str) -> list[dict]:
        return self._outgoing.get(nid, [])

    def incoming(self, nid: str) -> list[dict]:
        return self._incoming.get(nid, [])


def _trim_node(n: dict) -> dict:
    """Return a compact node representation suitable for an LLM.

    We drop verbose ``metadata`` unless it's small; the LLM can ask for
    the full node via ``get_node`` if needed.
    """
    out = {
        "id": n["id"],
        "label": n["label"],
        "kind": n.get("kind"),
        "language": n.get("language"),
    }
    loc = n.get("source_location")
    if n.get("source_file"):
        out["source"] = f"{n['source_file']}{':' + loc if loc else ''}"
    return out


def _trim_edge(e: dict, store: GraphStore) -> dict:
    return {
        "source": e["source"],
        "target": e["target"],
        "relation": e["relation"],
        "confidence": e.get("confidence"),
    }


def build_server(graph_path: Path) -> FastMCP:
    """Build a FastMCP server backed by the given graph file."""
    store = GraphStore(graph_path)
    mcp = FastMCP(
        name="graphfocus",
        instructions=(
            "Tools for querying a code knowledge graph built by GraphFocus. "
            "Use find_symbol to locate nodes by name, then get_node or "
            "get_neighbors to explore. Call find_callers to discover who "
            "depends on a function. Returns JSON; never load the whole "
            "graph unless you have a clear reason."
        ),
    )

    @mcp.tool()
    def find_symbol(
        query: str,
        limit: int = 20,
        language: str | None = None,
        kind: str | None = None,
    ) -> dict:
        """Find nodes whose label or id contains ``query`` (case-insensitive).

        Args:
            query: substring to match against node label or id
            limit: max results (default 20)
            language: optional filter, e.g. "java", "typescript"
            kind: optional filter, e.g. "class", "function", "table"
        """
        store.ensure_loaded()
        q = query.lower()
        matches: list[dict] = []
        for n in store.nodes:
            if language and n.get("language") != language:
                continue
            if kind and n.get("kind") != kind:
                continue
            if q in n["label"].lower() or q in n["id"].lower():
                matches.append(_trim_node(n))
                if len(matches) >= limit:
                    break
        return {"query": query, "total": len(matches), "results": matches}

    @mcp.tool()
    def get_node(node_id: str) -> dict:
        """Return the full node by id, plus all its incoming and outgoing edges.

        Use this after ``find_symbol`` to inspect a single node in detail.
        """
        store.ensure_loaded()
        node = store.by_id(node_id)
        if node is None:
            return {"error": f"node not found: {node_id}"}
        return {
            "node": node,
            "outgoing": [
                {**_trim_edge(e, store),
                 "target_label": store.by_id(e["target"])["label"]
                 if store.by_id(e["target"]) else None}
                for e in store.outgoing(node_id)
            ],
            "incoming": [
                {**_trim_edge(e, store),
                 "source_label": store.by_id(e["source"])["label"]
                 if store.by_id(e["source"]) else None}
                for e in store.incoming(node_id)
            ],
        }

    @mcp.tool()
    def get_neighbors(
        node_id: str,
        direction: str = "both",
        depth: int = 1,
        limit: int = 50,
    ) -> dict:
        """Walk the graph outwards from ``node_id`` up to ``depth`` hops.

        Args:
            node_id: starting node id
            direction: "out" (only follow outgoing), "in" (only incoming),
                or "both"
            depth: how many hops to expand (default 1)
            limit: cap on total nodes returned
        """
        store.ensure_loaded()
        if store.by_id(node_id) is None:
            return {"error": f"node not found: {node_id}"}

        visited = {node_id}
        frontier = deque([(node_id, 0)])
        collected_edges: list[dict] = []

        while frontier and len(visited) < limit:
            current, level = frontier.popleft()
            if level >= depth:
                continue
            edges: list[dict] = []
            if direction in ("out", "both"):
                edges.extend(store.outgoing(current))
            if direction in ("in", "both"):
                edges.extend(store.incoming(current))
            for e in edges:
                other = e["target"] if e["source"] == current else e["source"]
                collected_edges.append(e)
                if other not in visited:
                    visited.add(other)
                    frontier.append((other, level + 1))
                    if len(visited) >= limit:
                        break

        return {
            "root": node_id,
            "nodes": [_trim_node(store.by_id(nid))
                      for nid in visited if store.by_id(nid)],
            "edges": [_trim_edge(e, store) for e in collected_edges],
        }

    @mcp.tool()
    def find_callers(symbol: str, limit: int = 30) -> dict:
        """List every node that *calls* the given function or method.

        ``symbol`` can be either a node id or a label substring (e.g.
        "validate_user", "validateUser()"). We resolve it to one or more
        nodes, then return every incoming ``calls`` edge.
        """
        store.ensure_loaded()
        q = symbol.lower().strip("()")
        targets: list[dict] = []
        for n in store.nodes:
            if n["id"] == symbol:
                targets = [n]
                break
            label = n["label"].lower().strip("()").lstrip(".")
            if label == q:
                targets.append(n)

        if not targets:
            # Fallback to substring match.
            for n in store.nodes:
                if q in n["label"].lower() or q in n["id"].lower():
                    targets.append(n)
                    if len(targets) >= 5:
                        break

        results: list[dict] = []
        for t in targets:
            callers = [
                {
                    "caller": _trim_node(store.by_id(e["source"])
                                          or {"id": e["source"], "label": e["source"]}),
                    "edge": _trim_edge(e, store),
                }
                for e in store.incoming(t["id"])
                if e["relation"] == "calls"
            ]
            results.append({
                "target": _trim_node(t),
                "callers": callers[:limit],
                "total_callers": len(callers),
            })
        return {"symbol": symbol, "matches": results}

    @mcp.tool()
    def find_path(source: str, target: str, max_depth: int = 6) -> dict:
        """Find a shortest path of edges between two node ids (BFS, undirected).

        Useful for questions like "how is X connected to Y?".
        """
        store.ensure_loaded()
        if store.by_id(source) is None:
            return {"error": f"source not found: {source}"}
        if store.by_id(target) is None:
            return {"error": f"target not found: {target}"}

        prev: dict[str, tuple[str, dict] | None] = {source: None}
        queue: deque[tuple[str, int]] = deque([(source, 0)])
        found = False
        while queue:
            cur, depth = queue.popleft()
            if cur == target:
                found = True
                break
            if depth >= max_depth:
                continue
            for e in store.outgoing(cur) + store.incoming(cur):
                other = e["target"] if e["source"] == cur else e["source"]
                if other not in prev:
                    prev[other] = (cur, e)
                    queue.append((other, depth + 1))

        if not found:
            return {"path": None, "reason": f"no path within {max_depth} hops"}

        path_nodes: list[dict] = []
        path_edges: list[dict] = []
        cur = target
        chain: list[str] = []
        while cur is not None:
            chain.append(cur)
            link = prev[cur]
            if link is None:
                break
            cur = link[0]
            path_edges.append(_trim_edge(link[1], store))
        chain.reverse()
        path_edges.reverse()
        path_nodes = [_trim_node(store.by_id(nid))
                      for nid in chain if store.by_id(nid)]
        return {"path_nodes": path_nodes, "path_edges": path_edges,
                "length": len(path_edges)}

    @mcp.tool()
    def list_languages() -> dict:
        """List every language present in the graph along with node counts."""
        store.ensure_loaded()
        counts: dict[str, int] = defaultdict(int)
        for n in store.nodes:
            counts[n.get("language") or "unknown"] += 1
        return {
            "languages": [
                {"language": lang, "nodes": c}
                for lang, c in sorted(counts.items(), key=lambda kv: -kv[1])
            ],
        }

    @mcp.tool()
    def get_stats() -> dict:
        """Return overall graph statistics: counts, kinds, relations."""
        store.ensure_loaded()
        kinds: dict[str, int] = defaultdict(int)
        relations: dict[str, int] = defaultdict(int)
        for n in store.nodes:
            kinds[n.get("kind") or "unknown"] += 1
        for e in store.edges:
            relations[e["relation"]] += 1
        return {
            "total_nodes": len(store.nodes),
            "total_edges": len(store.edges),
            "by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
            "by_relation": dict(sorted(relations.items(), key=lambda kv: -kv[1])),
        }

    @mcp.tool()
    def get_context_pack(
        symbol: str,
        depth_callers: int = 2,
        depth_callees: int = 2,
        limit_per_section: int = 25,
    ) -> dict:
        """Bundle everything an LLM usually wants about a symbol into one call.

        Resolves ``symbol`` (id or label), then returns the node plus its
        callers (up to ``depth_callers`` hops in), its callees (up to
        ``depth_callees`` hops out), its immediate neighbors of any other
        relation, and a list of the community siblings. Designed to replace
        what would otherwise be 4-6 separate MCP calls.

        Args:
            symbol: node id, exact label, or substring (best match wins)
            depth_callers: how far back the caller chain reaches
            depth_callees: how far down the callee chain reaches
            limit_per_section: cap on each list to keep responses small
        """
        store.ensure_loaded()

        # Resolve symbol → node
        target = store.by_id(symbol)
        if target is None:
            q = symbol.lower().strip("()")
            for n in store.nodes:
                label = n["label"].lower().strip("()").lstrip(".")
                if label == q:
                    target = n
                    break
            if target is None:
                for n in store.nodes:
                    if q in n["label"].lower() or q in n["id"].lower():
                        target = n
                        break
        if target is None:
            return {"error": f"symbol not found: {symbol}"}

        # BFS-like collection of callers / callees.
        def _trace(start: str, direction: str, depth: int) -> list[dict]:
            seen = {start}
            collected: list[dict] = []
            frontier = deque([(start, 0)])
            while frontier and len(collected) < limit_per_section:
                cur, level = frontier.popleft()
                if level >= depth:
                    continue
                edges = (
                    store.incoming(cur) if direction == "in" else store.outgoing(cur)
                )
                for e in edges:
                    if e["relation"] != "calls":
                        continue
                    other_id = e["source"] if direction == "in" else e["target"]
                    if other_id in seen:
                        continue
                    seen.add(other_id)
                    other = store.by_id(other_id)
                    if other is None:
                        continue
                    collected.append({
                        **_trim_node(other),
                        "hops": level + 1,
                        "via": e["relation"],
                    })
                    frontier.append((other_id, level + 1))
                    if len(collected) >= limit_per_section:
                        break
            return collected

        callers = _trace(target["id"], "in", depth_callers)
        callees = _trace(target["id"], "out", depth_callees)

        # Immediate neighbors via non-"calls" relations.
        neighbors: list[dict] = []
        seen_neighbors: set[str] = set()
        for e in store.outgoing(target["id"]) + store.incoming(target["id"]):
            if e["relation"] == "calls":
                continue
            other_id = e["target"] if e["source"] == target["id"] else e["source"]
            if other_id in seen_neighbors:
                continue
            seen_neighbors.add(other_id)
            other = store.by_id(other_id)
            if other is None:
                continue
            arrow = "→" if e["source"] == target["id"] else "←"
            neighbors.append({
                **_trim_node(other),
                "via": f"{arrow} {e['relation']}",
            })
            if len(neighbors) >= limit_per_section:
                break

        # Community siblings (other top-degree nodes in the same community).
        community_id = target.get("community", 0)
        siblings: list[dict] = []
        if community_id is not None:
            scored = [
                (n, len(store.outgoing(n["id"])) + len(store.incoming(n["id"])))
                for n in store.nodes
                if n.get("community") == community_id and n["id"] != target["id"]
            ]
            scored.sort(key=lambda kv: -kv[1])
            siblings = [_trim_node(n) for n, _ in scored[:limit_per_section]]

        return {
            "symbol": _trim_node(target),
            "callers": callers,            # who reaches in
            "callees": callees,            # what it reaches out to
            "neighbors": neighbors,        # contains/extends/has_field/maps_to/etc.
            "community_id": community_id,
            "community_siblings": siblings,
            "summary": {
                "total_callers": len(callers),
                "total_callees": len(callees),
                "total_neighbors": len(neighbors),
                "community_size": len(siblings) + 1,
            },
        }

    @mcp.tool()
    def hot_paths(top_n: int = 20, relation: str = "calls") -> dict:
        """Return the most-traveled nodes (highest degree) of a relation.

        Useful for onboarding ("what are the most central pieces of this
        codebase?") and for finding god-nodes that are candidates for
        refactoring. Defaults to 'calls' edges so you see the busiest
        functions; pass relation='contains' to see the largest containers
        instead.
        """
        store.ensure_loaded()
        rel = relation
        in_count: dict[str, int] = {}
        out_count: dict[str, int] = {}
        for e in store.edges:
            if e["relation"] != rel:
                continue
            in_count[e["target"]] = in_count.get(e["target"], 0) + 1
            out_count[e["source"]] = out_count.get(e["source"], 0) + 1

        ranked: list[tuple[str, int, int]] = []
        for nid in set(in_count) | set(out_count):
            ranked.append((nid, in_count.get(nid, 0), out_count.get(nid, 0)))
        ranked.sort(key=lambda t: -(t[1] + t[2]))

        results = []
        for nid, ic, oc in ranked[:top_n]:
            node = store.by_id(nid)
            if node is None:
                continue
            results.append({
                **_trim_node(node),
                "incoming_count": ic,
                "outgoing_count": oc,
                "total_count": ic + oc,
            })
        return {"relation": rel, "results": results}

    @mcp.tool()
    def cross_language_links() -> dict:
        """Return only edges that connect nodes across different languages.

        Useful for understanding how a Java backend maps to SQL tables, or
        how a frontend Vue component references a TypeScript module.
        """
        store.ensure_loaded()
        out: list[dict] = []
        for e in store.edges:
            src = store.by_id(e["source"])
            tgt = store.by_id(e["target"])
            if not (src and tgt):
                continue
            if src.get("language") != tgt.get("language") and src.get("language") and tgt.get("language"):
                out.append({
                    **_trim_edge(e, store),
                    "source_label": src["label"],
                    "source_language": src.get("language"),
                    "target_label": tgt["label"],
                    "target_language": tgt.get("language"),
                })
        return {"total": len(out), "edges": out}

    return mcp


def run_stdio(graph_path: Path | None = None) -> None:
    """Run the MCP server over stdio (Claude Desktop, Trae AI default)."""
    path = graph_path or _resolve_graph_path()
    server = build_server(path)
    server.run()


def run_http(graph_path: Path | None = None, host: str = "127.0.0.1",
             port: int = 8765) -> None:
    """Run the MCP server over HTTP+SSE (Cursor, custom clients)."""
    path = graph_path or _resolve_graph_path()
    server = build_server(path)
    server.settings.host = host
    server.settings.port = port
    server.run(transport="sse")


def _resolve_graph_path() -> Path:
    """Find the graph file from env var or the default location."""
    env = os.environ.get("GRAPHFOCUS_GRAPH")
    if env:
        return Path(env)
    return _DEFAULT_GRAPH_PATH
