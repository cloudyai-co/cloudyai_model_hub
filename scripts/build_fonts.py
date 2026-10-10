#!/usr/bin/env python3
"""Regenerate the bundled IBM Plex fonts used by the web UI and the PDF report.

Sources are the official IBM Plex npm packages (``@ibm/plex-sans``, ``@ibm/plex-serif``,
``@ibm/plex-mono``), distributed under the SIL Open Font License 1.1.

* **Web UI** (``frontend/fonts``): the unmodified WOFF2 files that IBM ships in its "split" builds.
  They are copied as-is, so they keep their original names.
* **PDF report** (``backend/assets/fonts``): TrueType subsets converted from the "complete"
  WOFF2 files and limited to Latin, Greek, Cyrillic, Vietnamese and common typographic symbols.
  The OFL reserves the name "Plex" for unmodified versions, so the subsets are renamed to
  "CloudySans", "CloudySerif" and "CloudyMono". The copyright notice is kept, as the licence requires.

Usage::

    mkdir -p /tmp/plex && cd /tmp/plex
    for p in plex-sans plex-serif plex-mono; do
      npm pack @ibm/$p@latest >/dev/null && mkdir -p $p && tar -xzf ibm-$p-*.tgz -C $p
    done
    python scripts/build_fonts.py --source /tmp/plex

Requires ``fonttools`` and ``brotli`` (``pip install fonttools brotli``).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parent.parent
WEB_OUT = REPO / "frontend" / "fonts"
PDF_OUT = REPO / "backend" / "assets" / "fonts"

#: Split WOFF2 files shipped to browsers (IBM's own unicode-range subsets).
WEB_FILES = [
    ("plex-sans", "IBMPlexSans-Regular"),
    ("plex-sans", "IBMPlexSans-Medium"),
    ("plex-sans", "IBMPlexSans-SemiBold"),
    ("plex-serif", "IBMPlexSerif-Regular"),
    ("plex-serif", "IBMPlexSerif-Italic"),
    ("plex-mono", "IBMPlexMono-Regular"),
    ("plex-mono", "IBMPlexMono-Medium"),
]
WEB_SUBSETS = ("Latin1", "Latin2")

#: (package dir, source name, output name, PostScript name, family name)
PDF_FONTS = [
    ("plex-sans", "IBMPlexSans-Regular", "CloudySans-Regular", "CloudySans-Regular", "CloudySans"),
    ("plex-sans", "IBMPlexSans-Medium", "CloudySans-Medium", "CloudySans-Medium", "CloudySans Medium"),
    (
        "plex-sans",
        "IBMPlexSans-SemiBold",
        "CloudySans-SemiBold",
        "CloudySans-SemiBold",
        "CloudySans SemiBold",
    ),
    ("plex-serif", "IBMPlexSerif-Regular", "CloudySerif-Regular", "CloudySerif-Regular", "CloudySerif"),
    ("plex-serif", "IBMPlexSerif-Medium", "CloudySerif-Medium", "CloudySerif-Medium", "CloudySerif Medium"),
    ("plex-serif", "IBMPlexSerif-Italic", "CloudySerif-Italic", "CloudySerif-Italic", "CloudySerif Italic"),
    ("plex-mono", "IBMPlexMono-Regular", "CloudyMono-Regular", "CloudyMono-Regular", "CloudyMono"),
    ("plex-mono", "IBMPlexMono-Medium", "CloudyMono-Medium", "CloudyMono-Medium", "CloudyMono Medium"),
]

UNICODE_RANGES: list[tuple[int, int]] = [
    (0x0020, 0x007E),  # Basic Latin
    (0x00A0, 0x024F),  # Latin-1 Supplement, Latin Extended-A and -B
    (0x0370, 0x03FF),  # Greek
    (0x0400, 0x04FF),  # Cyrillic
    (0x1E00, 0x1EFF),  # Latin Extended Additional (Vietnamese)
    (0x2010, 0x2027),  # dashes, quotation marks, bullets
    (0x2030, 0x205E),  # per mille, primes, misc punctuation
    (0x20AC, 0x20AC),  # euro sign
    (0x2122, 0x2122),  # trade mark sign
    (0x2190, 0x21FF),  # arrows
    (0x2200, 0x22FF),  # mathematical operators
    (0x2713, 0x2714),  # check marks
]


def _unicodes() -> list[int]:
    codepoints: list[int] = []
    for start, end in UNICODE_RANGES:
        codepoints.extend(range(start, end + 1))
    return codepoints


def _set_names(font: TTFont, family: str, postscript: str) -> None:
    """Rename the font. Name IDs 0 (copyright) and 13 (licence) are left untouched."""
    name_table = font["name"]
    full = f"{family} ({postscript.split('-', 1)[-1]})" if "-" in postscript else family
    replacements = {
        1: family,
        2: "Regular",
        3: f"{postscript};CloudyAI subset",
        4: full,
        6: postscript,
    }
    name_table.names = [record for record in name_table.names if record.nameID not in (16, 17, 25)]
    for name_id, value in replacements.items():
        name_table.setName(value, name_id, 3, 1, 0x409)
        name_table.setName(value, name_id, 1, 0, 0)


def build_pdf_font(
    source: Path, out_dir: Path, package: str, source_name: str, out_name: str, postscript: str, family: str
) -> Path:
    src = source / package / "package" / "fonts" / "complete" / "woff2" / f"{source_name}.woff2"
    if not src.exists():
        raise FileNotFoundError(f"Missing font source: {src}")
    font = TTFont(str(src))
    font.flavor = None  # WOFF2 -> sfnt (TrueType outlines are already glyf-based)

    options = subset.Options()
    options.layout_features = ["kern", "liga", "calt", "tnum", "ccmp", "locl", "mark", "mkmk", "case"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.hinting = False
    options.drop_tables += ["DSIG"]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=_unicodes())
    subsetter.subset(font)

    _set_names(font, family, postscript)
    out = out_dir / f"{out_name}.ttf"
    font.save(str(out))
    return out


def copy_web_fonts(source: Path, out_dir: Path) -> list[Path]:
    written: list[Path] = []
    for package, base in WEB_FILES:
        for subset_name in WEB_SUBSETS:
            name = f"{base}-{subset_name}.woff2"
            src = source / package / "package" / "fonts" / "split" / "woff2" / name
            if not src.exists():
                print(f"  skip (not in package): {name}")
                continue
            dst = out_dir / name
            shutil.copyfile(src, dst)
            written.append(dst)
    return written


def copy_licence(source: Path, dirs: list[Path]) -> None:
    licence = source / "plex-sans" / "package" / "LICENSE.txt"
    if not licence.exists():
        raise FileNotFoundError(f"Missing licence text: {licence}")
    for directory in dirs:
        shutil.copyfile(licence, directory / "OFL.txt")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="Directory with extracted IBM Plex packages"
    )
    parser.add_argument("--skip-web", action="store_true", help="Only rebuild the PDF fonts")
    args = parser.parse_args(argv)
    source = args.source.resolve()

    PDF_OUT.mkdir(parents=True, exist_ok=True)
    WEB_OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory():
        if not args.skip_web:
            print("Copying web fonts (unmodified IBM split WOFF2 files)...")
            for path in copy_web_fonts(source, WEB_OUT):
                print(f"  {path.relative_to(REPO)}")
        print("Building PDF font subsets (renamed, OFL)...")
        for package, source_name, out_name, postscript, family in PDF_FONTS:
            out = build_pdf_font(source, PDF_OUT, package, source_name, out_name, postscript, family)
            print(f"  {out.relative_to(REPO)}  ({out.stat().st_size // 1024} KB)")
    copy_licence(source, [WEB_OUT, PDF_OUT])
    print("Licence copied to frontend/fonts/OFL.txt and backend/assets/fonts/OFL.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
