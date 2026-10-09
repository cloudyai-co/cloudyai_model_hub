"""HTTP API: contract, error handling, the PDF route, CORS, security headers and the static mount."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend import __version__
from backend.capacity import BYTES_PER_ELEMENT
from backend.main import FRONTEND_DIR, app
from backend.report import report_filename

NIMBUS = "acme-labs/nimbus-7b-instruct"
QWEN = "Qwen/Qwen2.5-7B-Instruct"
ZEPHYR = "HuggingFaceH4/zephyr-7b-beta"


def _json(response: Any) -> Any:
    assert response.headers["content-type"].startswith("application/json")
    return response.json()


class TestService:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert _json(response) == {"status": "ok", "version": __version__}

    def test_dtypes_lists_every_precision_with_a_label(self, client: TestClient) -> None:
        body = _json(client.get("/api/dtypes"))
        assert {item["id"] for item in body} == set(BYTES_PER_ELEMENT)
        assert all(item["label"] for item in body)
        fp16 = next(item for item in body if item["id"] == "fp16")
        assert fp16["bytes_per_element"] == 2.0


class TestSearch:
    def test_search_returns_normalised_hits(self, client: TestClient) -> None:
        body = _json(client.get("/api/models/search", params={"q": "qwen"}))
        assert body["query"] == "qwen"
        first = body["results"][0]
        assert first["id"] == QWEN
        assert first["author"] == "Qwen"
        assert first["downloads"] > 0
        assert isinstance(first["tags"], list)

    @pytest.mark.parametrize(
        "params",
        [{}, {"q": "a"}, {"q": "x" * 101}, {"q": "qwen", "limit": 0}, {"q": "qwen", "limit": 51}],
    )
    def test_invalid_search_parameters_are_rejected(self, client: TestClient, params: dict) -> None:
        assert client.get("/api/models/search", params=params).status_code == 422

    def test_limit_of_fifty_is_allowed(self, client: TestClient) -> None:
        assert client.get("/api/models/search", params={"q": "model", "limit": 50}).status_code == 200


class TestAibomJson:
    def test_generate_returns_bom_and_completeness(self, client: TestClient) -> None:
        body = _json(client.get("/api/aibom/generate", params={"model": NIMBUS}))
        assert body["model_id"] == NIMBUS
        assert body["aibom"]["bomFormat"] == "CycloneDX"
        assert body["aibom"]["specVersion"] == "1.6"
        assert body["completeness"]["level"] == "strong"

    def test_generate_accepts_links(self, client: TestClient) -> None:
        url = f"https://huggingface.co/{NIMBUS}/tree/main"
        body = _json(client.get("/api/aibom/generate", params={"model": url}))
        assert body["model_id"] == NIMBUS

    def test_dataset_link_is_a_clear_400(self, client: TestClient) -> None:
        response = client.get(
            "/api/aibom/generate", params={"model": "https://huggingface.co/datasets/org/name"}
        )
        assert response.status_code == 400
        assert "dataset" in _json(response)["detail"]

    def test_malformed_id_is_400(self, client: TestClient) -> None:
        assert client.get("/api/aibom/generate", params={"model": "../../secret"}).status_code == 400

    def test_missing_parameter_is_422(self, client: TestClient) -> None:
        assert client.get("/api/aibom/generate").status_code == 422

    def test_unknown_model_is_404_with_the_id(self, client: TestClient) -> None:
        response = client.get("/api/aibom/generate", params={"model": "nobody/none"})
        assert response.status_code == 404
        assert "nobody/none" in _json(response)["detail"]

    @pytest.mark.parametrize(("upstream", "expected"), [(401, 403), (429, 429), (500, 502)])
    def test_upstream_problems_map_to_clear_statuses(
        self, install_hub: Callable[..., FastAPI], upstream: int, expected: int
    ) -> None:
        install_hub(info_status={NIMBUS: upstream})
        with TestClient(app) as client:
            response = client.get("/api/aibom/generate", params={"model": NIMBUS})
        assert response.status_code == expected
        assert isinstance(_json(response)["detail"], str)

    def test_token_never_appears_in_responses(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        monkeypatch.setenv("HF_TOKEN", "hf_super_secret_token_value")
        response = client.get("/api/aibom/generate", params={"model": NIMBUS})
        assert "hf_super_secret_token_value" not in response.text
        assert "hf_super_secret_token_value" not in json.dumps(dict(response.headers))


class TestAibomPdf:
    def test_pdf_download_has_attachment_headers(self, client: TestClient) -> None:
        response = client.get("/api/aibom/report.pdf", params={"model": NIMBUS})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="{report_filename(NIMBUS)}"'
        )
        assert response.headers["cache-control"] == "no-store"
        assert response.content.startswith(b"%PDF-")

    def test_pdf_embeds_the_bom_for_the_same_model(self, client: TestClient) -> None:
        response = client.get("/api/aibom/report.pdf", params={"model": NIMBUS})
        attachments = PdfReader(io.BytesIO(response.content)).attachments
        embedded = json.loads(attachments["aibom.cdx.json"][0])
        assert embedded["metadata"]["component"]["name"] == "nimbus-7b-instruct"
        assert embedded["metadata"]["component"]["group"] == "acme-labs"

    def test_pdf_errors_are_json(self, client: TestClient) -> None:
        response = client.get("/api/aibom/report.pdf", params={"model": "nobody/none"})
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")

    def test_cors_exposes_the_filename_header(self, client: TestClient) -> None:
        response = client.get(
            "/api/aibom/report.pdf", params={"model": NIMBUS}, headers={"Origin": "https://example.com"}
        )
        assert "content-disposition" in response.headers["access-control-expose-headers"].lower()


class TestRequirements:
    def test_requirements_report_for_a_model(self, client: TestClient) -> None:
        body = _json(
            client.get(
                "/api/requirements",
                params={"model": QWEN, "dtype": "int4", "context_length": 8192, "batch_size": 2},
            )
        )
        assert body["model_id"] == QWEN
        assert body["parameters"] == 7_615_616_512
        assert body["dtype"] == "int4"
        assert body["estimate"]["context_length"] == 8192
        assert body["estimate"]["batch_size"] == 2
        assert len(body["hardware"]) == 12
        assert body["complexity"]["level"] in {"Low", "Medium", "High", "Very High"}

    def test_config_based_estimate_is_labelled(self, client: TestClient) -> None:
        body = _json(client.get("/api/requirements", params={"model": ZEPHYR}))
        assert body["parameter_source"] == "config"

    def test_alternatives_exclude_the_model_itself(self, client: TestClient) -> None:
        body = _json(client.get("/api/requirements", params={"model": ZEPHYR}))
        ids = [item["id"] for item in body["alternatives"]]
        assert ZEPHYR not in ids
        assert "mistralai/Mixtral-8x7B-Instruct-v0.1" in ids

    @pytest.mark.parametrize(
        "params",
        [{"dtype": "fp8"}, {"context_length": 64}, {"context_length": 300000}, {"batch_size": 0}],
    )
    def test_invalid_options_are_rejected(self, client: TestClient, params: dict) -> None:
        response = client.get("/api/requirements", params={"model": QWEN, **params})
        assert response.status_code == 422

    def test_model_without_size_information_is_422(
        self, tmp_path: Any, install_hub: Callable[..., FastAPI]
    ) -> None:
        model_dir = tmp_path / "tiny-none"
        model_dir.mkdir()
        (model_dir / "info.json").write_text(json.dumps({"id": "tiny/none"}), encoding="utf-8")
        install_hub(fixtures_dir=tmp_path)
        with TestClient(app) as client:
            response = client.get("/api/requirements", params={"model": "tiny/none"})
        assert response.status_code == 422
        assert "parameter count" in _json(response)["detail"]


class TestHttpSurface:
    def test_pages_get_security_headers(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        csp = response.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in response.headers["permissions-policy"]

    def test_api_responses_do_not_duplicate_page_headers(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert "content-security-policy" not in response.headers

    def test_cors_allows_get_and_rejects_post(self, client: TestClient) -> None:
        allowed = client.get("/api/health", headers={"Origin": "https://example.com"})
        assert allowed.headers["access-control-allow-origin"] == "*"
        preflight = client.options(
            "/api/health",
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"},
        )
        assert preflight.status_code == 200
        rejected = client.options(
            "/api/health",
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"},
        )
        assert rejected.status_code == 400

    def test_openapi_document_lists_every_route(self, client: TestClient) -> None:
        paths = _json(client.get("/api/openapi.json"))["paths"]
        for path in (
            "/api/health",
            "/api/dtypes",
            "/api/models/search",
            "/api/aibom/generate",
            "/api/aibom/report.pdf",
            "/api/requirements",
        ):
            assert path in paths

    def test_interactive_docs_are_served(self, client: TestClient) -> None:
        response = client.get("/api/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_static_mount_is_last_so_api_routes_win(self) -> None:
        assert FRONTEND_DIR.is_dir()
        assert app.routes[-1].name == "frontend"  # type: ignore[attr-defined]
        api_paths = [
            getattr(route, "path", "")
            for route in app.routes
            if getattr(route, "path", "").startswith("/api")
        ]
        assert api_paths

    def test_path_traversal_outside_the_frontend_is_refused(self, client: TestClient) -> None:
        assert client.get("/..%2F..%2Fpyproject.toml").status_code == 404
        assert client.get("/%2e%2e/%2e%2e/backend/main.py").status_code == 404
