"""HTTP API and static frontend for the CloudyAI Model Hub.

Routes under ``/api`` are declared before the static mount at ``/``. This order matters on Vercel,
where the static files are served by the CDN and the API by the Python function.

Interactive API docs live at ``/api/docs`` and the OpenAPI document at ``/api/openapi.json``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .aibom import build_aibom
from .capacity import BYTES_PER_ELEMENT, DTYPE_LABELS, build_requirements_report
from .hf_client import HubError, ModelBundle, fetch_bundle, normalize_model_id, search_models
from .report import render_report_pdf, report_filename
from .settings import get_settings

log = logging.getLogger("cloudyai.api")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

#: Headers for HTML pages. API responses are JSON or PDF and are never rendered by a browser.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}

Dtype = Literal[
    "fp32",
    "fp16",
    "bf16",
    "int8",
    "int4",
    "gptq_4bit",
    "awq_4bit",
    "gguf_q8_0",
    "gguf_q4_k_m",
    "gguf_q2_k",
]

ModelQuery = Annotated[
    str,
    Query(
        max_length=200,
        description="Model id (org/name) or a huggingface.co model link.",
        examples=["Qwen/Qwen2.5-7B-Instruct"],
    ),
]

TAGS_METADATA = [
    {"name": "AIBOM", "description": "CycloneDX 1.6 ML-BOM (JSON) and PDF report for a Hugging Face model."},
    {"name": "Capacity", "description": "Memory, hardware-fit and complexity estimates for serving a model."},
    {"name": "Discovery", "description": "Search Hugging Face models."},
    {"name": "Service", "description": "Health and reference data."},
]

app = FastAPI(
    title="CloudyAI Model Hub API",
    version=__version__,
    summary="Generate AI Bills of Materials (AIBOMs) and capacity estimates for Hugging Face models.",
    description=(
        "Read-only API. Each request fetches public metadata from the Hugging Face Hub, and nothing is "
        "stored. "
        "Responses are cached in memory per warm instance, for up to 10 minutes by default.\n\n"
        "Model ids look like `org/name`. Links such as `https://huggingface.co/org/name` are accepted too."
    ),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    openapi_tags=TAGS_METADATA,
    license_info={"name": "Apache-2.0", "identifier": "Apache-2.0"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Response:
    """Add page security headers. Only non-API paths get them (see vercel.json for the CDN)."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
    return response


class HealthResponse(BaseModel):
    status: str
    version: str


class DtypeOption(BaseModel):
    id: str
    label: str
    bytes_per_element: float


class SearchHit(BaseModel):
    id: str
    author: str | None = None
    likes: int = 0
    downloads: int = 0
    pipeline_tag: str | None = None
    library_name: str | None = None
    tags: list[str] = []
    created_at: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]


class AibomResponse(BaseModel):
    model_id: str
    aibom: dict[str, Any]
    completeness: dict[str, Any]


def _search_hit(item: dict[str, Any]) -> dict[str, Any]:
    model_id = item.get("id") or item.get("modelId") or ""
    return {
        "id": model_id,
        "author": model_id.split("/")[0] if "/" in model_id else None,
        "likes": int(item.get("likes") or 0),
        "downloads": int(item.get("downloads") or 0),
        "pipeline_tag": item.get("pipeline_tag"),
        "library_name": item.get("library_name"),
        "tags": [tag for tag in (item.get("tags") or []) if isinstance(tag, str)][:12],
        "created_at": item.get("createdAt"),
    }


async def _load_model(model: str, *, include_files: bool = True) -> tuple[str, ModelBundle]:
    """Validate the id, fetch the Hub data, and turn failures into HTTP errors."""
    try:
        model_id = normalize_model_id(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        bundle = await fetch_bundle(model_id, get_settings().hf_token, include_files=include_files)
    except HubError as exc:
        log.info("Hub lookup failed for %s (%s)", model_id, exc.__class__.__name__)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return model_id, bundle


def _build(model_id: str, bundle: ModelBundle) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_aibom(model_id, bundle.info, bundle.readme, bundle.effective_config, bundle.files)


@app.get("/api/health", response_model=HealthResponse, tags=["Service"], summary="Liveness check")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/dtypes", response_model=list[DtypeOption], tags=["Service"], summary="Weight precisions")
async def dtypes() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": DTYPE_LABELS[key], "bytes_per_element": value}
        for key, value in BYTES_PER_ELEMENT.items()
    ]


@app.get("/api/models/search", response_model=SearchResponse, tags=["Discovery"], summary="Search models")
async def search(
    q: Annotated[str, Query(min_length=2, max_length=100, description="Text to search for.")],
    limit: Annotated[int, Query(ge=1, le=50, description="Maximum number of results (1 to 50).")] = 8,
) -> dict[str, Any]:
    query = q.strip()
    try:
        items = await search_models(query, limit, get_settings().hf_token)
    except HubError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"query": query, "results": [_search_hit(item) for item in items]}


@app.get(
    "/api/aibom/generate",
    response_model=AibomResponse,
    tags=["AIBOM"],
    summary="Generate an AIBOM (CycloneDX 1.6 JSON)",
)
async def generate_aibom(model: ModelQuery) -> dict[str, Any]:
    model_id, bundle = await _load_model(model)
    bom, completeness = _build(model_id, bundle)
    return {"model_id": model_id, "aibom": bom, "completeness": completeness}


@app.get(
    "/api/aibom/report.pdf",
    tags=["AIBOM"],
    summary="Download the AIBOM as a PDF report",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF report. The CycloneDX JSON is attached as aibom.cdx.json.",
        }
    },
)
async def aibom_report(model: ModelQuery) -> Response:
    model_id, bundle = await _load_model(model)
    bom, completeness = _build(model_id, bundle)
    pdf = render_report_pdf(bom, completeness)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{report_filename(model_id)}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/requirements", tags=["Capacity"], summary="Estimate memory, hardware fit and complexity")
async def requirements(
    model: ModelQuery,
    dtype: Annotated[Dtype, Query(description="Weight precision used for the estimate.")] = "fp16",
    context_length: Annotated[
        int, Query(ge=128, le=262144, description="Tokens of context per request.")
    ] = 4096,
    batch_size: Annotated[int, Query(ge=1, le=256, description="Concurrent sequences.")] = 1,
) -> dict[str, Any]:
    model_id, bundle = await _load_model(model, include_files=False)
    try:
        report = build_requirements_report(
            bundle.info,
            bundle.effective_config,
            dtype=dtype,
            context_length=context_length,
            batch_size=batch_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    alternatives: list[dict[str, Any]] = []
    family = str(bundle.effective_config.get("model_type") or "")
    if family:
        try:
            related = await search_models(family, 6, get_settings().hf_token)
        except HubError:
            related = []
        alternatives = [
            _search_hit(item) for item in related if item.get("id") and item.get("id") != model_id
        ][:5]

    return {"model_id": model_id, **report, "alternatives": alternatives}


if FRONTEND_DIR.is_dir():
    # Mounted last so that /api routes take precedence. cdn = true in pyproject.toml lets Vercel
    # serve these files from its CDN; locally, FastAPI serves them directly.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
