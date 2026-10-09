"""Render an AIBOM as a human-readable PDF report.

The PDF is written for a compliance or procurement file. It has a cover with the key facts
and the documentation score, numbered sections that mirror the AIBOM, the model's file list
with SHA-256 digests, the completeness checklist, and notes on how to verify the report.

The machine-readable CycloneDX JSON is embedded in the PDF as the attachment
``aibom.cdx.json``, so one file carries both the readable report and the source data.

Fonts are the bundled CloudyAI subsets of IBM Plex (SIL OFL 1.1; see
``backend/assets/fonts/OFL.txt``). Characters the bundled fonts don't cover are shown as ``?``.
CJK text uses reportlab's built-in STSong-Light CID font.
"""

from __future__ import annotations

import io
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import __version__

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_FONT_FILES = {
    "CloudySans": "CloudySans-Regular.ttf",
    "CloudySans-Medium": "CloudySans-Medium.ttf",
    "CloudySans-SemiBold": "CloudySans-SemiBold.ttf",
    "CloudySerif": "CloudySerif-Regular.ttf",
    "CloudySerif-Medium": "CloudySerif-Medium.ttf",
    "CloudySerif-Italic": "CloudySerif-Italic.ttf",
    "CloudyMono": "CloudyMono-Regular.ttf",
    "CloudyMono-Medium": "CloudyMono-Medium.ttf",
}
_CJK_FALLBACK = "STSong-Light"
_CJK_RE = re.compile(r"[\u3000-\u303F\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]")

MAX_FILE_ROWS = 60
MAX_METRIC_ROWS = 40
MAX_COVER_DESCRIPTION = 420

# Palette shared with the web UI (frontend/css/tokens.css).
INK = "#15171A"
INK_2 = "#3D4248"
INK_3 = "#646A73"
RULE = "#D8D5CC"
PAPER_TINT = "#F4F2EC"
SIGNAL = "#F2542D"
SIGNAL_INK = "#B83A17"
OK_INK = "#2F7D4F"
BAD_INK = "#B42318"

REPORT_DISCLAIMER = (
    "This report summarises public metadata from Hugging Face at the time it was generated. It is not legal "
    "advice, a licence determination or a certification. Check licence terms, intended use and evaluation "
    "claims against the source repository before relying on them for compliance."
)

MM = 72 / 25.4
A4_WIDTH = 210 * MM
A4_HEIGHT = 297 * MM
MARGIN_X = 18 * MM
TOP_MARGIN = 26 * MM
BOTTOM_MARGIN = 20 * MM
CONTENT_WIDTH = A4_WIDTH - 2 * MARGIN_X


def report_filename(model_id: str) -> str:
    """A safe, ASCII-only download name, for example ``Qwen-Qwen2.5-7B-Instruct-aibom.pdf``."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model_id).strip("-._") or "model"
    return f"{slug[:120]}-aibom.pdf"


# ---------------------------------------------------------------------------
# Fonts and text
# ---------------------------------------------------------------------------

_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, filename in _FONT_FILES.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
    if _CJK_FALLBACK not in registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FALLBACK))
    _fonts_ready = True


def _charset(font_name: str) -> set[int]:
    from reportlab.pdfbase import pdfmetrics

    return set(pdfmetrics.getFont(font_name).face.charToGlyph.keys())


def _safe_text(text: Any, font_name: str = "CloudySans") -> str:
    """Plain text with characters the font can't draw replaced by ``?`` (no markup)."""
    charset = _charset(font_name)
    value = "" if text is None else str(text)
    return "".join(
        " " if ch in "\r\n\t" else (ch if (ch == " " or ord(ch) in charset or _CJK_RE.match(ch)) else "?")
        for ch in value
    )


def _markup(text: Any, font_name: str = "CloudySans") -> str:
    """Escape ``text`` for a reportlab Paragraph. CJK runs are wrapped in the CID fallback font."""
    value = _safe_text(text, font_name)
    pieces: list[str] = []
    run: list[str] = []
    for char in value:
        if _CJK_RE.match(char):
            run.append(char)
            continue
        if run:
            pieces.append(f'<font name="{_CJK_FALLBACK}">{escape("".join(run))}</font>')
            run = []
        pieces.append(escape(char))
    if run:
        pieces.append(f'<font name="{_CJK_FALLBACK}">{escape("".join(run))}</font>')
    return "".join(pieces)


