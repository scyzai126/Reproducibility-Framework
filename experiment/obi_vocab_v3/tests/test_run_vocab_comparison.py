"""Offline tests for experiment/obi_vocab_v3/run_vocab_comparison.py. No API call."""

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]


@pytest.fixture(scope="module")
def mod():
    script = HERE.parent / "run_vocab_comparison.py"
    spec = importlib.util.spec_from_file_location("run_vocab_comparison", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tiny_arm(mod, tmp_path, monkeypatch):
    """A two-term vocabulary: a childless term and a term whose child is also in the index."""
    index = [
        {"id": "OBI:0000661", "label": "enzyme-linked immunosorbent assay", "synonyms": ["ELISA"],
         "is_a": ["OBI:0000070"], "definition": "", "n_descendants": 0},
        {"id": "OBI:0001177", "label": "RNA sequencing assay", "synonyms": ["RNA-seq"],
         "is_a": ["OBI:0000070"], "definition": "", "n_descendants": 1},
        # Children come from obi.obo, not from the index's is_a, so this must be a real direct
        # child of RNA sequencing assay (bulk RNA-seq is its grandchild).
        {"id": "OBI:0001271", "label": "RNA-seq assay", "synonyms": [],
         "is_a": ["OBI:0001177"], "definition": "", "n_descendants": 2},
    ]
    index_path = tmp_path / "tiny_index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    emb_path = tmp_path / "tiny_embeddings.json"
    emb_path.write_text("[]", encoding="utf-8")
    monkeypatch.setitem(mod.ARMS, "tiny", {"index": index_path, "embeddings": emb_path, "unfiltered": True})
    return index_path, emb_path


def test_vocabulary_patches_and_restores_the_mapper(mod, tiny_arm):
    from app.agent import assay_obi_mapper as mapper

    before = (mapper._OBI_TERMS_PATH, mapper._EMBEDDINGS_PATH, mapper._is_generic_assay_term)
    index_path, emb_path = tiny_arm
    with mod.Vocabulary("tiny"):
        assert mapper._OBI_TERMS_PATH == index_path
        assert mapper._EMBEDDINGS_PATH == emb_path
        # unfiltered: a compositional label passes the load-time filter
        assert mapper._is_generic_assay_term("OBI:1", "assay measuring X by Y cells") is True
        assert mapper._build_lookup(index_path)["elisa"]["obi_id"] == "OBI:0000661"
    assert (mapper._OBI_TERMS_PATH, mapper._EMBEDDINGS_PATH, mapper._is_generic_assay_term) == before
    assert mapper._is_generic_assay_term("OBI:1", "assay measuring X by Y cells") is False
    assert mapper._build_lookup.cache_info().currsize == 0


def test_plan_charges_only_entries_that_reach_the_paid_step(mod, tiny_arm):
    assays = {
        "ELISA": {"name_in_paper": ["ELISA"]},                                     # exact, childless: free
        "RNA sequencing": {"name_in_paper": ["RNA sequencing assay"]},            # exact but has a child: pinned, paid
        "Luminex": {"name_in_paper": ["Luminex"], "standard_technique_name": "multiplex bead assay"},  # miss + technique: 3
        "FACS": {"name_in_paper": ["FACS"], "standard_technique_name": "facs"},   # miss, technique same name: 2
    }
    planned = dict(mod.plan("tiny", assays))
    assert planned == {"RNA sequencing": 2, "Luminex": 3, "FACS": 2}


def test_diff_arms_classifies_against_the_curator(mod, tmp_path):
    runs = {"pruned": tmp_path / "pruned", "full": tmp_path / "full"}
    reg = "123_SDY1"
    for arm, obi in (
        ("pruned", {"a": {"obi_id": "OBI:1", "obi_label": "one"}, "b": {"obi_id": "OBI:2", "obi_label": "two"},
                    "c": {"obi_id": "OBI:3", "obi_label": "three"}, "d": {"obi_id": "OBI:4", "obi_label": "four"}}),
        ("full", {"a": {"obi_id": "OBI:1", "obi_label": "one"},
                  "b": {"obi_id": "OBI:9", "obi_label": "assay measuring two by cells"},
                  "c": {"obi_id": "OBI:8", "obi_label": "eight"}, "d": {"obi_id": "OBI:5", "obi_label": "five"}}),
    ):
        (runs[arm] / reg).mkdir(parents=True)
        (runs[arm] / reg / "assays_OBI.json").write_text(json.dumps(obi), encoding="utf-8")
    curated = {(reg, "b"): {"obi_id": "OBI:2", "obi_label": "two"},   # pruned right
               (reg, "c"): {"obi_id": "OBI:8", "obi_label": "eight"}, # full right
               (reg, "d"): {"obi_id": "OBI:7", "obi_label": "seven"}} # neither
    rows = mod.diff_arms("pruned", "full", runs, curated, pruned_ids={"OBI:1", "OBI:2", "OBI:3", "OBI:4"})

    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == {"b", "c", "d"}  # "a" agreed, so it is not a diff
    assert by_key["b"]["agrees_with_curator"] == "pruned"
    assert by_key["b"]["full_term_is_compositional"] is True
    assert by_key["b"]["full_term_outside_pruned_index"] is True
    assert by_key["c"]["agrees_with_curator"] == "full"
    assert by_key["d"]["agrees_with_curator"] == "neither"


def test_registries_only_filter_matches_the_study_suffix(mod, tmp_path):
    for name in ("111_SDY1", "222_SDY12", "333_SDY1_pdf"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "assays.json").write_text("{}", encoding="utf-8")
    assert [d.name for d in mod.registries(tmp_path, "SDY1")] == ["111_SDY1", "333_SDY1_pdf"]
