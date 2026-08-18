"""OBI enrichment of the flat assay table must not distort the table it enriches.

Two hazards, neither of which involves the ontology being wrong: the same assay name
appearing in several papers must resolve to one OBI id rather than being re-decided per
row (step 3 of the chain is an LLM pick, so per-row mapping can disagree with itself),
and the OBI confidence must land in `obi_confidence` — `confidence` already means the
*extraction* confidence in the per-paper registries, and enrich_assays_with_obi
overwrites it.
"""

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

_FLOW = {
    "obi_id": "OBI:0000916",
    "obi_label": "flow cytometry assay",
    "resource": "exact_original",
    "confidence": "high",
}


def _load_runner():
    """Import scripts/map_assays_to_obi.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "map_assays_to_obi.py"
    spec = importlib.util.spec_from_file_location("map_assays_to_obi", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _row(study, assay, normalized, sample_type="PBMCs", readouts="cell frequencies"):
    return {
        "study": study,
        "assay": assay,
        "normalized_name": normalized,
        "sample_type": sample_type,
        "readouts": readouts,
    }


def _run(runner, monkeypatch, tmp_path, rows, mapper):
    """Drive main() over `rows` with map_assay_to_obi replaced by `mapper`."""
    import json
    import sys

    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(rows), encoding="utf-8")

    monkeypatch.setattr(runner, "map_assay_to_obi", mapper)
    monkeypatch.setattr(runner, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(
        sys, "argv", ["map_assays_to_obi.py", "--in", str(in_path), "--out", str(out_path)]
    )
    assert runner.main() == 0
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_a_repeated_pair_is_mapped_once_and_applied_to_every_row(runner, monkeypatch, tmp_path):
    calls = []

    def mapper(assay, normalized, **kwargs):
        calls.append(assay)
        return _FLOW

    rows = [
        _row("25834109_SDY212", "flow cytometry", "Flow Cytometry"),
        _row("23601689_SDY180", "flow cytometry", "Flow Cytometry"),
        _row("24725414_SDY80", "flow cytometry", "Flow Cytometry"),
    ]

    enriched = _run(runner, monkeypatch, tmp_path, rows, mapper)

    assert calls == ["flow cytometry"]
    assert {r["obi_id"] for r in enriched} == {"OBI:0000916"}
    assert len(enriched) == 3


def test_output_keeps_the_five_fields_and_adds_exactly_the_four_obi_ones(
    runner, monkeypatch, tmp_path
):
    rows = [_row("25834109_SDY212", "flow cytometry", "Flow Cytometry")]

    enriched = _run(runner, monkeypatch, tmp_path, rows, lambda *a, **k: _FLOW)

    assert enriched == [
        {
            "study": "25834109_SDY212",
            "assay": "flow cytometry",
            "normalized_name": "Flow Cytometry",
            "sample_type": "PBMCs",
            "readouts": "cell frequencies",
            "obi_id": "OBI:0000916",
            "obi_label": "flow cytometry assay",
            "resource": "exact_original",
            "obi_confidence": "high",
        }
    ]


def test_extraction_confidence_key_is_never_written(runner, monkeypatch, tmp_path):
    rows = [_row("25834109_SDY212", "flow cytometry", "Flow Cytometry")]

    enriched = _run(runner, monkeypatch, tmp_path, rows, lambda *a, **k: _FLOW)

    assert "confidence" not in enriched[0]
    assert enriched[0]["obi_confidence"] == "high"


def test_an_unmapped_pair_is_reported_rather_than_given_an_invented_id(
    runner, monkeypatch, tmp_path
):
    rows = [_row("20078211_SDY1293", "malaria thick blood smears", "malaria thick blood smears")]

    enriched = _run(runner, monkeypatch, tmp_path, rows, lambda *a, **k: None)

    assert enriched[0]["obi_id"] is None
    assert enriched[0]["obi_label"] is None
    assert enriched[0]["resource"] == "unresolved"
    assert enriched[0]["obi_confidence"] is None


def test_distinct_pairs_each_get_their_own_mapping(runner, monkeypatch, tmp_path):
    def mapper(assay, normalized, **kwargs):
        return _FLOW if assay == "flow cytometry" else None

    rows = [
        _row("25834109_SDY212", "flow cytometry", "Flow Cytometry"),
        _row("25834109_SDY212", "tetramer staining", "Flow Cytometry"),
    ]

    enriched = _run(runner, monkeypatch, tmp_path, rows, mapper)

    assert [r["resource"] for r in enriched] == ["exact_original", "unresolved"]


def test_pair_context_comes_from_the_first_row(runner):
    rows = [
        _row("a", "ELISA", "ELISA", sample_type="serum", readouts="titers"),
        _row("b", "ELISA", "ELISA", sample_type="plasma", readouts="something else"),
    ]

    pairs = runner._pairs_with_context(rows)

    assert pairs[("ELISA", "ELISA")] == {"sample_type": "serum", "readouts": "titers"}
