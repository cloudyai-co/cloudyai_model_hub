"""Runtime configuration, read from environment variables.

Every setting is optional. The defaults are chosen so that the app works out of
the box on a laptop and on Vercel. See ``docs/configuration.md`` for the full list.

Settings are read when :func:`get_settings` is called (not at import time), so
tests and long-lived processes can change the environment safely.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_HF_ENDPOINT = "https://huggingface.co"
DEFAULT_CACHE_TTL_SECONDS = 600
DEFAULT_CACHE_MAX_ENTRIES = 256
DEFAULT_HTTP_TIMEOUT_SECONDS = 12.0


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("Ignoring %s=%r: expected an integer, using %s", name, raw, default)
        return default
    return max(value, 0)


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("Ignoring %s=%r: expected a number, using %s", name, raw, default)
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the configuration for one request."""

    #: Base URL of the Hub API. Point this at a mirror or a local mock to work offline.
    hf_endpoint: str = DEFAULT_HF_ENDPOINT
    #: Optional access token used for gated or private repositories. Never returned to clients.
    hf_token: str | None = None
    #: How long successful Hub responses are kept in memory, in seconds. ``0`` disables caching.
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    #: Upper bound on cached entries per process.
    cache_max_entries: int = DEFAULT_CACHE_MAX_ENTRIES
    #: Timeout for each outbound HTTP request to the Hub.
    http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from ``env`` (defaults to ``os.environ``)."""
        source: Mapping[str, str] = os.environ if env is None else env
        endpoint = (source.get("HF_ENDPOINT") or DEFAULT_HF_ENDPOINT).strip().rstrip("/")
        token = (source.get("HF_TOKEN") or "").strip() or None
        return cls(
            hf_endpoint=endpoint or DEFAULT_HF_ENDPOINT,
            hf_token=token,
            cache_ttl_seconds=_int_env(source, "HUB_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS),
            cache_max_entries=_int_env(source, "HUB_CACHE_MAX_ENTRIES", DEFAULT_CACHE_MAX_ENTRIES),
            http_timeout_seconds=_float_env(source, "HUB_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS),
        )


def get_settings() -> Settings:
    """Return the settings for the current environment."""
    return Settings.from_env()
