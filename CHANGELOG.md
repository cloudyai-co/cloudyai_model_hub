# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-09

### Added

- **PDF report** for any AIBOM at `GET /api/aibom/report.pdf`. The report has a cover, eight numbered sections, a file digest table, the completeness checklist and verification notes. The CycloneDX JSON is attached inside the PDF as `aibom.cdx.json`.
- **Vercel deployment** on the Python (FastAPI) runtime, with static assets served from the CDN, function limits in `vercel.json` and a Content-Security-Policy for the frontend.
- **In-memory cache** for Hub responses, configured with `HUB_CACHE_TTL_SECONDS` and `HUB_CACHE_MAX_ENTRIES`. Cache keys hash the access token, so the token itself is never stored in them.
- **Model id parsing** that accepts `org/name`, bare names, and `huggingface.co` links with or without a scheme. Dataset and Space links are rejected with a clear message.
- **Completeness score** with twelve weighted checks, strong, partial and sparse ratings, and a visual ruler.
- **Hardware catalog** of twelve accelerators, a single-stream throughput ceiling and an explainable operational-complexity rating with reasons.
- **Interactive API documentation** at `/api/docs`, with the OpenAPI schema at `/api/openapi.json`.
- **Offline development**: a fixture-backed fake Hub (`backend/tests/fake_hub.py`), `scripts/mock_hub.py`, and `./run.sh --offline`.
- **Dark theme**, selected with a toggle or the system preference.
- **Self-hosted IBM Plex fonts** for the web UI and the PDF, under the SIL Open Font License 1.1.
- **Documentation** in `docs/`, plus `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.editorconfig` and `.gitignore`.
- **Continuous integration** on GitHub Actions (Python 3.11 to 3.13, Node 22), issue and pull request templates, and Dependabot updates.
- **Automated tests** for the AIBOM builder, schema validation against the vendored CycloneDX 1.6 schemas, the Hub client, the capacity model, the PDF report, the API, the static frontend, the project configuration and the Node modules.

### Changed

- **The UI is redesigned** as an engineering datasheet, with numbered sections, hairline rules and an SVG icon sprite. The previous dark dashboard is gone.
- **The front page is recomposed** as an editorial sequence instead of a hero-and-card grid: a full-width statement, an opened specimen sheet with crop marks, a hairline data band, alternating instrument rows built from real document fragments, and margin notes on a sticky rail. No two sections share a template.
- **A human layer** runs through the interface: serif-italic margin notes, wavy pencil underlines, an ink stamp on the datasheet ("reads public data · nothing downloaded"), drop caps and a faint paper grain. The stamp's claim is repeated in plain prose in the form hints and the README, because the hub only reads public metadata and never downloads weights.
- **Frontend code is organised as ES modules** (`frontend/js/` with `views/` and `components/`). The previous single-file scripts (`app.js`, `aibom.js`, `dashboard.js`, `selection.js`) and `css/style.css` were removed.
- **Dependencies are declared only in `pyproject.toml`**. `backend/requirements.txt` and `backend/requirements-dev.txt` were removed.
- **`run.sh` installs the project** with `pip install -e ".[dev]"` and starts uvicorn on port 8000.
- **Capacity estimates** include the KV cache with grouped-query attention, the activation overhead and a framework overhead, as described in [docs/capacity-model.md](docs/capacity-model.md).
- **API responses** have a documented shape, described in [docs/api.md](docs/api.md). Clients written against 0.1 may need updates.

### Security

- Every non-API response carries a Content-Security-Policy that blocks inline styles and scripts and any other origin. It also sends `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a strict referrer policy and a restrictive Permissions-Policy.
- Text from the Hub is written with `textContent`, and the frontend tests reject `innerHTML`-style sinks.
- Access tokens are read from the environment, are never returned to clients, and never appear in cache keys in plain text.

## [0.1.0]

- First working milestone: the AIBOM generator with a completeness score, Model Selection with memory and hardware estimates, and a dark dashboard served from the backend without a build step.
