"""The free estimate: what a run would cost, counted without calling anything.

This is the cost gate CLAUDE.md requires -- the number a human is shown before deciding to
spend -- so the tests care about two things above all. That no round is ever guessed at, and
that the CLI and the service reach the same answer, because a dry-run that disagrees with the
button means the gate means two different things in two places.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from app.agent import assay_service
from app.agent.assay_service import (
    PaperNotFoundError,
    available_papers,
    estimate_run,
    obi_misses,
    split_stem,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_XML = """<article><front><article-meta><article-title>A Paper</article-title></article-meta>
</front><body><sec><title>Methods</title><p>Cells were analyzed on an LSRII.</p></sec></body></article>"""

_ENTRY = {
    "name_in_paper": "flow cytometry", "aliases": [], "sample_type": "PBMCs",
    "readouts": "cell frequencies",
    "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                 "quote": "Cells were analyzed on an LSRII."},
}


@pytest.fixture
def paper(tmp_path, monkeypatch):
    """One paper on disk, both roots redirected into tmp_path."""
    xml_root, registry_root = tmp_path / "JAT_XML", tmp_path / "assay_registries"
    xml_root.mkdir()
    (xml_root / "SDY1_111.xml").write_text(_XML, encoding="utf-8")
    monkeypatch.setattr(assay_service, "XML_ROOT", xml_root)
    # PDF_ROOT is redirected at an empty directory so the listing cannot pick up the
    # repo's real PDFs: available_papers offers PDF-only papers too.
    _pdf_root = tmp_path / "pdf"
    _pdf_root.mkdir(exist_ok=True)
    monkeypatch.setattr(assay_service, "PDF_ROOT", _pdf_root)
    monkeypatch.setattr(assay_service, "REGISTRY_ROOT", registry_root)
    return registry_root / "111_SDY1"


@pytest.fixture
def vocabulary(monkeypatch):
    """A two-word OBI vocabulary, so the paid/free split is this file's decision.

    Left live, round 4's count would move whenever data/OBI is pruned, and a test about cost
    arithmetic would start failing over an ontology edit it never mentions.
    """
    monkeypatch.setattr(assay_service, "_build_lookup",
                        lambda: {"flow cytometry": "OBI:0000916"})


# ── splitting the two naming schemes ──────────────────────────────────────────

def test_either_naming_order_splits_the_same_way():
    """Registry dirs are <pmid>_<SDY> and XML files <SDY>_<pmid>."""
    assert split_stem("34252919_SDY2189") == ("34252919", "SDY2189")
    assert split_stem("SDY2189_34252919") == ("34252919", "SDY2189")


def test_a_stem_with_no_second_half_is_not_a_paper():
    """None rather than a raise: a directory walk skips, a CLI exits, and that is the
    caller's choice to make."""
    assert split_stem("SDY2189") is None


# ── what cannot be known is not guessed ───────────────────────────────────────

def test_a_paper_never_run_sizes_only_the_rounds_that_are_free_to_size(paper, vocabulary):
    """Rounds 2, 3 and 4 depend on how many assays the extraction finds, and nothing on disk
    says. `None` is the honest answer; a number would be an invented bill."""
    estimate = estimate_run("111", "SDY1")

    calls = {r["name"]: r["calls"] for r in estimate["rounds"]}
    assert calls == {"extract": 1, "verify": None, "correct": None, "obi": None,
                     "canonicalize": 0}
    assert estimate["total_calls_known"] is False
    assert estimate["total_calls"] is None
    # There is no "~" to explain on a paper whose rounds were never sized from anything.
    assert estimate["caveat"] is None
    assert estimate["has_registry"] is False


def test_canonicalizing_is_reported_as_free_even_when_it_cannot_be_sized(paper, vocabulary):
    """0, not None. "We cannot tell you what this costs" would be a lie about a round that
    costs nothing and always has."""
    canon = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "canonicalize"][0]

    assert (canon["calls"], canon["exact"]) == (0, True)
    assert canon["entries"] is None


# ── sized from the previous run ───────────────────────────────────────────────

