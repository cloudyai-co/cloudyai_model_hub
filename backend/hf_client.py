"""Client for the public Hugging Face Hub HTTP API.

Only public, read-only endpoints are used. Every request is made server-side,
so browsers never talk to Hugging Face directly and no credentials reach the
client. The optional ``HF_TOKEN`` is only needed for gated or private repositories.

Endpoints used (all relative to ``HF_ENDPOINT``, default https://huggingface.co):

* ``GET /api/models/{id}``                  model metadata, card data, tags, safetensors info
* ``GET /{id}/raw/main/README.md``          model card (optional)
* ``GET /{id}/raw/main/config.json``        architecture config (optional)
* ``GET /api/models/{id}/tree/main``        file listing with sizes and LFS SHA-256 (optional)
* ``GET /api/models?search=...``            model search for the model-selection view
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__
from .cache import TTLCache
from .settings import get_settings

log = logging.getLogger(__name__)

MAX_MODEL_ID_LENGTH = 140
MAX_README_CHARS = 500_000
MAX_CONFIG_BYTES = 1_000_000
MAX_TREE_PAGES = 10

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_HOST_PREFIX_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:huggingface\.co|hf\.co)(?:/|$)", re.IGNORECASE)
_HOSTS = {"huggingface.co", "www.huggingface.co", "hf.co", "www.hf.co"}

_cache: TTLCache = TTLCache(
    ttl_seconds=get_settings().cache_ttl_seconds, max_entries=get_settings().cache_max_entries
)

#: Test hook. Tests inject an ``httpx.MockTransport`` here instead of hitting the network.
_TRANSPORT: httpx.AsyncBaseTransport | None = None


class HubError(Exception):
    """Base class for failures that should be shown to the user."""

    status_code = 502


class HubNotFoundError(HubError):
    status_code = 404


class HubGatedError(HubError):
    status_code = 403


class HubRateLimitError(HubError):
    status_code = 429


class HubUnavailableError(HubError):
    status_code = 502


@dataclass
class ModelBundle:
    """Everything the AIBOM builder needs for one model. Optional parts may be ``None``."""

    model_id: str
    info: dict[str, Any]
    readme: str | None = None
    config: dict[str, Any] | None = None
    files: list[dict[str, Any]] | None = None

    @property
    def effective_config(self) -> dict[str, Any]:
        """``config.json`` when available, otherwise the small ``config`` block returned by the API."""
        if self.config:
            return self.config
        embedded = self.info.get("config")
        return embedded if isinstance(embedded, dict) else {}


def clear_cache() -> None:
    """Forget every cached Hub response. Used by tests and by the cache-busting code path."""
    _cache.clear()


def hub_base_url() -> str:
    return get_settings().hf_endpoint.rstrip("/")


def public_model_url(model_id: str) -> str:
    """Link to the public website, even when ``HF_ENDPOINT`` points at a mirror."""
    return f"https://huggingface.co/{model_id}"


def normalize_model_id(raw: str) -> str:
    """Turn user input into a canonical ``org/name`` (or bare ``name``) model id.

    Accepts ``org/name``, ``name``, ``huggingface.co/org/name``, ``https://huggingface.co/org/name/tree/main``
    and similar links. Dataset and Space URLs are rejected with an explicit message, because the
    rest of the app only understands models.

    Raises:
        ValueError: when the input is empty, too long, from another site, or not a valid model id.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("Enter a Hugging Face model id, such as Qwen/Qwen2.5-7B-Instruct.")
    if len(text) > MAX_MODEL_ID_LENGTH:
        raise ValueError("That input is too long to be a Hugging Face model id.")

    if "://" in text or _HOST_PREFIX_RE.match(text):
        parsed = urlsplit(text if "://" in text else f"https://{text}")
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in _HOSTS:
            raise ValueError("Only huggingface.co links are supported.")
        segments = [part for part in parsed.path.split("/") if part]
        if segments and segments[0] in {"datasets", "spaces"}:
            kind = "dataset" if segments[0] == "datasets" else "Space"
            raise ValueError(f"That link points to a {kind}, not a model. Paste a model link instead.")
        if segments and segments[0] == "models":
            segments = segments[1:]
        if not segments:
            raise ValueError("That link doesn't point at a model.")
        text = "/".join(segments[:2])

    text = text.strip("/")
    parts = text.split("/")
    if len(parts) > 2 or not all(_SEGMENT_RE.match(part) for part in parts):
        raise ValueError(
            "Model ids look like 'org/name' using letters, numbers, '.', '-' or '_' (for example "
            "Qwen/Qwen2.5-7B-Instruct)."
        )
    if any(part.endswith(".git") for part in parts):
        raise ValueError("Use the model id itself, not a git clone URL.")
    return text


