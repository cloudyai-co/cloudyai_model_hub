# Capacity model: memory, hardware and complexity

The Model selection view and `GET /api/requirements` estimate what a model needs to run. This page gives the formulas, the constants and their sources, and the limits of the estimate. Every number here is taken from `backend/capacity.py`, and the tests cover the formulas.

## Inputs

| Input | Range | Default | Effect |
|---|---|---|---|
| Parameter count | from the Hub or the config | | Weight memory. |
| Precision (`dtype`) | one of the ids in the table below | `fp16` | Bytes per weight element. |
| Context length | 128 to 262,144 tokens | 4,096 | KV cache size. |
| Batch size | 1 to 256 | 1 | KV cache size, because each sequence has its own cache. |

## Parameter count

1. **Exact when available.** If the repository has safetensors weights, the Hub reports the parameter total. The app uses it, and `parameter_source` is `safetensors`.
2. **Estimated otherwise.** The app estimates the count from `config.json` for a decoder-only transformer. `parameter_source` is `config`. The estimate is labelled as an estimate in the UI.

The estimate counts:

- attention projections, using grouped-query attention when `num_key_value_heads` is set: `hidden × heads × head_dim × 2` for query and output, plus `hidden × kv_heads × head_dim × 2` for keys and values;
- gated MLP blocks, three matrices of `hidden × intermediate_size`, multiplied by `num_local_experts` for mixture-of-experts models;
- input and output embeddings, `vocab_size × hidden_size`, counted twice unless `tie_word_embeddings` is set.

Layer norms, biases and routers are left out, because they are very small. The docstring of `estimate_params_from_config()` records that the estimate is within about 0.1% of the published counts for the Qwen2.5-7B, Mixtral-8x7B and Mistral-7B configurations. The estimate returns nothing when a required field is missing, so the app never shows a partial number.

It does not handle encoder-decoder models, multimodal models with separate towers, or other non-standard layouts. For those, the result is a rough figure.

## Memory formula

```
weights_gb    = parameters × bytes_per_element ÷ 1024³
kv_cache_gb   = 2 × layers × kv_heads × head_dim × context × batch × kv_bytes ÷ 1024³
activations   = 10% × weights_gb
framework     = 1.5 GB (fixed: CUDA or ROCm context and serving bookkeeping)
total_gb      = weights_gb + kv_cache_gb + activations + framework
```

- `kv_heads` is `num_key_value_heads` when set, otherwise `num_attention_heads`.
- `head_dim` is `head_dim` when set, otherwise `hidden_size ÷ num_attention_heads`.
- `kv_bytes` is never less than 2 bytes per element. The KV cache is not quantised as aggressively as the weights, so an `int4` model still gets a 16-bit cache.
- The KV cache is included only when the config has layers, hidden size and attention heads. The response field `kv_cache_estimated` says whether it was.

**Worked example.** Qwen2.5-7B-Instruct, `int4`, 8,192 tokens, batch 1, live result of `GET /api/requirements`:

| Component | GB |
|---|---|
| Weights (7.62 billion parameters × 0.5 bytes) | 3.55 |
| KV cache | 0.44 |
| Activations (10% of weights) | 0.35 |
| Framework overhead | 1.50 |
| **Total** | **5.84** |

The components are rounded, so they may not add to the total exactly.

## Precision

| `id` | Label | Bytes per element |
|---|---|---|
| `fp32` | FP32 (full precision) | 4 |
| `fp16` | FP16 / BF16 (half precision) | 2 |
| `bf16` | FP16 / BF16 (half precision) | 2 |
| `int8` | INT8 (8-bit) | 1 |
| `int4` | INT4 (4-bit, raw) | 0.5 |
| `gptq_4bit` | GPTQ 4-bit | 0.55 (4-bit values plus per-group scales and zero points) |
| `awq_4bit` | AWQ 4-bit | 0.55 |
| `gguf_q8_0` | GGUF Q8_0 | 1 |
| `gguf_q4_k_m` | GGUF Q4_K_M | 0.60 |
| `gguf_q2_k` | GGUF Q2_K | 0.35 |

These figures are the average storage per weight for each format. The real size of a particular file can differ, especially for mixed-precision GGUF files.

## Accelerator catalogue

