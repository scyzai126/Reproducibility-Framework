"""The benchmark comparison: what counts as the same assay under two different naming conventions.

The curator keys assays by OBI label, the agent keys them by the paper's own wording, so every test
here is about the matcher deciding those name two things or one. The tiers below a shared OBI id are
the risky part -- a Methods heading such as "Flow Cytometry Analysis and Cell Sorting for RNA
Sequencing" names two assays in one quote -- so most of these cases guard against a false pairing
rather than a missed one.

Fixtures are inline; nothing here reads the real corpus or the 1.6 MB OBI release.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_comparer():
    """Import scripts/compare_assay_benchmark.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "compare_assay_benchmark.py"
    spec = importlib.util.spec_from_file_location("compare_assay_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cmp_mod():
    return _load_comparer()


# A four-term slice of OBI: an assay, two RNA-seq terms in an is_a line, and one unrelated term.
_INDEX = [
    {"id": "OBI:0000916", "label": "flow cytometry assay", "synonyms": ["FACS"]},
    {"id": "OBI:0000920", "label": "cytometric bead array assay", "synonyms": ["Luminex assay"]},
    {"id": "OBI:0001271", "label": "RNA-seq assay", "synonyms": []},
    {"id": "OBI:0003090", "label": "bulk RNA-seq assay", "synonyms": []},
    {"id": "OBI:0600031", "label": "enzyme-linked immunospot assay", "synonyms": ["ELISpot"]},
]

_OBO = """format-version: 1.2

[Term]
id: OBI:0001271
name: RNA-seq assay

[Term]
id: OBI:0003090
name: bulk RNA-seq assay
is_a: OBI:0001271 ! RNA-seq assay

[Term]
id: OBI:0000916
name: flow cytometry assay

[Term]
id: OBI:0000920
name: cytometric bead array assay
synonym: "Luminex assay" EXACT []

[Term]
id: OBI:0600031
name: enzyme-linked immunospot assay
"""


@pytest.fixture(scope="module")
def obi(cmp_mod, tmp_path_factory):
    root = tmp_path_factory.mktemp("obi")
    index = root / "index.json"
    index.write_text(json.dumps(_INDEX), encoding="utf-8")
    obo = root / "obi.obo"
    obo.write_text(_OBO, encoding="utf-8")
    return cmp_mod.ObiGraph(index_path=index, obo_path=obo)


def _bench(name, aliases=(), quote="", key_obi=None):
    return {"name_in_paper": name, "aliases": list(aliases),
            "evidence_location": {"type": "text", "section": "Methods", "quote": quote}}


def _ours(key, name=None, aliases=(), obi_id=None, obi_label=None, quote="a quote", section="Methods"):
    return {"key": key, "name_in_paper": name or key, "aliases": list(aliases),
            "obi_id": obi_id, "obi_label": obi_label, "source": "methods",
            "evidence": {"section": section, "sentence_ids": ["S1"], "quote": quote}}


# ── term resolution ──────────────────────────────────────────────────────────


def test_resolve_finds_a_term_through_its_synonym(obi):
    """"Luminex assay" is only an EXACT synonym of OBI:0000920, and the curator keys on it."""
    assert obi.resolve("Luminex assay") == "OBI:0000920"


def test_resolve_returns_none_for_a_key_that_is_not_an_obi_term(obi):
    """Two SDY2189 keys are the curator's own placeholders, and SBA has no OBI term at all."""
    assert obi.resolve("serum bactericidal activity assay") is None
    assert obi.resolve("?") is None


# ── matching tiers ───────────────────────────────────────────────────────────


def test_equal_obi_ids_pair_at_the_strongest_tier(cmp_mod, obi):
    hit = cmp_mod.match_tier(_bench("flow cytometry"), "OBI:0000916",
                             _ours("Flow cytometric analysis", obi_id="OBI:0000916"), obi)
    assert hit == ("obi_exact", None)


def test_an_is_a_child_pairs_as_ancestry_and_records_the_direction(cmp_mod, obi):
    hit = cmp_mod.match_tier(_bench("RNA-Seq"), "OBI:0001271",
                             _ours("Bulk transcriptomics", obi_id="OBI:0003090"), obi)
    assert hit == ("obi_ancestry", "ours_narrower")


def test_names_pair_through_an_alias_on_either_side(cmp_mod, obi):
    """The curator's alias is often the agent's key verbatim, and vice versa."""
    hit = cmp_mod.match_tier(_bench("flow cytometry", aliases=["Surface and intracellular cytokine staining"]),
                             "OBI:0000916",
                             _ours("Surface and intracellular cytokine staining", obi_id="OBI:0001632"), obi)
    assert hit[0] == "name"


def test_greek_letters_and_hyphens_do_not_block_a_name_match(cmp_mod, obi):
    hit = cmp_mod.match_tier(_bench("ex vivo IFNγ ELISpot"), None,
                             _ours("ex vivo IFN-γ ELISpot", obi_id=None), obi)
    assert hit[0] == "name"


def test_a_longer_name_containing_the_benchmark_name_pairs(cmp_mod, obi):
    hit = cmp_mod.match_tier(_bench("neutralization titre assay"), None,
                             _ours("Focus reduction neutralization titre assay"), obi)
    assert hit[0] == "name_containment"


def test_the_benchmark_quote_naming_our_assay_pairs_at_the_weakest_tier(cmp_mod, obi):
    """The curator names an assay by a word too short to contain-match, and quotes the sentence."""
    hit = cmp_mod.match_tier(
        _bench("Olink", quote="We measured cytokines in plasma using the Olink multiplex proximity "
                              "extension assay inflammation panel"),
        None,
        _ours("Olink multiplex proximity extension assay inflammation panel", obi_id="OBI:0003112"), obi)
    assert hit == ("quote", "benchmark quote names our assay")


def test_the_quote_tier_refuses_an_assay_whose_obi_term_disagrees(cmp_mod, obi):
    """The same quote names an ELISA. Two unrelated OBI terms mean two assays in one sentence."""
    hit = cmp_mod.match_tier(
        _bench("flow cytometry", quote="performed by DENV-specific IgG ELISAs and flow cytometry"),
        "OBI:0000916",
        _ours("DENV-specific IgG ELISAs", obi_id="OBI:0000661"), obi)
    assert hit is None


# ── row assembly ─────────────────────────────────────────────────────────────


def _paper(tmp_path, bench: dict, ours: dict, ours_obi: dict) -> dict:
    registry = tmp_path / "12345_SDY1"
    registry.mkdir()
    (registry / "assays_benchmark.json").write_text(json.dumps(ours), encoding="utf-8")
    (registry / "assays_OBI.json").write_text(json.dumps(ours_obi), encoding="utf-8")
    bench_file = tmp_path / "SDY1_Assay_Hailong.json"
    bench_file.write_text(json.dumps(bench), encoding="utf-8")
    return {"study": "SDY1", "pmid": "12345", "benchmark": bench_file, "registry": registry}


def _entry(name, aliases=(), section="Methods", quote="the quote"):
    return {"name_in_paper": name, "aliases": list(aliases), "source": "methods",
            "evidence": {"section": section, "sentence_ids": ["S1", "S2"], "quote": quote}}


def test_two_entries_on_one_benchmark_row_become_one_split_carrying_both_evidence_blocks(cmp_mod, obi, tmp_path, monkeypatch):
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)
    pair = _paper(
        tmp_path,
        {"enzyme-linked immunospot assay": _bench("ELISpot")},
        {"ELISpot": _entry("ELISpot", quote="first"), "ELISpot kits": _entry("ELISpot kits", quote="second")},
        {"ELISpot": {"obi_id": "OBI:0600031"}, "ELISpot kits": {"obi_id": "OBI:0600031"}},
    )
    result = cmp_mod.compare_paper(pair, obi)
    row = result["rows"][0]
    assert row["status"] == "SPLIT"
    assert [o["key"] for o in row["ours"]] == ["ELISpot", "ELISpot kits"]
    assert [o["evidence"]["quote"] for o in row["ours"]] == ["first", "second"]
    assert result["metrics"]["matched"] == 1  # a split is one benchmark assay found, not two
    assert result["metrics"]["extra"] == 0


