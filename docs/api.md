# API reference

The API lives under `/api`. Every endpoint is read-only and returns JSON, except the PDF endpoint, which returns `application/pdf`.

- Interactive documentation: `/api/docs` (Swagger UI, generated from the code)
- OpenAPI schema: `/api/openapi.json`

## Conventions

- **Model ids.** Accepted as `org/name`, as a bare `name`, or as a `huggingface.co` or `hf.co` model link, with or without `https://` and `www.`. Input is limited to 140 characters. Links to datasets and Spaces are rejected with a message. A link to a file or branch inside a model is accepted, and only the model part is used.
- **Errors.** Error responses have the shape `{"detail": "<message>"}`. The message is written for people and can be shown as it is.
- **Caching.** Hub responses are cached in memory for `HUB_CACHE_TTL_SECONDS` (see [configuration.md](configuration.md)). The PDF endpoint sends `Cache-Control: no-store`. The JSON endpoints do not set cache headers.
- **CORS.** Cross-origin GET, HEAD and OPTIONS requests are allowed from any origin. Credentials are not accepted, and the API uses no cookies.
- **Authentication.** None. Requests to the Hub use the `HF_TOKEN` configured on the server, if any.

## Endpoints

### `GET /api/health`

Liveness check and version.

```json
{ "status": "ok", "version": "0.2.0" }
```

### `GET /api/dtypes`

The weight precisions accepted by `/api/requirements`. Each item has `id`, `label` and `bytes_per_element`. The full list is in [capacity-model.md](capacity-model.md#precision).

### `GET /api/models/search`

Searches the Hub, most downloaded first.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `q` | string | yes | 2 to 100 characters. |
| `limit` | integer | no | 1 to 50. Default 8. |

Response:

```json
{
  "query": "zephyr",
  "results": [
    {
      "id": "HuggingFaceH4/zephyr-7b-beta",
      "author": "HuggingFaceH4",
      "likes": 1900,
      "downloads": 91500,
      "pipeline_tag": "text-generation",
      "library_name": "transformers",
      "tags": ["transformers", "safetensors", "mistral", "text-generation"],
      "created_at": "2023-10-09T00:00:00.000Z"
    }
  ]
}
```

The numbers above are illustrative. `tags` holds at most 12 entries.

### `GET /api/aibom/generate`

Builds the AIBOM and the completeness score for one model.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | Model id or `huggingface.co` link, at most 140 characters. |

Response:

```json
{
  "model_id": "acme-labs/nimbus-7b-instruct",
  "aibom": { "bomFormat": "CycloneDX", "specVersion": "1.6", "...": "..." },
  "completeness": {
    "score": 100,
    "level": "strong",
    "breakdown": [
      { "key": "license", "label": "License declared", "weight": 10, "present": true }
    ]
  }
}
```

- `aibom` is a CycloneDX 1.6 JSON document. Its fields are described in [aibom-mapping.md](aibom-mapping.md).
- `completeness.level` is `strong` (80 and above), `partial` (50 to 79) or `sparse` (below 50).
- `serialNumber` and `metadata.timestamp` change on every call. Everything else comes from the Hub data, so two calls for the same model differ only in those fields, unless the Hub data itself has changed.

### `GET /api/aibom/report.pdf`

The same AIBOM, rendered as a PDF report. It takes the same `model` parameter as `/api/aibom/generate`.

- Content type: `application/pdf`.
- `Content-Disposition: attachment; filename="<org>-<name>-aibom.pdf"`. The file name is built from the model id: each run of characters outside `A–Z a–z 0–9 . _ -` becomes a single `-`, and the name is at most 120 characters before `-aibom.pdf`. For example, `Qwen/Qwen2.5-7B-Instruct` becomes `Qwen-Qwen2.5-7B-Instruct-aibom.pdf`.
- `Cache-Control: no-store`.
- The CycloneDX JSON is attached inside the PDF as `aibom.cdx.json`. See [pdf-report.md](pdf-report.md).

### `GET /api/requirements`

Estimates memory, hardware fit and operational complexity for one model and precision.

| Parameter | Type | Required | Default | Notes |
|---|---|---|---|---|
| `model` | string | yes | | Model id or link. |
| `dtype` | string | no | `fp16` | One of the ids from `/api/dtypes`. |
| `context_length` | integer | no | `4096` | 128 to 262144 tokens. |
| `batch_size` | integer | no | `1` | 1 to 256 concurrent sequences. |

Response (abbreviated, using Qwen2.5-7B-Instruct at `int4` with an 8192-token context):

```json
{
  "model_id": "Qwen/Qwen2.5-7B-Instruct",
  "parameters": 7615616512,
  "parameter_source": "safetensors",
  "dtype": "int4",
  "dtype_label": "INT4 (4-bit, raw)",
  "kv_cache_estimated": true,
  "estimate": {
    "dtype": "int4",
    "weights_gb": 3.55,
    "kv_cache_gb": 0.44,
    "activation_overhead_gb": 0.35,
    "framework_overhead_gb": 1.5,
    "total_gb": 5.84,
    "context_length": 8192,
    "batch_size": 1
  },
  "hardware": [
    {
      "id": "mi300x",
      "name": "AMD MI300X",
      "vram_gb": 192,
      "gpus_needed": 1,
      "fits_single_gpu": true,
      "interconnect_required": "None needed: fits on one GPU",
      "approx_tokens_per_sec_single_stream": 1493
    }
  ],
  "complexity": { "level": "Low", "reasons": ["No unusual deployment requirements detected"] },
  "alternatives": [{ "id": "...", "author": "...", "likes": 0, "downloads": 0, "...": "same fields as a search result" }]
}
```

- `parameter_source` is `safetensors` (exact, from the Hub) or `config` (estimated from `config.json`).
- `hardware` lists every accelerator in the catalogue, fewest GPUs first, then largest VRAM first.
- `complexity.level` is one of `Low`, `Medium`, `High` or `Very High`. `reasons` explains the rating.
- `alternatives` holds up to five search results for models with the same `model_type`, excluding the model itself. The list can be empty.

## Errors

| Status | When | Typical message |
|---|---|---|
| `400` | The model input is empty, longer than 140 characters, not a Hugging Face link, a dataset or Space link, or not a valid id. | "That link points to a dataset, not a model. Paste a model link instead." |
| `403` | The model is gated and the server's token does not have access. | Request access on Hugging Face, then set `HF_TOKEN` for an account that has it. |
| `404` | No model has that id. | "No model named '…' was found on Hugging Face." |
| `422` | A query parameter is out of range or unknown, the model input is longer than 200 characters (FastAPI validation), or no parameter count is available for the model. | |
| `429` | The Hub is rate limiting the server. | "Hugging Face is rate-limiting requests. Please wait a minute and retry." |
| `502` | The Hub timed out, could not be reached, or returned an unexpected response. | "Hugging Face took too long to respond. Please try again." |

## Examples

```bash
curl -s "http://localhost:8000/api/health"
curl -s "http://localhost:8000/api/models/search?q=zephyr&limit=5"
curl -s "http://localhost:8000/api/aibom/generate?model=HuggingFaceH4/zephyr-7b-beta" -o zephyr-aibom.json
curl -OJ "http://localhost:8000/api/aibom/report.pdf?model=HuggingFaceH4/zephyr-7b-beta"
curl -s "http://localhost:8000/api/requirements?model=HuggingFaceH4/zephyr-7b-beta&dtype=gguf_q4_k_m&context_length=8192&batch_size=4"
```
