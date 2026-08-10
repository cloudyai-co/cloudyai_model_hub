"""
Thin client around the public Hugging Face Hub HTTP API.

No API token is required for public models. Gated/private models will
403/404 without one — set the HF_TOKEN environment variable to supply one
(see README.md).
"""

from __future__ import annotations

import re
import httpx

HF_BASE = "https://huggingface.co"
HF_API = f"{HF_BASE}/api"

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$|^[A-Za-z0-9][\w.-]*$")

# Extra fields the default /api/models/{id} response doesn't always include.
EXPAND_FIELDS = [
    "safetensors",
    "config",
    "cardData",
    "downloadsAllTime",
    "lastModified",
    "createdAt",
    "gated",
    "library_name",
    "pipeline_tag",
    "tags",
    "model-index",
    "author",
    "siblings",
]


class HFNotFoundError(Exception):
    """No such model on the Hub."""


class HFGatedError(Exception):
    """Model exists but requires authentication/approval."""


def normalize_model_id(raw: str) -> str:
    """Accept 'org/name', a bare 'name', or a full HF URL and return 'org/name'."""
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = raw.split("://", 1)[1]
        segments = [p for p in raw.split("/") if p]
        segments = segments[1:]  # drop the "huggingface.co" host segment
        if len(segments) >= 2:
            raw = f"{segments[0]}/{segments[1]}"
        elif len(segments) == 1:
            raw = segments[0]
        else:
            raise ValueError("That URL doesn't point at a model.")
    raw = raw.strip("/")
    if not raw or not MODEL_ID_RE.match(raw):
        raise ValueError(
            f"'{raw}' doesn't look like a valid model id. "
            "Expected format: organization-or-username/model-name"
        )
    return raw


def _auth_headers(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


async def fetch_model_info(model_id: str, token: str | None = None) -> dict:
    params = [("expand[]", field) for field in EXPAND_FIELDS]
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{HF_API}/models/{model_id}", headers=_auth_headers(token), params=params
        )
    if resp.status_code == 404:
        raise HFNotFoundError(f"No model found for '{model_id}'.")
    if resp.status_code in (401, 403):
        raise HFGatedError(
            f"'{model_id}' is gated or private — set HF_TOKEN with an approved account's token."
        )
    resp.raise_for_status()
    return resp.json()


async def fetch_readme(model_id: str, token: str | None = None) -> str | None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{HF_BASE}/{model_id}/raw/main/README.md", headers=_auth_headers(token)
        )
    return resp.text if resp.status_code == 200 else None


async def search_models(query: str, limit: int = 20) -> list[dict]:
    params = {"search": query, "limit": limit, "sort": "downloads", "direction": -1}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{HF_API}/models", params=params)
    resp.raise_for_status()
    return resp.json()