def _store(paper: Path, assays: dict, verification: dict | None = None,
           obi: dict | None = None) -> None:
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "assays.json").write_text(json.dumps(assays), encoding="utf-8")
    if verification is not None:
        (paper / "assays_verification.json").write_text(json.dumps(verification), encoding="utf-8")
    if obi is not None:
        (paper / "assays_OBI.json").write_text(json.dumps(obi), encoding="utf-8")


def test_verify_is_sized_from_the_stored_registry_but_never_called_exact(paper, vocabulary):
    """One call per assay the last run found -- and this run re-extracts rather than reuses,
    so the number is a shape, not a promise."""
    _store(paper, {"flow cytometry": _ENTRY, "ELISA": _ENTRY})

    verify = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "verify"][0]

    assert verify["calls"] == 2
    assert verify["exact"] is False
    assert verify["basis"] == "last_run"


def test_correct_is_sized_from_the_flagged_fields_not_the_flagged_assays(paper, vocabulary):
    """correct_registry bills per FIELD. One assay with two unsupported fields is two calls,
    and reporting it as one would halve the bill on the gate."""
    _store(paper, {"flow cytometry": _ENTRY}, verification={"summary": {}, "results": [{
        "assay_id": "flow cytometry", "record_verdict": "REVIEW",
        "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [
            {"field_name": "sample_type", "verdict": "NOT_SUPPORTED", "reason": "unstated"},
            {"field_name": "readouts", "verdict": "NOT_REPORTED", "reason": "absent"},
        ]}]})

    correct = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "correct"][0]

    assert correct["calls"] == 2
    assert correct["rejected"] == 0


def test_a_rejected_assay_is_counted_as_set_aside_rather_than_re_extracted(paper, vocabulary):
    """A rejected assay is dropped, not repaired, so it costs nothing -- but the gate still
    has to say one is going to disappear."""
    _store(paper, {"GSEA": _ENTRY}, verification={"summary": {}, "results": [{
        "assay_id": "GSEA", "record_verdict": "REJECT",
        "assay_identity_verdict": "CONTRADICTED",
        "field_verifications": [{"field_name": "name_in_paper", "verdict": "CONTRADICTED",
                                 "reason": "not an assay"}]}]})

    correct = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "correct"][0]

    assert (correct["calls"], correct["rejected"]) == (0, 1)


# ── round 4: the only round whose count is exact ──────────────────────────────

def test_obi_charges_two_calls_for_every_name_the_vocabulary_misses(paper, vocabulary):
    """One embedding plus one pick per miss. Not exact: the count is right for the names the
    last run found, but this run re-extracts them."""
    _store(paper, {"flow cytometry": _ENTRY, "SIMoA": {**_ENTRY, "name_in_paper": "SIMoA"}})

    obi = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "obi"][0]

    assert obi["calls"] == 2
    assert obi["exact"] is False
    assert (obi["free_matches"], obi["misses"]) == (1, ["SIMoA"])


def test_obi_charges_a_third_call_when_the_normalized_name_is_a_second_query(paper, vocabulary):
    """_embedding_llm_match embeds the normalized name too when it differs from the paper's."""
    _store(paper, {"SIMoA": {**_ENTRY, "name_in_paper": "SIMoA",
                             "normalized_name": "single molecule array"}})

    obi = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "obi"][0]

    assert obi["calls"] == 3


def test_the_extractors_normalized_name_resolves_for_free(vocabulary):
    """Step 1b is a dict lookup on a field the extractor already wrote. Omitting it from the
    estimate bills a round that makes no call."""
    entry = {**_ENTRY, "name_in_paper": "FACS", "normalized_name": "flow cytometry"}

    assert obi_misses({"FACS": entry}) == []


def test_only_the_first_wording_is_looked_up_as_the_mapper_does(vocabulary):
    """The mapper queries names[0] and normalized_name, nothing else. Counting a later wording
    -- or the key, which after round 5 is an OBI label -- as free under-billed the round."""
    entry = {**_ENTRY, "name_in_paper": ["FACS", "flow cytometry"]}

    assert obi_misses({"flow cytometry": entry}) == ["flow cytometry"]


