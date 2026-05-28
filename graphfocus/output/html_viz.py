"""Interactive HTML visualization generator.

Produces a single self-contained HTML file with a D3.js force-directed graph.
The graph data is embedded inline as JSON, so the file can be opened directly
in a browser (no server required).

Features:
  - Node color by language
  - Node radius by degree
  - Edge styling by confidence (EXTRACTED solid, INFERRED dashed, AMBIGUOUS dotted)
  - Filter checkboxes: languages, kinds, confidence levels
  - Search box that highlights matching nodes
  - Click a node to see its details (with a vscode:// link to the source)
  - Drag, zoom and pan
"""

from __future__ import annotations

import json
from pathlib import Path

from graphfocus.extractors.base import Edge, Node

# Stable color palette indexed by language name.
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
}
_FALLBACK_COLOR = "#888888"


def generate_html(
    nodes: list[Node],
    edges: list[Edge],
    output_path: Path,
    communities: dict[str, int] | None = None,
    title: str = "GraphFocus",
) -> None:
    """Write an interactive HTML visualization of the graph.

    Args:
        nodes: extracted nodes
        edges: extracted edges
        output_path: where to write the .html file
        communities: optional mapping node_id -> community id (from Leiden)
        title: page title
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    communities = communities or {}

    # Compute node degree for sizing.
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1

    nodes_payload = []
    languages_seen: set[str] = set()
    kinds_seen: set[str] = set()
    for n in nodes:
        lang = n.language or "unknown"
        kind = n.kind or "unknown"
        languages_seen.add(lang)
        kinds_seen.add(kind)
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
        })

    edges_payload = []
    confidences_seen: set[str] = set()
    for e in edges:
        confidences_seen.add(e.confidence)
        edges_payload.append({
            "source": e.source,
            "target": e.target,
            "relation": e.relation,
            "confidence": e.confidence,
            "source_file": e.source_file,
            "source_location": e.source_location,
        })

    payload = {
        "title": title,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "languages": sorted(languages_seen),
        "kinds": sorted(kinds_seen),
        "confidences": sorted(confidences_seen),
        "language_colors": {
            lang: _LANGUAGE_COLORS.get(lang, _FALLBACK_COLOR)
            for lang in languages_seen
        },
    }

    html = _HTML_TEMPLATE.replace(
        "__GRAPHFOCUS_DATA__",
        json.dumps(payload, ensure_ascii=False),
    ).replace("__TITLE__", title)

    output_path.write_text(html, encoding="utf-8")


# Self-contained HTML + JS. D3.js v7 is loaded from a CDN.
# The data is injected via the __GRAPHFOCUS_DATA__ placeholder.
_HTML_TEMPLATE = r"""<!doctype html>
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
    grid-template-columns: 280px 1fr 320px;
    grid-template-rows: 48px 1fr;
    grid-template-areas:
      "header header header"
      "left   main   right";
  }
  header {
    grid-area: header;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 16px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  header h1 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.02em;
  }
  header .stats { color: var(--muted); font-size: 12px; }
  header .stats b { color: var(--text); }
  header .spacer { flex: 1; }
  header input[type="search"] {
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 10px;
    width: 240px;
    outline: none;
  }
  header input[type="search"]:focus { border-color: var(--accent); }
  aside.left, aside.right {
    background: var(--panel);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 12px;
  }
  aside.right { border-right: 0; border-left: 1px solid var(--border); grid-area: right; }
  aside.left { grid-area: left; }
  main { grid-area: main; position: relative; overflow: hidden; }
  .panel-title {
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin: 14px 0 6px;
  }
  .panel-title:first-child { margin-top: 0; }
  .filter-list { display: flex; flex-direction: column; gap: 4px; }
  .filter-row {
    display: flex; align-items: center; gap: 8px;
    padding: 4px 6px;
    border-radius: 4px;
    cursor: pointer;
    user-select: none;
  }
  .filter-row:hover { background: var(--panel-2); }
  .filter-row .swatch {
    width: 10px; height: 10px; border-radius: 50%;
    border: 1px solid rgba(255,255,255,0.15);
    flex-shrink: 0;
  }
  .filter-row .count { color: var(--muted); margin-left: auto; font-size: 11px; }
  .filter-row.disabled { opacity: 0.4; }
  .toolbar { display: flex; gap: 6px; flex-wrap: wrap; }
  .toolbar button {
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 5px 10px;
    cursor: pointer;
    font-size: 12px;
  }
  .toolbar button:hover { border-color: var(--accent); }
  svg { width: 100%; height: 100%; display: block; cursor: grab; }
  svg:active { cursor: grabbing; }
  .node circle { stroke: rgba(255,255,255,0.5); stroke-width: 1.2; }
  .node text {
    fill: var(--text);
    font-size: 10px;
    pointer-events: none;
    text-shadow: 0 0 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.9);
  }
  .node.dimmed { opacity: 0.08; }
  .node.match circle { stroke: #fff; stroke-width: 2.5; }
  .link {
    stroke: #4d5566;
    stroke-opacity: 0.55;
  }
  .link.confidence-INFERRED { stroke-dasharray: 4 3; }
  .link.confidence-AMBIGUOUS { stroke-dasharray: 1 3; }
  .link.dimmed { stroke-opacity: 0.05; }
  .tooltip {
    position: absolute;
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 8px;
    font-size: 12px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.1s;
    max-width: 320px;
    z-index: 10;
  }
  .detail-empty { color: var(--muted); font-style: italic; padding: 8px 0; }
  .detail-row { margin: 6px 0; }
  .detail-row .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .detail-row .v { color: var(--text); word-break: break-word; }
  .detail-row .v code { background: var(--panel-2); padding: 2px 4px; border-radius: 3px; font-size: 12px; }
  .detail-row a { color: var(--accent); text-decoration: none; }
  .detail-row a:hover { text-decoration: underline; }
  .neighbors li { list-style: none; padding: 3px 0; border-bottom: 1px solid var(--border); }
  .neighbors li .rel { color: var(--muted); font-size: 11px; margin-right: 6px; }
  .legend-line { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 11px; color: var(--muted); }
  .legend-line .line {
    display: inline-block;
    width: 28px; height: 0;
    border-top: 1.5px solid #4d5566;
  }
  .legend-line .line.INFERRED { border-top-style: dashed; }
  .legend-line .line.AMBIGUOUS { border-top-style: dotted; }
</style>
</head>
<body>
<header>
  <h1>GraphFocus</h1>
  <span class="stats" id="stats"></span>
  <span class="spacer"></span>
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

  <div class="panel-title">Edge legend</div>
  <div class="legend-line"><span class="line"></span> EXTRACTED</div>
  <div class="legend-line"><span class="line INFERRED"></span> INFERRED</div>
  <div class="legend-line"><span class="line AMBIGUOUS"></span> AMBIGUOUS</div>

  <div class="panel-title">View</div>
  <div class="toolbar">
    <button id="fit">Fit</button>
    <button id="reheat">Reheat</button>
    <button id="freeze">Toggle pin</button>
  </div>
</aside>

<main>
  <svg id="graph"></svg>
  <div class="tooltip" id="tooltip"></div>
</main>

<aside class="right">
  <div class="panel-title">Selection</div>
  <div id="detail" class="detail-empty">Click a node to inspect.</div>
</aside>

<script src="https://d3js.org/d3.v7.min.js"></script>
<script id="graph-data" type="application/json">__GRAPHFOCUS_DATA__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("graph-data").textContent);

  // Build mutable arrays — d3 force mutates objects in place.
  const nodesById = new Map();
  const nodes = DATA.nodes.map(n => {
    const copy = Object.assign({}, n);
    nodesById.set(n.id, copy);
    return copy;
  });
  const links = DATA.edges
    .filter(e => nodesById.has(e.source) && nodesById.has(e.target))
    .map(e => ({
      source: e.source,
      target: e.target,
      relation: e.relation,
      confidence: e.confidence,
    }));

  document.getElementById("stats").innerHTML =
    `<b>${nodes.length}</b> nodes · <b>${links.length}</b> edges · ` +
    `<b>${DATA.languages.length}</b> languages`;

  // ── Filter UI ───────────────────────────────────────────────────────────
  const enabled = {
    language: new Set(DATA.languages),
    kind: new Set(DATA.kinds),
    confidence: new Set(DATA.confidences),
  };

  function buildFilterUI(containerId, key, items, colorFn) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";
    const counts = {};
    if (key === "language" || key === "kind") {
      for (const n of nodes) counts[n[key]] = (counts[n[key]] || 0) + 1;
    } else if (key === "confidence") {
      for (const l of links) counts[l.confidence] = (counts[l.confidence] || 0) + 1;
    }
    for (const item of items) {
      const row = document.createElement("label");
      row.className = "filter-row";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.addEventListener("change", () => {
        if (cb.checked) enabled[key].add(item);
        else enabled[key].delete(item);
        updateVisibility();
      });
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = colorFn(item);
      const label = document.createElement("span");
      label.textContent = item;
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = counts[item] || 0;
      row.appendChild(cb);
      row.appendChild(swatch);
      row.appendChild(label);
      row.appendChild(count);
      container.appendChild(row);
    }
  }

  buildFilterUI("filter-languages", "language", DATA.languages,
    l => DATA.language_colors[l] || "#888");
  buildFilterUI("filter-kinds", "kind", DATA.kinds, () => "#666");
  buildFilterUI("filter-confidence", "confidence", DATA.confidences, () => "#666");

  // ── SVG setup ───────────────────────────────────────────────────────────
  const svg = d3.select("#graph");
  const tooltip = d3.select("#tooltip");
  const root = svg.append("g");
  const linkLayer = root.append("g").attr("class", "links");
  const nodeLayer = root.append("g").attr("class", "nodes");

  const zoom = d3.zoom().scaleExtent([0.1, 8]).on("zoom", evt => {
    root.attr("transform", evt.transform);
  });
  svg.call(zoom);

  const radius = d => Math.max(4, Math.min(14, 4 + Math.sqrt(d.degree || 0) * 1.4));

  const linkSel = linkLayer.selectAll("line").data(links).join("line")
    .attr("class", d => `link confidence-${d.confidence}`)
    .attr("stroke-width", 1);

  const nodeSel = nodeLayer.selectAll("g.node").data(nodes, d => d.id).join("g")
    .attr("class", "node")
    .call(d3.drag()
      .on("start", dragStart)
      .on("drag", dragged)
      .on("end", dragEnd));

  nodeSel.append("circle")
    .attr("r", radius)
    .attr("fill", d => d.color);

  nodeSel.append("title").text(d => `${d.label} (${d.kind})`);

  nodeSel.append("text")
    .attr("dx", d => radius(d) + 3)
    .attr("dy", "0.32em")
    .text(d => d.label.length > 22 ? d.label.slice(0, 21) + "…" : d.label);

  nodeSel.on("mouseover", (evt, d) => {
    tooltip.html(
      `<b>${escapeHtml(d.label)}</b><br>` +
      `<small>${escapeHtml(d.kind)} · ${escapeHtml(d.language)}</small>` +
      (d.source_file ? `<br><small>${escapeHtml(shorten(d.source_file))}${d.source_location ? ":" + escapeHtml(d.source_location) : ""}</small>` : "")
    );
    tooltip.style("opacity", 1);
  })
  .on("mousemove", evt => {
    tooltip.style("left", (evt.clientX + 12) + "px").style("top", (evt.clientY + 12) + "px");
  })
  .on("mouseout", () => tooltip.style("opacity", 0))
  .on("click", (evt, d) => selectNode(d));

  // ── Force simulation ────────────────────────────────────────────────────
  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(60).strength(0.6))
    .force("charge", d3.forceManyBody().strength(-180))
    .force("center", d3.forceCenter(0, 0))
    .force("collide", d3.forceCollide(d => radius(d) + 3))
    .on("tick", ticked);

  function ticked() {
    linkSel
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeSel.attr("transform", d => `translate(${d.x},${d.y})`);
  }

  function dragStart(evt, d) {
    if (!evt.active) sim.alphaTarget(0.3).restart();
    d.fx = d.x; d.fy = d.y;
  }
  function dragged(evt, d) { d.fx = evt.x; d.fy = evt.y; }
  function dragEnd(evt, d) {
    if (!evt.active) sim.alphaTarget(0);
    if (!pinning) { d.fx = null; d.fy = null; }
  }

  // ── Visibility / filters ────────────────────────────────────────────────
  function nodeVisible(n) {
    return enabled.language.has(n.language) && enabled.kind.has(n.kind);
  }
  function linkVisible(l) {
    return enabled.confidence.has(l.confidence) &&
           nodeVisible(typeof l.source === "object" ? l.source : nodesById.get(l.source)) &&
           nodeVisible(typeof l.target === "object" ? l.target : nodesById.get(l.target));
  }
  function updateVisibility() {
    nodeSel.style("display", d => nodeVisible(d) ? null : "none");
    linkSel.style("display", d => linkVisible(d) ? null : "none");
  }

  // ── Search ──────────────────────────────────────────────────────────────
  const searchInput = document.getElementById("search");
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    if (!q) {
      nodeSel.classed("dimmed", false).classed("match", false);
      linkSel.classed("dimmed", false);
      return;
    }
    const matches = new Set();
    nodes.forEach(n => {
      if (n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)) matches.add(n.id);
    });
    nodeSel.classed("match", d => matches.has(d.id))
           .classed("dimmed", d => !matches.has(d.id));
    linkSel.classed("dimmed", d => {
      const s = typeof d.source === "object" ? d.source.id : d.source;
      const t = typeof d.target === "object" ? d.target.id : d.target;
      return !(matches.has(s) || matches.has(t));
    });
  });

  // ── Selection / details panel ───────────────────────────────────────────
  function selectNode(d) {
    const detail = document.getElementById("detail");
    const neighbors = links.filter(l => {
      const s = typeof l.source === "object" ? l.source.id : l.source;
      const t = typeof l.target === "object" ? l.target.id : l.target;
      return s === d.id || t === d.id;
    });
    const fileLink = d.source_file
      ? `<a href="vscode://file/${encodeURI(d.source_file)}${d.source_location ? ':' + d.source_location.replace(/^L/, '') : ''}" target="_blank">${escapeHtml(shorten(d.source_file))}${d.source_location ? ":" + escapeHtml(d.source_location) : ""}</a>`
      : "<i>—</i>";
    detail.classList.remove("detail-empty");
    detail.innerHTML = `
      <div class="detail-row"><div class="k">Label</div><div class="v"><b>${escapeHtml(d.label)}</b></div></div>
      <div class="detail-row"><div class="k">ID</div><div class="v"><code>${escapeHtml(d.id)}</code></div></div>
      <div class="detail-row"><div class="k">Kind</div><div class="v">${escapeHtml(d.kind)}</div></div>
      <div class="detail-row"><div class="k">Language</div><div class="v">${escapeHtml(d.language)}</div></div>
      <div class="detail-row"><div class="k">Source</div><div class="v">${fileLink}</div></div>
      <div class="detail-row"><div class="k">Degree</div><div class="v">${d.degree}</div></div>
      <div class="detail-row"><div class="k">Neighbors (${neighbors.length})</div></div>
      <ul class="neighbors">
        ${neighbors.slice(0, 30).map(l => {
          const s = typeof l.source === "object" ? l.source : nodesById.get(l.source);
          const t = typeof l.target === "object" ? l.target : nodesById.get(l.target);
          const other = s.id === d.id ? t : s;
          const arrow = s.id === d.id ? "→" : "←";
          return `<li><span class="rel">${escapeHtml(l.relation)} ${arrow}</span> ${escapeHtml(other.label)}</li>`;
        }).join("")}
      </ul>
    `;
  }

  // ── Toolbar ─────────────────────────────────────────────────────────────
  let pinning = false;
  document.getElementById("fit").addEventListener("click", fit);
  document.getElementById("reheat").addEventListener("click", () => sim.alpha(1).restart());
  document.getElementById("freeze").addEventListener("click", () => {
    pinning = !pinning;
    if (!pinning) {
      nodes.forEach(n => { n.fx = null; n.fy = null; });
      sim.alpha(0.3).restart();
    } else {
      nodes.forEach(n => { n.fx = n.x; n.fy = n.y; });
    }
  });

  function fit() {
    const visibleNodes = nodes.filter(nodeVisible);
    if (!visibleNodes.length) return;
    const xs = visibleNodes.map(n => n.x), ys = visibleNodes.map(n => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const width = svg.node().clientWidth, height = svg.node().clientHeight;
    const dx = maxX - minX || 1, dy = maxY - minY || 1;
    const scale = 0.9 / Math.max(dx / width, dy / height);
    const tx = width / 2 - (minX + maxX) / 2 * scale;
    const ty = height / 2 - (minY + maxY) / 2 * scale;
    svg.transition().duration(500).call(
      zoom.transform,
      d3.zoomIdentity.translate(tx, ty).scale(Math.min(scale, 3))
    );
  }
  // First fit once the layout settles.
  setTimeout(fit, 1500);

  // ── Helpers ─────────────────────────────────────────────────────────────
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function shorten(path) {
    const parts = String(path).split("/");
    return parts.length > 4 ? ".../" + parts.slice(-3).join("/") : path;
  }
})();
</script>
</body>
</html>
"""
