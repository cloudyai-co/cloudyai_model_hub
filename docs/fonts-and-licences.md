# Fonts and licences

This page lists every third-party font and licence in the project, where each one is used, and how the bundled fonts are built.

## Summary

| Component | Licence | Where it lives |
|---|---|---|
| Project code and documentation | Apache License 2.0 | `LICENSE` |
| IBM Plex fonts, web (WOFF2) | SIL Open Font License 1.1 | `frontend/fonts/`, with `OFL.txt` |
| IBM Plex fonts, PDF (renamed TTF subsets) | SIL Open Font License 1.1 | `backend/assets/fonts/`, with `OFL.txt` |
| CycloneDX 1.6 JSON schemas (test data) | Apache License 2.0 | `backend/tests/schemas/cyclonedx/` |
| Python and JavaScript dependencies | Each project's own licence | Declared in `pyproject.toml`; installed packages carry their own licence files |

Runtime dependencies are declared in `pyproject.toml`: FastAPI, httpx, pypdf and reportlab. Development and test tools are listed under `[project.optional-dependencies] dev`. Check each package's licence file in its distribution before you redistribute a bundle that includes it.

## IBM Plex

### Source

The fonts come from the official IBM Plex npm packages, which are distributed under the SIL Open Font License 1.1:

- `@ibm/plex-sans` 1.1.0
- `@ibm/plex-serif` 2.0.0
- `@ibm/plex-mono` 2.5.0

### Web fonts

`frontend/fonts/` holds 14 WOFF2 files, unmodified apart from being split into subsets:

- IBM Plex Sans: Regular, Medium and SemiBold.
- IBM Plex Serif: Regular and Italic.
- IBM Plex Mono: Regular and Medium.

Each face comes in two subsets, Latin 1 and Latin 2 (`-Latin1.woff2`, `-Latin2.woff2`). `frontend/css/fonts.css` declares the `@font-face` rules and limits each subset with a `unicode-range` taken from the font's character map. `scripts/gen_font_css.py` writes that file, and a test checks that every font file it references exists.

The web fonts keep the IBM Plex names. They contain the upstream glyph outlines, split into Unicode ranges and converted to WOFF2, with no glyphs changed. This is the project's reading of the OFL. If you redistribute the fonts in another form, check the OFL and its FAQ for your case.

### PDF fonts

The PDF uses renamed TTF subsets: CloudySans (Regular, Medium, SemiBold), CloudySerif (Regular, Medium, Italic) and CloudyMono (Regular, Medium). They were made with `scripts/build_fonts.py`.

The SIL OFL does not allow modified versions to use the reserved name "Plex". The PDF files are re-packaged TrueType subsets, which this project treats as modified versions, so they are renamed. The licence text travels with them in `backend/assets/fonts/OFL.txt`.

### Glyph coverage

The web subsets do not contain arrows (→, ←), check marks (✓), or the symbols ≈, ≤ and ≥. The UI uses SVG icons for those. Do not add those characters to the interface text. The PDF fonts cover more characters. The CloudySans Regular file maps about 776 code points, against 385 in the web subsets of IBM Plex Sans Regular, and that includes arrows, check marks and ≈ ≤ ≥. Characters that remain missing are printed as `?`.

## Rebuilding the fonts

Only do this when you need to change the fonts or update the IBM Plex release. Download the three npm packages, extract them into one directory, then run:

```bash
python scripts/build_fonts.py --source /path/to/extracted-packages
python scripts/gen_font_css.py
```

- `build_fonts.py` writes the web WOFF2 files to `frontend/fonts/` and the renamed PDF TTF files to `backend/assets/fonts/`. Pass `--skip-web` to rebuild only the PDF fonts.
- `gen_font_css.py` takes no arguments. It rewrites `frontend/css/fonts.css` from the WOFF2 files in `frontend/fonts/`.
- Run `pytest` afterwards. The font tests check the file names, the licence files and the CSS references.

## CycloneDX schemas

The JSON schemas in `backend/tests/schemas/cyclonedx/` are copies of the CycloneDX 1.6 specification's `schema/` directory, taken at a fixed commit. They are used only by the tests. The directory's README gives the commit, and the schemas are licensed under the Apache License 2.0 (see the `LICENSE` file next to them).

## Test fixtures

The model metadata in `backend/tests/fixtures/` was captured from the public Hugging Face Hub, except for `nimbus-7b-instruct`, which is invented. Its name, README, tree and SHA-256 values are synthetic. See `backend/tests/fixtures/README.md` for each fixture's provenance.
