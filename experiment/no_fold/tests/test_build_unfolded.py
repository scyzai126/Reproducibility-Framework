"""Offline tests for experiment/no_fold/build_unfolded.py. No corpus."""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, str(HERE.parents[1] / "common"))
    spec = importlib.util.spec_from_file_location("build_unfolded", HERE.parent / "build_unfolded.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(name, **extra):
    return {"name_in_paper": name, "aliases": [], "generate_claim": True, "source": "methods",
            "evidence": {"section": "Methods", "quote": f"{name} quote"},
            "standard_technique_name": "x", "sample_type": "serum", "readouts": "titer", **extra}


CORRECTED = {"PRNT": _entry("PRNT"), "CPE neutralization": _entry("CPE neutralization"),
             "ELISA": _entry("ELISA", aliases=["enzyme immunoassay"]), "SIMOA": _entry("SIMOA")}
OBI = {"serum neutralization of viral infectivity assay": {"obi_id": "OBI:0001", "obi_label": "serum neutralization of viral infectivity assay", "resource": "embedding_llm"},
       "serum neutralization of viral infectivity assay (2)": {"obi_id": "OBI:0001", "obi_label": "serum neutralization of viral infectivity assay", "resource": "embedding_llm"},
       "enzyme-linked immunosorbent assay": {"obi_id": "OBI:0661", "obi_label": "enzyme-linked immunosorbent assay", "resource": "exact"},
       "SIMOA": {"obi_id": None, "obi_label": None, "resource": "none"}}
KEY_MAP = {"PRNT": "serum neutralization of viral infectivity assay",
           "CPE neutralization": "serum neutralization of viral infectivity assay (2)",
           "ELISA": "enzyme-linked immunosorbent assay", "SIMOA": "SIMOA"}


def test_unfolded_keeps_every_wording_with_its_canonical_terms(mod):
    bench, obi = mod.unfolded(CORRECTED, OBI, KEY_MAP)

    assert list(bench) == ["PRNT", "CPE neutralization", "ELISA", "SIMOA"]
    assert set(bench["PRNT"]) == set(mod.BENCH_FIELDS)  # the identity fields do not reach the scorer
    assert obi["PRNT"]["obi_id"] == obi["CPE neutralization"]["obi_id"] == "OBI:0001"
    assert obi["CPE neutralization"]["canonical_key"] == "serum neutralization of viral infectivity assay (2)"
    assert obi["SIMOA"] == {"obi_id": None, "obi_label": None, "resource": "none",
                            "canonical_key": "SIMOA", "name_in_paper": ["SIMOA"]}


def test_an_entry_the_key_map_does_not_place_keeps_no_term(mod):
    bench, obi = mod.unfolded({"PRNT": _entry("PRNT")}, OBI, {})
    assert obi["PRNT"]["obi_id"] is None and obi["PRNT"]["canonical_key"] is None


def test_term_fold_folds_every_entry_on_one_term_into_the_first(mod):
    bench, obi = mod.unfolded(CORRECTED, OBI, KEY_MAP)
    folded_b, folded_o = mod.term_fold(bench, obi)

    assert list(folded_b) == ["PRNT", "ELISA", "SIMOA"]
    assert folded_b["PRNT"]["name_in_paper"] == ["PRNT", "CPE neutralization"]
    assert folded_o["PRNT"]["folded_from"] == ["PRNT", "CPE neutralization"]
    assert folded_o["PRNT"]["name_in_paper"] == ["PRNT", "CPE neutralization"]
    # The host keeps its own evidence; the loser's aliases join the host's.
    assert folded_b["PRNT"]["evidence"]["quote"] == "PRNT quote"
    assert folded_b["ELISA"]["aliases"] == ["enzyme immunoassay"]


def test_term_fold_leaves_unmapped_entries_apart(mod):
    bench = {"a": _entry("a"), "b": _entry("b")}
    obi = {"a": {"obi_id": None}, "b": {"obi_id": None}}
    folded_b, _ = mod.term_fold(bench, obi)
    assert list(folded_b) == ["a", "b"]
