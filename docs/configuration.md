# Configuration

The app is configured with environment variables. Every variable is optional. The defaults work out of the box, both locally and on Vercel.

## Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `HF_TOKEN` | string | unset | Hugging Face access token, used for gated and private repositories. Whitespace is trimmed, and an empty value counts as unset. |
| `HF_ENDPOINT` | URL | `https://huggingface.co` | Base URL of the Hub API. A trailing slash is removed. Use `http://127.0.0.1:8787` with `scripts/mock_hub.py` to work offline. |
| `HUB_CACHE_TTL_SECONDS` | integer | `600` | Seconds that successful Hub responses stay in memory. `0` disables the cache. |
| `HUB_CACHE_MAX_ENTRIES` | integer | `256` | Maximum number of cached responses in each process. `0` disables the cache. |
| `HUB_HTTP_TIMEOUT_SECONDS` | number | `12` | Timeout, in seconds, for each request the server makes to the Hub. Must be greater than zero. |

**Invalid values.** An integer that cannot be parsed falls back to its default, and the app logs a warning. A negative integer is treated as `0`. A timeout of zero or less falls back to the default.

**When values are read.** Settings are read each time a request needs them, not once at start-up. Tests and long-running processes can change the environment without restarting.

## Setting variables

**Locally**, export them in the shell that starts the server:

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx     # never commit this value
./run.sh
```

The app does not read `.env` files. If you keep a local file, source it in your shell or use your editor's environment settings. `.gitignore` already excludes `.env` files.

**On Vercel**, add the variables in the project's **Settings → Environment Variables**. Store `HF_TOKEN` there and nowhere else. Redeploy after you change a variable, so the running function picks it up.

## Choosing a token

- Create a read-only token on Hugging Face and use the smallest set of permissions that works.
- Gated models need an account that has been granted access on the model's page. The token alone is not enough.
- Anyone who can use a public deployment can make requests that use its token. Use a token that you are comfortable sharing with all of the deployment's users.
- The token is never returned in responses and never written to logs. Cache keys contain only a 16-character SHA-256 prefix of it.

## Cache tuning

- Raise `HUB_CACHE_TTL_SECONDS` if you want fewer Hub requests and can accept slightly older metadata.
- Lower it, or set it to `0`, if you need the latest Hub data on every request.
- The cache is per process. On Vercel, each warm instance has its own cache, so a higher TTL helps most when traffic reaches the same instance repeatedly.

## Timeouts

`HUB_HTTP_TIMEOUT_SECONDS` applies to each Hub request. A complete AIBOM makes the metadata request first, then three requests in parallel, so the worst case is about two timeouts plus the time to render the PDF. The Vercel function's limit is set separately in `vercel.json`; see [deploy-vercel.md](deploy-vercel.md).

## Offline mode

```bash
python scripts/mock_hub.py --port 8787 &
HF_ENDPOINT=http://127.0.0.1:8787 uvicorn backend.main:app --port 8000
```

or simply `./run.sh --offline`. The fixture hub only knows the four models in `backend/tests/fixtures/`. Other ids return `404`, as the real Hub does for unknown models.
