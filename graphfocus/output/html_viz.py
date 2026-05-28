"""Interactive HTML visualization for graphs of any size.

We produce **two files** that work side-by-side from ``file://`` (no web
server needed) and scale to hundreds of thousands of nodes:

  * ``graph.html``     — tiny shell (~15 KB). UI + Sigma.js + graphology
                         loaded from CDN. Loads ``graph-data.js``.
  * ``graph-data.js``  — the data, assigned to ``window.__GRAPHFOCUS_DATA__``.

Why split and why not D3 anymore:

  * D3 + SVG dies around 5 000 nodes (one DOM element per node).
  * D3 force simulation runs every frame and saturates the CPU long
    before the DOM does.
  * Sigma.js renders to **WebGL** and comfortably handles 100 000+ nodes.
  * Running the force layout server-side once with ``igraph`` is orders
    of magnitude faster than running it in JavaScript every frame, and
    the browser only has to render — no physics.

For small graphs (< ~200 nodes) where ``igraph`` is unavailable we fall
back to a simple circular layout so the file still renders.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from graphfocus.extractors.base import Edge, Node

logger = logging.getLogger(__name__)


# Stable per-language palette (kept identical to v0.1.2 for UX continuity).
_LANGUAGE_COLORS = {
    "python": "#3572A5",
    "java": "#B07219",
    "csharp": "#178600",
    "plsql": "#DAD030",
    "sql": "#E38C00",
    "javascript": "#F1E05A",
    "typescript": "#3178C6",
    "go": "#00ADD8",
    "rust": "#DEA584",
    "kotlin": "#A97BFF",
    "ruby": "#701516",
    "php": "#4F5D95",
    "swift": "#F05138",
    "cpp": "#F34B7D",
    "c": "#555555",
    "scala": "#c22d40",
    "vue": "#41b883",
    "lua": "#000080",
    "dart": "#00B4AB",
    "r": "#198CE7",
}
_FALLBACK_COLOR = "#888888"


def generate_html(
    nodes: list[Node],
    edges: list[Edge],
    output_path: Path,
    communities: dict[str, int] | None = None,
    title: str = "GraphFocus",
) -> None:
    """Write ``graph.html`` and ``graph-data.js`` next to each other.

    ``output_path`` is the ``.html`` path the caller wants. The data file
    is written to ``output_path.with_name("graph-data.js")``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    communities = communities or {}

    # ── Compute node degree for sizing ─────────────────────────────
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1

    # ── Pre-compute layout server-side ─────────────────────────────
    positions = _compute_layout(nodes, edges)

    # ── Build payload ──────────────────────────────────────────────
    nodes_payload: list[dict] = []
    languages_seen: set[str] = set()
    kinds_seen: set[str] = set()
    for n in nodes:
        lang = n.language or "unknown"
        kind = n.kind or "unknown"
        languages_seen.add(lang)
        kinds_seen.add(kind)
        x, y = positions.get(n.id, (0.0, 0.0))
        nodes_payload.append({
            "id": n.id,
            "label": n.label,
            "language": lang,
            "kind": kind,
            "source_file": n.source_file,
            "source_location": n.source_location,
            "degree": degree.get(n.id, 0),
            "community": communities.get(n.id, 0),
            "color": _LANGUAGE_COLORS.get(lang, _FALLBACK_COLOR),
            "x": x,
            "y": y,
        })

    edges_payload: list[dict] = []
    confidences_seen: set[str] = set()
    for e in edges:
        confidences_seen.add(e.confidence)
        edges_payload.append({
            "source": e.source,
            "target": e.target,
            "relation": e.relation,
            "confidence": e.confidence,
        })

    community_count = (
        max(communities.values()) + 1 if communities else 1
    )

    payload = {
        "title": title,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "languages": sorted(languages_seen),
        "kinds": sorted(kinds_seen),
        "confidences": sorted(confidences_seen),
        "community_count": community_count,
        "language_colors": {
            lang: _LANGUAGE_COLORS.get(lang, _FALLBACK_COLOR)
            for lang in languages_seen
        },
    }

    # ── Write data + html ─────────────────────────────────────────
    data_path = output_path.with_name("graph-data.js")
    data_path.write_text(
        "window.__GRAPHFOCUS_DATA__ = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    output_path.write_text(
        _HTML_TEMPLATE.replace("__TITLE__", title),
        encoding="utf-8",
    )


# ── internals ───────────────────────────────────────────────────────────────


