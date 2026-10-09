# Contributing

Thank you for helping improve CloudyAI Model Hub. This guide covers the setup, the checks every change must pass, and the design rules that keep the project small.

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE), as described in section 5 of that licence.

## Ground rules

- **No build step, no framework, no bundler.** The frontend is plain HTML, CSS and ES modules, served as static files. Adding a bundler or a framework is a design change, so open an issue first.
- **Keep runtime dependencies few.** The backend currently depends on four packages: FastAPI, httpx, pypdf and reportlab. Justify every new runtime dependency in the pull request.
- **Be honest about estimates.** Capacity numbers and completeness scores are heuristics. Their documentation, labels and tests should say what they do and do not show.
- **Respect the users' privacy.** The app stores nothing between requests. Do not add analytics, third-party scripts, fonts from a CDN or anything that sends user input to a third party.

## Setting up

You need Python 3.11 or newer, and Node 22 or newer for the JavaScript checks.

```bash
./run.sh                       # creates .venv, installs the project, starts http://localhost:8000
./run.sh --offline             # the same, using the bundled fixture hub instead of the network
```

Or set it up by hand:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

The JavaScript checks need Node 22 or newer and no npm packages.

## Checks

Run these before you open a pull request. CI runs the same commands.

```bash
ruff check .
ruff format --check .
pytest
npm test
npm run check
```

- `pytest` runs entirely offline. The Hub is replaced by `backend/tests/fake_hub.py`, which serves the fixtures in `backend/tests/fixtures/`.
- `npm run check` runs `node --check` on every ES module in `frontend/js` and `tests/js`.
- The end-to-end browser check is not part of CI. If your change affects the UI, check it in a real browser at a desktop and a phone width, in light and dark themes.

## Frontend rules

The static tests in `backend/tests/test_frontend.py` enforce most of these rules. Read them before you change `frontend/`.

- **Text is never parsed as HTML.** Use `textContent` through the helpers in `frontend/js/dom.js`. Do not use `innerHTML`, `insertAdjacentHTML` or `document.write`.
- **No inline styles or event-handler attributes.** The Content-Security-Policy forbids them. Set dynamic widths through the CSSOM, and keep styles in `frontend/css/app.css`.
- **Only local resources.** No external URLs or `@import` in CSS, and only module scripts from the same origin.
- **Design system.** Paper and ink colours, IBM Plex type, hairline rules and numbered sections. No gradients, no shadows for decoration, no emoji and no purple accents. Icons come from the SVG sprite in `frontend/index.html`.
- **Glyphs.** The web fonts are subsets. Arrows (for example, → and ←), check marks, and the symbols ≈ ≤ ≥ are not in them, so use an icon instead. Every icon used in JavaScript must exist in the sprite.
- **Accessibility.** Each control needs a visible label. Errors use `role="alert"`, progress and status messages use `role="status"`, and the layout must work on a phone-sized screen (below 720 pixels wide) without horizontal scrolling. Respect `prefers-reduced-motion`.

## Backend rules

- Python 3.11+ with type hints. Ruff enforces the rules in `pyproject.toml`, with a line length of 110.
- Keep the Hub client, the AIBOM builder, the capacity model and the PDF renderer as pure functions where you can. They should not make network calls, except `hf_client.py`.
- Tests never use the network. New fixtures go in `backend/tests/fixtures/` and must be described in `backend/tests/fixtures/README.md`, with their provenance. Mark anything invented as invented.
- Routes under `/api` must stay declared before the static mount in `backend/main.py`. This order matters on Vercel.
- Do not commit access tokens, `.env` files or generated PDFs and JSON. `.gitignore` covers the common cases; check `git status` before you commit.

## Changing the output

- **AIBOM fields.** If you add, rename or remove a CycloneDX field or property, update [docs/aibom-mapping.md](docs/aibom-mapping.md), the schema-validation tests and the changelog.
- **Completeness checks.** The weights must still sum to 100. Update the table in `docs/aibom-mapping.md`.
- **Capacity constants.** Update [docs/capacity-model.md](docs/capacity-model.md) with the new value, its source and the test that covers it.
- **API shapes.** Update [docs/api.md](docs/api.md). Breaking changes need a changelog entry and a version bump.
- **Fonts.** Do not edit the files in `frontend/fonts/` or `backend/assets/fonts/` by hand. Regenerate them with `scripts/build_fonts.py` and `scripts/gen_font_css.py`. See [docs/fonts-and-licences.md](docs/fonts-and-licences.md).

## Pull requests

- Keep each pull request focused on one change, and explain why it is needed in the description.
- Add or update tests for behaviour you change. Add a changelog entry under "Unreleased" for user-visible changes.
- Include before and after screenshots for UI changes.
- Do not change the licence headers, the attribution line in the README, or the Apache-2.0 licence text.

## Reporting problems

- Bugs and feature requests: use the issue templates.
- Security problems: do not open a public issue. Follow [SECURITY.md](SECURITY.md).
- Conduct concerns: see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
