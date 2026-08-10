"""
Capacity planning for serving a Hugging Face model: memory footprint,
hardware fit, a rough throughput ceiling, and operational complexity.

Every number here is a transparent, back-of-the-envelope estimate — the
same category of math as Hugging Face's own `accelerate`-based memory
calculator (weights + KV cache + a fixed overhead buffer). It is not a
substitute for a real profiling run on target hardware. Figures are
rounded from public vendor spec sheets; re-check against current
datasheets before using this for procurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------------------
# Quantization -> bytes per parameter
# ---------------------------------------------------------------------------

BYTES_PER_ELEMENT: dict[str, float] = {
    "fp32": 4.0,
    "fp16": 2.0,
    "bf16": 2.0,
    "int8": 1.0,
    "int4": 0.5,
    "gptq_4bit": 0.55,     # raw 4-bit plus per-group scales/zero-points
    "awq_4bit": 0.55,
    "gguf_q8_0": 1.0,
    "gguf_q4_k_m": 0.60,
    "gguf_q2_k": 0.35,
}

DTYPE_LABELS: dict[str, str] = {
    "fp32": "FP32 (full precision)",
    "fp16": "FP16 / BF16 (half precision)",
    "bf16": "FP16 / BF16 (half precision)",
    "int8": "INT8 (8-bit)",
    "int4": "INT4 (4-bit, raw)",
    "gptq_4bit": "GPTQ 4-bit",
    "awq_4bit": "AWQ 4-bit",
    "gguf_q8_0": "GGUF Q8_0",
    "gguf_q4_k_m": "GGUF Q4_K_M",
    "gguf_q2_k": "GGUF Q2_K",
}

FRAMEWORK_OVERHEAD_GB = 1.5       # fixed CUDA/ROCm context + serving-framework bookkeeping
ACTIVATION_OVERHEAD_FRACTION = 0.10  # rough share of weight memory for activations


# ---------------------------------------------------------------------------
# Hardware catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Accelerator:
    id: str
    name: str
    vendor: str
    vram_gb: float
    bandwidth_gbps: float          # HBM/unified-memory bandwidth, GB/s
    interconnect: str              # native multi-GPU interconnect
    tier: str                      # "consumer" | "data_center" | "edge"


CATALOG: list[Accelerator] = [
    Accelerator("t4", "NVIDIA T4", "NVIDIA", 16, 320, "pcie", "data_center"),
    Accelerator("l4", "NVIDIA L4", "NVIDIA", 24, 300, "pcie", "data_center"),
    Accelerator("a10g", "NVIDIA A10G", "NVIDIA", 24, 600, "pcie", "data_center"),
    Accelerator("rtx4090", "NVIDIA RTX 4090", "NVIDIA", 24, 1008, "pcie", "consumer"),
    Accelerator("l40s", "NVIDIA L40S", "NVIDIA", 48, 864, "pcie", "data_center"),
    Accelerator("a100_40", "NVIDIA A100 40GB", "NVIDIA", 40, 1555, "nvlink", "data_center"),
    Accelerator("a100_80", "NVIDIA A100 80GB", "NVIDIA", 80, 2000, "nvlink", "data_center"),
    Accelerator("h100_80", "NVIDIA H100 80GB", "NVIDIA", 80, 3350, "nvswitch", "data_center"),
    Accelerator("h200", "NVIDIA H200", "NVIDIA", 141, 4800, "nvswitch", "data_center"),
    Accelerator("mi300x", "AMD MI300X", "AMD", 192, 5300, "infinity_fabric", "data_center"),
    Accelerator("m3_max", "Apple M3 Max (128GB)", "Apple", 128, 400, "unified", "edge"),
    Accelerator("m2_ultra", "Apple M2 Ultra (192GB)", "Apple", 192, 800, "unified", "edge"),
]


# ---------------------------------------------------------------------------
# Memory estimate
# ---------------------------------------------------------------------------

@dataclass
class MemoryEstimate:
    dtype: str
    weights_gb: float
    kv_cache_gb: float
    activation_overhead_gb: float
    framework_overhead_gb: float
    total_gb: float
    context_length: int
    batch_size: int


def estimate_kv_cache_gb(
    num_layers: int,
    hidden_size: int,
    num_attention_heads: int,
    num_key_value_heads: int | None,
    context_length: int,
    batch_size: int,
    bytes_per_element: float = 2.0,
) -> float:
    """KV cache size for a decoder transformer: 2x (K and V) across all layers.

    Uses num_key_value_heads instead of num_attention_heads when the model
    uses grouped-query / multi-query attention, since only the KV heads are
    actually cached.
    """
    kv_heads = num_key_value_heads or num_attention_heads
    head_dim = hidden_size / num_attention_heads
    total_bytes = 2 * num_layers * kv_heads * head_dim * context_length * batch_size * bytes_per_element
    return total_bytes / (1024 ** 3)


def estimate_memory(
    param_count: float,
    dtype: str = "fp16",
    num_layers: int | None = None,
    hidden_size: int | None = None,
    num_attention_heads: int | None = None,
    num_key_value_heads: int | None = None,
    context_length: int = 4096,
    batch_size: int = 1,
) -> MemoryEstimate:
    bytes_per_param = BYTES_PER_ELEMENT.get(dtype, 2.0)
    weights_gb = (param_count * bytes_per_param) / (1024 ** 3)

    kv_cache_gb = 0.0
    if num_layers and hidden_size and num_attention_heads:
        # KV cache is rarely quantized as aggressively as the weights; floor at fp16.
        kv_bytes = max(BYTES_PER_ELEMENT.get(dtype, 2.0), 1.0) if dtype != "fp32" else 4.0
        kv_cache_gb = estimate_kv_cache_gb(
            num_layers, hidden_size, num_attention_heads, num_key_value_heads,
            context_length, batch_size, kv_bytes,
        )

    activation_gb = weights_gb * ACTIVATION_OVERHEAD_FRACTION
    total_gb = weights_gb + kv_cache_gb + activation_gb + FRAMEWORK_OVERHEAD_GB

    return MemoryEstimate(
        dtype=dtype,
        weights_gb=round(weights_gb, 2),
        kv_cache_gb=round(kv_cache_gb, 2),
        activation_overhead_gb=round(activation_gb, 2),
        framework_overhead_gb=FRAMEWORK_OVERHEAD_GB,
        total_gb=round(total_gb, 2),
        context_length=context_length,
        batch_size=batch_size,
    )


def recommend_hardware(weights_gb: float, total_gb: float, max_gpus_single_node: int = 8) -> list[dict]:
    """For each cataloged accelerator: GPUs needed, interconnect note, and a
    rough single-request-stream throughput ceiling (memory-bandwidth-bound).

    That throughput number is a *ceiling for one stream*, not aggregate
    system throughput — serving frameworks with continuous batching
    (vLLM, TGI, etc.) push aggregate tokens/sec well past this by serving
    many requests concurrently, at some cost to per-request latency.
    """
    recs = []
    for accel in CATALOG:
        gpus_needed = max(1, math.ceil(total_gb / accel.vram_gb))
        fits_single = gpus_needed == 1
        if gpus_needed == 1:
            interconnect = "None needed — fits on one GPU"
        elif gpus_needed <= max_gpus_single_node:
            interconnect = "Intra-node — NVLink/NVSwitch preferred, PCIe workable at lower throughput"
        else:
            interconnect = "Multi-node — needs InfiniBand/RoCE for acceptable throughput"

        per_gpu_weights_gb = weights_gb / gpus_needed if gpus_needed else weights_gb
        throughput = accel.bandwidth_gbps / per_gpu_weights_gb if per_gpu_weights_gb > 0 else None

        recs.append({
            "id": accel.id,
            "name": accel.name,
            "vram_gb": accel.vram_gb,
            "gpus_needed": gpus_needed,
            "fits_single_gpu": fits_single,
            "interconnect_required": interconnect,
            "approx_tokens_per_sec_single_stream": round(throughput) if throughput else None,
        })
    return sorted(recs, key=lambda r: (r["gpus_needed"], -r["vram_gb"]))


# ---------------------------------------------------------------------------
# Operational complexity
# ---------------------------------------------------------------------------

_LEVELS = ["Low", "Medium", "High", "Very High"]
_COMMON_PERMISSIVE_LICENSES = {"mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause"}


def score_operational_complexity(info: dict, config: dict | None, total_memory_gb: float) -> dict:
    """Heuristic, explainable rating — not a certification. Flags *why* a
    deployment needs more engineering effort than a plain small chat model
    on one GPU, so the reasons matter more than the single-word level.
    """
    config = config or {}
    level = 0
    reasons: list[str] = []

    if total_memory_gb > 640:
        level = max(level, 3)
        reasons.append("Extremely large memory footprint (>640GB) — multi-node serving required")
    elif total_memory_gb > 160:
        level = max(level, 2)
        reasons.append("Large memory footprint (>160GB) — needs multiple high-end data-center GPUs")
    elif total_memory_gb > 48:
        level = max(level, 1)
        reasons.append("Moderate memory footprint (>48GB) — needs a data-center-class GPU or multi-GPU")

    if info.get("gated"):
        level = max(level, 1)
        reasons.append("Gated repository — requires requesting/approving access on Hugging Face")

    tags = {t.lower() for t in (info.get("tags") or [])}
    if "custom_code" in tags or config.get("auto_map"):
        level = max(level, 2)
        reasons.append("Requires custom modeling code (trust_remote_code) — extra security review needed")

    model_type = str(config.get("model_type") or "").lower()
    architectures = " ".join(config.get("architectures") or []).lower()
    if "moe" in model_type or "mixtral" in architectures or config.get("num_local_experts"):
        level = max(level, 2)
        reasons.append("Mixture-of-experts architecture — uneven memory/compute, needs MoE-aware serving")

    pipeline_tag = str(info.get("pipeline_tag") or "").lower()
    if any(k in pipeline_tag for k in ("image-text", "video", "audio", "any-to-any")):
        level = max(level, 1)
        reasons.append("Multi-modal pipeline — additional pre/post-processing stack required")

    card = info.get("cardData") or {}
    license_id = str(card.get("license") or info.get("license") or "").lower()
    if license_id and license_id not in _COMMON_PERMISSIVE_LICENSES:
        reasons.append(f"License '{license_id}' may carry usage restrictions — review before production use")

    if not reasons:
        reasons.append("No unusual deployment requirements detected")

    return {"level": _LEVELS[level], "reasons": reasons}


def estimate_to_dict(estimate: MemoryEstimate) -> dict:
    return asdict(estimate)
