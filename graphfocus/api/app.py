"""FastAPI application for GraphFocus.

Start with: uvicorn graphfocus.api.app:app --reload
Or via CLI: graphfocus serve

Authentication:

  * If ``GRAPHFOCUS_API_TOKEN`` is set in the environment, every request
    to ``/api/*`` must carry a matching ``Authorization: Bearer …``
    header. The ``/`` root and ``/docs`` stay open so the OpenAPI page
    still loads.
  * If the env var is unset, the server runs unauthenticated — the
    behaviour the project had before v0.3.0, so nothing breaks for
    existing users.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from graphfocus import __version__

app = FastAPI(
    title="GraphFocus API",
    description="Multi-language code knowledge graph generator",
    version=__version__,
)

# CORS — allow all origins in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _expected_token() -> str | None:
    """Read the auth token from the environment at request time so the
    value can be rotated without restarting the server."""
    token = os.environ.get("GRAPHFOCUS_API_TOKEN")
    return token.strip() if token else None


async def require_bearer(request: Request) -> None:
    """FastAPI dependency that enforces ``Authorization: Bearer <token>``
    when ``GRAPHFOCUS_API_TOKEN`` is set."""
    expected = _expected_token()
    if not expected:
        return  # unauthenticated mode (legacy default)
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = header.split(" ", 1)[1].strip()
    if presented != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )


# Register routes — every /api/* router enforces the auth dependency.
from graphfocus.api.routes import analyze, graph, health  # noqa: E402

app.include_router(
    health.router, prefix="/api", tags=["health"],
    dependencies=[Depends(require_bearer)],
)
app.include_router(
    analyze.router, prefix="/api", tags=["analyze"],
    dependencies=[Depends(require_bearer)],
)
app.include_router(
    graph.router, prefix="/api", tags=["graph"],
    dependencies=[Depends(require_bearer)],
)


@app.get("/")
async def root():
    return {
        "name": "GraphFocus API",
        "version": __version__,
        "docs": "/docs",
        "auth_required": _expected_token() is not None,
    }
