"""PDF report: structure, embedded CycloneDX attachment, fonts, escaping and file names."""

from __future__ import annotations

import copy
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from pypdf import PdfReader

from backend import __version__
from backend.aibom import build_aibom
from backend.report import _display_value, _markup, _safe_text, render_report_pdf, report_filename
from backend.tests.support import load_fixture

GENERATED_AT = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
SERIAL = "urn:uuid:6f1b8a52-0c4e-4d7a-9a57-2f0c5e1b9d10"


def _nimbus() -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_fixture("nimbus-7b-instruct")
    return build_aibom(
        data["info"]["id"],
        data["info"],
        data["readme"],
        data["config"],
        data["files"],
        generated_at=GENERATED_AT,
        serial_number=SERIAL,
    )


def _text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.fixture(scope="module")
def nimbus_report() -> tuple[dict[str, Any], bytes]:
    bom, completeness = _nimbus()
    return bom, render_report_pdf(bom, completeness)


class TestDocumentStructure:
    def test_is_a_pdf_with_the_expected_page_range(self, nimbus_report: tuple[dict, bytes]) -> None:
        _, pdf = nimbus_report
        assert pdf.startswith(b"%PDF-")
        pages = len(PdfReader(io.BytesIO(pdf)).pages)
        assert 3 <= pages <= 5

    def test_cover_names_the_model_and_its_score(self, nimbus_report: tuple[dict, bytes]) -> None:
        _, pdf = nimbus_report
        text = _normalise(_text(pdf))
        assert "acme-labs/nimbus-7b-instruct" in text
        assert "100" in text

    def test_footer_carries_version_and_pagination(self, nimbus_report: tuple[dict, bytes]) -> None:
        _, pdf = nimbus_report
        text = _normalise(_text(pdf))
        assert f"CloudyAI Model Hub {__version__}" in text
        assert "Verify before compliance use" in text
        assert re.search(r"Page 1 of \d", text)

    def test_numbered_sections_are_present(self, nimbus_report: tuple[dict, bytes]) -> None:
        _, pdf = nimbus_report
        text = _normalise(_text(pdf))
        for heading in ("Identity", "Licence", "Verification"):
            assert heading in text

    def test_minimal_model_still_renders(self) -> None:
        bom, completeness = build_aibom(
            "solo-model", {"id": "solo-model"}, None, None, generated_at=GENERATED_AT
        )
        pdf = render_report_pdf(bom, completeness)
        assert pdf.startswith(b"%PDF-")
        assert "solo-model" in _normalise(_text(pdf))


class TestEmbeddedAttachment:
    def test_cyclonedx_json_is_attached_and_matches_the_bom(self, nimbus_report: tuple[dict, bytes]) -> None:
        bom, pdf = nimbus_report
        attachments = PdfReader(io.BytesIO(pdf)).attachments
        assert "aibom.cdx.json" in attachments
        embedded = json.loads(attachments["aibom.cdx.json"][0])
        assert embedded == bom


class TestFonts:
    def test_only_renamed_cloudy_fonts_are_embedded(self, nimbus_report: tuple[dict, bytes]) -> None:
        _, pdf = nimbus_report
        names: set[str] = set()
        for page in PdfReader(io.BytesIO(pdf)).pages:
            fonts = page.get("/Resources", {}).get("/Font", {})
            for ref in fonts.values():
                base = ref.get_object().get("/BaseFont")
                if base:
                    names.add(str(base))
        embedded = {name for name in names if "Cloudy" in name}
        assert embedded, f"no CloudyAI font found in {names}"
        assert not any("Plex" in name for name in names), "reserved font name must not appear in the PDF"


class TestEscapingAndCharacters:
    def test_card_text_is_shown_literally(self) -> None:
        bom, completeness = _nimbus()
        hostile = "<b>bold</b> & <img src=x onerror=alert(1)> <font color=red>x</font>"
        bom["metadata"]["component"]["description"] = hostile
        pdf = render_report_pdf(bom, completeness)
        text = _normalise(_text(pdf))
        assert "<img src=x onerror=alert(1)>" in text
        assert "<b>bold</b>" in text

    def test_markup_escapes_reportlab_special_characters(self) -> None:
        assert _markup("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_unsupported_glyphs_become_question_marks(self) -> None:
        assert _safe_text("ok \u25cf done") == "ok ? done"

    def test_latin_text_is_kept(self) -> None:
        assert _safe_text("Café — naïve") == "Café — naïve"

    def test_cjk_text_is_kept_and_uses_the_cid_fallback(self) -> None:
        assert _safe_text("模型") == "模型"
        assert 'name="STSong-Light"' in _markup("模型")

    def test_control_characters_become_spaces(self) -> None:
        assert _safe_text("line one\nline two\tend") == "line one line two end"


class TestFilenames:
    @pytest.mark.parametrize(
        ("model_id", "expected"),
        [
            ("Qwen/Qwen2.5-7B-Instruct", "Qwen-Qwen2.5-7B-Instruct-aibom.pdf"),
            ("acme-labs/nimbus-7b-instruct", "acme-labs-nimbus-7b-instruct-aibom.pdf"),
            ("../../etc/passwd", "etc-passwd-aibom.pdf"),
            ("org/naïve model", "org-na-ve-model-aibom.pdf"),
            ("", "model-aibom.pdf"),
        ],
    )
    def test_names_are_ascii_and_safe(self, model_id: str, expected: str) -> None:
        assert report_filename(model_id) == expected

    def test_very_long_names_are_capped(self) -> None:
        name = report_filename("org/" + "a" * 500)
        assert len(name) <= 120 + len("-aibom.pdf")
        assert name.endswith("-aibom.pdf")


def test_rendering_does_not_modify_the_bom() -> None:
    bom, completeness = _nimbus()
    snapshot = copy.deepcopy(bom)
    render_report_pdf(bom, completeness)
    assert bom == snapshot


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("62.030716723549485", "62.03"),
        ("9.66243708053691", "9.662"),
        ("12345.678901", "12346"),
        ("0.000123456789", "0.0001235"),
        ("0.906", "0.906"),
        ("7.34", "7.34"),
        ("unknown", "unknown"),
    ],
)
def test_long_metric_values_are_shortened_for_print(raw: str, shown: str) -> None:
    assert _display_value(raw) == shown


def test_zephyr_evaluation_table_shows_short_values() -> None:
    data = load_fixture("zephyr-7b-beta")
    bom, completeness = build_aibom(
        data["info"]["id"],
        data["info"],
        data["readme"],
        data["config"],
        data["files"],
        generated_at=GENERATED_AT,
        serial_number=SERIAL,
    )
    text = _normalise(_text(render_report_pdf(bom, completeness)))
    assert "62.03" in text
    assert "62.03071672" not in text
