"""
CloudyAI Model Hub — backend.

Serves the JSON API under /api/* and the static frontend (frontend/) at /.

Run from the project root:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import hf_client
from .aibom import build_aibom
from .capacity import (
    BYTES_PER_ELEMENT,
    DTYPE_LABELS,
    estimate_memory,
    estimate_to_dict,
    recommend_hardware,
    score_operational_complexity,
)

app = FastAPI(title="CloudyAI Model Hub", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HF_TOKEN = os.environ.get("HF_TOKEN")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/dtypes")
async def dtypes():
    return [{"id": k, "label": v} for k, v in DTYPE_LABELS.items()]


@app.get("/api/models/search")
async def search(q: str = Query(..., min_length=1), limit: int = 20):
    try:
        results = await hf_client.search_models(q, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hugging Face search failed: {exc}")
    return [
        {
            "id": m.get("id"),
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "pipeline_tag": m.get("pipeline_tag"),
            "library_name": m.get("library_name"),
            "gated": bool(m.get("gated")),
        }
        for m in results
    ]


async def _load_model(model: str):
    model_id = hf_client.normalize_model_id(model)
    try:
        info = await hf_client.fetch_model_info(model_id, HF_TOKEN)
    except hf_client.HFNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except hf_client.HFGatedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't reach Hugging Face: {exc}")
    readme = await hf_client.fetch_readme(model_id, HF_TOKEN)
    config = info.get("config")
    return model_id, info, readme, config


@app.get("/api/aibom/generate")
async def generate_aibom(model: str = Query(...)):
    model_id, info, readme, config = await _load_model(model)
    bom, completeness = build_aibom(model_id, info, readme, config)
    return {"aibom": bom, "completeness": completeness}


def _config_has_transformer_signal(config: dict) -> bool:
    return bool(config) and any(
        k in config for k in ("hidden_size", "n_embd", "d_model", "num_hidden_layers", "n_layer")
    )


def _estimate_params_from_config(config: dict) -> float:
    """Rough parameter count for a standard decoder-only transformer.
    Assumes SwiGLU-style MLP (gate/up/down); will over/under-shoot for
    encoder-decoder, MoE, or otherwise non-standard architectures.
    """
    hidden = config.get("hidden_size") or config.get("d_model") or config.get("n_embd")
    layers = config.get("num_hidden_layers") or config.get("n_layer")
    inter = config.get("intermediate_size") or (hidden * 4 if hidden else None)
    vocab = config.get("vocab_size") or 32000
    attn_params = 4 * hidden * hidden
    mlp_params = 3 * hidden * inter
    embedding_params = vocab * hidden
    return layers * (attn_params + mlp_params) + embedding_params


@app.get("/api/requirements")
async def requirements(
    model: str = Query(...),
    dtype: str = Query("fp16"),
    context_length: int = Query(4096, ge=256, le=131072),
    batch_size: int = Query(1, ge=1, le=256),
):
    if dtype not in BYTES_PER_ELEMENT:
        raise HTTPException(status_code=400, detail=f"Unknown dtype '{dtype}'. Options: {list(BYTES_PER_ELEMENT)}")

    model_id, info, readme, config = await _load_model(model)
    config = config or {}
    safetensors = info.get("safetensors") or {}
    param_count = safetensors.get("total")
    param_is_estimate = not bool(param_count)

    if not param_count:
        if _config_has_transformer_signal(config):
            param_count = _estimate_params_from_config(config)
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Not enough metadata to estimate parameters for this model — "
                    "no safetensors info, and config.json doesn't look like a standard transformer."
                ),
            )

    estimate = estimate_memory(
        param_count=param_count,
        dtype=dtype,
        num_layers=config.get("num_hidden_layers"),
        hidden_size=config.get("hidden_size"),
        num_attention_heads=config.get("num_attention_heads"),
        num_key_value_heads=config.get("num_key_value_heads"),
        context_length=context_length,
        batch_size=batch_size,
    )
    recommendations = recommend_hardware(estimate.weights_gb, estimate.total_gb)
    complexity = score_operational_complexity(info, config, estimate.total_gb)

    alternatives = []
    try:
        base_query = re.split(r"[-_]", model_id.split("/")[-1])[0]
        candidates = await hf_client.search_models(base_query, limit=6)
        alternatives = [
            {"id": c.get("id"), "downloads": c.get("downloads", 0), "pipeline_tag": c.get("pipeline_tag")}
            for c in candidates
            if c.get("id") != model_id
        ][:4]
    except Exception:
        alternatives = []

    return {
        "model_id": model_id,
        "param_count": param_count,
        "param_count_is_estimate": param_is_estimate,
        "estimate": estimate_to_dict(estimate),
        "recommendations": recommendations,
        "complexity": complexity,
        "alternatives": alternatives,
    }


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
