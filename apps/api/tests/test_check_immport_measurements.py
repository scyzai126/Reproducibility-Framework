"""Unit tests for scripts/check_immport_measurements.py — no database, no network.

The script's judgement is the match level, so that is what is pinned here: each level on a
hand-built pair, plus the two things that quietly corrupt a coverage number if they regress —
`Other` being counted, and a SIBLING rule loose enough to pair unrelated assays.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def mod():
    path = REPO_ROOT / "scripts" / "check_immport_measurements.py"
    spec = importlib.util.spec_from_file_location("check_immport_measurements", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def obi(mod):
    return mod.ObiGraph()


def entry(obi_id: str | None, key: str = "e", forms: list[str] | None = None) -> dict:
    return {"pmid": "1", "key": key, "obi_id": obi_id, "obi_label": key, "forms": forms or []}


def test_term_ids_reads_purls_and_puts_obi_first(mod):
    link = "http://purl.obolibrary.org/obo/NCIT_C18113 ; http://purl.obolibrary.org/obo/OBI_0000916"
    assert mod.term_ids(link) == ["OBI:0000916", "NCIT:C18113"]
    assert mod.term_ids(None) == []
    assert mod.term_ids("http://en.wikipedia.org/wiki/Circular_Dichroism") == []


def test_exact_when_the_ids_agree(mod, obi):
    level, hit = mod.classify(["OBI:0000916"], "Flow Cytometry", [entry("OBI:0000916")], obi)
    assert level == "EXACT"
    assert hit["obi_id"] == "OBI:0000916"


def test_descendant_when_we_were_more_specific(mod, obi):
    """OBI:0001724 hangs under OBI:0000875, the term ImmPort's "Hemagglutination Inhibition"
    resolves to — we named the finer assay, which still answers what ImmPort registered."""
    assert "OBI:0000875" in obi.ancestors("OBI:0001724")
    level, _ = mod.classify(["OBI:0000875"], "Hemagglutination Inhibition",
                            [entry("OBI:0001724")], obi)
    assert level == "DESCENDANT"


def test_sibling_needs_a_shared_direct_parent(mod, obi):
    """Real time RT-PCR is not *under* real time PCR — both hang off `PCR assay`."""
    level, _ = mod.classify(["OBI:0000893"], "Q-PCR", [entry("OBI:0000911")], obi)
    assert level == "SIBLING"


def test_sibling_does_not_pair_unrelated_assays(mod, obi):
    """The earlier rule — any common ancestor below the root — paired these. One is_a step apart
    is the whole difference between a sibling and a stranger."""
    level, _ = mod.classify(["OBI:0000872"], "Neutralizing Antibody Titer Assay",
                            [entry("OBI:0001463")], obi)   # transcription profiling by array
    assert level == "MISS"
    level, _ = mod.classify(["OBI:0002115"], "CyTOF", [entry("OBI:0000875")], obi)
    assert level == "MISS"


def test_sibling_rejects_a_shared_hub_parent(mod, obi):
    """`analyte assay` groups by having an analyte, not by method, so its children are not a
    family: ELISA, bead array and neutralizing-antibody titer all hang directly off it. Pinning
    the two pairs that got through when only the root was excluded."""
    assert "OBI:0000443" in obi.parents["OBI:0000661"]
    assert "OBI:0000443" in obi.parents["OBI:0000872"]
    assert "OBI:0000443" in obi.parents["OBI:0000920"]

    level, _ = mod.classify(["OBI:0000872"], "Neutralizing Antibody Titer Assay",
                            [entry("OBI:0000661")], obi)          # our ELISA
    assert level == "MISS"
    level, _ = mod.classify(["OBI:0000661"], "ELISA", [entry("OBI:0000920")], obi)
    assert level == "MISS"


def test_expname_matches_when_the_controlled_term_does_not(mod, obi):
    """SDY1325: the technique reads `Neutralizing Antibody Titer Assay` (a viral term) while the
    experiment name reads what the paper actually ran."""
    ours = entry("OBI:0003797", forms=["serum bactericidal assay", "sba"])
    assert mod.classify(["OBI:0000872"], "Neutralizing Antibody Titer Assay", [ours], obi)[0] == "MISS"
    level, hit = mod.classify(["OBI:0000872"], "Neutralizing Antibody Titer Assay", [ours], obi,
                              ["Serum bactericidal assay"])
    assert level == "EXPNAME"
    assert hit["obi_id"] == "OBI:0003797"


def test_expname_matches_inside_a_long_experiment_name(mod, obi):
    """SDY1373: ImmPort filed RNA-seq data under the array technique; only the name says so."""
    ours = entry("OBI:0003090", forms=["rna seq", "next generation rna sequencing"])
    level, _ = mod.classify(["OBI:0001463"], "Transcription profiling by array", [ours], obi,
                            ["Next Generation Sequencing RNA Seq data from UKE Phase I rVSV "
                             "ZEBOV vaccine clinical trial, from full blood samples on Days 0,1,3,7"])
    assert level == "EXPNAME"


def test_expname_matches_when_ours_is_the_longer_string(mod, obi):
    """SDY1655: `Cytokine Array` sits inside the paper's full product name."""
    ours = entry("OBI:0000920",
                 forms=["human cytokine array chemokine array 71 403 plex panel hd71"])
    level, _ = mod.classify(["OBI:0400149"], "Protein microarray", [ours], obi, ["Cytokine Array"])
    assert level == "EXPNAME"


