"""A stand-in for the Hugging Face Hub, backed by the JSON and Markdown files in ``tests/fixtures``.

It implements the subset of the public API that the app uses:

* ``GET /api/models/{id}``                 model metadata (404 for unknown ids)
* ``GET /api/models/{id}/tree/main``       file tree (404 when the fixture has none)
* ``GET /api/models``                      search by substring, most downloaded first
* ``GET /{org}/{name}/raw/main/{path}``    README.md and config.json (404 when absent)

Tests use it in-process through ``httpx.ASGITransport``. ``scripts/mock_hub.py`` serves the same
app over HTTP so the frontend can be developed offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, PlainTextResponse

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture_models(fixtures_dir: Path = FIXTURES_DIR) -> dict[str, dict[str, Any]]:
    """Map each model id to its fixture directory, using the ``id`` field of ``info.json``."""
    models: dict[str, dict[str, Any]] = {}
    for info_path in sorted(fixtures_dir.glob("*/info.json")):
        info = json.loads(info_path.read_text(encoding="utf-8"))
        models[info["id"]] = {"dir": info_path.parent, "info": info}
    return models


def _summary(info: dict[str, Any]) -> dict[str, Any]:
    """Shape of an item in ``GET /api/models`` (search results omit most card fields)."""
    return {
        "_id": info.get("_id", info["id"]),
        "id": info["id"],
        "modelId": info["id"],
        "likes": info.get("likes", 0),
        "downloads": info.get("downloads", 0),
        "private": False,
        "tags": info.get("tags", []),
        "pipeline_tag": info.get("pipeline_tag"),
        "library_name": info.get("library_name"),
        "createdAt": info.get("createdAt"),
    }


def create_fake_hub(
    fixtures_dir: Path = FIXTURES_DIR,
    *,
    info_status: dict[str, int] | None = None,
    raw_status: dict[str, int] | None = None,
) -> FastAPI:
    """Build the fake Hub app.

    Args:
        fixtures_dir: directory containing one sub-directory per model.
        info_status: model id -> HTTP status to return from the model-info endpoint (fault injection).
        raw_status: ``"org/name/path"`` -> HTTP status to return from raw file requests (fault injection).
    """
    models = load_fixture_models(fixtures_dir)
    info_status = info_status or {}
    raw_status = raw_status or {}
    app = FastAPI(title="fake-hub", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/models/{org}/{name}/tree/main")
    def tree(org: str, name: str) -> Any:
        model_id = f"{org}/{name}"
        entry = models.get(model_id)
        tree_path = entry["dir"] / "tree.json" if entry else None
        if not tree_path or not tree_path.exists():
            return JSONResponse({"error": "Not Found"}, status_code=404)
        return JSONResponse(json.loads(tree_path.read_text(encoding="utf-8")))

    @app.get("/api/models/{org}/{name}")
    def model_info(org: str, name: str) -> Any:
        model_id = f"{org}/{name}"
        if model_id in info_status:
            return JSONResponse({"error": "injected"}, status_code=info_status[model_id])
        entry = models.get(model_id)
        if entry is None:
            return JSONResponse({"error": "Repository not found"}, status_code=404)
        return JSONResponse(entry["info"])

    @app.get("/api/models")
    def search(
        search: str = Query(""),
        limit: int = Query(20, ge=1, le=100),
        sort: str = Query("downloads"),
        direction: int = Query(-1),
    ) -> Any:
        needle = search.lower()
        matches = [
            _summary(entry["info"])
            for entry in models.values()
            if not needle or needle in entry["info"]["id"].lower()
        ]
        matches.sort(key=lambda item: item.get("downloads", 0), reverse=direction < 0)
        return JSONResponse(matches[:limit])

    @app.get("/{org}/{name}/raw/main/{path:path}")
    def raw(org: str, name: str, path: str) -> Any:
        model_id = f"{org}/{name}"
        key = f"{model_id}/{path}"
        if key in raw_status:
            return PlainTextResponse("injected", status_code=raw_status[key])
        entry = models.get(model_id)
        if entry is None or path not in {"README.md", "config.json"}:
            return PlainTextResponse("Not Found", status_code=404)
        file_path = entry["dir"] / path
        if not file_path.exists():
            return PlainTextResponse("Not Found", status_code=404)
        return PlainTextResponse(file_path.read_text(encoding="utf-8"))

    return app
