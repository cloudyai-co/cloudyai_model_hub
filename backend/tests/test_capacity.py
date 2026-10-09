"""Capacity estimates: parameter counts, memory, hardware fit and operational complexity."""

from __future__ import annotations

import math

import pytest

from backend.capacity import (
    BYTES_PER_ELEMENT,
    CATALOG,
    DTYPE_LABELS,
    build_requirements_report,
    estimate_kv_cache_gb,
    estimate_memory,
    estimate_params_from_config,
    is_gated,
    recommend_hardware,
    score_operational_complexity,
)
from backend.tests.support import load_fixture

GIB = 1024**3


class TestParameterCount:
    def test_qwen_config_estimate_is_close_to_published_count(self) -> None:
        estimate = estimate_params_from_config(load_fixture("qwen2.5-7b-instruct")["config"])
        assert estimate is not None
        assert abs(estimate - 7_615_616_512) / 7_615_616_512 < 0.005

    def test_mixtral_moe_estimate_is_close_to_published_count(self) -> None:
        estimate = estimate_params_from_config(load_fixture("mixtral-8x7b-instruct")["config"])
        assert estimate is not None
        assert abs(estimate - 46_702_792_704) / 46_702_792_704 < 0.005

    def test_zephyr_config_estimate_matches_mistral_7b_size(self) -> None:
        estimate = estimate_params_from_config(load_fixture("zephyr-7b-beta")["config"])
        assert estimate is not None
        assert abs(estimate - 7.24e9) / 7.24e9 < 0.005

    @pytest.mark.parametrize(
        "config",
        [
            None,
            {},
            {"hidden_size": 4096, "num_hidden_layers": 32},
            {"hidden_size": True, "num_hidden_layers": 32, "vocab_size": 32000, "num_attention_heads": 32},
            {"hidden_size": -4096, "num_hidden_layers": 32, "vocab_size": 32000, "num_attention_heads": 32},
            {"hidden_size": 4096, "num_hidden_layers": 0, "vocab_size": 32000, "num_attention_heads": 32},
        ],
    )
    def test_incomplete_or_invalid_config_gives_none(self, config: dict | None) -> None:
        assert estimate_params_from_config(config) is None

    def test_missing_kv_heads_default_to_attention_heads(self) -> None:
        base = {"hidden_size": 1024, "num_hidden_layers": 2, "vocab_size": 1000, "num_attention_heads": 8}
        with_kv = dict(base, num_key_value_heads=8)
        assert estimate_params_from_config(base) == estimate_params_from_config(with_kv)


class TestKvCacheAndMemory:
    def test_kv_cache_formula_for_a_known_shape(self) -> None:
        # 2 (K and V) x 32 layers x 8 KV heads x 128 head dim x 4096 tokens x 1 sequence x 2 bytes = 0.5 GiB
        assert estimate_kv_cache_gb(32, 4096, 32, 8, 4096, 1, 2.0) == pytest.approx(0.5)

    def test_kv_cache_scales_with_batch_and_head_dim(self) -> None:
        base = estimate_kv_cache_gb(32, 4096, 32, 8, 4096, 1, 2.0)
        assert estimate_kv_cache_gb(32, 4096, 32, 8, 4096, 4, 2.0) == pytest.approx(4 * base)
        assert estimate_kv_cache_gb(32, 4096, 32, 8, 4096, 1, 2.0, head_dim=64) == pytest.approx(base / 2)

    def test_missing_kv_heads_use_full_attention(self) -> None:
        assert estimate_kv_cache_gb(32, 4096, 32, None, 4096, 1, 2.0) == pytest.approx(2.0)

    def test_weights_are_bytes_per_parameter_times_count(self) -> None:
        estimate = estimate_memory(7e9, dtype="fp16")
        assert estimate.weights_gb == round(7e9 * 2 / GIB, 2)

    def test_total_includes_activation_and_framework_overhead(self) -> None:
        estimate = estimate_memory(7e9, dtype="fp16")
        assert estimate.total_gb == pytest.approx(estimate.weights_gb * 1.1 + 1.5, abs=0.02)

    def test_quantised_weights_are_smaller(self) -> None:
        fp16 = estimate_memory(7e9, dtype="fp16").weights_gb
        int4 = estimate_memory(7e9, dtype="int4").weights_gb
        assert fp16 == pytest.approx(4 * int4, rel=0.01)

    def test_kv_cache_never_uses_fewer_than_two_bytes_per_element(self) -> None:
        shape = {"num_layers": 32, "hidden_size": 4096, "num_attention_heads": 32, "num_key_value_heads": 8}
        int4 = estimate_memory(7e9, dtype="int4", **shape)
        fp16 = estimate_memory(7e9, dtype="fp16", **shape)
        assert int4.kv_cache_gb == fp16.kv_cache_gb == pytest.approx(0.5, abs=0.01)

    def test_unknown_dtype_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown dtype"):
            estimate_memory(7e9, dtype="fp8")

    def test_labels_cover_every_dtype(self) -> None:
        assert set(DTYPE_LABELS) == set(BYTES_PER_ELEMENT)

    def test_catalog_ids_are_unique(self) -> None:
        ids = [accelerator.id for accelerator in CATALOG]
        assert len(ids) == len(set(ids))


