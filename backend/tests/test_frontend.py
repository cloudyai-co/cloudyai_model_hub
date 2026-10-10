"""Static checks for the zero-build frontend. They enforce the security and design rules in code.

* No HTML sinks (innerHTML and friends) and no inline script, style or event attributes (CSP).
* Every icon used by the code exists in the sprite, every import resolves, and every font file exists.
* No external resources, no gradients and no emoji (see the design notes in docs/architecture.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
INDEX = FRONTEND / "index.html"
JS_FILES = sorted((FRONTEND / "js").rglob("*.js"))
CSS_FILES = sorted((FRONTEND / "css").glob("*.css"))
ALL_TEXT_FILES = [INDEX, *JS_FILES, *CSS_FILES]

HTML_SINKS = re.compile(
    r"\b(?:innerHTML|outerHTML|insertAdjacentHTML|document\.write(?:ln)?)\b|\beval\s*\(|new\s+Function\s*\("
)
INLINE_STYLE = re.compile(r"""setAttribute\(\s*["']style["']|\bstyle\s*=\s*["']|<style\b""")
INLINE_HANDLER = re.compile(r"""\s(on[a-z]+)\s*=\s*["']""")
GRADIENT = re.compile(
    r"(?:linear|radial|conic|repeating-linear|repeating-radial)-gradient\s*\(|\bgradient\b", re.I
)
EMOJI = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\U0001f000-\U0001f2ff]")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_numbers(text: str, pattern: re.Pattern[str]) -> list[int]:
    return [text.count("\n", 0, match.start()) + 1 for match in pattern.finditer(text)]


@pytest.mark.parametrize("path", ALL_TEXT_FILES, ids=lambda p: str(p.relative_to(FRONTEND)))
def test_no_html_injection_sinks(path: Path) -> None:
    text = _read(path)
    assert _line_numbers(text, HTML_SINKS) == [], f"HTML sink in {path.name}"


@pytest.mark.parametrize("path", ALL_TEXT_FILES, ids=lambda p: str(p.relative_to(FRONTEND)))
def test_no_inline_styles_or_handlers(path: Path) -> None:
    text = _read(path)
    assert _line_numbers(text, INLINE_STYLE) == [], f"inline style in {path.name}"
    if path.suffix == ".html":
        assert _line_numbers(text, INLINE_HANDLER) == [], "inline event handler attribute in index.html"


def test_index_has_no_inline_scripts_and_only_module_scripts() -> None:
    text = _read(INDEX)
    scripts = re.findall(r"<script\b[^>]*>", text)
    assert scripts, "index.html must load its module script"
    for tag in scripts:
        assert 'type="module"' in tag and "src=" in tag, f"non-module or inline script: {tag}"


def test_index_loads_only_local_resources() -> None:
    text = _read(INDEX)
    for attribute in re.findall(r'\b(?:src|href)="([^"]+)"', text):
        if attribute.startswith("#"):
            continue
        if attribute.startswith("https://") and "github.com" in attribute:
            continue  # footer links to the source repository only
        assert not attribute.startswith(("http://", "https://", "//")), f"external resource: {attribute}"


@pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
def test_css_has_no_external_urls_or_imports(path: Path) -> None:
    text = _read(path)
    assert "@import" not in text
    for url in re.findall(r"url\(\s*[\"']?([^\"')]+)", text):
        assert not url.startswith(("http:", "https:", "//")), f"external URL in {path.name}: {url}"


@pytest.mark.parametrize("path", ALL_TEXT_FILES, ids=lambda p: str(p.relative_to(FRONTEND)))
def test_no_gradients_or_emoji(path: Path) -> None:
    text = _read(path)
    assert _line_numbers(text, GRADIENT) == [], f"gradient in {path.name}"
    assert _line_numbers(text, EMOJI) == [], f"emoji in {path.name}"


def test_every_icon_used_exists_in_the_sprite() -> None:
    sprite_ids = set(re.findall(r'<symbol id="i-([a-z-]+)"', _read(INDEX)))
    used: set[str] = set()
    for path in [INDEX, *JS_FILES]:
        text = _read(path)
        used.update(re.findall(r'<use href="#i-([a-z-]+)"', text))
        used.update(re.findall(r'\bicon\(\s*"([a-z-]+)"', text))
        used.update(re.findall(r'iconName:\s*"([a-z-]+)"', text))
    assert used, "expected icon usage"
    missing = used - sprite_ids
    assert not missing, f"icons missing from the sprite: {sorted(missing)}"


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: str(p.relative_to(FRONTEND)))
def test_js_imports_resolve_to_files(path: Path) -> None:
    for spec in re.findall(r'from\s+"(\.{1,2}/[^"]+)"', _read(path)):
        target = (path.parent / spec).resolve()
        assert target.is_file(), f"{path.name} imports missing module {spec}"


def test_font_css_points_at_existing_font_files() -> None:
    css = _read(FRONTEND / "css" / "fonts.css")
    referenced = re.findall(r'url\("\.\./fonts/([^"]+)"\)', css)
    on_disk = {path.name for path in (FRONTEND / "fonts").glob("*.woff2")}
    assert len(referenced) == len(on_disk) == 14
    assert set(referenced) == on_disk
    assert all("unicode-range" in rule for rule in css.split("@font-face")[1:])


def test_app_css_references_each_font_family_it_uses() -> None:
    css = _read(FRONTEND / "css" / "app.css")
    fonts = _read(FRONTEND / "css" / "fonts.css")
    for family in ("Plex Sans", "Plex Serif", "Plex Mono"):
        assert f'"{family}"' in css
        assert f'font-family: "{family}"' in fonts


def test_frontend_has_no_build_tooling() -> None:
    assert not any(FRONTEND.rglob("package.json"))
    assert not any(FRONTEND.rglob("*.ts"))
    assert not any(FRONTEND.rglob("vite.config.*"))
