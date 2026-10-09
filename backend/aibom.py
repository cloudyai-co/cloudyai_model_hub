"""Build CycloneDX 1.6 AI Bills of Materials (AIBOMs) from Hugging Face metadata.

The document has three parts:

* ``metadata.component`` is the model itself (``machine-learning-model``) with the
  CycloneDX ML-BOM ``modelCard`` extension: task, architecture, datasets, performance
  metrics and considerations (use cases, limitations, ethics) taken from the model card.
* ``components`` lists the model's files (weights, configuration, tokenizer, licence,
  documentation). Files stored in Git LFS carry their SHA-256 digest, which is what a
  supply-chain reviewer usually needs to verify an artefact.
* ``dependencies`` links the model to those files.

Alongside the BOM we compute a transparent *documentation completeness* score. It
measures how much of the information a reviewer typically asks for is present. It says
nothing about whether the model is safe or compliant.

References:
* CycloneDX 1.6 JSON reference: https://cyclonedx.org/docs/1.6/json/
* ML-BOM modelCard: https://cyclonedx.org/docs/1.6/json/#metadata_component_modelCard

Validate output against the official CycloneDX schema (see ``backend/tests``) before
relying on it in compliance-critical workflows.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from . import __version__

CYCLONEDX_SPEC_VERSION = "1.6"
TOOL_NAME = "cloudyai-aibom-generator"
PUBLIC_HUB = "https://huggingface.co"

MAX_FILE_COMPONENTS = 200
MAX_LIST_ITEMS = 25
MAX_ITEM_CHARS = 800
MAX_DESCRIPTION_CHARS = 1000

#: Hugging Face licence tags that are valid SPDX identifiers (matched case-insensitively).
#: The values are the canonical SPDX spelling; every value is present in the CycloneDX SPDX enum.
SPDX_LICENSE_IDS: dict[str, str] = {
    "apache-2.0": "Apache-2.0",
    "mit": "MIT",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "cc0-1.0": "CC0-1.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
    "gpl-3.0": "GPL-3.0",
    "lgpl-3.0": "LGPL-3.0",
    "agpl-3.0": "AGPL-3.0-only",
    "mpl-2.0": "MPL-2.0",
    "unlicense": "Unlicense",
}

#: Common licence tags that are *not* SPDX identifiers. They are reported by name instead.
LICENSE_NAMES: dict[str, str] = {
    "openrail": "OpenRAIL",
    "openrail++": "OpenRAIL++",
    "creativeml-openrail-m": "CreativeML OpenRAIL-M",
    "bigscience-openrail-m": "BigScience OpenRAIL-M",
    "bigscience-bloom-rail-1.0": "BigScience BLOOM RAIL 1.0",
    "llama2": "Llama 2 Community License",
    "llama3": "Llama 3 Community License",
    "llama3.1": "Llama 3.1 Community License",
    "llama3.2": "Llama 3.2 Community License",
    "llama3.3": "Llama 3.3 Community License",
    "gemma": "Gemma Terms of Use",
    "other": "Other (see licence link)",
}

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_ATX_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)")
_EMPHASIS_RE = re.compile(r"\*\*|__|`")
_SPACE_RE = re.compile(r"\s+")

# Section-title patterns used to pull prose out of a model card.
USE_CASE_RE = re.compile(
    r"\b(uses?|use cases?|direct use|downstream use|intended uses?|out[- ]of[- ]scope)\b", re.IGNORECASE
)
LIMITATION_RE = re.compile(r"\b(limitations?|bias|risks?|known issues|caveats)\b", re.IGNORECASE)
ETHICS_RE = re.compile(
    r"\b(ethical|ethics|responsible use|misuse|societal impact|safety considerations)\b", re.IGNORECASE
)
USERS_RE = re.compile(r"\b(intended users?|target users?|who should use)\b", re.IGNORECASE)

_FILE_ROLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "weights",
        re.compile(
            r"\.(safetensors|bin|pt|pth|ckpt|gguf|ggml|onnx|h5|msgpack|tflite|mlpackage)$", re.IGNORECASE
        ),
    ),
    (
        "configuration",
        re.compile(
            r"(^|/)(config|generation_config|preprocessor_config|processor_config|adapter_config|quantize_config)\.json$",
            re.IGNORECASE,
        ),
    ),
    (
        "tokenizer",
        re.compile(
            r"(^|/)(tokenizer[^/]*|vocab\.(json|txt)|merges\.txt|spiece\.model|sentencepiece[^/]*|"
            r"special_tokens_map\.json|added_tokens\.json)$",
            re.IGNORECASE,
        ),
    ),
    ("license", re.compile(r"(^|/)(LICEN[CS]E[^/]*|COPYING[^/]*|NOTICE[^/]*)$", re.IGNORECASE)),
    ("documentation", re.compile(r"(^|/)(README[^/]*|[^/]*\.(md|rst|txt))$", re.IGNORECASE)),
    ("code", re.compile(r"\.(py|js|ts|cpp|cc|c|h|cu|rs|go)$", re.IGNORECASE)),
)


# ---------------------------------------------------------------------------
# Model card helpers
# ---------------------------------------------------------------------------


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_frontmatter(readme: str) -> str:
    return _FRONTMATTER_RE.sub("", readme, count=1)


def _sections(readme: str | None) -> list[tuple[int, str, list[str]]]:
    """Split a model card into ``(level, title, body_lines)`` tuples.

    * Fenced code blocks are skipped entirely, so ``# comment`` lines inside them are never
      mistaken for headings and their contents never leak into prose.
    * HTML comments are removed first.
    * The first tuple is the preamble before any heading (level 0, empty title).
    """
    if not readme:
        return []
    text = _HTML_COMMENT_RE.sub("", _strip_frontmatter(_normalize_newlines(readme)))
    sections: list[tuple[int, str, list[str]]] = [(0, "", [])]
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        header = _ATX_HEADER_RE.match(line)
        if header:
            sections.append((len(header.group(1)), header.group(2).strip(), []))
            continue
        sections[-1][2].append(line)
    return sections


def _clean_markdown(text: str) -> str:
    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _EMPHASIS_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def _paragraphs(lines: Iterable[str], prefix: str | None = None) -> list[str]:
    """Turn body lines into prose items: one per paragraph and one per bullet. Tables are skipped."""
    items: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            items.append(" ".join(buffer))
            buffer.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("|"):
            flush()
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            flush()
            buffer.append(bullet.group(1))
            flush()
            continue
        buffer.append(line)
    flush()

    cleaned = [_clean_markdown(item)[:MAX_ITEM_CHARS] for item in items]
    cleaned = [item for item in cleaned if len(item) >= 3]
    if prefix and cleaned:
        cleaned[0] = f"{prefix}: {cleaned[0]}"
    return cleaned


CATEGORY_USE = "use"
CATEGORY_LIMITATIONS = "limitations"
CATEGORY_ETHICS = "ethics"
CATEGORY_USERS = "users"


def _category_for(title: str) -> str | None:
    """Assign a heading to exactly one category, so the same prose is never listed twice.

    Ethics and users are checked first because their headings are the most specific. A heading such as
    "Intended uses & limitations" therefore counts as a use-case section.
    """
    if ETHICS_RE.search(title):
        return CATEGORY_ETHICS
    if USERS_RE.search(title):
        return CATEGORY_USERS
    if USE_CASE_RE.search(title):
        return CATEGORY_USE
    if LIMITATION_RE.search(title):
        return CATEGORY_LIMITATIONS
    return None


def _extract_sections(readme: str | None, category: str) -> list[str]:
    """Prose from every heading in ``category``, including the sub-headings nested under it.

    A sub-heading title is prefixed to its first paragraph, so "Direct Use" stays readable on its own.
    Headings nested inside an already-captured section are not captured twice.
    """
    sections = _sections(readme)
    items: list[str] = []
    index = 1  # skip the preamble
    while index < len(sections):
        level, title, body = sections[index]
        if _category_for(title) != category:
            index += 1
            continue
        items.extend(_paragraphs(body))
        end = index + 1
        while end < len(sections) and sections[end][0] > level:
            child_title, child_body = sections[end][1], sections[end][2]
            items.extend(_paragraphs(child_body, prefix=child_title))
            end += 1
        index = end
    return items[:MAX_LIST_ITEMS]


def _intro_paragraph(readme: str | None) -> str:
    """The first real sentence-bearing paragraph of the card, used when no description is given."""
    for _, _, body in _sections(readme):
        for item in _paragraphs(body):
            if len(item) >= 40:
                return item[:MAX_DESCRIPTION_CHARS]
    return ""


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _license_value(info: dict[str, Any], card: dict[str, Any]) -> list[str]:
    """Licence tags from card data, falling back to a ``license:`` tag on the model."""
    values = _as_list(card.get("license"))
    if not values:
        for tag in info.get("tags") or []:
            if isinstance(tag, str) and tag.startswith("license:"):
                values.append(tag.split(":", 1)[1])
                break
    return values


def _is_public_link(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _license_entries(info: dict[str, Any], card: dict[str, Any]) -> list[dict[str, Any]]:
    values = _license_value(info, card)
    link = card.get("license_link")
    custom_name = card.get("license_name")
    entries: list[dict[str, Any]] = []
    for value in values:
        key = value.lower()
        if key in SPDX_LICENSE_IDS:
            license_obj: dict[str, Any] = {"id": SPDX_LICENSE_IDS[key]}
        else:
            name = custom_name if key == "other" and custom_name else LICENSE_NAMES.get(key, value)
            license_obj = {"name": str(name)}
        if len(values) == 1 and _is_public_link(link):
            license_obj["url"] = link
        entries.append({"license": license_obj})
    return entries


def _model_index(info: dict[str, Any], card: dict[str, Any]) -> list[Any]:
    """``model-index`` (evaluation results). The Hub returns it at the top level; some cards nest it."""
    value = info.get("model-index") or card.get("model-index")
    return value if isinstance(value, list) else []


def _dataset_entries(card: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name in _as_list(card.get("datasets"))[:MAX_LIST_ITEMS]:
        entry: dict[str, Any] = {"type": "dataset", "name": name}
        if "/" in name:
            entry["contents"] = {"url": f"{PUBLIC_HUB}/datasets/{name}"}
        entries.append(entry)
    return entries


def _performance_metrics(model_index: list[Any]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for entry in model_index:
        if not isinstance(entry, dict):
            continue
        for result in entry.get("results") or []:
            if not isinstance(result, dict):
                continue
            dataset = result.get("dataset") or {}
            dataset_name = dataset.get("name") if isinstance(dataset, dict) else None
            for metric in result.get("metrics") or []:
                if not isinstance(metric, dict) or metric.get("value") is None:
                    continue
                metrics.append(
                    {
                        "type": str(metric.get("type") or metric.get("name") or "metric"),
                        "value": str(metric.get("value")),
                        "slice": dataset_name,
                    }
                )
    return metrics


def _model_name_parts(model_id: str) -> tuple[str, str]:
    parts = model_id.split("/")
    return (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])


def _safetensors_dtypes(info: dict[str, Any]) -> str | None:
    parameters = (info.get("safetensors") or {}).get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        return None
    return ",".join(f"{dtype}:{count}" for dtype, count in sorted(parameters.items()))


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)


def _prune(value: Any) -> Any:
    """Drop ``None``, empty strings, empty lists and empty objects, recursively.

    CycloneDX forbids ``null`` for optional fields, and empty containers only add noise. ``False``
    and ``0`` are real values and are kept.
    """
    if isinstance(value, dict):
        pruned = {key: _prune(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if not _is_empty(item)}
    if isinstance(value, list):
        pruned_items = [_prune(item) for item in value]
        return [item for item in pruned_items if not _is_empty(item)]
    return value


def _file_role(path: str) -> str:
    for role, pattern in _FILE_ROLE_RULES:
        if pattern.search(path):
            return role
    return "other"


def _file_component(entry: dict[str, Any]) -> dict[str, Any] | None:
    path = entry.get("path")
    if not isinstance(path, str) or not path or entry.get("type") != "file":
        return None
    properties: list[dict[str, str]] = [
        {"name": "aibom:fileRole", "value": _file_role(path)},
    ]
    size = entry.get("size")
    if isinstance(size, int):
        properties.append({"name": "hf:sizeBytes", "value": str(size)})
    component: dict[str, Any] = {
        "type": "file",
        "bom-ref": f"file:{path}",
        "name": path,
    }
    lfs = entry.get("lfs") if isinstance(entry.get("lfs"), dict) else {}
    digest = lfs.get("oid")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
        component["hashes"] = [{"alg": "SHA-256", "content": digest}]
        properties.append({"name": "hf:storage", "value": "lfs"})
    else:
        properties.append({"name": "hf:storage", "value": "git"})
        if isinstance(entry.get("oid"), str):
            properties.append({"name": "hf:gitObjectId", "value": entry["oid"]})
    if isinstance(entry.get("xetHash"), str):
        properties.append({"name": "hf:xetHash", "value": entry["xetHash"]})
    component["properties"] = properties
    return component


_ROLE_ORDER = {"weights": 0, "configuration": 1, "tokenizer": 2, "license": 3, "documentation": 4}


def _component_property(component: dict[str, Any], name: str) -> str | None:
    for prop in component["properties"]:
        if prop["name"] == name:
            return prop["value"]
    return None


def _file_components(files: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], int, int]:
    """Return ``(components, total_file_count, total_bytes)``.

    Weights come first, then configuration, tokenizer, licence and documentation; within a role,
    larger files come first. The list is capped at ``MAX_FILE_COMPONENTS``; the true count is kept
    in the ``hf:fileCount`` property.
    """
    components = [c for c in (_file_component(e) for e in files or []) if c is not None]
    total_bytes = sum(int(_component_property(c, "hf:sizeBytes") or 0) for c in components)

    def sort_key(component: dict[str, Any]) -> tuple[int, int]:
        role = _component_property(component, "aibom:fileRole") or "other"
        size = int(_component_property(component, "hf:sizeBytes") or 0)
        return (_ROLE_ORDER.get(role, 9), -size)

    ordered = sorted(components, key=sort_key)
    return ordered[:MAX_FILE_COMPONENTS], len(components), total_bytes


def _props(pairs: Iterable[tuple[str, Any]]) -> list[dict[str, str]]:
    """``(name, value)`` pairs to CycloneDX properties. Unknown (``None``) values are omitted."""
    return [{"name": name, "value": _as_property_value(value)} for name, value in pairs if value is not None]


def _as_property_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# AIBOM construction
# ---------------------------------------------------------------------------


def build_aibom(
    model_id: str,
    info: dict[str, Any],
    readme: str | None,
    config: dict[str, Any] | None,
    files: list[dict[str, Any]] | None = None,
    *,
    generated_at: datetime | None = None,
    serial_number: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(bom, completeness)`` for one model.

    Args:
        model_id: canonical ``org/name`` id.
        info: model metadata from ``GET /api/models/{id}``.
        readme: the model card (Markdown) or ``None``.
        config: the architecture config (``config.json``) or ``None``.
        files: entries from the repository tree, or ``None`` when it was not fetched.
        generated_at: timestamp to embed (defaults to now, UTC). Pass a fixed value in tests.
        serial_number: ``urn:uuid:`` serial to use (defaults to a random UUID).
    """
    info = info or {}
    card = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    config = config or {}
    group, name = _model_name_parts(model_id)
    generated_at = (generated_at or datetime.now(UTC)).astimezone(UTC)
    model_index = _model_index(info, card)

    commit = info.get("sha") if isinstance(info.get("sha"), str) else None
    card_description = card.get("description") if isinstance(card.get("description"), str) else ""
    description_text = card_description.strip() or _intro_paragraph(readme)

    total_params = (info.get("safetensors") or {}).get("total")
    base_model = _as_list(card.get("base_model"))
    context_length = config.get("max_position_embeddings")
    file_components, file_count, total_bytes = _file_components(files)

    model_ref = f"model:{model_id}"
    limitations = _extract_sections(readme, CATEGORY_LIMITATIONS)
    ethics = _extract_sections(readme, CATEGORY_ETHICS)
    use_cases = _extract_sections(readme, CATEGORY_USE)
    users = _extract_sections(readme, CATEGORY_USERS)

    external_references: list[dict[str, str]] = [
        {"type": "website", "url": f"{PUBLIC_HUB}/{model_id}"},
        {"type": "distribution", "url": f"{PUBLIC_HUB}/{model_id}/tree/main"},
        {"type": "documentation", "url": f"{PUBLIC_HUB}/{model_id}/blob/main/README.md"},
    ]
    license_link = card.get("license_link")
    if _is_public_link(license_link):
        external_references.append({"type": "license", "url": license_link})

    model_component: dict[str, Any] = {
        "type": "machine-learning-model",
        "bom-ref": model_ref,
        "supplier": _supplier(info, group),
        "group": group or None,
        "name": name,
        "version": (commit[:12] if commit else "main"),
        "description": description_text[:MAX_DESCRIPTION_CHARS] or None,
        "licenses": _license_entries(info, card),
        "externalReferences": external_references,
        "modelCard": {
            "modelParameters": {
                "task": info.get("pipeline_tag"),
                "architectureFamily": config.get("model_type"),
                "modelArchitecture": (_as_list(config.get("architectures")) or [None])[0],
                "datasets": _dataset_entries(card),
            },
            "quantitativeAnalysis": {"performanceMetrics": _performance_metrics(model_index)},
            "considerations": {
                "users": users,
                "useCases": use_cases,
                "technicalLimitations": limitations,
                "ethicalConsiderations": [{"name": item} for item in ethics],
            },
        },
        "properties": _props(
            [
                ("hf:downloads", info.get("downloads")),
                ("hf:downloadsAllTime", info.get("downloadsAllTime")),
                ("hf:likes", info.get("likes")),
                ("hf:libraryName", info.get("library_name")),
                ("hf:accessMode", _access_mode(info.get("gated"))),
                ("hf:private", bool(info.get("private"))),
                ("hf:lastModified", info.get("lastModified")),
                ("hf:createdAt", info.get("createdAt")),
                ("hf:commitSha", commit),
                ("hf:totalParameters", total_params or "unknown"),
                ("hf:weightDtypes", _safetensors_dtypes(info)),
                ("hf:baseModel", ", ".join(base_model) if base_model else None),
                ("hf:contextLength", context_length),
                ("hf:fileCount", file_count if files is not None else None),
                ("hf:totalSizeBytes", total_bytes if files is not None else None),
            ]
        ),
    }

    completeness = score_completeness(info, card, readme, config)
    model_component["properties"] += _props(
        [
            ("aibom:completenessScore", completeness["score"]),
            ("aibom:completenessLevel", completeness["level"]),
        ]
    )

    bom: dict[str, Any] = {
        "$schema": f"http://cyclonedx.org/schema/bom-{CYCLONEDX_SPEC_VERSION}.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": serial_number or f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": {
                "components": [
                    {"type": "application", "name": TOOL_NAME, "version": __version__},
                ]
            },
            "component": model_component,
        },
        "components": file_components,
    }
    if file_components:
        bom["dependencies"] = [{"ref": model_ref, "dependsOn": [c["bom-ref"] for c in file_components]}]
    bom = _prune(bom)
    bom.setdefault("components", [])
    return bom, completeness


