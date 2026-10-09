"""Hugging Face client: id normalisation, error mapping, optional parts, pagination, caching and secrets."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from backend import hf_client
from backend.hf_client import (
    HubGatedError,
    HubNotFoundError,
    HubRateLimitError,
    HubUnavailableError,
    ModelBundle,
    fetch_bundle,
    fetch_file_tree,
    fetch_model_info,
    normalize_model_id,
    public_model_url,
    search_models,
)
from backend.tests.fake_hub import load_fixture_models

NIMBUS = "acme-labs/nimbus-7b-instruct"


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


class CountingTransport(httpx.AsyncBaseTransport):
    """Wraps another transport and records the path of every request."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.paths: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return await self.inner.handle_async_request(request)


class RaisingTransport(httpx.AsyncBaseTransport):
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise self.error


class TestNormalizeModelId:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-7B-Instruct"),
            ("  Qwen/Qwen2.5-7B-Instruct  ", "Qwen/Qwen2.5-7B-Instruct"),
            ("gpt2", "gpt2"),
            ("/Qwen/Qwen2.5-7B-Instruct/", "Qwen/Qwen2.5-7B-Instruct"),
            ("huggingface.co/Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-7B-Instruct"),
            ("https://huggingface.co/Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-7B-Instruct"),
            ("https://www.huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/main", "Qwen/Qwen2.5-7B-Instruct"),
            ("https://hf.co/models/Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-7B-Instruct"),
            ("https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"),
        ],
    )
    def test_accepted_inputs(self, raw: str, expected: str) -> None:
        assert normalize_model_id(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ("", "Enter a Hugging Face model id"),
            ("   ", "Enter a Hugging Face model id"),
            ("x" * 200, "too long"),
            ("https://huggingface.co/datasets/org/name", "dataset"),
            ("https://huggingface.co/spaces/org/app", "Space"),
            ("https://huggingface.co/", "doesn't point at a model"),
            ("https://huggingface.co:8443/org/name", "Only huggingface.co"),
            ("https://example.com/org/name", "Only huggingface.co"),
            ("ftp://huggingface.co/org/name", "Only huggingface.co"),
            ("org/name/extra", "Model ids look like"),
            ("../../etc/passwd", "Model ids look like"),
            ("org/..", "Model ids look like"),
            ("org name", "Model ids look like"),
            ("org/na?me", "Model ids look like"),
            ("org/name.git", "git clone"),
        ],
    )
    def test_rejected_inputs(self, raw: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            normalize_model_id(raw)


class TestBundle:
    def test_bundle_collects_every_part(self, hub: Any) -> None:
        bundle = run(fetch_bundle(NIMBUS))
        assert isinstance(bundle, ModelBundle)
        assert bundle.info["id"] == NIMBUS
        assert bundle.readme and "Nimbus" in bundle.readme
        assert bundle.config["model_type"] == "nimbus"
        assert len(bundle.files) == 11

    def test_include_files_false_skips_the_tree(self, hub: Any) -> None:
        bundle = run(fetch_bundle(NIMBUS, include_files=False))
        assert bundle.files is None

    def test_missing_tree_and_card_are_optional(self, hub: Any) -> None:
        bundle = run(fetch_bundle("mistralai/Mixtral-8x7B-Instruct-v0.1"))
        assert bundle.files is None
        assert bundle.readme is None
        assert bundle.config is not None

    def test_failed_card_download_does_not_fail_the_bundle(self, install_hub: Any) -> None:
        install_hub(raw_status={f"{NIMBUS}/README.md": 500})
        bundle = run(fetch_bundle(NIMBUS))
        assert bundle.readme is None
        assert bundle.config is not None

    def test_effective_config_prefers_config_json_then_embedded_block(self) -> None:
        bundle = ModelBundle("org/m", info={"config": {"model_type": "embedded"}}, config=None)
        assert bundle.effective_config == {"model_type": "embedded"}
        full = ModelBundle(
            "org/m", info={"config": {"model_type": "embedded"}}, config={"model_type": "full"}
        )
        assert full.effective_config == {"model_type": "full"}
        assert ModelBundle("org/m", info={}).effective_config == {}

    def test_unknown_model_is_not_found(self, hub: Any) -> None:
        with pytest.raises(HubNotFoundError) as caught:
            run(fetch_bundle("nobody/nothing-here"))
        assert caught.value.status_code == 404
        assert "nobody/nothing-here" in str(caught.value)


class TestErrorMapping:
    def test_gated_model_maps_to_403(self, install_hub: Any) -> None:
        install_hub(info_status={NIMBUS: 401})
        with pytest.raises(HubGatedError) as caught:
            run(fetch_model_info(NIMBUS))
        assert caught.value.status_code == 403
        assert "gated or private" in str(caught.value)

    def test_rate_limit_maps_to_429(self, install_hub: Any) -> None:
        install_hub(info_status={NIMBUS: 429})
        with pytest.raises(HubRateLimitError) as caught:
            run(fetch_model_info(NIMBUS))
        assert caught.value.status_code == 429

    def test_upstream_failure_maps_to_502(self, install_hub: Any) -> None:
        install_hub(info_status={NIMBUS: 500})
        with pytest.raises(HubUnavailableError) as caught:
            run(fetch_model_info(NIMBUS))
        assert caught.value.status_code == 502

    @pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
    def test_network_errors_map_to_unavailable_without_leaking_details(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception
    ) -> None:
        monkeypatch.setattr(hf_client, "_TRANSPORT", RaisingTransport(error))
        with pytest.raises(HubUnavailableError) as caught:
            run(fetch_model_info(NIMBUS))
        assert "refused" not in str(caught.value)
        assert "slow" not in str(caught.value)

    def test_non_object_metadata_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            hf_client, "_TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(200, json=[1]))
        )
        with pytest.raises(HubUnavailableError):
            run(fetch_model_info(NIMBUS))


