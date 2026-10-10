"""Configuration parsing and the in-memory TTL cache."""

from __future__ import annotations

import pytest

from backend.cache import TTLCache
from backend.settings import (
    DEFAULT_CACHE_MAX_ENTRIES,
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_HF_ENDPOINT,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    Settings,
    get_settings,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestSettings:
    def test_defaults_when_nothing_is_set(self) -> None:
        settings = Settings.from_env({})
        assert settings.hf_endpoint == DEFAULT_HF_ENDPOINT
        assert settings.hf_token is None
        assert settings.cache_ttl_seconds == DEFAULT_CACHE_TTL_SECONDS == 600
        assert settings.cache_max_entries == DEFAULT_CACHE_MAX_ENTRIES
        assert settings.http_timeout_seconds == DEFAULT_HTTP_TIMEOUT_SECONDS

    def test_endpoint_is_trimmed_of_slashes_and_whitespace(self) -> None:
        assert Settings.from_env({"HF_ENDPOINT": " https://mirror.example.test/// "}).hf_endpoint == (
            "https://mirror.example.test"
        )

    def test_blank_token_is_treated_as_unset(self) -> None:
        assert Settings.from_env({"HF_TOKEN": "   "}).hf_token is None
        assert Settings.from_env({"HF_TOKEN": " hf_abc "}).hf_token == "hf_abc"

    def test_invalid_integers_fall_back_to_defaults(self) -> None:
        settings = Settings.from_env({"HUB_CACHE_TTL_SECONDS": "soon", "HUB_CACHE_MAX_ENTRIES": ""})
        assert settings.cache_ttl_seconds == DEFAULT_CACHE_TTL_SECONDS
        assert settings.cache_max_entries == DEFAULT_CACHE_MAX_ENTRIES

    def test_negative_integers_are_clamped_to_zero(self) -> None:
        assert Settings.from_env({"HUB_CACHE_TTL_SECONDS": "-5"}).cache_ttl_seconds == 0

    @pytest.mark.parametrize("value", ["-1", "0", "fast"])
    def test_non_positive_timeout_falls_back_to_default(self, value: str) -> None:
        assert (
            Settings.from_env({"HUB_HTTP_TIMEOUT_SECONDS": value}).http_timeout_seconds
            == DEFAULT_HTTP_TIMEOUT_SECONDS
        )

    def test_get_settings_reads_the_environment_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HUB_CACHE_TTL_SECONDS", "42")
        assert get_settings().cache_ttl_seconds == 42
        monkeypatch.setenv("HUB_CACHE_TTL_SECONDS", "7")
        assert get_settings().cache_ttl_seconds == 7

    def test_settings_are_immutable(self) -> None:
        settings = Settings.from_env({})
        with pytest.raises(AttributeError):
            settings.hf_token = "changed"  # type: ignore[misc]


class TestTTLCache:
    def test_value_is_returned_until_it_expires(self) -> None:
        clock = FakeClock()
        cache = TTLCache(ttl_seconds=60, max_entries=10, clock=clock)
        cache.set("k", "v")
        clock.now += 59
        assert cache.get("k") == "v"
        clock.now += 2
        assert cache.get("k") is None
        assert len(cache) == 0

    def test_least_recently_used_entry_is_evicted_first(self) -> None:
        clock = FakeClock()
        cache = TTLCache(ttl_seconds=600, max_entries=2, clock=clock)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.get("a") == 1  # touching "a" makes "b" the oldest
        cache.set("c", 3)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3

    def test_zero_ttl_disables_the_cache(self) -> None:
        cache = TTLCache(ttl_seconds=0, max_entries=10)
        cache.set("k", "v")
        assert cache.enabled is False
        assert cache.get("k") is None

    def test_clear_empties_the_cache(self) -> None:
        cache = TTLCache(ttl_seconds=60, max_entries=10)
        cache.set("k", "v")
        cache.clear()
        assert len(cache) == 0