def _supplier(info: dict[str, Any], group: str) -> dict[str, Any] | None:
    author = info.get("author") if isinstance(info.get("author"), str) else None
    name = author or group
    if not name:
        return None
    return {"name": name, "url": [f"{PUBLIC_HUB}/{name}"]}


def _access_mode(gated: Any) -> str:
    """``gated`` is ``false``, ``"auto"`` (instant approval) or ``"manual"`` (reviewed) on the Hub."""
    if gated in (False, None, "", "false", 0):
        return "open"
    if gated == "auto":
        return "gated-auto"
    if gated == "manual":
        return "gated-manual"
    return "gated"


# ---------------------------------------------------------------------------
# Completeness score
# ---------------------------------------------------------------------------

# (key, label, weight). Weights sum to 100.
CHECKS: list[tuple[str, str, int]] = [
    ("license", "License declared", 10),
    ("description", "Description or summary present", 8),
    ("pipeline_tag", "Task (pipeline tag) set", 6),
    ("architecture", "Architecture config available (config.json)", 10),
    ("datasets", "Training datasets listed", 10),
    ("intended_use", "Intended use or use cases documented", 12),
    ("limitations", "Limitations, risks or bias section present", 12),
    ("ethical_considerations", "Ethical considerations documented", 8),
    ("eval_results", "Evaluation results (model-index) present", 10),
    ("parameter_count", "Parameter count available (safetensors)", 8),
    ("tags", "Descriptive tags present", 4),
    ("author", "Author or organization identified", 2),
]
_TOTAL_WEIGHT = sum(weight for _, _, weight in CHECKS)


