from backend.capacity import (
    estimate_memory,
    recommend_hardware,
    score_operational_complexity,
)

SEVEN_B = 7_241_732_096


def test_estimate_memory_fp16_matches_expected_ballpark():
    est = estimate_memory(SEVEN_B, dtype="fp16")
    # 7.24B params * 2 bytes = ~13.5GB of weights before overhead.
    assert 13.0 < est.weights_gb < 14.0
    assert est.total_gb > est.weights_gb  # overhead must be added, never negative


def test_estimate_memory_int4_is_roughly_quarter_of_fp16():
    fp16 = estimate_memory(SEVEN_B, dtype="fp16")
    int4 = estimate_memory(SEVEN_B, dtype="int4")
    assert int4.weights_gb < fp16.weights_gb / 3


def test_estimate_memory_includes_kv_cache_when_architecture_known():
    est = estimate_memory(
        SEVEN_B, dtype="fp16",
        num_layers=32, hidden_size=4096, num_attention_heads=32, num_key_value_heads=8,
        context_length=8192, batch_size=4,
    )
    assert est.kv_cache_gb > 0
    # doubling batch size should roughly double the KV cache
    est_double_batch = estimate_memory(
        SEVEN_B, dtype="fp16",
        num_layers=32, hidden_size=4096, num_attention_heads=32, num_key_value_heads=8,
        context_length=8192, batch_size=8,
    )
    assert est_double_batch.kv_cache_gb == round(est.kv_cache_gb * 2, 2)


def test_recommend_hardware_sorted_by_gpus_needed_then_vram():
    recs = recommend_hardware(weights_gb=15.0, total_gb=17.0)
    gpu_counts = [r["gpus_needed"] for r in recs]
    assert gpu_counts == sorted(gpu_counts)
    single_gpu_fits = [r for r in recs if r["fits_single_gpu"]]
    assert any(r["id"] == "a100_80" for r in single_gpu_fits)
    assert not any(r["id"] == "t4" for r in single_gpu_fits)  # 17GB total > T4's 16GB VRAM at 1x


def test_recommend_hardware_flags_multi_node_for_huge_models():
    recs = recommend_hardware(weights_gb=1400, total_gb=1500)
    biggest_single_card = max(r["vram_gb"] for r in recs)
    needs_many_gpus = [r for r in recs if r["gpus_needed"] > 8]
    assert needs_many_gpus
    assert all("multi-node" in r["interconnect_required"].lower() for r in needs_many_gpus)


def test_operational_complexity_flags_gated_and_large_models():
    result = score_operational_complexity({"gated": True}, {}, total_memory_gb=200)
    assert result["level"] in ("High", "Very High")
    assert any("gated" in r.lower() for r in result["reasons"])


def test_operational_complexity_low_for_small_open_model():
    result = score_operational_complexity(
        {"gated": False, "tags": [], "pipeline_tag": "text-generation"}, {}, total_memory_gb=14
    )
    assert result["level"] == "Low"
