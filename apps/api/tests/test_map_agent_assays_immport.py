"""Unit tests for scripts/map_agent_assays_to_immport.py — no database, no network.

The script turns the technique-level grading of `check_immport_measurements.py` around: one
agent entry at a time, down to the experiment row. What can go quietly wrong is the second
level — picking one experiment where nothing chooses — so that is pinned alongside the levels.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

FLOW, ELISA, ICS_PARENT = "OBI:0000916", "OBI:0000661", "OBI:0003230"


@pytest.fixture(scope="module")
def mod():
    path = REPO_ROOT / "scripts" / "map_agent_assays_to_immport.py"
    spec = importlib.util.spec_from_file_location("map_agent_assays_to_immport", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def obi(mod):
    return mod.ObiGraph()


def entry(obi_id, key="e", forms=None, **extra):
    return {"pmid": "1", "key": key, "obi_id": obi_id, "obi_label": key,
            "forms": forms or [], **extra}


def exp(accession, name, description=""):
    return {"accession": accession, "name": name, "description": description}


def group(technique, ids, *experiments):
    return {"technique": technique, "ids": list(ids), "experiments": list(experiments)}


def test_build_groups_keeps_uninformative_marked_and_groups_by_technique(mod):
    rows = [
        ("SDY1", "Flow Cytometry", "EXP1", "B cell", None),
        ("SDY1", "Flow Cytometry", "EXP2", "T cell", "panel"),
        ("SDY1", "Other", "EXP3", "misc", None),
    ]
    groups, dropped = mod.build_groups(
        rows, {"Flow Cytometry": "http://purl.obolibrary.org/obo/OBI_0000916"})
    flow, other = groups["SDY1"]
    assert (flow["technique"], flow["ids"], flow["uninformative"]) == ("Flow Cytometry", [FLOW], False)
    assert [e["accession"] for e in flow["experiments"]] == ["EXP1", "EXP2"]
    assert (other["technique"], other["ids"], other["uninformative"]) == ("Other", [], True)
    assert dropped == [("SDY1", "Other", ["EXP3"])]


def other(*experiments):
    return {"technique": "Other", "ids": [], "experiments": list(experiments),
            "uninformative": True}


def test_other_experiment_matched_when_its_name_is_the_assays_own_name(mod, obi):
    groups = [other(exp("EXP1", "O-link"), exp("EXP2", "Determination of LPS in plasma"))]
    result = mod.map_entry(
        entry("OBI:0003112", key="Olink assay", forms=["olink multiplex inflammation panel"],
              sample_type="plasma"), groups, obi)
    assert result["level"] == "EXPNAME"
    assert result["links"][0]["experiments"] == [{"accession": "EXP1", "name": "O-link"}]
    assert result["links"][0]["evidence"] == "experiment name is the assay's own name"


def test_other_experiment_matched_on_two_shared_content_words(mod, obi):
    groups = [other(exp("EXP1", "O-link"), exp("EXP2", "Determination of LPS in plasma"))]
    result = mod.map_entry(
        entry(None, forms=["tlr4 based reporter assay"], sample_type="plasma",
              readouts="lipopolysaccharide (LPS) levels in plasma"), groups, obi)
    assert result["level"] == "EXPNAME"
    assert [e["accession"] for e in result["links"][0]["experiments"]] == ["EXP2"]
    assert result["links"][0]["evidence"] == "shared words: lps, plasma"


def test_other_experiment_not_matched_on_one_shared_word(mod, obi):
    groups = [other(exp("EXP1", "MHC_peptide_binding"))]
    result = mod.map_entry(
        entry("OBI:0600031", forms=["elispot"],
              readouts="spot-forming cells after stimulation with a peptide pool"), groups, obi)
    assert result == {"level": "NONE", "links": []}


def test_other_bucket_leaves_its_unnamed_experiments_unreached(mod, obi):
    entries = {"SDY1": [entry("OBI:0003112", key="olink", forms=["olink panel"])]}
    groups = {"SDY1": [other(exp("EXP1", "O-link"), exp("EXP2", "MHC_peptide_binding"))]}
    records, unreached = mod.map_all(entries, groups, obi)
    assert records[0]["level"] == "EXPNAME"
    assert unreached == {"SDY1": [
        {"technique": "Other", "accession": "EXP2", "name": "MHC_peptide_binding"}]}


def test_exact_single_experiment(mod, obi):
    result = mod.map_entry(entry(ELISA), [group("ELISA", [ELISA], exp("EXP1", "titers"))], obi)
    assert result["level"] == "EXACT"
    assert result["links"][0]["status"] == "SINGLE"
    assert result["links"][0]["experiments"] == [{"accession": "EXP1", "name": "titers"}]


def test_descendant_when_agent_term_is_more_specific(mod, obi):
    result = mod.map_entry(
        entry(ICS_PARENT), [group("Flow Cytometry", [FLOW], exp("EXP1", "AIM"))], obi)
    assert result["level"] == "DESCENDANT"


def test_none_when_no_technique_matches(mod, obi):
    result = mod.map_entry(
        entry(ELISA, forms=["elisa"]),
        [group("Flow Cytometry", [FLOW], exp("EXP1", "B cell"))], obi)
    assert result == {"level": "NONE", "links": []}


def test_best_level_wins_and_ties_are_all_kept(mod, obi):
    groups = [
        group("Flow Cytometry", [FLOW], exp("EXP1", "B cell")),
        group("FACS panel", [FLOW], exp("EXP2", "T cell")),
        group("ELISA", [ELISA], exp("EXP3", "titers")),
    ]
    result = mod.map_entry(entry(FLOW), groups, obi)
    assert result["level"] == "EXACT"
    assert [link["technique"] for link in result["links"]] == ["Flow Cytometry", "FACS panel"]


def test_expname_level_and_named_by_experiment_name(mod, obi):
    groups = [group("Neutralizing Antibody Titer Assay", ["OBI:0000872"],
                    exp("EXP1", "Serum bactericidal assay"), exp("EXP2", "HAI titers"))]
    result = mod.map_entry(entry(None, forms=["serum bactericidal assay"]), groups, obi)
    assert result["level"] == "EXPNAME"
    link = result["links"][0]
    assert link["status"] == "NAMED"
    assert link["experiments"] == [{"accession": "EXP1", "name": "Serum bactericidal assay"}]


def test_named_by_words_only_the_siblings_do_not_share(mod):
    experiments = [exp("EXP1", "Flow Cytometry B cell"), exp("EXP2", "Flow Cytometry T cell")]
    picked = mod.pick_experiments(
        entry(FLOW, forms=["flow cytometry"], readouts="frequency of B cell subsets"),
        experiments)
    assert picked["status"] == "NAMED"
    assert picked["experiments"][0]["accession"] == "EXP1"
    assert picked["evidence"] == "shared words: b"


def test_ambiguous_when_nothing_chooses(mod):
    experiments = [exp("EXP1", "IM_panel_BA Flow Cytometry"),
                   exp("EXP2", "IM_panel_BB Flow Cytometry")]
    picked = mod.pick_experiments(entry(FLOW, forms=["flow cytometry"]), experiments)
    assert picked["status"] == "AMBIGUOUS"
    assert picked["experiments"] == []
    assert [c["accession"] for c in picked["candidates"]] == ["EXP1", "EXP2"]


def test_ambiguous_when_two_experiments_tie_on_words(mod):
    experiments = [exp("EXP1", "T cell day 0"), exp("EXP2", "T cell day 7")]
    picked = mod.pick_experiments(
        entry(FLOW, forms=["flow cytometry"], readouts="T cell frequency"), experiments)
    assert picked["status"] == "AMBIGUOUS"


def test_map_all_lists_unreached_experiments_and_ignores_sibling(mod, obi):
    entries = {"SDY1": [entry(ELISA, key="elisa")]}
    groups = {"SDY1": [
        group("ELISA", [ELISA], exp("EXP1", "titers")),
        group("Flow Cytometry", [FLOW], exp("EXP2", "B cell")),
    ]}
    records, unreached = mod.map_all(entries, groups, obi)
    assert [(r["key"], r["level"]) for r in records] == [("elisa", "EXACT")]
    assert unreached == {"SDY1": [
        {"technique": "Flow Cytometry", "accession": "EXP2", "name": "B cell"}]}


def test_map_all_merges_sample_type_and_readouts_from_extras(mod, obi):
    entries = {"SDY1": [entry(FLOW, key="flow")]}
    groups = {"SDY1": [group("Flow Cytometry", [FLOW],
                             exp("EXP1", "B cell"), exp("EXP2", "T reg"))]}
    extras = {("1", "flow"): {"sample_type": "PBMC", "readouts": "T reg frequency",
                              "name_in_paper": ["flow"]}}
    records, _ = mod.map_all(entries, groups, obi, extras)
    link = records[0]["links"][0]
    assert link["status"] == "NAMED" and link["experiments"][0]["accession"] == "EXP2"


def test_report_counts_every_entry_once(mod, obi):
    entries = {"SDY1": [entry(ELISA, key="elisa"), entry(None, key="sds page")]}
    groups = {"SDY1": [group("ELISA", [ELISA], exp("EXP1", "titers"))]}
    records, unreached = mod.map_all(entries, groups, obi)
    text = "\n".join(mod.report_lines(records, unreached, [], groups, []))
    assert "**Mapped: 1 of 2** agent entries. Not in ImmPort: 1." in text
    assert "| sds page | unmapped | NONE | not in ImmPort | |" in text
