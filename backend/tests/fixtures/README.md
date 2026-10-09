# Test fixtures

Each directory is one Hugging Face model as the public Hub API presents it. `backend/tests/fake_hub.py`
serves these files, so the test suite and `scripts/mock_hub.py` run without network access.

| Directory | Source | What it exercises |
|---|---|---|
| `qwen2.5-7b-instruct/` | Public Hub API and raw files, captured 2026-10-09 | A full file tree with Git LFS SHA-256 digests (four weight shards). No model card, so the description, intended-use and related checks are missing. |
| `zephyr-7b-beta/` | Public Hub API and raw files, captured 2026-10-09 | A model card with long tables, citations and widget data removed. No safetensors metadata and no file tree, so the parameter count comes from `config.json`. Model-index metrics are present. |
| `mixtral-8x7b-instruct/` | Public Hub API and raw files, captured 2026-10-09 | A mixture-of-experts config. No `pipeline_tag`, no model card and no file tree. |
| `nimbus-7b-instruct/` | **Invented for tests** | Deliberately well documented. Everything in it, including the metadata, model card, config and file tree, is synthetic. The SHA-256 values are made up. |

Fields such as `chat_template` are removed to keep the fixtures small. Nothing in these files is a claim about the real models beyond the public metadata they were copied from.

## Adding a fixture

1. Create a directory named after the model, in lower case with hyphens.
2. Copy `info.json` from `/api/models/{id}`. Add `config.json`, `README.md` and `tree.json` from the raw and tree endpoints where they are needed.
3. Remove anything large, and anything that identifies a person or contains a token.
4. Do not add fixtures for gated or private models.
5. Add a row to the table above, and a test that uses the new fixture.
