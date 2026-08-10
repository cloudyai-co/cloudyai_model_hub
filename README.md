# CloudyAI Model Hub

A dashboard for picking the right Hugging Face model for the job, and
generating an AI Bill of Materials (AIBOM) in CycloneDX format for it.

## What's here (v0.1 — first working milestone)

- **AIBOM Generator** — enter a Hugging Face model id or URL, get a
  CycloneDX 1.6 `machine-learning-model` AIBOM (the ML-BOM `modelCard`
  extension), plus a documentation "completeness score" with a visible
  breakdown of what's present and what's missing.
- **Model Selection** — search Hugging Face, then estimate memory
  footprint (weights + KV cache) across quantization levels, get a
  recommended hardware list with GPU count and interconnect needs, a
  rough single-stream throughput ceiling, operational-complexity rating,
  and a few alternative models worth a look.
- Dark, warm, telemetry-style dashboard UI. No frontend build step —
  plain HTML/CSS/JS served straight from the backend, so there's one
  thing to install and one thing to run.

## Quick start

```bash
cd cloudyai-model-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000**.

Gated/private models: export `HF_TOKEN=hf_xxx` (an access token from an
account that's been granted access) before starting the server.

## Running the tests

```bash
pip install -r backend/requirements-dev.txt
pytest
```

## Project layout

```
backend/
  main.py          FastAPI app: routes + serves frontend/ as static files

  hf_client.py      Hugging Face Hub API client (search, model info, README)

  aibom.py          CycloneDX AIBOM builder + completeness scoring

  capacity.py       Memory estimate, hardware catalog/matching, throughput,
                    operational-complexity heuristic

  tests/            pytest suite (fixtures, no network required)

frontend/
  index.html, css/style.css, js/*.js    no build step, no framework
```

## How the numbers are calculated

- **Parameter count** — read from Hugging Face's `safetensors.total`
  field when the repo has safetensors weights (exact). Otherwise
  estimated from `config.json` assuming a standard decoder-only,
  SwiGLU-MLP transformer — this undershoots/overshoots for
  encoder-decoder models, mixture-of-experts, and other non-standard
  architectures, and is labeled as an estimate in the UI when used.
- **Memory** — `weights (params × bytes-per-element) + KV cache + ~10%
  activation overhead + 1.5GB fixed framework overhead`. Same category
  of math as Hugging Face's own `accelerate`-based memory calculator.
  KV cache accounts for grouped-query attention when the model's config
  exposes `num_key_value_heads`.
- **Hardware fit** — `ceil(total memory / accelerator VRAM)` against a
  small static catalog of common accelerators (consumer, data-center,
  and Apple unified-memory). 2–8 GPUs on one node is flagged as needing
  NVLink/NVSwitch (PCIe works, just slower); beyond that, multi-node
  InfiniBand/RoCE.
- **Throughput** — `accelerator memory bandwidth ÷ per-GPU weight size`,
  a rough ceiling for *single-request* decoding (each generated token
  requires reading the weights once at batch size 1). This is a
  theoretical ceiling, not a benchmark, and it's specifically a
  single-stream number — continuous-batching servers get much higher
  *aggregate* throughput by serving many requests concurrently.
- **Operational complexity** — a transparent, explainable heuristic
  (not a certification): flags gated repos, `trust_remote_code`, MoE
  architectures, multi-modal pipelines, non-permissive licenses, and
  large memory footprints, and shows the specific reasons alongside the
  Low/Medium/High/Very High label.
- **Completeness score** — weighted checklist over license, description,
  architecture info, datasets, intended use, limitations/bias section,
  ethical considerations, eval results, parameter count, tags, and
  author. Section text (intended use, limitations, ethics) is pulled
  from the model card README by matching against Hugging Face's
  standard template headings (e.g. "Bias, Risks, and Limitations").

## Known limitations

- Every capacity number above is an estimate, not a substitute for a
  real profiling run on your target hardware.
- README/model-card section extraction is a heading-keyword match. A
  model that's well documented but doesn't follow the standard HF
  template will score lower than it deserves.
- No auth, accounts, or persistent history yet — this is a single-tenant
  local tool for now.
- The generated AIBOM should be validated against the official
  CycloneDX JSON schema before being relied on for compliance workflows.

## Contributions
You can pull requests for any intended improvements.


Built with love by KhanKindle.