def test_a_leftover_entry_sharing_an_obi_term_is_folded_into_the_split(cmp_mod, obi, tmp_path, monkeypatch):
    """SDY2189 runs its neutralization assay twice, wild-type and variant. That is not a new find."""
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)
    pair = _paper(
        tmp_path,
        {"?Neutralizing Antibody Titer Assay?": _bench("neutralization titre assay")},
        {"Focus reduction neutralization titre assay": _entry("Focus reduction neutralization titre assay"),
         "FRNT assay against the variants of concern": _entry("FRNT assay against the variants of concern")},
        {"Focus reduction neutralization titre assay": {"obi_id": "OBI:0000872"},
         "FRNT assay against the variants of concern": {"obi_id": "OBI:0000872"}},
    )
    result = cmp_mod.compare_paper(pair, obi)
    assert result["rows"][0]["status"] == "SPLIT"
    assert len(result["rows"][0]["ours"]) == 2
    assert result["metrics"]["extra"] == 0


def test_an_unmatched_benchmark_row_is_missed_and_keeps_the_curator_quote(cmp_mod, obi, tmp_path, monkeypatch):
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)
    pair = _paper(
        tmp_path,
        {"flow cytometry assay": _bench("flow cytometry", quote="cells were analysed by flow cytometry")},
        {"Hi-C data": _entry("Hi-C data")},
        {"Hi-C data": {"obi_id": "OBI:0002042"}},
    )
    result = cmp_mod.compare_paper(pair, obi)
    missed = [r for r in result["rows"] if r["status"] == "MISSED"]
    assert len(missed) == 1
    assert missed[0]["benchmark"]["evidence_location"]["quote"] == "cells were analysed by flow cytometry"
    assert result["metrics"]["recall"] == 0.0


