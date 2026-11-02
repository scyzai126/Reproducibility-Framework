"""Offline tests for experiment/dictionary_baseline/run_dictionary.py. No corpus, no model."""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

INDEX = [
    {"id": "OBI:0000916", "label": "flow cytometry assay", "synonyms": ["FACS"]},
    {"id": "OBI:0000415", "label": "polymerase chain reaction assay", "synonyms": ["PCR"]},
    {"id": "OBI:0000893", "label": "real time polymerase chain reaction assay", "synonyms": ["real-time PCR", "qPCR"]},
    {"id": "OBI:0000070", "label": "assay", "synonyms": []},
    {"id": "OBI:0000001", "label": "gel assay", "synonyms": ["gel", "GEL"]},
]


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, str(HERE.parents[1] / "common"))
    spec = importlib.util.spec_from_file_location("run_dictionary", HERE.parent / "run_dictionary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def dictionary(mod):
    return mod.build_dictionary(INDEX)


def test_forms_include_the_label_without_its_trailing_assay(mod):
    assert mod.forms_of(INDEX[0]) == ["flow cytometry assay", "FACS", "flow cytometry"]


def test_the_root_short_forms_and_short_lowercase_words_are_dropped(mod):
    assert mod.dropped_forms(INDEX) == ["assay", "gel"]
    # "GEL" is a 3-letter acronym and stays, matched in its own case.
    forms = {f for f, _, _ in mod.build_dictionary(INDEX)}
    assert "GEL" in forms and "gel" not in forms


def test_longest_span_wins_so_real_time_pcr_is_one_term(mod, dictionary):
    found = mod.match_sentence("Expression was measured by real-time PCR and flow cytometry.", dictionary)
    assert [(f["term"], f["text"]) for f in found] == [
        ("OBI:0000893", "real-time PCR"), ("OBI:0000916", "flow cytometry")]


def test_forms_match_whole_words_and_a_hyphen_or_space_inside(mod, dictionary):
    assert mod.match_sentence("Samples were PCR-amplified.", dictionary) == []  # PCR- is not a whole word
    assert [f["term"] for f in mod.match_sentence("real time PCR was used.", dictionary)] == ["OBI:0000893"]
    assert [f["term"] for f in mod.match_sentence("A PCR step followed.", dictionary)] == ["OBI:0000415"]


def test_an_acronym_matches_in_its_own_case_only(mod, dictionary):
    assert mod.match_sentence("the pcr product", dictionary) == []
    assert mod.match_sentence("gel electrophoresis", dictionary) == []
    assert [f["term"] for f in mod.match_sentence("GEL shift", dictionary)] == ["OBI:0000001"]


def _paper(haystack, kind="xml"):
    return {"kind": kind, "haystack": haystack, "text": None}


HAY = ("## Abstract  [abstract]\n[S1] FACS showed activation.\n## Methods  [methods]\n"
       "[S2] Cells were analysed by flow cytometry.\n[S3] Transcripts were quantified by qPCR.\n")


def test_one_entry_per_term_with_every_wording_and_the_first_sentence(mod, dictionary):
    labels = {t["id"]: t["label"] for t in INDEX}
    entries, record = mod.match_paper(_paper(HAY), dictionary, "paper", labels)
    flow = next(e for e in entries if e["obi_id"] == "OBI:0000916")
    assert flow["names"] == ["FACS", "flow cytometry"]
    assert flow["quote"] == "FACS showed activation." and flow["section"] == "abstract"
    assert flow["sentence_ids"] == [1] and flow["hits"] == 2
    bench, obi = mod.term_registry(entries, resource="dictionary:test")
    assert bench["flow cytometry assay"]["evidence"]["sentence_ids"] == ["S1"]
    assert bench["flow cytometry assay"]["source"] is None and bench["polymerase chain reaction assay (2)" if False else "real time polymerase chain reaction assay"]["source"] == "methods"
    assert obi["flow cytometry assay"]["resource"] == "dictionary:test"
    assert record["scope_applied"] == "paper" and len(record["hits"]) == 3


def test_methods_scope_keeps_only_methods_sentences(mod, dictionary):
    labels = {t["id"]: t["label"] for t in INDEX}
    entries, record = mod.match_paper(_paper(HAY), dictionary, "methods", labels)
    assert sorted(e["obi_id"] for e in entries) == ["OBI:0000893", "OBI:0000916"]
    flow = next(e for e in entries if e["obi_id"] == "OBI:0000916")
    assert flow["names"] == ["flow cytometry"] and flow["section"] == "methods"
    assert record["sentences"] == 2


def test_a_pdf_has_no_headings_so_methods_scope_matches_the_whole_text(mod, dictionary):
    labels = {t["id"]: t["label"] for t in INDEX}
    entries, record = mod.match_paper(_paper("FACS was used. Then qPCR.", kind="pdf"), dictionary, "methods", labels)
    assert len(entries) == 2 and record["scope_applied"] == "paper (no headings)"
    assert entries[0]["sentence_ids"] == [] and entries[0]["section"] is None
