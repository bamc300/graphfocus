"""Health check endpoint."""

from fastapi import APIRouter

from graphfocus import __version__
from graphfocus.extractors.registry import ExtractorRegistry

router = APIRouter()


@router.get("/health")
async def health():
    registry = ExtractorRegistry()
    return {
        "status": "ok",
        "version": __version__,
        "languages": [lang["name"] for lang in registry.list_languages()],
    }