def test_an_unmatched_entry_of_ours_is_extra_and_keeps_its_paper_evidence(cmp_mod, obi, tmp_path, monkeypatch):
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)
    pair = _paper(
        tmp_path,
        {"enzyme-linked immunospot assay": _bench("ELISpot")},
        {"ELISpot": _entry("ELISpot"),
         "Hi-C data": _entry("Hi-C data", section="Chromatin", quote="Hi-C libraries were prepared")},
        {"ELISpot": {"obi_id": "OBI:0600031"}, "Hi-C data": {"obi_id": "OBI:0002042"}},
    )
    result = cmp_mod.compare_paper(pair, obi)
    extra = [r for r in result["rows"] if r["status"] == "EXTRA"]
    assert [r["ours"][0]["key"] for r in extra] == ["Hi-C data"]
    assert extra[0]["ours"][0]["source"] == "methods"
    assert extra[0]["ours"][0]["evidence"]["section"] == "Chromatin"
    assert extra[0]["ours"][0]["evidence"]["quote"] == "Hi-C libraries were prepared"
    assert result["metrics"]["recall"] == 1.0  # an extra never costs recall


def test_metrics_report_recall_and_no_precision(cmp_mod, obi, tmp_path, monkeypatch):
    """The benchmark is a recall reference; a precision figure would assume it is exhaustive."""
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)
    pair = _paper(tmp_path, {"enzyme-linked immunospot assay": _bench("ELISpot")},
                  {"ELISpot": _entry("ELISpot")}, {"ELISpot": {"obi_id": "OBI:0600031"}})
    metrics = cmp_mod.compare_paper(pair, obi)["metrics"]
    assert "precision" not in metrics
    assert metrics == {"benchmark_total": 1, "ours_total": 1, "matched": 1, "missed": 0, "extra": 0, "recall": 1.0}


def test_a_conflicting_obi_mapping_is_flagged_with_both_terms_named(cmp_mod, obi, tmp_path, monkeypatch):
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)
    pair = _paper(
        tmp_path,
        {"flow cytometry assay": _bench("Intracellular cytokine staining assay")},
        {"Intracellular cytokine staining assay": _entry("Intracellular cytokine staining assay")},
        {"Intracellular cytokine staining assay": {"obi_id": "OBI:0001632", "obi_label": "immuno staining assay"}},
    )
    row = cmp_mod.compare_paper(pair, obi)["rows"][0]
    assert row["status"] == "MATCH_OBI_CONFLICT"
    assert "OBI:0000916" in row["reason"] and "OBI:0001632" in row["reason"]


# ── pairing papers to registries ─────────────────────────────────────────────


def test_a_benchmark_filename_with_a_pmid_picks_that_registry(cmp_mod, tmp_path, monkeypatch):
    """SDY1364 has two registries, one per paper, so its benchmark filename carries the PMID."""
    bench_dir = tmp_path / "benchmark_assay"
    bench_dir.mkdir()
    (bench_dir / "SDY1364_23266342_Assay_Hailong.json").write_text("{}", encoding="utf-8")
    registries = tmp_path / "assay_registries"
    for name in ("23266342_SDY1364", "23844129_SDY1364"):
        (registries / name).mkdir(parents=True)
        (registries / name / "assays_benchmark.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cmp_mod, "BENCHMARK_DIR", bench_dir)
    monkeypatch.setattr(cmp_mod, "REGISTRY_DIR", registries)
    monkeypatch.setattr(cmp_mod, "REPO_ROOT", tmp_path)

    pairs = cmp_mod.discover_pairs()
    assert [(p["study"], p["pmid"]) for p in pairs] == [("SDY1364", "23266342")]


def test_an_ambiguous_pairing_stops_rather_than_guesses(cmp_mod, tmp_path, monkeypatch):
    bench_dir = tmp_path / "benchmark_assay"
    bench_dir.mkdir()
    (bench_dir / "SDY1364_Assay_Hailong.json").write_text("{}", encoding="utf-8")
    registries = tmp_path / "assay_registries"
    for name in ("23266342_SDY1364", "23844129_SDY1364"):
        (registries / name).mkdir(parents=True)
        (registries / name / "assays_benchmark.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cmp_mod, "BENCHMARK_DIR", bench_dir)
    monkeypatch.setattr(cmp_mod, "REGISTRY_DIR", registries)

    with pytest.raises(SystemExit, match="expected exactly one registry"):
        cmp_mod.discover_pairs()


def test_our_side_matches_through_any_wording_of_a_canonicalized_entry(cmp_mod, obi):
    """After round 5 our `name_in_paper` is a list, and the benchmark may name either wording."""
    hit = cmp_mod.match_tier(_bench("ELISA kits"), None,
                             {**_ours("enzyme-linked immunosorbent assay"),
                              "name_in_paper": ["ELISA", "ELISA kits"]}, obi)

    assert hit[0] == "name"


def test_surface_forms_accepts_a_list_or_a_string(cmp_mod):
    assert cmp_mod._surface_forms(["ELISA", "ELISA kits"], []) == ["elisa", "elisa kits"]
    assert cmp_mod._surface_forms("ELISA", ["FACS"]) == ["elisa", "facs"]
