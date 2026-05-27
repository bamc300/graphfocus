"""Analyze endpoint — trigger code analysis."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from graphfocus.config import GraphFocusConfig
from graphfocus.detect.detector import detect_files
from graphfocus.extractors.registry import ExtractorRegistry

router = APIRouter()


class AnalyzeRequest(BaseModel):
    path: str
    mode: str = "normal"
    skip_semantic: bool = False


class AnalyzeResponse(BaseModel):
    total_files: int
    total_nodes: int
    total_edges: int
    by_language: dict[str, int]
    output_dir: str


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """Analyze a directory and build a knowledge graph."""
    input_path = Path(request.path).resolve()

    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {request.path}")

    if not input_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    config = GraphFocusConfig(
        input_path=input_path,
        mode=request.mode,
        skip_semantic=request.skip_semantic,
    )

    # Detect files
    detection = detect_files(config.input_path)
    if detection["total_files"] == 0:
        raise HTTPException(status_code=404, detail="No supported files found")

    # Extract
    registry = ExtractorRegistry()
    all_nodes = []
    all_edges = []

    for file_info in detection["files"]:
        file_path = Path(file_info["path"])
        extractor = registry.get_extractor(file_path.suffix)
        if extractor:
            result = extractor.extract(file_path)
            all_nodes.extend(result.nodes)
            all_edges.extend(result.edges)

    # Save output
    config.output_dir.mkdir(parents=True, exist_ok=True)

    from graphfocus.output.json_export import export_json

    export_json(all_nodes, all_edges, config.output_dir / "graph.json")

    return AnalyzeResponse(
        total_files=detection["total_files"],
        total_nodes=len(all_nodes),
        total_edges=len(all_edges),
        by_language=detection.get("by_language", {}),
        output_dir=str(config.output_dir),
    )
