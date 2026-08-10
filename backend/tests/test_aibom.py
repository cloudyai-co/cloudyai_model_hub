import json
from pathlib import Path

from backend.aibom import build_aibom, score_completeness

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture():
    info = json.loads((FIXTURES / "sample_model.json").read_text())
    readme = (FIXTURES / "sample_readme.md").read_text()
    return info, readme


def test_build_aibom_shape():
    info, readme = load_fixture()
    bom, completeness = build_aibom("acme-labs/nimbus-7b-instruct", info, readme, info["config"])

    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert bom["serialNumber"].startswith("urn:uuid:")

    component = bom["metadata"]["component"]
    assert component["type"] == "machine-learning-model"
    assert component["group"] == "acme-labs"
    assert component["name"] == "nimbus-7b-instruct"
    assert component["licenses"] == [{"license": {"id": "apache-2.0"}}]

    model_params = component["modelCard"]["modelParameters"]
    assert model_params["task"] == "text-generation"
    assert model_params["architectureFamily"] == "nimbus"
    assert model_params["modelArchitecture"] == "NimbusForCausalLM"
    assert len(model_params["datasets"]) == 2

    metrics = component["modelCard"]["quantitativeAnalysis"]["performanceMetrics"]
    assert metrics[0]["type"] == "accuracy"
    assert metrics[0]["slice"] == "MMLU"

    considerations = component["modelCard"]["considerations"]
    assert any("high-stakes" in u.lower() or "direct use" in u.lower() for u in considerations["useCases"])
    assert any("bias" in l.lower() or "underrepresented" in l.lower() for l in considerations["technicalLimitations"])
    assert considerations["ethicalConsiderations"][0]["name"]

    param_prop = next(p for p in component["properties"] if p["name"] == "hf:totalParameters")
    assert param_prop["value"] == "7241732096"

    # Whole thing must round-trip through json.dumps without error.
    json.dumps(bom)


def test_completeness_score_rewards_present_fields():
    info, readme = load_fixture()
    result = score_completeness(info, info["cardData"], readme, info["config"])
    assert 0 <= result["score"] <= 100
    # This fixture is deliberately well-documented; expect a high score.
    assert result["score"] >= 80
    present_keys = {row["key"] for row in result["breakdown"] if row["present"]}
    assert "license" in present_keys
    assert "eval_results" in present_keys
    assert "parameter_count" in present_keys


def test_completeness_score_penalizes_missing_fields():
    result = score_completeness({}, {}, None, None)
    assert result["score"] == 0
    assert all(not row["present"] for row in result["breakdown"])
