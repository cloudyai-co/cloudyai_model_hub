# Deploying to Vercel

The app deploys to Vercel as a single Python function with a FastAPI application, and its frontend is served from Vercel's CDN. This guide covers the setup, what is configured in the repository, the limits to plan for, and how to check a deployment.

## Before you start

- A Vercel account and a GitHub repository containing this code (a fork is fine).
- Optional: a Hugging Face access token, if you need gated or private models.

## Deploy

1. Click **Deploy with Vercel** in the [README](../README.md), or import the repository from the Vercel dashboard.
2. Keep the default settings for the build and output directories. Vercel finds the FastAPI application from `[tool.vercel] entrypoint = "backend.main:app"` in `pyproject.toml`, so you do not need a build command.
3. Optionally add environment variables, such as `HF_TOKEN`. See [configuration.md](configuration.md).
4. Deploy, then run the checks below.

## What is configured in the repository

| File | Setting | Purpose |
|---|---|---|
| `pyproject.toml` | `[project] dependencies` | The runtime dependencies (FastAPI, httpx, pypdf, reportlab). Vercel installs them from here. Development extras are not installed on Vercel. |
| `pyproject.toml` | `[tool.vercel] entrypoint = "backend.main:app"` | The FastAPI application that Vercel runs. |
| `pyproject.toml` | `[tool.vercel.fastapi.static] cdn = true` | Serves `frontend/` from the CDN instead of through the function. |
| `vercel.json` | `functions["backend/main.py"]` | `maxDuration: 30` seconds, and `excludeFiles` for tests, the root JavaScript tests, docs, scripts and `.github`. |
| `vercel.json` | `headers` | The Content-Security-Policy and other security headers for every page and asset, but not for `/api`. Font files get a one-year immutable cache header. |
| `backend/main.py` | Route order | `/api` routes are declared before the static mount at `/`, so they always take precedence. |

The function bundle includes `backend/assets/fonts/`, which the PDF renderer needs.

Vercel picks the Python version from `requires-python` (`>=3.11`), or from a `.python-version` file if you add one. Check the build log to confirm which version was used.

## Limits and what to expect

- **Duration.** Each function call may run for up to 30 seconds (`maxDuration`). With the default 12-second Hub timeout, a complete AIBOM can spend up to about 24 seconds waiting for the Hub: the metadata request first, then the parallel requests. The PDF rendering time comes on top of that. The margin is therefore small. If you see timeouts, lower `HUB_HTTP_TIMEOUT_SECONDS`, and check your plan's maximum duration in Vercel's documentation.
- **Cold starts.** The first request to an idle instance takes longer, because the function must start and import the libraries.
- **Cache.** Each instance has its own in-memory cache. Requests may land on different instances, so cache hits are not guaranteed. Results never depend on the cache, only the speed does.
- **Storage.** The app writes nothing to disk, so it needs no database and no object storage.
- **Bundle size.** Keep large assets out of `backend/`. The PDF fonts are about 750 KB.

## Check a deployment

Replace `https://your-deployment.vercel.app` with your URL.

```bash
curl -s https://your-deployment.vercel.app/api/health
# {"status":"ok","version":"0.2.0"}

curl -sI https://your-deployment.vercel.app/ | grep -i "content-security-policy\|x-content-type"
curl -s "https://your-deployment.vercel.app/api/aibom/generate?model=HuggingFaceH4/zephyr-7b-beta" | head -c 300
curl -OJ "https://your-deployment.vercel.app/api/aibom/report.pdf?model=HuggingFaceH4/zephyr-7b-beta"
```

Then open the home page, generate an AIBOM for a public model, download the PDF, and try the model selection view.

## Local preview with the Vercel CLI

Install the Vercel CLI (version 48.1.8 or later is recommended for FastAPI projects), then run:

```bash
vercel dev
```

The CLI uses the same configuration as production. For plain local development, `./run.sh` is faster.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The build cannot find an application | Check that `pyproject.toml` still has `[tool.vercel] entrypoint = "backend.main:app"`, and that `backend/main.py` defines `app`. The test `test_project.py` checks both. |
| Every model returns `502` | The function cannot reach `huggingface.co`, or `HF_ENDPOINT` is set to an unreachable address. Check the value in the project settings. |
| A gated model returns `403` | Request access on Hugging Face with the account that owns the token, then set `HF_TOKEN` for that account. |
| The PDF shows `?` for some characters | The character is not in the bundled fonts. See [pdf-report.md](pdf-report.md#fonts-and-text). |
| The page loads without styles or fonts | Check that `frontend/` was included and that the security headers do not block the files. The CSP allows only same-origin resources. |
| `/api/...` returns the HTML page | A route was added after the static mount. Move it above the `StaticFiles` mount in `backend/main.py`. |

## Verification status

The configuration was checked against Vercel's documentation for FastAPI and the Python runtime, and against the source of Vercel's Python builder. A live deployment was not part of the automated tests in this repository, so run the checks above after your first deploy.