class TestTreeAndSearch:
    def test_tree_follows_pagination_links(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "cursor=page2" in str(request.url):
                return httpx.Response(200, json=[{"type": "file", "path": "b.bin", "size": 2}])
            return httpx.Response(
                200,
                json=[{"type": "file", "path": "a.bin", "size": 1}],
                headers={
                    "Link": '<https://huggingface.co/api/models/x/y/tree/main?recursive=true&cursor=page2>; rel="next"'
                },
            )

        monkeypatch.setattr(hf_client, "_TRANSPORT", httpx.MockTransport(handler))
        files = run(fetch_file_tree("x/y"))
        assert [entry["path"] for entry in files] == ["a.bin", "b.bin"]

    def test_tree_pagination_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[{"type": "file", "path": "f.bin", "size": 1}],
                headers={"Link": '<https://huggingface.co/api/models/x/y/tree/main?cursor=more>; rel="next"'},
            )

        monkeypatch.setattr(hf_client, "_TRANSPORT", httpx.MockTransport(handler))
        files = run(fetch_file_tree("x/y"))
        assert len(files) == hf_client.MAX_TREE_PAGES

    def test_search_returns_most_downloaded_first(self, hub: Any) -> None:
        models = load_fixture_models()
        results = run(search_models("", 10))
        downloads = [item["downloads"] for item in results]
        assert downloads == sorted(downloads, reverse=True)
        assert {item["id"] for item in results} == set(models)

    def test_search_respects_limit(self, hub: Any) -> None:
        assert len(run(search_models("", 2))) == 2

    def test_search_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hf_client, "_TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(500)))
        with pytest.raises(HubUnavailableError):
            run(search_models("qwen", 5))


class TestCachingAndSecrets:
    def test_repeat_lookup_is_served_from_memory(self, monkeypatch: pytest.MonkeyPatch, hub: Any) -> None:
        counting = CountingTransport(httpx.ASGITransport(app=hub))
        monkeypatch.setattr(hf_client, "_TRANSPORT", counting)
        run(fetch_bundle(NIMBUS))
        first = len(counting.paths)
        run(fetch_bundle(NIMBUS))
        assert first > 0
        assert len(counting.paths) == first

    def test_token_is_sent_as_bearer_and_never_stored_in_cache_keys(
        self, monkeypatch: pytest.MonkeyPatch, hub: Any
    ) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("authorization", ""))
            return httpx.Response(200, json={"id": NIMBUS})

        monkeypatch.setattr(hf_client, "_TRANSPORT", httpx.MockTransport(handler))
        run(fetch_model_info(NIMBUS, token="hf_secret_value_123"))
        assert seen == ["Bearer hf_secret_value_123"]
        assert all("hf_secret_value_123" not in repr(key) for key in hf_client._cache._items)

    def test_hf_endpoint_override_is_used_for_api_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(404)

        monkeypatch.setenv("HF_ENDPOINT", "https://mirror.example.test/")
        monkeypatch.setattr(hf_client, "_TRANSPORT", httpx.MockTransport(handler))
        with pytest.raises(HubNotFoundError):
            run(fetch_model_info("x/y"))
        assert seen == ["https://mirror.example.test/api/models/x/y"]

    def test_public_links_ignore_the_mirror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HF_ENDPOINT", "https://mirror.example.test")
        assert public_model_url("x/y") == "https://huggingface.co/x/y"
