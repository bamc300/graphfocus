"""Bundled third-party JS libraries shipped with each release.

We ship sigma.min.js and graphology.umd.min.js so the generated
``graph.html`` works completely offline — no CDN, no internet, and no
browser content-blocker can prevent it from loading.

The files are copied next to ``graph.html`` by ``html_viz.generate_html``.
"""