def test_expname_needs_more_than_one_word(mod, obi):
    """A single token inside free text is not evidence — `AntiS1IgG` must not pair with our
    ELISA, and a bare `elisa` must not be carried by an unrelated experiment name."""
    # A one-token form of ours sitting inside an unrelated experiment name carries nothing.
    ours = entry("OBI:0000661", forms=["elisa"])
    level, _ = mod.classify(["OBI:0400149"], "Protein microarray", [ours], obi,
                            ["Serum elisa plate controls for the array run"])
    assert level == "MISS"
    # ImmPort's own one-token names likewise: `AntiS1IgG` must not reach our bead array.
    bead = entry("OBI:0000920", forms=["human cytokine array chemokine array 71 403 plex panel"])
    level, _ = mod.classify(["OBI:0000661"], "ELISA", [bead], obi, ["AntiS1IgG", "AntiS1IgM"])
    assert level == "MISS"


def test_expname_ranks_below_the_ontology_levels(mod):
    assert mod.classify.__doc__
    ranks = {"MISS": 0, "SIBLING": 1, "EXPNAME": 2, "NAME": 3,
             "ANCESTOR": 4, "DESCENDANT": 5, "EXACT": 6}
    assert ranks["EXPNAME"] > ranks["SIBLING"]
    assert ranks["EXPNAME"] < ranks["NAME"]


def test_name_match_when_we_have_no_term(mod, obi):
    level, hit = mod.classify([], "Nanostring", [entry(None, forms=["nanostring"])], obi)
    assert level == "NAME"
    assert hit["forms"] == ["nanostring"]


def test_any_of_several_ids_counts(mod, obi):
    """RNA sequencing carries two PURLs; matching either one is a match."""
    level, _ = mod.classify(["OBI:0001177", "OBI:0001271"], "RNA sequencing",
                            [entry("OBI:0001271")], obi)
    assert level == "EXACT"


def test_miss_when_nothing_relates(mod, obi):
    level, hit = mod.classify(["OBI:0400149"], "Protein microarray", [entry("OBI:0000916")], obi)
    assert level == "MISS"
    assert hit is None


def test_uninformative_techniques_are_recognised(mod):
    assert mod.normalize("Other") in mod.UNINFORMATIVE
    assert mod.normalize("Flow Cytometry") not in mod.UNINFORMATIVE


def test_our_entries_unions_papers_of_one_study(mod, tmp_path):
    """ImmPort registers per study; two papers of one study must land in one bucket."""
    for pmid, key in (("111", "flow cytometry assay"), ("222", "enzyme-linked immunosorbent assay")):
        folder = tmp_path / f"{pmid}_SDY1"
        folder.mkdir()
        (folder / "assays_benchmark.json").write_text(
            json.dumps({key: {"name_in_paper": [key], "aliases": []}}), encoding="utf-8")
        (folder / "assays_OBI.json").write_text(
            json.dumps({key: {"obi_id": "OBI:0000916", "obi_label": key}}), encoding="utf-8")

    by_study = mod.our_entries(tmp_path)

    assert set(by_study) == {"SDY1"}
    assert sorted(e["pmid"] for e in by_study["SDY1"]) == ["111", "222"]
