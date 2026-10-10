"""Packaging and deployment wiring: version numbers, the Vercel entrypoint, bundled assets and licences."""

from __future__ import annotations

import importlib
import json
import tomllib
from pathlib import Path

from fastapi import FastAPI

from backend import __version__

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_package_version_matches_the_application_version() -> None:
    assert _pyproject()["project"]["version"] == __version__


def test_runtime_dependencies_are_declared_in_pyproject() -> None:
    names = {
        dep.split(">")[0].split("[")[0].split("=")[0].strip()
        for dep in _pyproject()["project"]["dependencies"]
    }
    assert {"fastapi", "httpx", "pypdf", "reportlab"} <= names


def test_vercel_entrypoint_is_importable_fastapi_app() -> None:
    entrypoint = _pyproject()["tool"]["vercel"]["entrypoint"]
    module_name, attribute = entrypoint.split(":")
    app = getattr(importlib.import_module(module_name), attribute)
    assert isinstance(app, FastAPI)


def test_vercel_function_config_is_keyed_by_the_entrypoint_file() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    module_name = _pyproject()["tool"]["vercel"]["entrypoint"].split(":")[0]
    assert f"{module_name.replace('.', '/')}.py" in config["functions"]


def test_static_files_are_promoted_to_the_cdn() -> None:
    assert _pyproject()["tool"]["vercel"]["fastapi"]["static"]["cdn"] is True


def test_function_bundle_excludes_tests_and_docs() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    patterns = " ".join(config["functions"]["backend/main.py"]["excludeFiles"])
    assert "backend/tests" in patterns and "docs" in patterns


def test_bundled_pdf_fonts_and_licence_are_present() -> None:
    fonts = sorted(path.name for path in (ROOT / "backend" / "assets" / "fonts").glob("*.ttf"))
    assert len(fonts) == 8
    assert all(name.startswith(("CloudySans", "CloudySerif", "CloudyMono")) for name in fonts)
    assert "SIL OPEN FONT LICENSE" in (ROOT / "backend" / "assets" / "fonts" / "OFL.txt").read_text(
        encoding="utf-8"
    )


def test_web_fonts_and_licence_are_present() -> None:
    assert len(list((ROOT / "frontend" / "fonts").glob("*.woff2"))) == 14
    assert "SIL OPEN FONT LICENSE" in (ROOT / "frontend" / "fonts" / "OFL.txt").read_text(encoding="utf-8")


def test_project_licence_is_apache_2() -> None:
    assert "Apache License" in (ROOT / "LICENSE").read_text(encoding="utf-8")[:200]
    assert _pyproject()["project"]["license"] == "Apache-2.0"
