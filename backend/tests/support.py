"""Helpers shared by the test modules: fixture loading and offline CycloneDX schema validation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from backend.tests.fake_hub import FIXTURES_DIR

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas" / "cyclonedx"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture(name: str) -> dict[str, Any]:
    """Return ``info``, ``readme``, ``config`` and ``files`` for one fixture directory.

    Optional parts that a fixture does not provide are ``None``, which mirrors what the Hub client
    returns when a file is missing.
    """
    folder = FIXTURES_DIR / name
    readme_path = folder / "README.md"
    config_path = folder / "config.json"
    tree_path = folder / "tree.json"
    return {
        "info": _read_json(folder / "info.json"),
        "readme": readme_path.read_text(encoding="utf-8") if readme_path.exists() else None,
        "config": _read_json(config_path) if config_path.exists() else None,
        "files": _read_json(tree_path) if tree_path.exists() else None,
    }


@lru_cache(maxsize=1)
def _bom_validator() -> jsonschema.Draft7Validator:
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        document = _read_json(path)
        resources.append((document["$id"], Resource.from_contents(document, default_specification=DRAFT7)))
    registry = Registry().with_resources(resources)
    main_schema = _read_json(SCHEMA_DIR / "bom-1.6.schema.json")
    return jsonschema.Draft7Validator(main_schema, registry=registry)


def bom_schema_errors(bom: dict[str, Any]) -> list[str]:
    """Human-readable schema violations for ``bom`` (empty when it is valid CycloneDX 1.6 JSON)."""
    errors = sorted(_bom_validator().iter_errors(bom), key=lambda error: [str(part) for part in error.path])
    return [f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in errors]
