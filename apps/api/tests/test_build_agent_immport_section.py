"""Unit tests for scripts/build_agent_immport_section.py — no database, no network.

The page's Comment column mixes two kinds of text: what the review wrote and what the rule can
say on its own. What must not happen is a guessed reason passing for a reviewed one, or a hand
note silently matching nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def mod():
    path = REPO_ROOT / "scripts" / "build_agent_immport_section.py"
    spec = importlib.util.spec_from_file_location("build_agent_immport_section", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exp(accession, technique, name=""):
    return {"accession": accession, "name": name, "technique": technique}


def link(technique, *accessions, status="SINGLE", evidence="", **extra):
    return {"technique": technique, "ids": [], "status": status, "evidence": evidence,
            "experiments": [{"accession": a, "name": ""} for a in accessions],
            "candidates": [], **extra}


def rec(key, level, *links):
    return {"pmid": "1", "study": "SDY1", "key": key, "obi_id": "OBI:1", "obi_label": key,
            "name_in_paper": [key], "level": level, "links": list(links)}


def test_exact_row_has_no_comment_and_lists_every_experiment_of_the_technique(mod):
    mine = [exp("EXP1", "Flow Cytometry"), exp("EXP2", "Flow Cytometry")]
    rows, warnings = mod.plan_study([rec("flow", "EXACT", link("Flow Cytometry", "EXP1"))], mine, {})
    assert warnings == []
    assert [e["accession"] for e in rows[0]["experiments"]] == ["EXP1", "EXP2"]
    assert (rows[0]["comment"], rows[0]["reviewed"]) == ("", False)
    assert mod.review_progress(rows) == (0, 0)


def test_unreviewed_rows_say_so_and_mention_other_papers(mod):
    rows, _ = mod.plan_study([rec("western blot", "NONE")], [exp("EXP1", "ELISA")], {}, n_extra=2)
    agent_only, immport_only = rows
    assert (agent_only["level"], immport_only["level"]) == ("NONE", "IMMPORT_ONLY")
    assert agent_only["comment"] == "Not reviewed yet. Study has 2 other papers."
    assert immport_only["comment"] == "Not reviewed yet. Study has 2 other papers."
    assert mod.review_progress(rows) == (0, 2)


def test_hand_comment_wins_over_the_automatic_line(mod):
    notes = {"agent": {"western blot": {"verdict": "Not deposited in ImmPort", "comment": "x"}},
             "immport": {"EXP1": {"verdict": "Not in paper", "comment": "y"}}}
    rows, warnings = mod.plan_study([rec("western blot", "NONE")], [exp("EXP1", "ELISA")], notes)
    assert warnings == []
    assert [(r["verdict"], r["comment"], r["reviewed"]) for r in rows] == [
        ("Not deposited in ImmPort", "x", True), ("Not in paper", "y", True)]
    assert mod.review_progress(rows) == (2, 2)


def test_hand_match_pairs_the_experiment_and_frees_the_rest(mod):
    # the rule's weak sibling link lists both PCR experiments; the review pairs only one
    mine = [exp("EXP1", "Q-PCR", "Np"), exp("EXP2", "Q-PCR", "Saliva")]
    notes = {"agent": {"rt-qpcr": {"match": ["EXP1"], "comment": "same assay"}}}
    rows, _ = mod.plan_study([rec("rt-qpcr", "SIBLING", link("Q-PCR"))], mine, notes)
    assert [(r["level"], [e["accession"] for e in r["experiments"]]) for r in rows] == [
        ("HAND", ["EXP1"]), ("IMMPORT_ONLY", ["EXP2"])]
    assert mod.count_levels(rows) == {"HAND": 1, "IMMPORT_ONLY": 1}


def test_hand_matched_experiment_is_not_listed_under_another_assay(mod):
    mine = [exp("EXP1", "Luminex xMAP"), exp("EXP2", "Luminex xMAP")]
    recs = [rec("cytokines", "EXACT", link("Luminex xMAP", "EXP1")), rec("pneumo", "NONE")]
    notes = {"agent": {"pneumo": {"match": ["EXP2"], "comment": "c"}}}
    rows, _ = mod.plan_study(recs, mine, notes)
    assert [(r["record"]["key"], [e["accession"] for e in r["experiments"]]) for r in rows] == [
        ("cytokines", ["EXP1"]), ("pneumo", ["EXP2"])]


def test_agent_only_removes_the_rule_match(mod):
    notes = {"agent": {"tetramer": {"agent_only": True, "comment": "mouse work"}}}
    rows, _ = mod.plan_study([rec("tetramer", "DESCENDANT", link("Flow Cytometry", "EXP1"))],
                             [exp("EXP1", "Flow Cytometry")], notes)
    assert [(r["level"], r["experiments"] != []) for r in rows] == [
        ("NONE", False), ("IMMPORT_ONLY", True)]


def test_other_bucket_shows_only_the_name_matched_experiment(mod):
    mine = [exp("EXP1", "Other", "O-link"), exp("EXP2", "Other", "MHC_peptide_binding")]
    rows, _ = mod.plan_study(
        [rec("Olink assay", "EXPNAME",
             link("Other", "EXP1", status="NAMED", evidence="own name", uninformative=True))],
        mine, {})
    assert [e["accession"] for e in rows[0]["experiments"]] == ["EXP1"]
    assert rows[0]["comment"] == "Matched on the experiment name: own name."
    assert rows[1]["level"] == "IMMPORT_ONLY"


def test_experiment_note_inside_a_matched_row_is_appended(mod):
    notes = {"immport": {"EXP2": {"verdict": "v", "comment": "a different panel"}}}
    mine = [exp("EXP1", "Flow Cytometry"), exp("EXP2", "Flow Cytometry")]
    rows, _ = mod.plan_study([rec("flow", "EXACT", link("Flow Cytometry", "EXP1"))], mine, notes)
    assert rows[0]["comment"] == "EXP2: a different panel"


def test_note_keys_that_match_nothing_are_reported(mod):
    notes = {"agent": {"typo": {"comment": "c"}, "flow": {"match": ["EXP9"], "comment": "c"}},
             "immport": {"EXP7": {"comment": "c"}}}
    _, warnings = mod.plan_study([rec("flow", "NONE")], [exp("EXP1", "ELISA")], notes)
    assert warnings == ["agent key not in this study: typo",
                        "experiment not in this study: EXP7",
                        "match names an unknown experiment: EXP9"]


def test_an_assay_spanning_two_techniques_is_counted_once(mod):
    mine = [exp("EXP1", "Flow Cytometry"), exp("EXP2", "FACS")]
    rows, _ = mod.plan_study(
        [rec("flow", "EXACT", link("Flow Cytometry", "EXP1"), link("FACS", "EXP2"))], mine, {})
    assert len(rows) == 2
    assert mod.count_levels(rows) == {"EXACT": 1}


def test_render_row_escapes_and_carries_verdict_and_comment(mod):
    notes = {"immport": {"EXP1": {"verdict": "Not in paper", "comment": "a <b> & c"}}}
    rows, _ = mod.plan_study([], [exp("EXP1", "ELISA", "Anti<S1>")], notes)
    out = mod.render_row(rows[0], {"ELISA": ["OBI:0000661"]}, {"OBI:0000661": "ELISA assay"})
    assert '<td class="cmt"><b>Not in paper.</b> a &lt;b&gt; &amp; c</td>' in out
    assert "Anti&lt;S1&gt;" in out and "ImmPort only" in out and "OBI:0000661" in out


def test_replace_section_swaps_only_the_marked_block(mod):
    page = ("<main>keep\n<!-- BEGIN agent-vs-immport (old) -->old"
            "<!-- END agent-vs-immport -->\n</main>")
    assert mod.replace_section(page, "NEW") == "<main>keepNEW</main>"
