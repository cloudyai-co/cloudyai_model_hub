"""Capacity planning for serving a Hugging Face model: memory footprint, hardware fit,
a rough throughput ceiling, and operational complexity.

Every number here is a transparent back-of-the-envelope estimate in the same family as
Hugging Face's ``accelerate``-based memory calculator: weights + KV cache + a fixed
overhead. It is not a substitute for profiling on target hardware. Hardware figures are
rounded from public vendor spec sheets; re-check current datasheets before procurement.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Quantization -> bytes per parameter
# ---------------------------------------------------------------------------

BYTES_PER_ELEMENT: dict[str, float] = {
    "fp32": 4.0,
    "fp16": 2.0,
    "bf16": 2.0,
    "int8": 1.0,
    "int4": 0.5,
    "gptq_4bit": 0.55,  # raw 4-bit plus per-group scales and zero-points
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

#: The KV cache is rarely quantized as aggressively as the weights, so it is never estimated
#: below this many bytes per element (fp16).
KV_CACHE_MIN_BYTES_PER_ELEMENT = 2.0

FRAMEWORK_OVERHEAD_GB = 1.5  # fixed CUDA/ROCm context and serving-framework bookkeeping
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
    bandwidth_gbps: float  # HBM / unified-memory bandwidth, GB/s
    interconnect: str  # native multi-GPU interconnect
    tier: str  # "consumer" | "data_center" | "edge"


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
# Parameter count and memory estimate
# ---------------------------------------------------------------------------


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def estimate_params_from_config(config: dict[str, Any] | None) -> float | None:
    """Approximate parameter count of a decoder-only transformer from its ``config.json``.

    Used only when Hugging Face has no safetensors metadata for the repository. The estimate counts
    attention projections (grouped-query aware), gated MLP blocks (three matrices, one per expert for
    mixture-of-experts models) and input/output embeddings. For the Qwen2.5-7B, Mixtral-8x7B and
    Mistral-7B configurations it lands within about 0.1% of the published counts. Returns ``None``
    when the required fields are missing, so callers never see a half-computed value.
    """
    if not config:
        return None
    hidden = _positive_number(config.get("hidden_size"))
    layers = _positive_number(config.get("num_hidden_layers"))
    vocab = _positive_number(config.get("vocab_size"))
    if not (hidden and layers and vocab):
        return None

    heads = _positive_number(config.get("num_attention_heads")) or 0.0
    kv_heads = _positive_number(config.get("num_key_value_heads")) or heads
    if not heads or not kv_heads:
        return None
    head_dim = _positive_number(config.get("head_dim")) or hidden / heads
    intermediate = _positive_number(config.get("intermediate_size")) or 4 * hidden
    experts = _positive_number(config.get("num_local_experts")) or 1.0

    attention = hidden * heads * head_dim * 2 + hidden * kv_heads * head_dim * 2
    mlp = experts * 3 * hidden * intermediate
    embeddings = vocab * hidden * (1 if config.get("tie_word_embeddings") else 2)
    return layers * (attention + mlp) + embeddings


def estimate_kv_cache_gb(
    num_layers: int,
    hidden_size: int,
    num_attention_heads: int,
    num_key_value_heads: int | None,
    context_length: int,
    batch_size: int,
    bytes_per_element: float = 2.0,
    head_dim: int | None = None,
) -> float:
    """KV cache size for a decoder transformer: keys and values, for every layer.

    Grouped-query and multi-query attention cache only the KV heads, so ``num_key_value_heads``
    is used when present.
    """
    kv_heads = num_key_value_heads or num_attention_heads
    per_head = head_dim or hidden_size / num_attention_heads
    total_bytes = 2 * num_layers * kv_heads * per_head * context_length * batch_size * bytes_per_element
    return total_bytes / (1024**3)


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


def estimate_memory(
    param_count: float,
    dtype: str = "fp16",
    num_layers: int | None = None,
    hidden_size: int | None = None,
    num_attention_heads: int | None = None,
    num_key_value_heads: int | None = None,
    context_length: int = 4096,
    batch_size: int = 1,
    head_dim: int | None = None,
) -> MemoryEstimate:
    if dtype not in BYTES_PER_ELEMENT:
        raise ValueError(f"Unknown dtype '{dtype}'")
    bytes_per_param = BYTES_PER_ELEMENT[dtype]
    weights_gb = (param_count * bytes_per_param) / (1024**3)

    kv_cache_gb = 0.0
    if num_layers and hidden_size and num_attention_heads:
        kv_bytes = max(bytes_per_param, KV_CACHE_MIN_BYTES_PER_ELEMENT)
        kv_cache_gb = estimate_kv_cache_gb(
            num_layers,
            hidden_size,
            num_attention_heads,
            num_key_value_heads,
            context_length,
            batch_size,
            kv_bytes,
            head_dim=head_dim,
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
    """For each cataloged accelerator: GPUs needed, interconnect note, and a rough single-stream
    throughput ceiling (memory-bandwidth-bound).

    The throughput figure is a ceiling for *one* request stream. Serving frameworks with continuous
    batching push aggregate tokens per second well past it, at some cost to per-request latency.
    """
    recs = []
    for accel in CATALOG:
        gpus_needed = max(1, math.ceil(total_gb / accel.vram_gb))
        fits_single = gpus_needed == 1
        if gpus_needed == 1:
            interconnect = "None needed: fits on one GPU"
        elif gpus_needed <= max_gpus_single_node:
            interconnect = "Intra-node: NVLink/NVSwitch preferred, PCIe workable at lower throughput"
        else:
            interconnect = "Multi-node: needs InfiniBand or RoCE for acceptable throughput"

        per_gpu_weights_gb = weights_gb / gpus_needed if gpus_needed else weights_gb
        throughput = accel.bandwidth_gbps / per_gpu_weights_gb if per_gpu_weights_gb > 0 else None

        recs.append(
            {
                "id": accel.id,
                "name": accel.name,
                "vram_gb": accel.vram_gb,
                "gpus_needed": gpus_needed,
                "fits_single_gpu": fits_single,
                "interconnect_required": interconnect,
                "approx_tokens_per_sec_single_stream": round(throughput) if throughput else None,
            }
        )
    return sorted(recs, key=lambda r: (r["gpus_needed"], -r["vram_gb"]))


# ---------------------------------------------------------------------------
# Operational complexity
# ---------------------------------------------------------------------------

_LEVELS = ["Low", "Medium", "High", "Very High"]
_COMMON_PERMISSIVE_LICENSES = {"mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause"}


def is_gated(value: Any) -> bool:
    """The Hub reports ``gated`` as ``false``, ``"auto"`` or ``"manual"``. Anything but off counts."""
    return value not in (False, None, "", "false", 0)


def score_operational_complexity(info: dict, config: dict | None, total_memory_gb: float) -> dict:
    """Heuristic, explainable rating, not a certification. The reasons matter more than the level."""
    config = config or {}
    info = info or {}
    level = 0
    reasons: list[str] = []

    if total_memory_gb > 640:
        level = max(level, 3)
        reasons.append("Extremely large memory footprint (>640GB): multi-node serving required")
    elif total_memory_gb > 160:
        level = max(level, 2)
        reasons.append("Large memory footprint (>160GB): needs multiple high-end data-center GPUs")
    elif total_memory_gb > 48:
        level = max(level, 1)
        reasons.append("Moderate memory footprint (>48GB): needs a data-center-class GPU or multiple GPUs")

    if is_gated(info.get("gated")):
        level = max(level, 1)
        reasons.append("Gated repository: access must be requested and approved on Hugging Face")

    tags = {str(t).lower() for t in (info.get("tags") or [])}
    if "custom_code" in tags or config.get("auto_map"):
        level = max(level, 2)
        reasons.append("Requires custom modeling code (trust_remote_code): extra security review needed")

    model_type = str(config.get("model_type") or "").lower()
    architectures = " ".join(config.get("architectures") or []).lower()
    if "moe" in model_type or "mixtral" in architectures or config.get("num_local_experts"):
        level = max(level, 2)
        reasons.append("Mixture-of-experts architecture: uneven memory and compute, needs MoE-aware serving")

    pipeline_tag = str(info.get("pipeline_tag") or "").lower()
    if any(k in pipeline_tag for k in ("image-text", "video", "audio", "any-to-any")):
        level = max(level, 1)
        reasons.append("Multi-modal pipeline: an additional pre- and post-processing stack is required")

    card = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    raw_license = card.get("license") or info.get("license") or ""
    license_id = str(raw_license[0] if isinstance(raw_license, list) and raw_license else raw_license).lower()
    if license_id and license_id not in _COMMON_PERMISSIVE_LICENSES:
        reasons.append(f"License '{license_id}' may carry usage restrictions: review before production use")

    if not reasons:
        reasons.append("No unusual deployment requirements detected")

    return {"level": _LEVELS[level], "reasons": reasons}


def estimate_to_dict(estimate: MemoryEstimate) -> dict:
    return asdict(estimate)


# ---------------------------------------------------------------------------
# Assembled report (pure function, no network access)
# ---------------------------------------------------------------------------


def build_requirements_report(
    info: dict[str, Any],
    config: dict[str, Any] | None,
    *,
    dtype: str = "fp16",
    context_length: int = 4096,
    batch_size: int = 1,
) -> dict[str, Any]:
    """Memory, hardware fit and complexity for one model.

    Raises:
        ValueError: when neither safetensors metadata nor the config gives a parameter count.
    """
    safetensors_total = _positive_number((info.get("safetensors") or {}).get("total"))
    if safetensors_total:
        parameters, source = safetensors_total, "safetensors"
    else:
        parameters = estimate_params_from_config(config)
        source = "config" if parameters else None
    if not parameters:
        raise ValueError(
            "This repository doesn't publish a parameter count or a complete config.json, "
            "so memory can't be estimated."
        )

    config = config or {}
    estimate = estimate_memory(
        parameters,
        dtype=dtype,
        num_layers=int(config.get("num_hidden_layers") or 0) or None,
        hidden_size=int(config.get("hidden_size") or 0) or None,
        num_attention_heads=int(config.get("num_attention_heads") or 0) or None,
        num_key_value_heads=int(config.get("num_key_value_heads") or 0) or None,
        context_length=context_length,
        batch_size=batch_size,
        head_dim=int(config.get("head_dim") or 0) or None,
    )
    return {
        "parameters": int(parameters),
        "parameter_source": source,
        "dtype": dtype,
        "dtype_label": DTYPE_LABELS[dtype],
        "kv_cache_estimated": estimate.kv_cache_gb > 0,
        "estimate": estimate_to_dict(estimate),
        "hardware": recommend_hardware(weights_gb=estimate.weights_gb, total_gb=estimate.total_gb),
        "complexity": score_operational_complexity(info, config, estimate.total_gb),
    }