| `id` | Accelerator | Vendor | VRAM (GB) | Memory bandwidth (GB/s) | Interconnect | Class |
|---|---|---|---|---|---|---|
| `t4` | NVIDIA T4 | NVIDIA | 16 | 320 | PCIe | Data centre |
| `l4` | NVIDIA L4 | NVIDIA | 24 | 300 | PCIe | Data centre |
| `a10g` | NVIDIA A10G | NVIDIA | 24 | 600 | PCIe | Data centre |
| `rtx4090` | NVIDIA RTX 4090 | NVIDIA | 24 | 1008 | PCIe | Consumer |
| `l40s` | NVIDIA L40S | NVIDIA | 48 | 864 | PCIe | Data centre |
| `a100_40` | NVIDIA A100 40GB | NVIDIA | 40 | 1555 | NVLink | Data centre |
| `a100_80` | NVIDIA A100 80GB | NVIDIA | 80 | 2000 | NVLink | Data centre |
| `h100_80` | NVIDIA H100 80GB | NVIDIA | 80 | 3350 | NVSwitch | Data centre |
| `h200` | NVIDIA H200 | NVIDIA | 141 | 4800 | NVSwitch | Data centre |
| `mi300x` | AMD MI300X | AMD | 192 | 5300 | Infinity Fabric | Data centre |
| `m3_max` | Apple M3 Max (128 GB) | Apple | 128 | 400 | Unified memory | Edge |
| `m2_ultra` | Apple M2 Ultra (192 GB) | Apple | 192 | 800 | Unified memory | Edge |

The figures are the catalogue values in `backend/capacity.py`. Check the vendor's datasheet for your exact SKU and configuration before you rely on them. To add an accelerator, add an entry to `CATALOG` and extend the tests.

## Hardware fit

For each accelerator:

- **GPUs needed** = `max(1, ceil(total_gb ÷ VRAM))`.
- **Interconnect note**, returned as `interconnect_required`. One GPU: `None needed: fits on one GPU`. Two to eight GPUs on one node: `Intra-node: NVLink/NVSwitch preferred, PCIe workable at lower throughput`. More than eight: `Multi-node: needs InfiniBand or RoCE for acceptable throughput`.
- **Throughput ceiling.** `memory bandwidth ÷ (weights_gb ÷ GPUs needed)`, in tokens per second. This is the rate at which one request stream can decode if every token reads all the weights once.

Results are sorted by GPUs needed (fewest first), then by VRAM (largest first).

**What the throughput number means.** It is a theoretical ceiling for a single stream at batch size 1. Real serving stacks add overheads, and continuous batching serves many requests at once, so the aggregate rate is much higher. The ceiling is also pessimistic for mixture-of-experts models, because the rule uses the full weight size, while each token reads only the active experts.

## Operational complexity

The rating is a transparent heuristic, not a certification. The level starts at Low and moves up to the highest level that any rule triggers. Every triggered rule adds a reason, and the reasons matter most. The memory rules use the total estimated memory for the chosen precision, context length and batch size. The API returns each reason with the exact wording below.

| Condition | Level at least | Reason returned by the API |
|---|---|---|
| Total memory above 640 GB | Very High | `Extremely large memory footprint (>640GB): multi-node serving required` |
| Total memory above 160 GB | High | `Large memory footprint (>160GB): needs multiple high-end data-center GPUs` |
| Total memory above 48 GB | Medium | `Moderate memory footprint (>48GB): needs a data-center-class GPU or multiple GPUs` |
| `gated` is `auto` or `manual` | Medium | `Gated repository: access must be requested and approved on Hugging Face` |
| `pipeline_tag` contains `image-text`, `video`, `audio` or `any-to-any` | Medium | `Multi-modal pipeline: an additional pre- and post-processing stack is required` |
| A `custom_code` tag, or `auto_map` in `config.json` | High | `Requires custom modeling code (trust_remote_code): extra security review needed` |
| `model_type` contains `moe`, the architecture is Mixtral, or `num_local_experts` is set | High | `Mixture-of-experts architecture: uneven memory and compute, needs MoE-aware serving` |
| A licence outside MIT, Apache-2.0, BSD-2-Clause and BSD-3-Clause | No change | `License '<id>' may carry usage restrictions: review before production use` |

In the licence reason, `<id>` is the licence identifier from the card, in lower case.

If no rule applies, the only reason is `No unusual deployment requirements detected`. The licence rule adds a reason but does not change the level, so a restrictive licence is visible without overstating the rating.

## Alternatives

The app runs a Hub search for the model's `model_type` and lists up to five results, excluding the model you asked about. The search is a text search, so the results are related models rather than an exact filter. The list is for orientation only. It does not compare quality, licence, size or fit.

## Limitations

- Every figure is an estimate. Confirm it with a profiling run on your hardware and serving stack before you commit.
- The model counts the weights, KV cache and a fixed overhead. It does not model prefill compute, speculative decoding, LoRA adapters, quantisation tooling, tensor-parallel communication costs, or fragmentation.
- Activation memory is a fixed 10% of the weights, which is a rough rule for typical transformer inference.
- Throughput uses a bandwidth-bound formula. It ignores compute limits and the effect of batch size on throughput.