def completeness_level(score: int) -> str:
    """Bands used in the UI and the PDF: strong (>= 80), partial (>= 50), sparse (below 50)."""
    if score >= 80:
        return "strong"
    if score >= 50:
        return "partial"
    return "sparse"


def score_completeness(
    info: dict[str, Any] | None,
    card: dict[str, Any] | None,
    readme: str | None,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Weighted checklist describing how well the model is documented.

    Returns ``{"score": int 0-100, "level": str, "breakdown": [{key, label, weight, present}, ...]}``.
    """
    info = info or {}
    card = card or {}
    config = config or {}
    present = {
        "license": bool(_license_entries(info, card)),
        "description": bool(_as_list(card.get("description")) or _intro_paragraph(readme)),
        "pipeline_tag": bool(info.get("pipeline_tag")),
        "architecture": bool(config.get("architectures") or config.get("model_type")),
        "datasets": bool(_as_list(card.get("datasets"))),
        "intended_use": bool(_extract_sections(readme, CATEGORY_USE)),
        "limitations": bool(_extract_sections(readme, CATEGORY_LIMITATIONS)),
        "ethical_considerations": bool(_extract_sections(readme, CATEGORY_ETHICS)),
        "eval_results": bool(_model_index(info, card)),
        "parameter_count": bool((info.get("safetensors") or {}).get("total")),
        "tags": bool(info.get("tags")),
        "author": bool(info.get("author")),
    }
    earned = sum(weight for key, _, weight in CHECKS if present.get(key))
    score = round(100 * earned / _TOTAL_WEIGHT)
    breakdown = [
        {"key": key, "label": label, "weight": weight, "present": present[key]}
        for key, label, weight in CHECKS
    ]
    return {"score": score, "level": completeness_level(score), "breakdown": breakdown}