def _compute_layout(
    nodes: list[Node],
    edges: list[Edge],
) -> dict[str, tuple[float, float]]:
    """Return a node-id -> (x, y) mapping, normalized to [0, 1000].

    Strategy:
      * If ``igraph`` is installed, use a force-directed layout. For very
        large graphs we use DRL (designed for huge graphs); for medium
        ones we use Fruchterman-Reingold (nicer aesthetics).
      * Otherwise fall back to a circle layout so the file still renders.
    """
    n = len(nodes)
    if n == 0:
        return {}

    node_ids = [node.id for node in nodes]
    index_of = {nid: i for i, nid in enumerate(node_ids)}

    try:
        import igraph as ig
    except ImportError:
        logger.info("igraph not installed; using fallback circular layout.")
        return _circle_layout(node_ids)

    try:
        ig_edges = [
            (index_of[e.source], index_of[e.target])
            for e in edges
            if e.source in index_of and e.target in index_of
        ]
        h = ig.Graph(n=n, edges=ig_edges, directed=False)

        if n > 3000:
            layout = h.layout_drl()
        elif n > 500:
            layout = h.layout_fruchterman_reingold(niter=80)
        else:
            layout = h.layout_fruchterman_reingold(niter=200)

        coords = list(layout.coords)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(f"Layout computation failed ({exc}); using circle.")
        return _circle_layout(node_ids)

    return _normalize(node_ids, coords)


