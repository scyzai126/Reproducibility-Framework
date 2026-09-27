"""app.agent.assay_table: the row builder shared by the Corpus table and the Extract tab.

Covered in depth by test_build_assay_table.py, which loads the CLI that re-exports it. This file
pins what only the per-paper path does: `only=` restricts both the rows and the benchmark pairing
to one registry, missed curator assays included.
"""

import json

import pytest

from app.agent import assay_service, assay_table

_OBI = {"enzyme-linked immunosorbent assay": {
    "name_in_paper": ["ELISA"], "normalized_name": "ELISA", "sample_type": "serum",
    "readouts": "titers", "obi_id": "OBI:0000661", "obi_label": "enzyme-linked immunosorbent assay",
    "resource": "exact_original", "obi_confidence": "high"}}


def _curated(name, obi_id, label):
    return {"name_in_paper": name, "aliases": [],
            "OBI ontology": {"obi_id": obi_id, "obi_label": label},
            "evidence_location": {"quote": ""}}


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Two papers with registries; one curator file, for the first, naming one assay we missed."""
    monkeypatch.setattr(assay_service, "XML_ROOT", tmp_path / "JAT_XML")
    registries = tmp_path / "registries"
    for stem in ("24336226_SDY1260", "19029902_SDY1264"):
        (registries / stem).mkdir(parents=True)
        for name in ("assays_OBI.json", "assays_benchmark.json"):
            (registries / stem / name).write_text(json.dumps(_OBI), encoding="utf-8")
    bench = tmp_path / "benchmark_assay"
    bench.mkdir()
    (bench / "SDY1260_Assay_Test.json").write_text(json.dumps({
        "ELISA": _curated("ELISA", "OBI:0000661", "enzyme-linked immunosorbent assay"),
        "SIMOA": _curated("single-molecule array", None, None),
    }), encoding="utf-8")
    return registries, bench


def test_only_limits_the_rows_to_one_paper(corpus):
    registries, bench = corpus

    rows = assay_table.table_rows(registries, bench, only="24336226_SDY1260")

    assert {r["study"] for r in rows} == {"24336226_SDY1260"}
    assert [r["benchmark_assay"] for r in rows] == ["ELISA", "single-molecule array"]
    assert rows[1]["benchmark_only"] is True


def test_one_paper_s_rows_equal_its_rows_in_the_whole_table(corpus):
    registries, bench = corpus

    whole = [r for r in assay_table.table_rows(registries, bench) if r["study"] == "24336226_SDY1260"]

    assert assay_table.table_rows(registries, bench, only="24336226_SDY1260") == whole


def test_a_paper_without_a_curator_file_still_gets_its_rows(corpus):
    registries, bench = corpus

    rows = assay_table.table_rows(registries, bench, only="19029902_SDY1264")

    assert [(r["assay"], r["benchmark_assay"]) for r in rows] == [("ELISA", None)]


def test_an_unknown_registry_gives_no_rows(corpus):
    registries, bench = corpus

    assert assay_table.table_rows(registries, bench, only="1_SDY1") == []
