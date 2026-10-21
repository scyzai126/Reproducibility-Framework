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
    obi_query_calls,
    split_stem,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _embedding_strategy(monkeypatch):
    """The OBI estimates below are the embedding strategy's exact 2/3-call bill, which is the
    default; pinning it keeps a developer's .env (OBI_MAPPING_STRATEGY=descend) out of the
    arithmetic. The descent's own estimate is tested in the "tree descent" section at the
    end, which sets the strategy itself."""
    monkeypatch.setattr(assay_service.settings, "OBI_MAPPING_STRATEGY", "embedding")

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
    # A leaf here, so the hit stays free; the live index gives flow cytometry a child.
    monkeypatch.setattr(assay_service, "_index_children", lambda: {})


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
    """Rounds 2 to 5 depend on how many assays the extraction finds -- and, for round 5, how
    many of them share a term -- and nothing on disk says. `None` is the honest answer; a
    number would be an invented bill."""
    estimate = estimate_run("111", "SDY1")

    calls = {r["name"]: r["calls"] for r in estimate["rounds"]}
    assert calls == {"extract": 1, "verify": None, "correct": None, "obi": None,
                     "canonicalize": None}
    assert estimate["total_calls_known"] is False
    assert estimate["total_calls"] is None
    # There is no "~" to explain on a paper whose rounds were never sized from anything.
    assert estimate["caveat"] is None
    assert estimate["has_registry"] is False


def test_canonicalizing_is_unsized_rather_than_guessed_when_nothing_is_stored(paper, vocabulary):
    """None, not 0. Round 5 costs one judge call per group of entries sharing a term, and a
    paper never run says nothing about how many such groups there are."""
    canon = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "canonicalize"][0]

    assert (canon["calls"], canon["exact"], canon["basis"]) == (None, False, "unknown")
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


def test_an_exact_hit_on_a_term_with_children_is_billed(paper, vocabulary, monkeypatch):
    """The picker refines such a hit ("exact_original_llm"), so the estimate must charge it."""
    monkeypatch.setattr(assay_service, "_index_children",
                        lambda: {"OBI:0000916": ("OBI:0003535",)})
    _store(paper, {"flow cytometry": _ENTRY})

    obi = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "obi"][0]

    assert obi["misses"] == ["flow cytometry"]
    assert obi["calls"] >= 2


def test_obi_charges_a_third_call_when_the_technique_is_a_second_query(paper, vocabulary):
    """_embedding_llm_match embeds the technique too when it differs from the paper's."""
    _store(paper, {"SIMoA": {**_ENTRY, "name_in_paper": "SIMoA",
                             "standard_technique_name": "single molecule array"}})

    obi = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "obi"][0]

    assert obi["calls"] == 3


def test_a_technique_that_exact_matches_is_still_a_paid_miss(vocabulary):
    """The mapper no longer looks the technique up exactly (removed 2026-10-02), so an
    entry only it would have resolved goes to step 2 and must be billed."""
    entry = {**_ENTRY, "name_in_paper": "FACS", "standard_technique_name": "flow cytometry"}

    assert obi_misses({"FACS": entry}) == ["FACS"]
    assert obi_query_calls("FACS", entry) == 3