def test_a_finished_paper_is_sized_from_its_extraction_not_its_canonical_registry(
        paper, vocabulary):
    """Round 5 re-keys assays.json by OBI label and folds entries; the verification keeps the
    extractor's keys. Sizing from assays.json under-counted verify, matched no verification id
    for correct, and found every OBI label free -- 10 calls quoted for a paper that cost 36."""
    extracted = {"FACS": {**_ENTRY, "name_in_paper": "FACS"},
                 "SIMoA": {**_ENTRY, "name_in_paper": "SIMoA"},
                 "SIMoA kit": {**_ENTRY, "name_in_paper": "SIMoA kit"}}
    verification = {"summary": {}, "results": [{
        "assay_id": "SIMoA", "record_verdict": "REVIEW", "assay_identity_verdict": "SUPPORTED",
        "field_verifications": [
            {"field_name": "sample_type", "verdict": "NOT_SUPPORTED", "reason": "unstated"}]}]}
    canonical = {"flow cytometry": {**_ENTRY, "name_in_paper": ["FACS"]},
                 "digital ELISA": {**_ENTRY, "name_in_paper": ["SIMoA", "SIMoA kit"]}}
    obi = {"flow cytometry": {"obi_id": "OBI:1", "obi_label": "flow cytometry"},
           "digital ELISA": {"obi_id": "OBI:2", "obi_label": "digital ELISA"}}
    _store(paper, canonical, verification=verification, obi=obi)
    (paper / "assays_precorrection.json").write_text(json.dumps(extracted), encoding="utf-8")
    (paper / "assays_corrected.json").write_text(json.dumps(extracted), encoding="utf-8")

    rounds = {r["name"]: r for r in estimate_run("111", "SDY1")["rounds"]}

    assert rounds["verify"]["calls"] == 3
    assert rounds["correct"]["calls"] == 1
    assert rounds["obi"]["misses"] == ["FACS", "SIMoA", "SIMoA kit"]
    assert rounds["obi"]["calls"] == 6
    # Recovered without a stored key_map, through the wordings the survivor keeps.
    assert rounds["canonicalize"]["folds"] == [
        {"key": "digital ELISA", "members": ["SIMoA", "SIMoA kit"]}]


# ── round 5: what would fold ──────────────────────────────────────────────────

def test_the_estimate_names_the_entries_that_would_fold_onto_one_term(paper, vocabulary):
    """Free and deterministic, so this is not a projection -- it is what will happen. Two
    write-ups of one OBI term become one entry, and the gate says which."""
    _store(paper,
           {"ELISA": _ENTRY, "ELISA kits": _ENTRY},
           obi={"ELISA": {"obi_id": "OBI:0000661", "obi_label": "ELISA"},
                "ELISA kits": {"obi_id": "OBI:0000661", "obi_label": "ELISA"}})

    canon = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "canonicalize"][0]

    assert (canon["entries"], canon["groups"]) == (2, 1)
    assert canon["folds"][0]["members"] == ["ELISA", "ELISA kits"]
    assert canon["calls"] == 0


# ── the whole bill ────────────────────────────────────────────────────────────

def test_the_total_is_the_sum_of_the_rounds_once_every_one_is_known(paper, vocabulary):
    _store(paper, {"flow cytometry": _ENTRY}, verification={"summary": {}, "results": []})

    estimate = estimate_run("111", "SDY1")

    # 1 extract + 1 verify + 0 correct + 0 obi (the vocabulary knows it) + 0 canonicalize.
    assert estimate["total_calls"] == 2
    assert estimate["total_calls_known"] is True
    assert estimate["caveat"]


def test_an_unreadable_registry_degrades_to_unsized_rather_than_failing(paper, vocabulary):
    """A half-written file from an interrupted run must not take down the page that was about
    to offer to re-run it."""
    paper.mkdir(parents=True)
    (paper / "assays.json").write_text("{not json", encoding="utf-8")

    verify = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "verify"][0]

    assert verify["calls"] is None


def test_estimating_a_paper_with_no_xml_raises_rather_than_costing_nothing_quietly(paper):
    with pytest.raises(PaperNotFoundError):
        estimate_run("999", "SDY999")


# ── the picker's list ─────────────────────────────────────────────────────────