def _mono(text: Any, size: float | None = None) -> str:
    """Markup that switches to the monospace face (used for ids, digests and paths)."""
    attrs = f' size="{size}"' if size else ""
    return f'<font name="CloudyMono"{attrs}>{_markup(text, "CloudyMono")}</font>'


def _styles() -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    def make(
        name: str, font: str, size: float, leading: float, color: str = INK, **extra: Any
    ) -> ParagraphStyle:
        return ParagraphStyle(
            name,
            fontName=font,
            fontSize=size,
            leading=leading,
            textColor=colors.HexColor(color),
            **extra,
        )

    bullet_common = {"leftIndent": 11, "bulletIndent": 0, "bulletFontName": "CloudySans", "spaceAfter": 3}
    return {
        "kicker": make("kicker", "CloudyMono-Medium", 7.5, 10, SIGNAL_INK, spaceAfter=10),
        "title": make("title", "CloudySerif", 31, 35, INK, spaceAfter=6),
        "subtitle": make("subtitle", "CloudyMono", 9.5, 13, INK_3, spaceAfter=12),
        "lead": make("lead", "CloudySerif-Italic", 11.5, 16.5, INK_2, spaceAfter=8),
        "h2": make("h2", "CloudySerif-Medium", 17, 22, INK, spaceBefore=2, spaceAfter=2),
        "body": make("body", "CloudySans", 9.2, 13.5, INK_2, spaceAfter=5),
        "body_strong": make("body_strong", "CloudySans-Medium", 9.2, 13.5, INK, spaceAfter=3),
        "small": make("small", "CloudySans", 7.8, 11, INK_3, spaceAfter=3),
        "label": make("label", "CloudyMono-Medium", 6.8, 9, INK_3),
        "value": make("value", "CloudySans", 9.2, 12.5, INK, wordWrap="CJK"),
        "bullet": make("bullet", "CloudySans", 9.2, 13.5, INK_2, **bullet_common),
        "bullet_mono": make("bullet_mono", "CloudyMono", 7.4, 10.5, INK_2, **bullet_common, wordWrap="CJK"),
        "cell": make("cell", "CloudySans", 8.4, 11.2, INK),
        "cell_mono": make("cell_mono", "CloudyMono", 7.2, 9.8, INK_2, wordWrap="CJK"),
        "cell_head": make("cell_head", "CloudyMono-Medium", 6.8, 9, INK_3),
        "pill_ok": make("pill_ok", "CloudyMono-Medium", 6.9, 9, OK_INK),
        "pill_bad": make("pill_bad", "CloudyMono-Medium", 6.9, 9, BAD_INK),
        "score": make("score", "CloudySerif", 46, 48, INK),
        "score_unit": make("score_unit", "CloudyMono", 11, 14, INK_3),
        "score_label": make("score_label", "CloudySans-Medium", 9.2, 13.5, INK, spaceBefore=6),
        "note": make("note", "CloudySans", 7.6, 10.5, INK_3),
        "toc": make("toc", "CloudyMono", 7.8, 12, INK_2),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _prop(component: dict[str, Any], name: str) -> str | None:
    for item in component.get("properties", []):
        if item.get("name") == name:
            return item.get("value")
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _fmt_count(value: Any) -> str:
    number = _as_int(value)
    return f"{number:,}" if number is not None else "unknown"


def _fmt_bytes(value: Any) -> str:
    size = _as_int(value)
    if size is None:
        return "unknown"
    amount = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _fmt_params(value: Any) -> str:
    count = _as_int(value)
    if count is None:
        return "unknown"
    if count >= 1e9:
        return f"{count / 1e9:.2f} B"
    if count >= 1e6:
        return f"{count / 1e6:.1f} M"
    return f"{count:,}"


def _fmt_date(value: str | None) -> str:
    if not value:
        return "not reported"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value


def _fmt_timestamp(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")


def _access_label(access: str | None) -> str:
    return {
        "open": "Open",
        "gated-auto": "Gated (automatic approval)",
        "gated-manual": "Gated (manual approval)",
        "gated": "Gated",
    }.get(access or "open", access or "Open")


def _model_id(component: dict[str, Any]) -> str:
    group = component.get("group")
    name = component.get("name") or "model"
    return f"{group}/{name}" if group else name


def _licence_text(component: dict[str, Any]) -> str:
    names = []
    for item in component.get("licenses", []):
        licence = item.get("license", {})
        names.append(licence.get("id") or licence.get("name") or "unspecified")
    return ", ".join(names) if names else "not declared"


def _weights_text(component: dict[str, Any]) -> str:
    dtypes = _prop(component, "hf:weightDtypes")
    if not dtypes:
        return "not published"
    parts = []
    for item in dtypes.split(","):
        dtype, _, count = item.partition(":")
        parts.append(f"{dtype} {_fmt_params(count)}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Flowables
# ---------------------------------------------------------------------------


def _make_score_bar(score: int, width: float, height: float = 24) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Flowable

    class ScoreBar(Flowable):
        """A ruler-style gauge: hairline track, signal-coloured fill, ticks every 5 points."""

        def __init__(self) -> None:
            super().__init__()
            self.width = width
            self.height = height
            self.value = max(0, min(100, int(score)))

        def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
            return self.width, self.height

        def draw(self) -> None:
            canvas = self.canv
            track_y = 12
            canvas.setStrokeColor(colors.HexColor(RULE))
            canvas.setLineWidth(0.6)
            canvas.line(0, track_y, self.width, track_y)
            canvas.setFillColor(colors.HexColor(SIGNAL))
            canvas.rect(0, track_y - 2, self.width * self.value / 100, 4, stroke=0, fill=1)
            canvas.setStrokeColor(colors.HexColor(INK))
            canvas.setLineWidth(0.5)
            for mark in range(0, 101, 5):
                x = self.width * mark / 100
                tick = 4.5 if mark % 25 == 0 else 2.2
                canvas.line(x, track_y - 1, x, track_y - 1 - tick)
            canvas.setFillColor(colors.HexColor(INK_3))
            canvas.setFont("CloudyMono", 6.2)
            for mark, anchor in ((0, "left"), (25, "center"), (50, "center"), (75, "center"), (100, "right")):
                label = str(mark)
                x = self.width * mark / 100
                label_width = canvas.stringWidth(label, "CloudyMono", 6.2)
                if anchor == "center":
                    x -= label_width / 2
                elif anchor == "right":
                    x -= label_width
                canvas.drawString(x, 0, label)

    return ScoreBar()


def _hairline(width: float, color: str = RULE, thickness: float = 0.6) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Flowable

    class Hairline(Flowable):
        def __init__(self) -> None:
            super().__init__()
            self.width = width
            self.height = 2

        def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
            return self.width, self.height

        def draw(self) -> None:
            self.canv.setStrokeColor(colors.HexColor(color))
            self.canv.setLineWidth(thickness)
            self.canv.line(0, 1, self.width, 1)

    return Hairline()


def _numbered_canvas(footer_text: str) -> type:
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as pdf_canvas

    class NumberedCanvas(pdf_canvas.Canvas):
        """Two-pass canvas so that "Page X of Y" can show the final total."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._page_states: list[dict[str, Any]] = []

        def showPage(self) -> None:
            self._page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._page_states)
            for number, state in enumerate(self._page_states, start=1):
                self.__dict__.update(state)
                self.setFont("CloudyMono", 6.8)
                self.setFillColor(colors.HexColor(INK_3))
                self.drawString(MARGIN_X, 9 * MM, _safe_text(footer_text, "CloudyMono"))
                self.drawRightString(A4_WIDTH - MARGIN_X, 9 * MM, f"Page {number} of {total}")
                super().showPage()
            super().save()

    return NumberedCanvas


def _decorate_cover(canvas: Any, doc: Any) -> None:
    from reportlab.lib import colors

    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor(INK))
    canvas.setLineWidth(1.2)
    canvas.line(MARGIN_X, A4_HEIGHT - 12 * MM, A4_WIDTH - MARGIN_X, A4_HEIGHT - 12 * MM)
    canvas.setStrokeColor(colors.HexColor(RULE))
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN_X, 14 * MM, A4_WIDTH - MARGIN_X, 14 * MM)
    canvas.restoreState()


def _decorate_body(model_id: str) -> Any:
    from reportlab.lib import colors

    def draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("CloudyMono-Medium", 6.8)
        canvas.setFillColor(colors.HexColor(INK_3))
        canvas.drawString(MARGIN_X, A4_HEIGHT - 13 * MM, "AI BILL OF MATERIALS")
        canvas.setFont("CloudyMono", 6.8)
        canvas.drawRightString(A4_WIDTH - MARGIN_X, A4_HEIGHT - 13 * MM, _safe_text(model_id, "CloudyMono"))
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN_X, A4_HEIGHT - 16 * MM, A4_WIDTH - MARGIN_X, A4_HEIGHT - 16 * MM)
        canvas.line(MARGIN_X, 14 * MM, A4_WIDTH - MARGIN_X, 14 * MM)
        canvas.restoreState()

    return draw


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def _kv_table(
    rows: list[tuple[str, str]], label_width: float, total_width: float, styles: dict[str, Any]
) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    data = [
        [
            Paragraph(_markup(label.upper(), "CloudyMono-Medium"), styles["label"]),
            Paragraph(value, styles["value"]),
        ]
        for label, value in rows
    ]
    table = Table(data, colWidths=[label_width, total_width - label_width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(RULE)),
            ]
        )
    )
    return table


def _grid_table(header: list[str], rows: list[list[Any]], widths: list[float], styles: dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    head = [Paragraph(_markup(text.upper(), "CloudyMono-Medium"), styles["cell_head"]) for text in header]
    table = Table([head] + rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PAPER_TINT)),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(INK)),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(RULE)),
            ]
        )
    )
    return table


def _section(number: str, title: str, styles: dict[str, Any], content: list[Any]) -> list[Any]:
    """A numbered heading, a hairline, then ``content``. The heading never ends a page on its own."""
    from reportlab.platypus import KeepTogether, Paragraph, Spacer

    heading = Paragraph(
        f'<font name="CloudyMono-Medium" color="{SIGNAL_INK}">{number}</font>&nbsp;&nbsp;'
        f"{_markup(title, 'CloudySerif-Medium')}",
        styles["h2"],
    )
    head = [heading, _hairline(CONTENT_WIDTH, RULE, 0.8), Spacer(1, 7)]
    if not content:
        return [KeepTogether(head)]
    return [KeepTogether(head + content[:1]), *content[1:]]


def _bullets(items: list[str], styles: dict[str, Any], *, mono: bool = False) -> list[Any]:
    from reportlab.platypus import Paragraph

    style = styles["bullet_mono"] if mono else styles["bullet"]
    return [
        Paragraph(_markup(item, "CloudyMono" if mono else "CloudySans"), style, bulletText="\u2013")
        for item in items
    ]


def _paragraph(markup: str, style: Any) -> Any:
    from reportlab.platypus import Paragraph

    return Paragraph(markup, style)


# ---------------------------------------------------------------------------
# Cover
# ---------------------------------------------------------------------------


def _cover(bom: dict[str, Any], completeness: dict[str, Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Spacer, Table, TableStyle

    component = bom["metadata"]["component"]
    card_params = component.get("modelCard", {}).get("modelParameters", {})
    score = int(completeness.get("score", 0))
    level = completeness.get("level", "sparse")
    level_label = {
        "strong": "Well documented",
        "partial": "Partly documented",
        "sparse": "Sparsely documented",
    }.get(level, level)
    publisher = (component.get("supplier") or {}).get("name") or component.get("group") or "unknown"
    params = _prop(component, "hf:totalParameters")
    description = (component.get("description") or "").strip()
    if len(description) > MAX_COVER_DESCRIPTION:
        description = description[:MAX_COVER_DESCRIPTION].rsplit(" ", 1)[0] + "…"

    flow: list[Any] = [
        Spacer(1, 6),
        _paragraph("AI BILL OF MATERIALS  ·  CYCLONEDX 1.6 ML-BOM", styles["kicker"]),
        _paragraph(_markup(component.get("name", "Model"), "CloudySerif"), styles["title"]),
        _paragraph(_mono(_model_id(component), 9.5), styles["subtitle"]),
    ]
    if description:
        flow.append(_paragraph(_markup(description, "CloudySerif-Italic"), styles["lead"]))
    flow.append(Spacer(1, 12))

    left = [
        _paragraph(_markup("DOCUMENTATION COMPLETENESS", "CloudyMono-Medium"), styles["label"]),
        Spacer(1, 4),
        _paragraph(
            f'<font name="CloudySerif">{score}</font>'
            f'<font name="CloudyMono" size="11" color="{INK_3}"> / 100</font>',
            styles["score"],
        ),
        _paragraph(_markup(level_label, "CloudySans-Medium"), styles["score_label"]),
    ]
    facts = _kv_table(
        [
            ("Publisher", _markup(publisher)),
            ("Licence", _markup(_licence_text(component))),
            ("Task", _markup(card_params.get("task") or "not set")),
            ("Parameters", _markup(_fmt_params(params) if params not in (None, "unknown") else "unknown")),
            ("Weights", _markup(_weights_text(component))),
            ("Access", _markup(_access_label(_prop(component, "hf:accessMode")))),
        ],
        label_width=24 * MM,
        total_width=CONTENT_WIDTH * 0.6,
        styles=styles,
    )
    summary = Table([[left, facts]], colWidths=[CONTENT_WIDTH * 0.4, CONTENT_WIDTH * 0.6], hAlign="LEFT")
    summary.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    flow.append(summary)
    flow.append(Spacer(1, 12))
    flow.append(_score_bar_row(score))
    flow.append(Spacer(1, 64 * MM))

    flow.append(_hairline(CONTENT_WIDTH, RULE, 0.8))
    flow.append(Spacer(1, 8))
    serial = bom.get("serialNumber", "")
    flow.append(_paragraph(_mono(f"Serial      {serial}", 7.2), styles["toc"]))
    flow.append(
        _paragraph(
            _mono(f"Generated   {_fmt_timestamp(bom.get('metadata', {}).get('timestamp'))}", 7.2),
            styles["toc"],
        )
    )
    flow.append(Spacer(1, 14))
    contents = [
        ("01", "Identity"),
        ("02", "Licence"),
        ("03", "Architecture and data"),
        ("04", "Evaluation results"),
        ("05", "Considerations"),
        ("06", "Files and digests"),
        ("07", "Completeness checklist"),
        ("08", "Verification"),
    ]
    rows = []
    for index in range(0, len(contents), 2):
        pair = contents[index : index + 2]
        rows.append(
            [
                _paragraph(
                    f'<font name="CloudyMono-Medium" color="{SIGNAL_INK}">{num}</font>'
                    f"&nbsp;&nbsp;{_markup(title)}",
                    styles["body"],
                )
                for num, title in pair
            ]
        )
    toc = Table(rows, colWidths=[CONTENT_WIDTH / 2, CONTENT_WIDTH / 2], hAlign="LEFT")
    toc.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    flow.append(toc)
    flow.append(Spacer(1, 16))
    flow.append(
        _paragraph(
            "The CycloneDX 1.6 document is embedded in this PDF as the attachment "
            + _mono("aibom.cdx.json", 7.4)
            + ".",
            styles["small"],
        )
    )
    return flow


def _score_bar_row(score: int) -> Any:
    from reportlab.platypus import Table, TableStyle

    table = Table([[_make_score_bar(score, CONTENT_WIDTH)]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


# ---------------------------------------------------------------------------
# Body sections
# ---------------------------------------------------------------------------


def _identity(component: dict[str, Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Spacer

    refs = {ref.get("type"): ref.get("url") for ref in component.get("externalReferences", [])}
    downloads = _fmt_count(_prop(component, "hf:downloadsAllTime"))
    rows = [
        ("Model id", _mono(_model_id(component))),
        ("Publisher", _markup((component.get("supplier") or {}).get("name") or "unknown")),
        ("Commit", _mono(_prop(component, "hf:commitSha") or "not reported")),
        ("Library", _markup(_prop(component, "hf:libraryName") or "not reported")),
        ("Access", _markup(_access_label(_prop(component, "hf:accessMode")))),
        ("Created", _markup(_fmt_date(_prop(component, "hf:createdAt")))),
        ("Last modified", _markup(_fmt_date(_prop(component, "hf:lastModified")))),
        ("Downloads", _markup(f"{downloads} (all time)")),
        ("Likes", _markup(_fmt_count(_prop(component, "hf:likes")))),
        ("Repository", _mono(refs.get("website") or "")),
    ]
    return [_kv_table(rows, 34 * MM, CONTENT_WIDTH, styles), Spacer(1, 10)]


def _licence(component: dict[str, Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Spacer

    rows: list[tuple[str, str]] = []
    for item in component.get("licenses", []):
        licence = item.get("license", {})
        rows.append(("Declared", _markup(licence.get("id") or licence.get("name") or "unspecified")))
        if licence.get("url"):
            rows.append(("Licence text", _mono(licence["url"], 7.4)))
    if not rows:
        rows.append(("Declared", _markup("not declared on the model card")))
    return [
        _kv_table(rows, 34 * MM, CONTENT_WIDTH, styles),
        Spacer(1, 4),
        _paragraph(
            _markup(
                "This report records the licence the model card declares. It does not interpret the licence "
                "text. Read the linked terms before commercial use."
            ),
            styles["small"],
        ),
        Spacer(1, 8),
    ]


def _architecture(bom: dict[str, Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    component = bom["metadata"]["component"]
    params = component.get("modelCard", {}).get("modelParameters", {})
    context = _prop(component, "hf:contextLength")
    total = _prop(component, "hf:totalParameters")
    rows = [
        ("Task", _markup(params.get("task") or "not set")),
        ("Architecture", _mono(params.get("modelArchitecture") or "not reported")),
        ("Model family", _mono(params.get("architectureFamily") or "not reported")),
        ("Context length", _markup(_fmt_count(context) + " tokens" if context else "not reported")),
        ("Parameters", _markup(_fmt_params(total) if total not in (None, "unknown") else "unknown")),
        ("Weight dtypes", _markup(_weights_text(component))),
        ("Base model", _mono(_prop(component, "hf:baseModel") or "not declared")),
    ]
    flow: list[Any] = [_kv_table(rows, 34 * MM, CONTENT_WIDTH, styles), Spacer(1, 8)]
    flow.append(
        _paragraph(_markup("Training and evaluation datasets", "CloudySans-Medium"), styles["body_strong"])
    )
    datasets = params.get("datasets") or []
    if not datasets:
        flow.append(_paragraph(_markup("No datasets are listed on the model card."), styles["small"]))
    for dataset in datasets:
        line = _markup(dataset.get("name", "unnamed"))
        url = (dataset.get("contents") or {}).get("url")
        if url:
            line += f"&nbsp;&nbsp;{_mono(url, 6.8)}"
        flow.append(Paragraph(line, styles["bullet"], bulletText="\u2013"))
    flow.append(Spacer(1, 10))
    return flow


def _display_value(value: str) -> str:
    """Shorten a long decimal to four significant figures for print.

    Short values are kept as the card publishes them. The embedded JSON always keeps the full value.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(number) or len(value) <= 8:
        return value
    if abs(number) < 1:
        return f"{number:.4g}"
    integer_digits = len(str(int(abs(number))))
    decimals = max(0, 4 - integer_digits)
    return f"{number:.{decimals}f}"


def _evaluation(component: dict[str, Any], styles: dict[str, Any], width: float) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    metrics = component.get("modelCard", {}).get("quantitativeAnalysis", {}).get("performanceMetrics") or []
    if not metrics:
        return [
            _paragraph(
                _markup("No structured evaluation results (model-index) are published for this model."),
                styles["body"],
            ),
            Spacer(1, 10),
        ]
    rows = []
    for metric in metrics[:MAX_METRIC_ROWS]:
        rows.append(
            [
                Paragraph(_markup(metric.get("slice") or "unspecified"), styles["cell"]),
                Paragraph(_markup(metric.get("type", "metric"), "CloudyMono"), styles["cell_mono"]),
                Paragraph(_markup(_display_value(str(metric.get("value", "")))), styles["cell"]),
            ]
        )
    flow: list[Any] = [
        _grid_table(["Dataset", "Metric", "Value"], rows, [width * 0.56, width * 0.26, width * 0.18], styles)
    ]
    hidden = len(metrics) - MAX_METRIC_ROWS
    if hidden > 0:
        flow.append(Spacer(1, 4))
        flow.append(_paragraph(_markup(f"{hidden} more results are in the embedded JSON."), styles["small"]))
    flow.append(Spacer(1, 10))
    return flow


def _considerations(component: dict[str, Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import CondPageBreak, Spacer

    considerations = component.get("modelCard", {}).get("considerations", {})
    groups = [
        ("Intended users", considerations.get("users") or []),
        ("Use cases and out-of-scope use", considerations.get("useCases") or []),
        ("Technical limitations, risks and bias", considerations.get("technicalLimitations") or []),
        (
            "Ethical considerations",
            [item.get("name", "") for item in considerations.get("ethicalConsiderations") or []],
        ),
    ]
    flow: list[Any] = []
    for title, items in groups:
        flow.append(CondPageBreak(28 * MM))
        flow.append(_paragraph(_markup(title, "CloudySans-Medium"), styles["body_strong"]))
        if items:
            flow.extend(_bullets(items, styles))
        else:
            flow.append(_paragraph(_markup("Not documented on the model card."), styles["small"]))
        flow.append(Spacer(1, 6))
    return flow


def _files(bom: dict[str, Any], styles: dict[str, Any], width: float) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    component = bom["metadata"]["component"]
    files = [c for c in bom.get("components", []) if c.get("type") == "file"]
    if not files:
        return [
            _paragraph(
                _markup("The repository file list was not available when this report was generated."),
                styles["body"],
            ),
            Spacer(1, 10),
        ]
    rows = []
    for item in files[:MAX_FILE_ROWS]:
        digest = (item.get("hashes") or [{}])[0].get("content")
        role = _prop(item, "aibom:fileRole") or "other"
        digest_cell = (
            Paragraph(_mono(digest, 6.9), styles["cell_mono"])
            if digest
            else Paragraph(_markup("no LFS digest (git object)"), styles["small"])
        )
        rows.append(
            [
                Paragraph(_mono(item.get("name", ""), 7.0), styles["cell_mono"]),
                Paragraph(_markup(role), styles["cell"]),
                Paragraph(_markup(_fmt_bytes(_prop(item, "hf:sizeBytes"))), styles["cell"]),
                digest_cell,
            ]
        )
    flow: list[Any] = [
        _grid_table(
            ["Path", "Role", "Size", "SHA-256"],
            rows,
            [width * 0.30, width * 0.13, width * 0.12, width * 0.45],
            styles,
        )
    ]
    total = _as_int(_prop(component, "hf:fileCount")) or len(files)
    hidden = total - min(len(files), MAX_FILE_ROWS)
    if hidden > 0:
        flow.append(Spacer(1, 4))
        flow.append(
            _paragraph(_markup(f"{hidden} more files are listed in the embedded JSON."), styles["small"])
        )
    flow.append(Spacer(1, 10))
    return flow


def _checklist(completeness: dict[str, Any], styles: dict[str, Any], width: float) -> list[Any]:
    from reportlab.platypus import Paragraph, Spacer

    rows = []
    for row in completeness.get("breakdown", []):
        present = bool(row.get("present"))
        status = Paragraph(
            _markup("PRESENT" if present else "MISSING", "CloudyMono-Medium"),
            styles["pill_ok" if present else "pill_bad"],
        )
        rows.append(
            [
                status,
                Paragraph(_markup(row.get("label", "")), styles["cell"]),
                Paragraph(_mono(f"{row.get('weight', 0)} pts", 7.2), styles["cell_mono"]),
            ]
        )
    return [
        _grid_table(["Status", "Check", "Weight"], rows, [width * 0.16, width * 0.66, width * 0.18], styles),
        Spacer(1, 6),
        _paragraph(
            _markup(
                "The score measures how much documentation is present. It does not measure model quality, "
                "safety or "
                "legal compliance. Bands: 80 and above is well documented, 50 to 79 is partly documented, "
                "below 50 is "
                "sparsely documented."
            ),
            styles["small"],
        ),
        Spacer(1, 10),
    ]


def _verification(styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Spacer

    steps = [
        "Compare each SHA-256 digest with the file you download, for example with sha256sum on Linux or "
        "macOS, "
        "or Get-FileHash on Windows. Only files stored in Git LFS have a SHA-256 digest in this report.",
        "Validate the embedded aibom.cdx.json against the CycloneDX 1.6 JSON schema (bom-1.6.schema.json) "
        "using any "
        "CycloneDX-compatible tool.",
        "Check the commit reference against the model repository to confirm that this report describes the "
        "revision you use.",
    ]
    return [*_bullets(steps, styles), Spacer(1, 10), _paragraph(_markup(REPORT_DISCLAIMER), styles["note"])]


def _body(bom: dict[str, Any], completeness: dict[str, Any], styles: dict[str, Any]) -> list[Any]:
    from reportlab.platypus import Spacer

    component = bom["metadata"]["component"]
    width = CONTENT_WIDTH
    flow: list[Any] = []
    flow += _section("01", "Identity", styles, _identity(component, styles))
    flow += _section("02", "Licence", styles, _licence(component, styles))
    flow += _section("03", "Architecture and data", styles, _architecture(bom, styles))
    flow += _section("04", "Evaluation results", styles, _evaluation(component, styles, width))
    flow += _section("05", "Considerations", styles, _considerations(component, styles))
    flow.append(Spacer(1, 6))
    flow += _section("06", "Files and digests", styles, _files(bom, styles, width))
    flow += _section("07", "Completeness checklist", styles, _checklist(completeness, styles, width))
    flow += _section("08", "Verification", styles, _verification(styles))
    return flow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_report_pdf(bom: dict[str, Any], completeness: dict[str, Any]) -> bytes:
    """Return the PDF for ``bom`` (a CycloneDX dict) and its completeness score.

    The CycloneDX JSON is embedded as an attachment named ``aibom.cdx.json``.
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.platypus import BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate

    _register_fonts()
    component = bom["metadata"]["component"]
    model_id = _model_id(component)
    generated = _fmt_timestamp(bom.get("metadata", {}).get("timestamp"))
    footer = f"Generated {generated}  ·  CloudyAI Model Hub {__version__}  ·  Verify before compliance use"

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=(A4_WIDTH, A4_HEIGHT),
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"AI Bill of Materials: {model_id}",
        author="CloudyAI Model Hub",
        subject="CycloneDX 1.6 ML-BOM report with documentation completeness score",
        creator=f"CloudyAI Model Hub {__version__}",
        keywords="AIBOM, CycloneDX, Hugging Face, model card, compliance",
    )
    cover_frame = Frame(
        MARGIN_X, BOTTOM_MARGIN, CONTENT_WIDTH, A4_HEIGHT - 14 * MM - BOTTOM_MARGIN, id="cover"
    )
    body_frame = Frame(
        MARGIN_X, BOTTOM_MARGIN, CONTENT_WIDTH, A4_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN, id="body"
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="Cover", frames=[cover_frame], onPage=_decorate_cover),
            PageTemplate(id="Body", frames=[body_frame], onPage=_decorate_body(model_id)),
        ]
    )

    styles = _styles()
    story: list[Any] = _cover(bom, completeness, styles)
    story += [NextPageTemplate("Body"), PageBreak()]
    story += _body(bom, completeness, styles)
    doc.build(story, canvasmaker=_numbered_canvas(footer))

    reader = PdfReader(io.BytesIO(buffer.getvalue()))
    writer = PdfWriter(clone_from=reader)
    payload = json.dumps(bom, indent=2, ensure_ascii=False).encode("utf-8")
    writer.add_attachment("aibom.cdx.json", payload)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