def _token_fingerprint(token: str | None) -> str:
    """Cache keys must not contain the token itself, so hash it."""
    if not token:
        return "anon"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": f"cloudyai-model-hub/{__version__} (+https://github.com/cloudyai-co/cloudyai_model_hub)",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _get(url: str, token: str | None, params: dict[str, Any] | None = None) -> httpx.Response:
    """GET ``url``. Network-level failures become :class:`HubUnavailableError`."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers=_headers(token),
            transport=_TRANSPORT,
        ) as client:
            return await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise HubUnavailableError("Hugging Face took too long to respond. Please try again.") from exc
    except httpx.HTTPError as exc:
        log.warning("Hub request failed: %s", exc.__class__.__name__)
        raise HubUnavailableError("Couldn't reach Hugging Face right now. Please try again.") from exc


def _raise_for_model_response(response: httpx.Response, model_id: str) -> None:
    status = response.status_code
    if status == 200:
        return
    if status == 404:
        raise HubNotFoundError(f"No model named '{model_id}' was found on Hugging Face.")
    if status in {401, 403}:
        raise HubGatedError(
            f"'{model_id}' is gated or private. Accept its terms on Hugging Face. If you run your own "
            "instance, set HF_TOKEN on the server."
        )
    if status == 429:
        raise HubRateLimitError("Hugging Face is rate-limiting requests. Please wait a minute and retry.")
    raise HubUnavailableError(f"Hugging Face returned an unexpected response (HTTP {status}).")


async def fetch_model_info(model_id: str, token: str | None = None) -> dict[str, Any]:
    """Model metadata. The plain endpoint is used on purpose: with ``expand[]`` parameters the
    API returns only the requested fields, which silently drops ``downloads``, ``likes`` and ``sha``.
    """
    key = ("info", model_id, _token_fingerprint(token))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    response = await _get(f"{hub_base_url()}/api/models/{model_id}", token)
    _raise_for_model_response(response, model_id)
    data = response.json()
    if not isinstance(data, dict):
        raise HubUnavailableError("Hugging Face returned metadata in an unexpected shape.")
    _cache.set(key, data)
    return data


async def _fetch_raw_text(model_id: str, path: str, token: str | None, max_chars: int) -> str | None:
    """Fetch an optional repository file. Missing or inaccessible files return ``None``."""
    key = ("raw", model_id, path, _token_fingerprint(token))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        response = await _get(f"{hub_base_url()}/{model_id}/raw/main/{path}", token)
    except HubUnavailableError:
        return None
    if response.status_code != 200:
        return None
    text = response.text[:max_chars]
    _cache.set(key, text)
    return text


async def fetch_readme(model_id: str, token: str | None = None) -> str | None:
    return await _fetch_raw_text(model_id, "README.md", token, MAX_README_CHARS)


async def fetch_config(model_id: str, token: str | None = None) -> dict[str, Any] | None:
    """The full ``config.json``. It carries ``hidden_size`` and layer counts, which the API's
    embedded ``config`` block does not include."""
    text = await _fetch_raw_text(model_id, "config.json", token, MAX_CONFIG_BYTES)
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        log.info("config.json for %s is not valid JSON; ignoring it", model_id)
        return None
    return data if isinstance(data, dict) else None


async def fetch_file_tree(model_id: str, token: str | None = None) -> list[dict[str, Any]] | None:
    """Recursive file listing of the default branch, following pagination (bounded)."""
    key = ("tree", model_id, _token_fingerprint(token))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    url: str | None = f"{hub_base_url()}/api/models/{model_id}/tree/main"
    params: dict[str, Any] | None = {"recursive": "true"}
    entries: list[dict[str, Any]] = []
    try:
        for _ in range(MAX_TREE_PAGES):
            if url is None:
                break
            response = await _get(url, token, params)
            if response.status_code != 200:
                return None
            page = response.json()
            if not isinstance(page, list):
                return None
            entries.extend(item for item in page if isinstance(item, dict))
            url = response.links.get("next", {}).get("url")
            params = None
    except (HubUnavailableError, ValueError):
        return None
    _cache.set(key, entries)
    return entries


async def fetch_bundle(model_id: str, token: str | None = None, *, include_files: bool = True) -> ModelBundle:
    """Fetch metadata first (it decides whether the model exists), then the optional parts in parallel."""
    info = await fetch_model_info(model_id, token)
    optional = [
        fetch_readme(model_id, token),
        fetch_config(model_id, token),
    ]
    if include_files:
        optional.append(fetch_file_tree(model_id, token))
    results = await asyncio.gather(*optional, return_exceptions=True)
    values: list[Any] = [None if isinstance(item, BaseException) else item for item in results]
    readme, config = values[0], values[1]
    files = values[2] if include_files else None
    return ModelBundle(model_id=model_id, info=info, readme=readme, config=config, files=files)


async def search_models(query: str, limit: int = 8, token: str | None = None) -> list[dict[str, Any]]:
    """Search models by name, most downloaded first."""
    key = ("search", query.lower(), limit, _token_fingerprint(token))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    params = {"search": query, "limit": limit, "sort": "downloads", "direction": -1}
    response = await _get(f"{hub_base_url()}/api/models", token, params)
    if response.status_code != 200:
        raise HubUnavailableError(f"Hugging Face search returned HTTP {response.status_code}.")
    data = response.json()
    results = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    _cache.set(key, results)
    return results