def test_every_paper_with_an_xml_is_offered_and_finished_ones_carry_their_count(paper, vocabulary):
    """The XML is the gate -- assay_report reads nothing else to find a paper."""
    _store(paper, {"flow cytometry": _ENTRY})
    (paper / "assays_benchmark.json").write_text(json.dumps({"flow cytometry assay": {}}),
                                                 encoding="utf-8")

    papers = available_papers()

    assert len(papers) == 1
    assert papers[0]["study_accession"] == "SDY1"
    assert papers[0]["pubmed_id"] == "111"
    assert papers[0]["paper_title"] == "A Paper"
    assert papers[0]["has_registry"] is True
    assert papers[0]["assays"] == 1
    assert papers[0]["updated_at"]


def test_a_paper_that_has_never_been_run_is_still_offered(paper, vocabulary):
    papers = available_papers()

    assert papers[0]["has_registry"] is False
    assert papers[0]["assays"] is None


# ── the CLI prints what the service counted ───────────────────────────────────

@pytest.fixture(scope="module")
def pipeline_script():
    """Import scripts/run_assay_pipeline.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "run_assay_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_assay_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_dry_run_still_prints_the_format_it_always_has(paper, vocabulary, pipeline_script,
                                                           monkeypatch, capsys):
    """--dry-run is the documented cost gate, and its wording is in the script's own docstring.
    estimate_run moved the counting out; it must not have moved the output.

    The source kind in brackets was added with the PDF route: which of the two prompts round 1
    will read is part of what a reader is deciding on before paying, so it belongs on the gate.
    """
    monkeypatch.setattr(pipeline_script, "estimate_run", estimate_run)
    _store(paper, {"flow cytometry": _ENTRY, "SIMoA": {**_ENTRY, "name_in_paper": "SIMoA"}},
           verification={"summary": {}, "results": []})

    pipeline_script._dry_run("111", "SDY1")

    out = capsys.readouterr().out
    assert "SDY1_111.xml [xml]: " in out and "title 'A Paper'" in out
    assert "  round 1 extract: will run                            1 call" in out
    assert ("  round 2 verify:  will run                            ~2 calls"
            "   (the last run found that many)") in out
    assert ("  round 3 correct: will run                            ~0 calls"
            "   (0 assay(s) set aside last run)") in out
    assert ("  round 4 OBI:     will run                            ~2 calls"
            "   (1 of 2 match the vocabulary for free)") in out
    assert "      needs embedding + LLM: SIMoA" in out
    assert ("  round 5 canon:   will run                            0 calls"
            "   (2 entries → 2, keyed by OBI term)") in out
    assert "~ because rounds 2-4 are sized from the previous run's output" in out
    assert out.rstrip().endswith("--dry-run: nothing called.")


def test_the_dry_run_reports_an_unsized_paper_with_question_marks(paper, vocabulary,
                                                                  pipeline_script, monkeypatch,
                                                                  capsys):
    monkeypatch.setattr(pipeline_script, "estimate_run", estimate_run)

    pipeline_script._dry_run("111", "SDY1")

    out = capsys.readouterr().out
    assert "  round 2 verify:  will run, 1 call per assay found    ? calls" in out
    assert "  round 3 correct: will run, 1 call per flagged field  ? calls" in out
    assert "  round 4 OBI:     will run, 2-3 calls per unmatched   ? calls" in out
    assert "  round 5 canon:   will run, free                       0 calls" in out
    # No "~" paragraph: nothing on this paper was sized from a previous run.
    assert "~ because rounds 2 and 3" not in out


def test_the_dry_run_exits_with_the_scripts_own_wording_for_a_missing_paper(paper,
                                                                           pipeline_script,
                                                                           monkeypatch):
    """PaperNotFoundError is a library concern; a CLI exits.

    The message changed with the PDF route and had to: "No JATS XML" was the whole truth when
    XML was the only source, and would now send someone looking for the wrong file. It names
    both roots it searched instead.
    """
    monkeypatch.setattr(pipeline_script, "estimate_run", estimate_run)

    with pytest.raises(SystemExit) as exc:
        pipeline_script._dry_run("999", "SDY999")

    message = str(exc.value)
    assert message.startswith(
        "No paper for pubmed_id='999' study_accession='SDY999': ")
    assert "no JATS XML under " in message and "no PDF under " in message
