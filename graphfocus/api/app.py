"""FastAPI application for GraphFocus.

Start with: uvicorn graphfocus.api.app:app --reload
Or via CLI: graphfocus serve
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from graphfocus import __version__

app = FastAPI(
    title="GraphFocus API",
    description="Multi-language code knowledge graph generator",
    version=__version__,
)

# CORS — allow all origins in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
from graphfocus.api.routes import analyze, graph, health  # noqa: E402

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(analyze.router, prefix="/api", tags=["analyze"])
app.include_router(graph.router, prefix="/api", tags=["graph"])


@app.get("/")
async def root():
    return {
        "name": "GraphFocus API",
        "version": __version__,
        "docs": "/docs",
    }