class TestHardware:
    def test_each_option_has_the_documented_fields(self) -> None:
        options = recommend_hardware(weights_gb=13.0, total_gb=17.0)
        assert len(options) == len(CATALOG)
        for option in options:
            assert {"id", "name", "vram_gb", "gpus_needed", "fits_single_gpu"} <= option.keys()
            assert option["fits_single_gpu"] == (option["gpus_needed"] == 1)

    def test_small_model_fits_a_consumer_card(self) -> None:
        options = {option["id"]: option for option in recommend_hardware(weights_gb=13.0, total_gb=17.0)}
        assert options["rtx4090"]["fits_single_gpu"] is True

    def test_gpu_count_rounds_up_to_fit_memory(self) -> None:
        options = {option["id"]: option for option in recommend_hardware(weights_gb=150.0, total_gb=200.0)}
        assert options["h100_80"]["gpus_needed"] == math.ceil(200 / 80) == 3
        assert options["h100_80"]["fits_single_gpu"] is False


class TestComplexity:
    def test_mixture_of_experts_is_flagged(self) -> None:
        config = load_fixture("mixtral-8x7b-instruct")["config"]
        result = score_operational_complexity({"tags": []}, config, 97.0)
        assert result["level"] in {"High", "Very High"}
        assert any("Mixture-of-experts" in reason for reason in result["reasons"])

    def test_manual_gating_adds_an_access_step(self) -> None:
        result = score_operational_complexity({"gated": "manual", "tags": []}, {}, 20.0)
        assert result["level"] == "Medium"
        assert any("Gated repository" in reason for reason in result["reasons"])

    def test_plain_model_has_no_unusual_requirements(self) -> None:
        result = score_operational_complexity({"tags": ["license:apache-2.0"]}, {}, 12.0)
        assert result["level"] == "Low"
        assert result["reasons"] == ["No unusual deployment requirements detected"]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("manual", True), ("auto", True), (False, False), (None, False), ("false", False)],
    )
    def test_is_gated(self, value: object, expected: bool) -> None:
        assert is_gated(value) is expected


class TestRequirementsReport:
    def test_safetensors_total_is_preferred_over_config(self) -> None:
        data = load_fixture("qwen2.5-7b-instruct")
        report = build_requirements_report(data["info"], data["config"], dtype="fp16")
        assert report["parameters"] == 7_615_616_512
        assert report["parameter_source"] == "safetensors"
        assert report["dtype_label"] == DTYPE_LABELS["fp16"]
        assert report["kv_cache_estimated"] is True
        assert len(report["hardware"]) == len(CATALOG)

    def test_config_estimate_is_used_without_safetensors(self) -> None:
        data = load_fixture("zephyr-7b-beta")
        report = build_requirements_report(data["info"], data["config"])
        assert report["parameter_source"] == "config"
        assert 7.2e9 < report["parameters"] < 7.3e9

    def test_longer_context_needs_more_memory(self) -> None:
        data = load_fixture("qwen2.5-7b-instruct")
        short = build_requirements_report(data["info"], data["config"], context_length=2048)
        long = build_requirements_report(data["info"], data["config"], context_length=32768)
        assert long["estimate"]["kv_cache_gb"] > short["estimate"]["kv_cache_gb"]
        assert long["estimate"]["total_gb"] > short["estimate"]["total_gb"]

    def test_model_without_any_size_information_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="parameter count"):
            build_requirements_report({"id": "tiny/none"}, {})