def test_only_the_first_wording_is_looked_up_as_the_mapper_does(vocabulary):
    """The mapper looks up names[0] exactly, nothing else. Counting a later wording
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


# ── round 5: the candidate groups, one judge call each ─────────────────────

def test_the_estimate_names_the_candidate_groups_and_bills_one_call_each(paper, vocabulary):
    """Two write-ups of one OBI term are one candidate group: one judge call, and the gate says
    which entries it will be asked about. Whether they fold is the judge's answer, so the
    round is "~" like the others, not exact."""
    _store(paper,
           {"ELISA": _ENTRY, "ELISA kits": _ENTRY},
           obi={"ELISA": {"obi_id": "OBI:0000661", "obi_label": "ELISA"},
                "ELISA kits": {"obi_id": "OBI:0000661", "obi_label": "ELISA"}})

    canon = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "canonicalize"][0]

    assert (canon["entries"], canon["groups"]) == (2, 1)
    assert canon["folds"][0]["members"] == ["ELISA", "ELISA kits"]
    assert (canon["calls"], canon["exact"], canon["basis"]) == (1, False, "last_run")


def test_a_registry_with_no_mapping_has_no_candidate_groups_and_is_billed_zero(paper, vocabulary):
    """Stored but never mapped: nothing shares a term, so round 5 is sized at 0, not left
    unsized -- the caveat already says the shape may move."""
    _store(paper, {"ELISA": _ENTRY, "ELISA kits": _ENTRY})

    canon = [r for r in estimate_run("111", "SDY1")["rounds"] if r["name"] == "canonicalize"][0]

    assert (canon["calls"], canon["folds"]) == (0, [])


# ── the whole bill ────────────────────────────────────────────────────────────

def test_the_total_is_the_sum_of_the_rounds_once_every_one_is_known(paper, vocabulary):
    _store(paper, {"flow cytometry": _ENTRY}, verification={"summary": {}, "results": []})

    estimate = estimate_run("111", "SDY1")

    # 1 extract + 1 verify + 0 correct + 0 obi (the vocabulary knows it) + 0 canonicalize
    # (one entry shares a term with nothing).
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
    assert ("  round 5 canon:   will run                            ~0 calls"
            "   (2 entries → 2, 0 group(s) to judge)") in out
    assert "~ because rounds 2-5 are sized from the previous run's output" in out
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
    assert "  round 5 canon:   will run, 1 call per candidate group ? calls" in out
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


def test_the_dry_run_names_each_candidate_group_the_judge_will_see(paper, vocabulary,
                                                                   pipeline_script, monkeypatch,
                                                                   capsys):
    """What round 5 will spend on, by name: the entries sharing a term, which is what a reader
    deciding whether to pay wants to see -- a fold is no longer certain, a call is."""
    monkeypatch.setattr(pipeline_script, "estimate_run", estimate_run)
    _store(paper, {"ELISA": _ENTRY, "ELISA kits": _ENTRY},
           obi={"ELISA": {"obi_id": "OBI:0000661", "obi_label": "ELISA"},
                "ELISA kits": {"obi_id": "OBI:0000661", "obi_label": "ELISA"}})

    pipeline_script._dry_run("111", "SDY1")

    out = capsys.readouterr().out
    assert ("  round 5 canon:   will run                            ~1 calls"
            "   (2 entries → 1, 1 group(s) to judge)") in out
    assert "      candidate group ELISA: ELISA, ELISA kits" in out
    assert "folds onto" not in out


# ── 2026-10-20: tree descent ──────────────────────────────────────────────────

def test_the_descent_bills_one_call_from_an_exact_hit_and_three_from_the_root(vocabulary,
                                                                               monkeypatch):
    """An exact hit on a term with children is where the walk starts, so it usually ends at
    the next reply; a name the vocabulary misses starts at the root and is billed the depth
    most targets sit at. The embedding bill of 2/3 never applies under the descent."""
    monkeypatch.setattr(assay_service.settings, "OBI_MAPPING_STRATEGY", "descend")
    monkeypatch.setattr(assay_service, "_index_children", lambda: {"OBI:0000916": ("OBI:x",)})
    hit = {**_ENTRY, "name_in_paper": "flow cytometry", "standard_technique_name": "FACS"}
    miss = {**_ENTRY, "name_in_paper": "SIMoA", "standard_technique_name": "single molecule array"}

    assert obi_misses({"a": hit, "b": miss}) == ["a", "b"]
    assert obi_query_calls("a", hit) == 1
    assert obi_query_calls("b", miss) == assay_service.DESCENT_TYPICAL_CALLS
    assert obi_query_calls("b", miss, strategy="embedding") == 3


def test_the_dry_run_names_the_descent_as_the_paid_step(paper, vocabulary, pipeline_script,
                                                        monkeypatch, capsys):
    monkeypatch.setattr(assay_service.settings, "OBI_MAPPING_STRATEGY", "descend")
    monkeypatch.setattr(pipeline_script, "estimate_run", estimate_run)
    _store(paper, {"SIMoA": {**_ENTRY, "name_in_paper": "SIMoA"}})

    pipeline_script._dry_run("111", "SDY1")

    out = capsys.readouterr().out
    assert ("  round 4 OBI:     will run                            ~3 calls"
            "   (0 of 1 match the vocabulary for free)") in out
    assert "      needs OBI tree descent + LLM: SIMoA" in out


def test_the_dry_run_rates_the_descent_in_the_same_column(paper, vocabulary, pipeline_script,
                                                         monkeypatch, capsys):
    monkeypatch.setattr(assay_service.settings, "OBI_MAPPING_STRATEGY", "descend")
    monkeypatch.setattr(pipeline_script, "estimate_run", estimate_run)

    pipeline_script._dry_run("111", "SDY1")

    out = capsys.readouterr().out
    assert "  round 4 OBI:     will run, ~3 calls per unmatched    ? calls" in out


def test_the_hybrid_bills_the_embedding_calls_plus_one(vocabulary, monkeypatch):
    monkeypatch.setattr(assay_service.settings, "OBI_MAPPING_STRATEGY", "hybrid")
    plain = {**_ENTRY, "name_in_paper": "SIMoA"}
    two_queries = {**_ENTRY, "name_in_paper": "SIMoA", "standard_technique_name": "single molecule array"}

    assert obi_query_calls("a", plain) == 3
    assert obi_query_calls("b", two_queries) == 4
    assert obi_query_calls("b", two_queries, strategy="embedding") == 3
