"""
Builds a CycloneDX 1.6 AIBOM (component type `machine-learning-model`, with
the ML-BOM `modelCard` extension) from a Hugging Face model-info payload,
plus a transparent "documentation completeness" score.

Reference: CycloneDX ML-BOM / modelCard —
https://cyclonedx.org/docs/1.6/json/#metadata_component_modelCard

Validate output against the official CycloneDX JSON schema before relying
on it for compliance-critical workflows — this generator does its best
with what Hugging Face exposes, but metadata quality varies wildly across
the Hub, which is exactly what the completeness score is trying to surface.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

CYCLONEDX_SPEC_VERSION = "1.6"
TOOL_NAME = "cloudyai-aibom-generator"
TOOL_VERSION = "0.1.0"

_SPDX_HINTS = {
    "mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "cc-by-4.0",
    "cc-by-sa-4.0", "gpl-3.0", "lgpl-3.0", "cc-by-nc-4.0", "cc0-1.0",
}

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_HEADER_RE = re.compile(r"^#{1,4}\s+(.*)")

_SECTION_KEYWORDS = {
    "useCases": ("direct use", "downstream use", "intended use", "## uses"),
    "technicalLimitations": ("bias, risks, and limitations", "limitations", "risks", "out-of-scope"),
    "ethicalConsiderations": ("ethical considerations", "responsible use", "misuse"),
    "users": ("intended users", "who should use"),
}


# ---------------------------------------------------------------------------
# README helpers
# ---------------------------------------------------------------------------

def _strip_frontmatter(readme: str) -> str:
    return _FRONTMATTER_RE.sub("", readme)


def _first_paragraph(readme: str | None) -> str:
    if not readme:
        return ""
    text = _strip_frontmatter(readme)
    for para in text.split("\n\n"):
        para = para.strip()
        if para and not para.startswith("#") and not para.startswith("!["):
            return para
    return ""


def _extract_sections(readme: str | None, keywords: tuple[str, ...]) -> list[str]:
    if not readme:
        return []
    text = _strip_frontmatter(readme)
    results, buffer, capturing = [], [], False
    for line in text.split("\n"):
        header = _HEADER_RE.match(line)
        if header:
            if capturing and buffer:
                results.append(" ".join(buffer).strip())
                buffer = []
            capturing = any(kw in header.group(1).lower() for kw in keywords)
            continue
        if capturing and line.strip():
            buffer.append(line.strip())
    if capturing and buffer:
        results.append(" ".join(buffer).strip())
    return [r[:2000] for r in results if r]


def _has_real_intro(readme: str | None) -> bool:
    para = _first_paragraph(readme)
    return len(para) > 20


# ---------------------------------------------------------------------------
# AIBOM construction
# ---------------------------------------------------------------------------

def _license_entries(info: dict, card: dict) -> list[dict]:
    lic = card.get("license") or info.get("license")
    if not lic:
        return []
    values = lic if isinstance(lic, list) else [lic]
    return [
        {"license": {"id": v}} if v.lower() in _SPDX_HINTS else {"license": {"name": v}}
        for v in values
    ]


def _dataset_entries(card: dict) -> list[dict]:
    datasets = card.get("datasets") or []
    if isinstance(datasets, str):
        datasets = [datasets]
    return [{"type": "dataset", "name": d} for d in datasets]


def _performance_metrics(card: dict) -> list[dict]:
    metrics = []
    for entry in card.get("model-index") or []:
        for result in entry.get("results", []):
            dataset_name = (result.get("dataset") or {}).get("name")
            for metric in result.get("metrics", []):
                metrics.append({
                    "type": metric.get("type") or metric.get("name") or "metric",
                    "value": str(metric.get("value")),
                    "slice": dataset_name,
                })
    return metrics


def build_aibom(model_id: str, info: dict, readme: str | None, config: dict | None) -> tuple[dict, dict]:
    card = info.get("cardData") or {}
    config = config or {}
    parts = model_id.split("/")
    group, name = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])

    safetensors = info.get("safetensors") or {}
    total_params = safetensors.get("total")

    limitations = _extract_sections(readme, _SECTION_KEYWORDS["technicalLimitations"])
    ethical = _extract_sections(readme, _SECTION_KEYWORDS["ethicalConsiderations"])
    use_cases = _extract_sections(readme, _SECTION_KEYWORDS["useCases"])
    users = _extract_sections(readme, _SECTION_KEYWORDS["users"])

    description = card.get("description") or _first_paragraph(readme) or ""

    model_component = {
        "type": "machine-learning-model",
        "bom-ref": f"model:{model_id}",
        "group": group,
        "name": name,
        "version": str(info.get("sha") or "main")[:12],
        "description": description[:1000],
        "licenses": _license_entries(info, card),
        "externalReferences": [
            {"type": "distribution", "url": f"https://huggingface.co/{model_id}"},
            {"type": "documentation", "url": f"https://huggingface.co/{model_id}/blob/main/README.md"},
        ],
        "modelCard": {
            "modelParameters": {
                "task": info.get("pipeline_tag"),
                "architectureFamily": config.get("model_type"),
                "modelArchitecture": (config.get("architectures") or [None])[0],
                "datasets": _dataset_entries(card),
            },
            "quantitativeAnalysis": {
                "performanceMetrics": _performance_metrics(card),
            },
            "considerations": {
                "users": users,
                "useCases": use_cases,
                "technicalLimitations": limitations,
                "ethicalConsiderations": [{"name": e} for e in ethical],
            },
        },
        "properties": [
            {"name": "hf:downloads", "value": str(info.get("downloads", 0))},
            {"name": "hf:downloadsAllTime", "value": str(info.get("downloadsAllTime", 0))},
            {"name": "hf:likes", "value": str(info.get("likes", 0))},
            {"name": "hf:libraryName", "value": str(info.get("library_name"))},
            {"name": "hf:gated", "value": str(bool(info.get("gated")))},
            {"name": "hf:lastModified", "value": str(info.get("lastModified"))},
            {"name": "hf:totalParameters", "value": str(total_params) if total_params else "unknown"},
        ],
    }

    completeness = score_completeness(info, card, readme, config)
    model_component["properties"].append(
        {"name": "aibom:completenessScore", "value": str(completeness["score"])}
    )

    bom = {
        "$schema": f"http://cyclonedx.org/schema/bom-{CYCLONEDX_SPEC_VERSION}.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": {"components": [{"type": "application", "name": TOOL_NAME, "version": TOOL_VERSION}]},
            "component": model_component,
        },
        "components": [],
    }
    return bom, completeness


# ---------------------------------------------------------------------------
# Completeness score
# ---------------------------------------------------------------------------

# (key, label, weight)
CHECKS = [
    ("license", "License declared", 10),
    ("description", "Description / summary present", 8),
    ("pipeline_tag", "Task / pipeline tag set", 6),
    ("architecture", "Architecture info available (config.json)", 10),
    ("datasets", "Training datasets listed", 10),
    ("intended_use", "Intended use / use cases documented", 12),
    ("limitations", "Limitations or bias section present", 12),
    ("ethical_considerations", "Ethical considerations documented", 8),
    ("eval_results", "Evaluation results (model-index) present", 10),
    ("parameter_count", "Parameter count available (safetensors)", 8),
    ("tags", "Descriptive tags present", 4),
    ("author", "Author / organization identified", 2),
]
_TOTAL_WEIGHT = sum(w for *_, w in CHECKS)


def score_completeness(info: dict, card: dict, readme: str | None, config: dict | None) -> dict:
    readme_lower = (readme or "").lower()
    present = {
        "license": bool(card.get("license") or info.get("license")),
        "description": bool(card.get("description")) or _has_real_intro(readme),
        "pipeline_tag": bool(info.get("pipeline_tag")),
        "architecture": bool(config),
        "datasets": bool(card.get("datasets")),
        "intended_use": any(k in readme_lower for k in _SECTION_KEYWORDS["useCases"]),
        "limitations": any(k in readme_lower for k in _SECTION_KEYWORDS["technicalLimitations"]),
        "ethical_considerations": any(k in readme_lower for k in _SECTION_KEYWORDS["ethicalConsiderations"]),
        "eval_results": bool(card.get("model-index")),
        "parameter_count": bool((info.get("safetensors") or {}).get("total")),
        "tags": bool(info.get("tags")),
        "author": bool(info.get("author")),
    }
    earned = sum(weight for key, _, weight in CHECKS if present.get(key))
    score = round(100 * earned / _TOTAL_WEIGHT)
    breakdown = [
        {"key": key, "label": label, "weight": weight, "present": present.get(key, False)}
        for key, label, weight in CHECKS
    ]
    return {"score": score, "breakdown": breakdown}
