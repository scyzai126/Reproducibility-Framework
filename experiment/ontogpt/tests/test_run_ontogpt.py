"""Offline tests for experiment/ontogpt/run_ontogpt.py: a stored OntoGPT output, no call."""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, str(HERE.parents[1] / "common"))
    spec = importlib.util.spec_from_file_location("run_ontogpt", HERE.parent / "run_ontogpt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEXT = ("Serum cytokines were measured by Luminex multiplex assay and neutralizing titres by a plaque "
        "reduction neutralization test (PRNT). PBMC subsets were quantified by flow cytometry and gene "
        "expression by RNA-seq.")
HAY = "## Methods  [methods]\n[S1] " + TEXT.split(". ")[0] + ".\n[S2] " + TEXT.split(". ")[1] + "\n"
OUTPUT = {"named_entities": [
    {"id": "OBI:0001443", "label": "Luminex multiplex assay", "original_spans": ["33:55"]},
    {"id": "AUTO:plaque%20reduction%20neutralization%20test%20%28PRNT%29",
     "label": "plaque reduction neutralization test (PRNT)", "original_spans": ["86:128"]},
    {"id": "OBI:0000916", "label": "flow cytometry", "original_spans": ["163:176"]},
    {"id": "OBI:0000916", "label": "FACS"},
]}
VOCAB = {"OBI:0000916": "flow cytometry assay"}


def test_sentence_offsets_follow_the_text_ontogpt_read(mod):
    laid = mod.sentence_offsets({"kind": "xml", "haystack": HAY}, TEXT)
    assert [(s["id"], s["start"], s["section"]) for s in laid] == [(1, 0, "methods"), (2, 131, "methods")]


def test_entries_classify_grounded_outside_and_auto_ids(mod):
    laid = mod.sentence_offsets({"kind": "xml", "haystack": HAY}, TEXT)
    entries = mod.entries_from_output(OUTPUT, TEXT, laid, VOCAB)
    assert [e["id_status"] for e in entries] == ["outside_vocabulary", "none", "valid", "valid"]
    assert entries[0]["obi_id"] is None and entries[0]["grounded_id"] == "OBI:0001443"
    assert entries[2]["obi_label"] == "flow cytometry assay" and entries[2]["sentence_ids"] == [2]
    assert entries[2]["quote"].startswith("PBMC subsets")
    # An entity without a span is placed by its label; one whose label is nowhere has no quote.
    assert entries[3]["quote"] == "" and entries[3]["sentence_ids"] == []


def test_registry_files_key_by_term_and_repeat_as_the_agent_does(mod):
    laid = mod.sentence_offsets({"kind": "xml", "haystack": HAY}, TEXT)
    bench, obi = mod.registry_files(mod.entries_from_output(OUTPUT, TEXT, laid, VOCAB))
    assert list(bench) == ["Luminex multiplex assay", "plaque reduction neutralization test (PRNT)",
                           "flow cytometry assay", "flow cytometry assay (2)"]
    assert bench["flow cytometry assay"]["evidence"]["sentence_ids"] == ["S2"]
    assert bench["flow cytometry assay"]["source"] == "methods"
    assert obi["Luminex multiplex assay"] == {"obi_id": None, "obi_label": None, "resource": "ontogpt",
                                              "id_status": "outside_vocabulary", "grounded_id": "OBI:0001443",
                                              "name_in_paper": ["Luminex multiplex assay"]}


def test_usage_is_read_from_the_verbose_log_once_per_reply(mod, tmp_path):
    line = ('{"id": "chatcmpl-1", "choices": [], "usage": {"completion_tokens": 13, "prompt_tokens": 96, '
            '"prompt_tokens_details": {"cached_tokens": 0}}}')
    log = tmp_path / "ontogpt.log"
    log.write_text("INFO something\n" + line + "\n" + line + "\nDEBUG:root:Grounding\n")
    assert mod.usage_from_log(log) == {"prompt_tokens": 96, "completion_tokens": 13, "cached_tokens": 0, "calls": 1}
