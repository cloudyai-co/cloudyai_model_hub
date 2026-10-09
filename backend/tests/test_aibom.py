"""AIBOM construction: schema validity, licences, card parsing, file components and completeness."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from backend import __version__
from backend.aibom import (
    CATEGORY_ETHICS,
    CATEGORY_LIMITATIONS,
    CATEGORY_USE,
    CHECKS,
    MAX_FILE_COMPONENTS,
    SPDX_LICENSE_IDS,
    _access_mode,
    _category_for,
    build_aibom,
    completeness_level,
)
from backend.tests.support import SCHEMA_DIR, bom_schema_errors, load_fixture

GENERATED_AT = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
SERIAL = "urn:uuid:6f1b8a52-0c4e-4d7a-9a57-2f0c5e1b9d10"
FIXTURE_MODELS = ["nimbus-7b-instruct", "qwen2.5-7b-instruct", "mixtral-8x7b-instruct", "zephyr-7b-beta"]


def build_fixture(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_fixture(name)
    return build_aibom(
        data["info"]["id"],
        data["info"],
        data["readme"],
        data["config"],
        data["files"],
        generated_at=GENERATED_AT,
        serial_number=SERIAL,
    )


def model_component(bom: dict[str, Any]) -> dict[str, Any]:
    return bom["metadata"]["component"]


def properties(component: dict[str, Any]) -> dict[str, str]:
    return {prop["name"]: prop["value"] for prop in component.get("properties", [])}


def _walk(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


class TestDocumentShape:
    @pytest.mark.parametrize("name", FIXTURE_MODELS)
    def test_every_fixture_produces_schema_valid_cyclonedx(self, name: str) -> None:
        bom, _ = build_fixture(name)
        assert bom_schema_errors(bom) == []

    def test_header_fields(self) -> None:
        bom, _ = build_fixture("nimbus-7b-instruct")
        assert bom["bomFormat"] == "CycloneDX"
        assert bom["specVersion"] == "1.6"
        assert bom["serialNumber"] == SERIAL
        assert bom["version"] == 1
        assert bom["metadata"]["timestamp"] == "2026-10-09T12:00:00Z"
        tool = bom["metadata"]["tools"]["components"][0]
        assert tool["name"] == "cloudyai-aibom-generator"
        assert tool["version"] == __version__

    def test_model_component_identity(self) -> None:
        bom, _ = build_fixture("nimbus-7b-instruct")
        component = model_component(bom)
        assert component["type"] == "machine-learning-model"
        assert component["bom-ref"] == "model:acme-labs/nimbus-7b-instruct"
        assert component["group"] == "acme-labs"
        assert component["name"] == "nimbus-7b-instruct"
        assert component["version"] == "abcdef123456"
        assert component["supplier"] == {"name": "acme-labs", "url": ["https://huggingface.co/acme-labs"]}

    def test_no_null_or_empty_values_are_emitted(self) -> None:
        for name in FIXTURE_MODELS:
            bom, _ = build_fixture(name)
            for path, value in _walk(bom):
                assert value is not None, f"null at {path}"
                if path == "$.components":
                    continue  # always present, so consumers can rely on the key (empty is valid CycloneDX)
                if isinstance(value, (str, list, dict)):
                    assert len(value) > 0, f"empty container at {path}"

    def test_external_references_point_to_public_site(self) -> None:
        bom, _ = build_fixture("qwen2.5-7b-instruct")
        urls = [ref["url"] for ref in model_component(bom)["externalReferences"]]
        assert urls
        assert all(url.startswith("https://huggingface.co/") for url in urls)

    def test_minimal_model_still_produces_valid_bom(self) -> None:
        bom, completeness = build_aibom(
            "solo-model", {"id": "solo-model"}, None, None, generated_at=GENERATED_AT
        )
        assert bom_schema_errors(bom) == []
        assert model_component(bom)["name"] == "solo-model"
        assert "group" not in model_component(bom)
        assert completeness["level"] == "sparse"

    def test_description_falls_back_to_first_paragraph_of_card(self) -> None:
        readme = "# Title\n\nThis introductory paragraph describes the model in enough detail to be useful to readers."
        bom, _ = build_aibom("org/tiny", {"id": "org/tiny"}, readme, None, generated_at=GENERATED_AT)
        assert model_component(bom)["description"].startswith("This introductory paragraph")


class TestLicences:
    @pytest.mark.parametrize(
        ("card_license", "expected"),
        [
            ("apache-2.0", {"id": "Apache-2.0"}),
            ("MIT", {"id": "MIT"}),
            ("mit", {"id": "MIT"}),
        ],
    )
    def test_spdx_licence_ids_are_canonical(self, card_license: str, expected: dict[str, str]) -> None:
        info = {"id": "org/model", "cardData": {"license": card_license}}
        bom, _ = build_aibom("org/model", info, None, None, generated_at=GENERATED_AT)
        assert model_component(bom)["licenses"] == [{"license": expected}]

    def test_custom_licence_uses_name_and_link(self) -> None:
        info = {
            "id": "org/model",
            "cardData": {
                "license": "other",
                "license_name": "Acme Community Licence",
                "license_link": "https://example.com/licence",
            },
        }
        bom, _ = build_aibom("org/model", info, None, None, generated_at=GENERATED_AT)
        assert model_component(bom)["licenses"] == [
            {"license": {"name": "Acme Community Licence", "url": "https://example.com/licence"}}
        ]

    def test_every_mapped_spdx_id_is_in_the_vendored_spdx_list(self) -> None:
        spdx = json.loads((SCHEMA_DIR / "spdx.schema.json").read_text(encoding="utf-8"))
        allowed = set(spdx["enum"])
        assert SPDX_LICENSE_IDS
        assert set(SPDX_LICENSE_IDS.values()) <= allowed

    def test_licence_falls_back_to_licence_tag(self) -> None:
        info = {"id": "org/model", "tags": ["license:apache-2.0", "text-generation"]}
        bom, _ = build_aibom("org/model", info, None, None, generated_at=GENERATED_AT)
        assert model_component(bom)["licenses"] == [{"license": {"id": "Apache-2.0"}}]


class TestCardParsing:
    def test_heading_is_assigned_to_exactly_one_category(self) -> None:
        assert _category_for("Intended uses & limitations") == CATEGORY_USE
        assert _category_for("Bias, Risks, and Limitations") == CATEGORY_LIMITATIONS
        assert _category_for("Ethical considerations") == CATEGORY_ETHICS
        assert _category_for("Training hyperparameters") is None

    def test_nimbus_use_cases_are_labelled_and_unique(self) -> None:
        bom, _ = build_fixture("nimbus-7b-instruct")
        use_cases = model_component(bom)["modelCard"]["considerations"]["useCases"]
        assert len(use_cases) == len(set(use_cases))
        assert use_cases[0].startswith("Direct Use: ")
        assert use_cases[1].startswith("Out-of-Scope Use: ")

    def test_code_block_comments_are_not_read_as_headings(self) -> None:
        bom, _ = build_fixture("zephyr-7b-beta")
        considerations = model_component(bom)["modelCard"]["considerations"]
        text = json.dumps(considerations)
        assert "Install transformers from source" not in text
        assert "You are a friendly chatbot" not in text

    def test_html_comments_and_front_matter_are_not_copied(self) -> None:
        bom, _ = build_fixture("zephyr-7b-beta")
        assert "Trimmed excerpt" not in json.dumps(bom)

    def test_limitations_come_from_the_bias_section(self) -> None:
        bom, _ = build_fixture("zephyr-7b-beta")
        limitations = model_component(bom)["modelCard"]["considerations"]["technicalLimitations"]
        assert any("not been aligned to human preferences" in item for item in limitations)

    def test_ethics_section_is_read_when_present(self) -> None:
        bom, completeness = build_fixture("nimbus-7b-instruct")
        ethics = model_component(bom)["modelCard"]["considerations"]["ethicalConsiderations"]
        assert ethics and all("name" in item for item in ethics)
        present = {item["key"]: item["present"] for item in completeness["breakdown"]}
        assert present["ethical_considerations"] is True

    def test_evaluation_metrics_come_from_model_index(self) -> None:
        bom, _ = build_fixture("zephyr-7b-beta")
        metrics = model_component(bom)["modelCard"]["quantitativeAnalysis"]["performanceMetrics"]
        assert len(metrics) == 9
        assert {metric["type"] for metric in metrics} >= {"acc_norm", "f1", "mc2"}


class TestFileComponents:
    def test_qwen_files_are_ordered_weights_first_and_counted(self) -> None:
        data = load_fixture("qwen2.5-7b-instruct")
        bom, _ = build_fixture("qwen2.5-7b-instruct")
        components = bom["components"]
        props = properties(model_component(bom))
        expected_files = [entry for entry in data["files"] if entry.get("type") == "file"]
        assert len(components) == len(expected_files) == 14
        assert props["hf:fileCount"] == "14"
        assert props["hf:totalSizeBytes"] == str(sum(entry["size"] for entry in expected_files))
        assert [properties(c)["aibom:fileRole"] for c in components[:4]] == ["weights"] * 4
        assert all("-of-00004.safetensors" in c["name"] for c in components[:4])

    def test_lfs_files_carry_sha256_and_git_files_do_not(self) -> None:
        bom, _ = build_fixture("qwen2.5-7b-instruct")
        by_name = {component["name"]: component for component in bom["components"]}
        shard = by_name["model-00001-of-00004.safetensors"]
        assert shard["hashes"][0]["alg"] == "SHA-256"
        assert len(shard["hashes"][0]["content"]) == 64
        assert properties(shard)["hf:storage"] == "lfs"
        config = by_name["config.json"]
        assert "hashes" not in config
        assert properties(config)["hf:storage"] == "git"
        assert "hf:gitObjectId" in properties(config)

    def test_directory_entries_are_not_components(self) -> None:
        data = load_fixture("nimbus-7b-instruct")
        bom, _ = build_fixture("nimbus-7b-instruct")
        names = [component["name"] for component in bom["components"]]
        assert "onnx" not in names
        assert len(names) == sum(1 for entry in data["files"] if entry["type"] == "file") == 10

    def test_invalid_lfs_digest_is_ignored(self) -> None:
        files = [{"type": "file", "path": "weights.bin", "size": 5, "lfs": {"oid": "NOT-A-DIGEST"}}]
        bom, _ = build_aibom("org/m", {"id": "org/m"}, None, None, files, generated_at=GENERATED_AT)
        component = bom["components"][0]
        assert "hashes" not in component
        assert properties(component)["hf:storage"] == "git"

    def test_file_list_is_capped_but_true_count_is_kept(self) -> None:
        files = [
            {"type": "file", "path": f"shard-{i}.bin", "size": i + 1} for i in range(MAX_FILE_COMPONENTS + 25)
        ]
        bom, _ = build_aibom("org/m", {"id": "org/m"}, None, None, files, generated_at=GENERATED_AT)
        assert len(bom["components"]) == MAX_FILE_COMPONENTS
        assert properties(model_component(bom))["hf:fileCount"] == str(MAX_FILE_COMPONENTS + 25)

    def test_missing_tree_omits_file_counts(self) -> None:
        bom, _ = build_fixture("mixtral-8x7b-instruct")
        props = properties(model_component(bom))
        assert "hf:fileCount" not in props
        assert "hf:totalSizeBytes" not in props
        assert bom["components"] == []


class TestCompleteness:
    def test_weights_sum_to_one_hundred(self) -> None:
        assert sum(weight for _, _, weight in CHECKS) == 100

    @pytest.mark.parametrize(
        ("score", "level"),
        [(100, "strong"), (80, "strong"), (79, "partial"), (50, "partial"), (49, "sparse"), (0, "sparse")],
    )
    def test_level_bands(self, score: int, level: str) -> None:
        assert completeness_level(score) == level

    def test_nimbus_is_fully_documented(self) -> None:
        bom, completeness = build_fixture("nimbus-7b-instruct")
        assert completeness["score"] == 100
        assert completeness["level"] == "strong"
        assert all(item["present"] for item in completeness["breakdown"])
        assert properties(model_component(bom))["aibom:completenessScore"] == "100"

    def test_zephyr_reports_its_gaps(self) -> None:
        _, completeness = build_fixture("zephyr-7b-beta")
        missing = {item["key"] for item in completeness["breakdown"] if not item["present"]}
        assert missing == {"ethical_considerations", "parameter_count"}

    def test_score_is_the_weighted_share_of_present_checks(self) -> None:
        _, completeness = build_fixture("qwen2.5-7b-instruct")
        earned = sum(item["weight"] for item in completeness["breakdown"] if item["present"])
        assert completeness["score"] == round(earned)

    def test_sparse_model_scores_low(self) -> None:
        _, completeness = build_aibom(
            "solo-model", {"id": "solo-model"}, None, None, generated_at=GENERATED_AT
        )
        assert completeness["score"] < 50
        assert completeness["level"] == "sparse"

    def test_limitations_only_card_is_partial_not_strong(self) -> None:
        readme = "# Model\n\nA short but useful description of the model in a few words here.\n\n## Limitations\n\nIt can be wrong."
        _, completeness = build_aibom("org/m", {"id": "org/m"}, readme, None, generated_at=GENERATED_AT)
        present = {item["key"]: item["present"] for item in completeness["breakdown"]}
        assert present["limitations"] is True
        assert present["ethical_considerations"] is False
        assert completeness["level"] != "strong"


class TestMetadata:
    def test_mixtral_without_pipeline_tag_has_no_task(self) -> None:
        bom, completeness = build_fixture("mixtral-8x7b-instruct")
        assert "task" not in model_component(bom)["modelCard"]["modelParameters"]
        assert {item["key"]: item["present"] for item in completeness["breakdown"]}["pipeline_tag"] is False
        assert properties(model_component(bom))["hf:totalParameters"] == "46702792704"

    def test_zephyr_without_safetensors_reports_unknown_count(self) -> None:
        bom, _ = build_fixture("zephyr-7b-beta")
        props = properties(model_component(bom))
        assert props["hf:totalParameters"] == "unknown"
        assert "hf:weightDtypes" not in props

    @pytest.mark.parametrize(
        ("gated", "expected"),
        [
            (False, "open"),
            (None, "open"),
            ("auto", "gated-auto"),
            ("manual", "gated-manual"),
            (True, "gated"),
        ],
    )
    def test_access_mode(self, gated: Any, expected: str) -> None:
        assert _access_mode(gated) == expected

    def test_private_flag_is_serialized_as_text(self) -> None:
        bom, _ = build_fixture("nimbus-7b-instruct")
        assert properties(model_component(bom))["hf:private"] == "false"

    def test_limitations_and_use_cases_are_not_duplicated_across_categories(self) -> None:
        bom, _ = build_fixture("zephyr-7b-beta")
        considerations = model_component(bom)["modelCard"]["considerations"]
        use_cases = set(considerations.get("useCases", []))
        limitations = set(considerations.get("technicalLimitations", []))
        assert not use_cases & limitations


def test_fixture_bom_is_stable_for_fixed_inputs() -> None:
    first, _ = build_fixture("zephyr-7b-beta")
    second, _ = build_fixture("zephyr-7b-beta")
    assert first == second


def test_build_does_not_mutate_inputs() -> None:
    data = load_fixture("nimbus-7b-instruct")
    snapshot = copy.deepcopy(data)
    build_aibom(
        data["info"]["id"],
        data["info"],
        data["readme"],
        data["config"],
        data["files"],
        generated_at=GENERATED_AT,
    )
    assert data == snapshot
