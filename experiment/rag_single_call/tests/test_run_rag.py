"""Offline tests for experiment/rag_single_call/run_rag.py. No API call."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

OBO = """format-version: 1.2

[Term]
id: OBI:0000070
name: assay

[Term]
id: OBI:0000661
name: enzyme-linked immunosorbent assay
synonym: "ELISA" EXACT []
is_a: OBI:0000070 ! assay

[Term]
id: OBI:0000916
name: flow cytometry assay
is_a: OBI:0000070 ! assay

[Term]
id: OBI:0000999
name: obsolete old assay
is_obsolete: true
"""
INDEX = [{"id": "OBI:0000661", "label": "enzyme-linked immunosorbent assay", "synonyms": ["ELISA"],
          "definition": "An assay with an enzyme-linked antibody.", "n_descendants": 0}]


@pytest.fixture(scope="module")
def mod():
    for p in ("common", "llm_baseline", "obi_llm_fulllist"):
        sys.path.insert(0, str(REPO / "experiment" / p))
    spec = importlib.util.spec_from_file_location("run_rag", HERE.parent / "run_rag.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def index_path(tmp_path):
    p = tmp_path / "index.json"
    p.write_text(json.dumps(INDEX))
    return p


def test_prompt_puts_the_vocabulary_before_the_instructions_and_the_title_last(mod, index_path):
    prompt = mod.build_prompt("My paper", index_path)
    assert "(1 terms)" in prompt
    line = "1. OBI:0000661 | enzyme-linked immunosorbent assay | ELISA | definition: An assay with an enzyme-linked antibody. | descendants: 0"
    assert line in prompt
    assert prompt.index(line) < prompt.index("## Task") < prompt.index("Paper title: My paper")
    assert prompt.rstrip().endswith("Paper title: My paper")


def test_only_an_id_from_the_vocabulary_is_kept(mod, tmp_path):
    obo = tmp_path / "obi.obo"
    obo.write_text(OBO)
    ids = mod.ObiIds(obo)
    vocab = {"OBI:0000661": "enzyme-linked immunosorbent assay"}
    bench, obi = mod.to_registry([
        {"name_in_paper": "ELISA", "quote": "q1", "obi_id": "OBI:0000661", "obi_label": "ELISA"},
        {"name_in_paper": "FACS", "quote": "q2", "obi_id": "OBI_0000916", "obi_label": "flow cytometry assay"},
        {"name_in_paper": "old", "quote": "q3", "obi_id": "OBI:0000999", "obi_label": "obsolete old assay"},
        {"name_in_paper": "made up", "quote": "q4", "obi_id": "OBI:0099999", "obi_label": "x"},
        {"name_in_paper": "nothing", "quote": "q5", "obi_id": None, "obi_label": None},
    ], ids, vocab)
    assert list(bench) == ["enzyme-linked immunosorbent assay", "flow cytometry assay", "obsolete old assay", "x", "nothing"]
    assert [e["id_status"] for e in obi.values()] == ["valid", "outside_vocabulary", "obsolete", "nonexistent", "none"]
    assert obi["flow cytometry assay"]["obi_id"] is None  # a real term, but not one the model was shown
    assert obi["enzyme-linked immunosorbent assay"]["obi_label"] == "enzyme-linked immunosorbent assay"