def _normalize(
    node_ids: list[str],
    coords: list[tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Normalize layout coords into the [0, 1000] x [0, 1000] box."""
    if not coords:
        return {}
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    range_x = (max_x - min_x) or 1.0
    range_y = (max_y - min_y) or 1.0
    return {
        nid: (
            (coords[i][0] - min_x) / range_x * 1000.0,
            (coords[i][1] - min_y) / range_y * 1000.0,
        )
        for i, nid in enumerate(node_ids)
    }


def _circle_layout(node_ids: list[str]) -> dict[str, tuple[float, float]]:
    """Last-resort layout: place every node evenly around a circle."""
    n = len(node_ids)
    if n == 0:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for i, nid in enumerate(node_ids):
        angle = 2 * math.pi * i / n
        out[nid] = (500 + 450 * math.cos(angle), 500 + 450 * math.sin(angle))
    return out


# ── HTML template ───────────────────────────────────────────────────────────


_HTML_TEMPLATE = r"""<!doctype html>
<!--
  Generated by GraphFocus. This file expects ``graph-data.js`` to sit
  next to it. If you move the .html, move the .js too.
-->
<html lang="en">
<head>
<meta charset="utf-8" />
<title>__TITLE__ — GraphFocus</title>
<style>
  :root {
    --bg: #0f1117;
    --panel: #181b24;
    --panel-2: #21252f;
    --text: #e6e6e6;
    --muted: #8b91a1;
    --accent: #4ea1f3;
    --border: #2a2f3a;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font: 13px/1.4 -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
    display: grid;
    grid-template-columns: 260px 1fr 300px;
    grid-template-rows: 48px 1fr;
    grid-template-areas:
      "header header header"
      "left   main   right";
  }
  header {
    grid-area: header;
    display: flex; align-items: center; gap: 14px;
    padding: 0 14px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  header h1 { margin: 0; font-size: 14px; font-weight: 600; }
  header .stats { color: var(--muted); font-size: 12px; }
  header .stats b { color: var(--text); }
  header .spacer { flex: 1; }
  header select, header input[type="search"] {
    background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 5px 8px; outline: none;
  }
  header input[type="search"] { width: 220px; }
  header select:focus, header input:focus { border-color: var(--accent); }
  aside.left, aside.right {
    background: var(--panel);
    overflow-y: auto;
    padding: 12px;
  }
  aside.left { grid-area: left; border-right: 1px solid var(--border); }
  aside.right { grid-area: right; border-left: 1px solid var(--border); }
  main { grid-area: main; position: relative; overflow: hidden; }
  #sigma-container { position: absolute; inset: 0; }
  .panel-title {
    text-transform: uppercase; font-size: 11px;
    letter-spacing: 0.08em; color: var(--muted);
    margin: 14px 0 6px;
  }
  .panel-title:first-child { margin-top: 0; }
  .filter-list { display: flex; flex-direction: column; gap: 2px; }
  .filter-row {
    display: flex; align-items: center; gap: 8px;
    padding: 4px 6px; border-radius: 4px;
    cursor: pointer; user-select: none;
  }
  .filter-row:hover { background: var(--panel-2); }
  .filter-row .swatch {
    width: 10px; height: 10px; border-radius: 50%;
    border: 1px solid rgba(255,255,255,0.15);
    flex-shrink: 0;
  }
  .filter-row .count {
    color: var(--muted); margin-left: auto; font-size: 11px;
  }
  .toolbar { display: flex; gap: 6px; flex-wrap: wrap; }
  .toolbar button {
    background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 5px 10px; cursor: pointer; font-size: 12px;
  }
  .toolbar button:hover { border-color: var(--accent); }
  .detail-empty { color: var(--muted); font-style: italic; padding: 8px 0; }
  .detail-row { margin: 6px 0; }
  .detail-row .k {
    color: var(--muted); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
  .detail-row .v { color: var(--text); word-break: break-word; }
  .detail-row .v code {
    background: var(--panel-2); padding: 2px 4px;
    border-radius: 3px; font-size: 12px;
  }
  .detail-row a { color: var(--accent); text-decoration: none; }
  .detail-row a:hover { text-decoration: underline; }
  .neighbors li {
    list-style: none; padding: 3px 0;
    border-bottom: 1px solid var(--border);
  }
  .neighbors li .rel {
    color: var(--muted); font-size: 11px; margin-right: 6px;
  }
  .legend-line {
    display: flex; align-items: center; gap: 8px;
    padding: 3px 0; font-size: 11px; color: var(--muted);
  }
  #loading {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    background: var(--bg); color: var(--muted);
    font-size: 14px; z-index: 100;
  }
</style>
</head>
<body>
<header>
  <h1>GraphFocus</h1>
  <span class="stats" id="stats">loading…</span>
  <span class="spacer"></span>
  <label style="color:var(--muted);font-size:12px;">
    Color by
    <select id="color-mode">
      <option value="language" selected>Language</option>
      <option value="kind">Kind</option>
      <option value="community">Community</option>
    </select>
  </label>
  <input id="search" type="search" placeholder="Search nodes…" autocomplete="off" />
</header>

<aside class="left">
  <div class="panel-title">Filters</div>

  <div class="panel-title">Languages</div>
  <div class="filter-list" id="filter-languages"></div>

  <div class="panel-title">Kinds</div>
  <div class="filter-list" id="filter-kinds"></div>

  <div class="panel-title">Confidence</div>
  <div class="filter-list" id="filter-confidence"></div>

  <div class="panel-title">View</div>
  <div class="toolbar">
    <button id="fit">Fit</button>
    <button id="reset">Reset filters</button>
  </div>
</aside>

<main>
  <div id="sigma-container"></div>
  <div id="loading">Loading graph…</div>
</main>

<aside class="right">
  <div class="panel-title">Selection</div>
  <div id="detail" class="detail-empty">Click a node to inspect.</div>
</aside>

<!-- Libraries: graphology (data structure) + Sigma.js v3 (WebGL renderer) -->
<script src="https://cdn.jsdelivr.net/npm/graphology@0.25.4/dist/graphology.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/sigma@3.0.0/dist/sigma.min.js"></script>
<!-- Data file — must be next to this HTML -->
<script src="./graph-data.js"></script>

<script>
(function () {
  const DATA = window.__GRAPHFOCUS_DATA__;
  if (!DATA) {
    document.getElementById("loading").textContent =
      "Could not load graph-data.js (it must sit next to graph.html).";
    return;
  }

  // ── 20-color palette reused for kinds and communities ────────────────
  const CATEGORICAL = [
    "#4c78a8","#f58518","#e45756","#72b7b2","#54a24b","#eeca3b",
    "#b279a2","#ff9da6","#9d755d","#bab0ac","#1f77b4","#aec7e8",
    "#ffbb78","#98df8a","#d62728","#ff9896","#c5b0d5","#c49c94",
    "#f7b6d2","#dbdb8d",
  ];
  const kindPalette = {};
  DATA.kinds.forEach((k, i) => { kindPalette[k] = CATEGORICAL[i % CATEGORICAL.length]; });

  function colorOf(attrs, mode) {
    if (mode === "kind") return kindPalette[attrs.kind] || "#888";
    if (mode === "community") {
      return CATEGORICAL[(attrs.community || 0) % CATEGORICAL.length];
    }
    return DATA.language_colors[attrs.language] || "#888";
  }

  // ── Build the graphology graph ──────────────────────────────────────
  const graph = new graphology.Graph();
  const ids = new Set();

  // Node sizes scale with degree (sqrt to keep huge hubs from dominating).
  for (const n of DATA.nodes) {
    if (ids.has(n.id)) continue;
    ids.add(n.id);
    graph.addNode(n.id, {
      label: n.label,
      x: n.x,
      y: n.y,
      size: Math.max(2, Math.min(14, 2 + Math.sqrt(n.degree || 0))),
      color: colorOf(n, "language"),
      // Keep original attrs accessible via the node data.
      language: n.language,
      kind: n.kind,
      community: n.community || 0,
      degree: n.degree || 0,
      source_file: n.source_file,
      source_location: n.source_location,
    });
  }

  let droppedEdges = 0;
  for (const e of DATA.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) { droppedEdges++; continue; }
    try {
      graph.addEdge(e.source, e.target, {
        size: 0.4,
        color: "rgba(170,170,180,0.45)",
        relation: e.relation,
        confidence: e.confidence,
      });
    } catch (_) {
      // graphology disallows parallel edges by default; ignore extras.
    }
  }

  document.getElementById("stats").innerHTML =
    `<b>${graph.order}</b> nodes · <b>${graph.size}</b> edges · ` +
    `<b>${DATA.languages.length}</b> languages` +
    (droppedEdges ? ` · <span style="color:#c66">${droppedEdges} orphan edges</span>` : "");

  // ── Filter state ────────────────────────────────────────────────────
  const enabled = {
    language: new Set(DATA.languages),
    kind: new Set(DATA.kinds),
    confidence: new Set(DATA.confidences),
  };
  let colorMode = "language";
  let highlight = new Set();          // search match ids
  let highlightOn = false;

  function buildFilterUI(containerId, key, items, paletteFn) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";
    const counts = {};
    if (key === "language") {
      for (const n of DATA.nodes) counts[n.language] = (counts[n.language] || 0) + 1;
    } else if (key === "kind") {
      for (const n of DATA.nodes) counts[n.kind] = (counts[n.kind] || 0) + 1;
    } else if (key === "confidence") {
      for (const e of DATA.edges) counts[e.confidence] = (counts[e.confidence] || 0) + 1;
    }
    for (const item of items) {
      const row = document.createElement("label");
      row.className = "filter-row";
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = true;
      cb.addEventListener("change", () => {
        if (cb.checked) enabled[key].add(item);
        else enabled[key].delete(item);
        renderer.refresh();
      });
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = paletteFn(item);
      const label = document.createElement("span");
      label.textContent = item;
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = counts[item] || 0;
      row.appendChild(cb); row.appendChild(swatch);
      row.appendChild(label); row.appendChild(count);
      container.appendChild(row);
    }
  }

  buildFilterUI("filter-languages", "language", DATA.languages,
    l => DATA.language_colors[l] || "#888");
  buildFilterUI("filter-kinds", "kind", DATA.kinds, k => kindPalette[k] || "#888");
  buildFilterUI("filter-confidence", "confidence", DATA.confidences, () => "#666");

  // ── Sigma renderer ──────────────────────────────────────────────────
  const container = document.getElementById("sigma-container");
  const renderer = new Sigma(graph, container, {
    renderEdgeLabels: false,
    labelDensity: 0.07,
    labelGridCellSize: 60,
    labelRenderedSizeThreshold: 8,
    minCameraRatio: 0.05,
    maxCameraRatio: 20,
    defaultEdgeColor: "rgba(170,170,180,0.4)",
  });

  // Hide the loading screen once Sigma has done the first paint.
  requestAnimationFrame(() => {
    document.getElementById("loading").style.display = "none";
  });

  // Reducers — Sigma calls these per node/edge each frame and we can
  // override attrs based on the current filter/color state.
  renderer.setSetting("nodeReducer", (id, attrs) => {
    const visible =
      enabled.language.has(attrs.language) &&
      enabled.kind.has(attrs.kind);
    if (!visible) return { ...attrs, hidden: true };

    let color = colorOf(attrs, colorMode);
    if (highlightOn && !highlight.has(id)) {
      color = "rgba(180,180,180,0.15)";
    }
    return { ...attrs, color };
  });

  renderer.setSetting("edgeReducer", (id, attrs) => {
    if (!enabled.confidence.has(attrs.confidence)) {
      return { ...attrs, hidden: true };
    }
    const [s, t] = graph.extremities(id);
    const ns = graph.getNodeAttributes(s);
    const nt = graph.getNodeAttributes(t);
    if (!enabled.language.has(ns.language) || !enabled.kind.has(ns.kind) ||
        !enabled.language.has(nt.language) || !enabled.kind.has(nt.kind)) {
      return { ...attrs, hidden: true };
    }
    return attrs;
  });

  // ── Color-by selector ──────────────────────────────────────────────
  document.getElementById("color-mode").addEventListener("change", (evt) => {
    colorMode = evt.target.value;
    renderer.refresh();
  });

  // ── Search ─────────────────────────────────────────────────────────
  const searchInput = document.getElementById("search");
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    if (!q) {
      highlight = new Set();
      highlightOn = false;
    } else {
      highlight = new Set();
      graph.forEachNode((id, attrs) => {
        if ((attrs.label || "").toLowerCase().includes(q) ||
            id.toLowerCase().includes(q)) {
          highlight.add(id);
        }
      });
      highlightOn = true;
    }
    renderer.refresh();
  });

  // ── Click → detail panel ───────────────────────────────────────────
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function shorten(p) {
    const parts = String(p).split("/");
    return parts.length > 4 ? ".../" + parts.slice(-3).join("/") : p;
  }

  function showDetail(id) {
    const attrs = graph.getNodeAttributes(id);
    const out = [];
    out.push(`<div class="detail-row"><div class="k">Label</div>` +
             `<div class="v"><b>${escapeHtml(attrs.label)}</b></div></div>`);
    out.push(`<div class="detail-row"><div class="k">ID</div>` +
             `<div class="v"><code>${escapeHtml(id)}</code></div></div>`);
    out.push(`<div class="detail-row"><div class="k">Kind</div>` +
             `<div class="v">${escapeHtml(attrs.kind)}</div></div>`);
    out.push(`<div class="detail-row"><div class="k">Language</div>` +
             `<div class="v">${escapeHtml(attrs.language)}</div></div>`);
    if (attrs.source_file) {
      const loc = attrs.source_location;
      const ln = loc ? loc.replace(/^L/, "") : "";
      const href = "vscode://file/" + encodeURI(attrs.source_file) +
                   (ln ? ":" + ln : "");
      out.push(`<div class="detail-row"><div class="k">Source</div>` +
               `<div class="v"><a href="${href}">${escapeHtml(shorten(attrs.source_file))}` +
               (loc ? ":" + escapeHtml(loc) : "") + `</a></div></div>`);
    }
    out.push(`<div class="detail-row"><div class="k">Degree</div>` +
             `<div class="v">${attrs.degree}</div></div>`);
    out.push(`<div class="detail-row"><div class="k">Community</div>` +
             `<div class="v">${attrs.community}</div></div>`);

    // Neighbours
    const neighbours = [];
    graph.forEachEdge(id, (eid, eattrs, s, t) => {
      const otherId = s === id ? t : s;
      const other = graph.getNodeAttributes(otherId);
      const arrow = s === id ? "→" : "←";
      neighbours.push(
        `<li><span class="rel">${escapeHtml(eattrs.relation)} ${arrow}</span> ` +
        `${escapeHtml(other.label)}</li>`,
      );
      if (neighbours.length >= 40) return;
    });
    if (neighbours.length) {
      out.push(`<div class="detail-row"><div class="k">Neighbors</div></div>`);
      out.push(`<ul class="neighbors">${neighbours.join("")}</ul>`);
    }

    const detail = document.getElementById("detail");
    detail.classList.remove("detail-empty");
    detail.innerHTML = out.join("");
  }

  renderer.on("clickNode", ({ node }) => showDetail(node));
  renderer.on("clickStage", () => {
    const d = document.getElementById("detail");
    d.classList.add("detail-empty");
    d.innerHTML = "Click a node to inspect.";
  });

  // ── Toolbar ────────────────────────────────────────────────────────
  document.getElementById("fit").addEventListener("click", () => {
    renderer.getCamera().animatedReset();
  });
  document.getElementById("reset").addEventListener("click", () => {
    DATA.languages.forEach(l => enabled.language.add(l));
    DATA.kinds.forEach(k => enabled.kind.add(k));
    DATA.confidences.forEach(c => enabled.confidence.add(c));
    document.querySelectorAll(".filter-row input[type=checkbox]")
      .forEach(cb => cb.checked = true);
    searchInput.value = "";
    highlight = new Set();
    highlightOn = false;
    renderer.refresh();
  });
})();
</script>
</body>
</html>
"""
