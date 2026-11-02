"""The CLI's findings printer: every reason not to trust an entry is a line, never a count.

CLAUDE.md requires WARNING / REVIEW / REJECT / DROPPED / MERGED lines be reported rather than
summarised. These are the findings that used to reach disk and never the terminal.
"""

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def cli():
    path = _REPO_ROOT / "scripts" / "run_assay_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_assay_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ENTRY = {
    "name_in_paper": ["flow cytometry"], "standard_technique_name": None, "aliases": [],
    "platform": None, "sample_type": None, "readouts": None, "measurement_role": "reported",
    "parent_hint": None, "source": "methods",
    "evidence": {"section": "Methods", "sentence_ids": [], "quote": "Cells were stained."},
}


def _result(**over) -> dict:
    result = {
        "paper_source": "SDY1_111.pdf", "paper_source_kind": "pdf", "paper_title": "A Paper",
        "rounds": {}, "assays": {"flow cytometry": _ENTRY},
        "quote_check": {"verified": 1, "total": 1, "missing": 0, "misattributed": 0,
                        "source_aligned": 0, "per_assay": {}},
        "verification": None, "corrections": None, "dropped": {}, "merges": None, "obi": None,
        "meta": {"llm_calls": 1, "benchmark_path": "b", "registry_path": "r"},
    }
    result.update(over)
    return result


def test_a_pdf_registry_is_not_warned_about_missing_sentence_ids(cli, capsys):
    """A PDF has no [S<n>] markers; demanding ids there warned on every entry."""
    cli.report_result(_result())

    assert "sentence_ids" not in capsys.readouterr().out


def test_a_verification_that_failed_is_a_line_of_its_own(cli, capsys):
    cli.report_result(_result(verification={"results": [
        {"assay_id": "FACS", "record_verdict": "ERROR", "error": "verifier returned an empty reply"}]},
        merges={"results": [], "key_map": {"FACS": "flow cytometry"}}))

    out = capsys.readouterr().out
    assert "ERROR  FACS → flow cytometry: verifier returned an empty reply" in out


def test_a_refused_correction_is_reported(cli, capsys):
    cli.report_result(_result(corrections={"results": [{"assay_id": "FACS", "corrections": [
        {"field": "evidence", "action": "UNCHANGED",
         "note": "replacement quote rejected: quote does not appear anywhere in the document"}]}]}))

    assert "CORRECT REFUSED  FACS / evidence: replacement quote rejected" in capsys.readouterr().out


def test_an_obi_lookup_error_is_told_apart_from_an_unmapped_name(cli, capsys):
    cli.report_result(_result(rounds={"obi": {"source": "mapped", "unresolved": ["a", "b"],
                                              "errors": {"b": "TimeoutError: slow"}}}))

    out = capsys.readouterr().out
    assert "UNMAPPED  a: no OBI term" in out
    assert "OBI ERROR  b: TimeoutError: slow" in out
    assert "UNMAPPED  b" not in out


def test_a_miscited_quote_is_reported(cli, capsys):
    cli.report_result(_result(quote_check={
        "verified": 0, "total": 1, "missing": 0, "misattributed": 1, "source_aligned": 0,
        "per_assay": {"flow cytometry": {"status": "misattributed",
                                         "detail": "quote is verbatim but cites S9; it is in S2"}}}))

    assert "QUOTE MISATTRIBUTED  flow cytometry: quote is verbatim but cites S9" in (
        capsys.readouterr().out)


def test_a_registry_keyed_by_obi_label_is_not_warned_about(cli, capsys):
    """After round 5 the key is the OBI label, and the mapping is what says so. Without it
    every single-wording entry of a finished paper printed `not the key`."""
    entry = {**_ENTRY, "name_in_paper": ["FACS"]}
    cli.report_result(_result(
        assays={"flow cytometry assay": entry},
        obi={"flow cytometry assay": {**entry, "obi_id": "OBI:0000916",
                                      "obi_label": "flow cytometry assay",
                                      "resource": "exact_original"}}))

    assert "not the key" not in capsys.readouterr().out


def test_a_failed_extraction_call_is_a_warning_line(cli, capsys):
    """Round 1 voted around a reply that was not a registry; the count alone would hide it."""
    cli.report_result(_result(rounds={"extract": {
        "source": "extracted", "calls": 3, "extractions": 3, "assays": 1, "minority": 0,
        "failed": {"run2": "AssayExtractionError: model returned unparseable JSON: Expecting value"}}}))

    out = capsys.readouterr().out
    assert "WARNING  extraction run2 failed: AssayExtractionError: model returned unparseable JSON" in out


def test_a_blocked_fold_is_a_review_line(cli, capsys):
    """Two entries on one term that round 5 kept apart: a reader decides, so it is printed."""
    cli.report_result(_result(merges={"results": [], "key_map": {}, "blocked": [{
        "member": "ICS", "kept_apart_from": "flow cytometry assay", "obi_id": "OBI:0000916",
        "obi_label": "flow cytometry assay", "reason": "mapping is BROAD"}]}))

    out = capsys.readouterr().out
    assert ("REVIEW  not folded  ICS kept apart from flow cytometry assay (OBI:0000916): "
            "mapping is BROAD") in out


def test_a_judged_fold_and_a_judged_refusal_each_print_the_verdict(cli, capsys):
    """Round 6 folds on the model's say-so and keeps apart with its reason: both are printed
    under the line they belong to, since neither is a fold a rule stands behind."""
    cli.report_result(_result(merges={
        "key_map": {},
        "results": [{"key": "serum neutralization of viral infectivity assay",
                     "obi_id": "OBI:0000872", "folded": ["FRNT"],
                     "judged": {"verdict": "SAME", "reason": "one focus reduction test"}}],
        "blocked": [{"member": "ICS", "kept_apart_from": "flow cytometry assay",
                     "obi_id": "OBI:0000916", "reason": "readouts differs: 'a' vs 'b'",
                     "judged": {"verdict": "DIFFERENT", "reason": "two marker sets"}}]}))

    out = capsys.readouterr().out
    assert "MERGED  FRNT → serum neutralization of viral infectivity assay (OBI:0000872)" in out
    assert "JUDGED  SAME: one focus reduction test" in out
    assert "REVIEW  not folded  ICS kept apart from flow cytometry assay" in out
    assert "JUDGED  DIFFERENT: two marker sets" in out

def test_a_dropped_alias_is_a_line_of_its_own(cli, capsys):
    """A wording removed before round 2 because the paper does not contain it is a finding."""
    cli.report_result(_result(rounds={"extract": {
        "source": "extracted", "calls": 3, "extractions": 3, "assays": 1, "minority": 0,
        "aliases_dropped": {"flow cytometry": ["FACS"]}}}))

    out = capsys.readouterr().out
    assert "DROPPED ALIAS  flow cytometry: 'FACS' does not appear in the source text" in out


def test_a_review_line_says_what_round_three_did_with_each_field(cli, capsys):
    """The verdicts are pre-correction; a doubt the blind re-read settled must not read like a
    value that was replaced and never re-judged, and the identity is never correctable."""
    cli.report_result(_result(
        verification={"results": [{
            "assay_id": "FACS", "record_verdict": "REVIEW", "assay_identity_verdict": "NOT_SUPPORTED",
            "field_verifications": [
                {"field_name": "name_in_paper", "verdict": "NOT_SUPPORTED", "reason": "a product"},
                {"field_name": "sample_type", "verdict": "NOT_SUPPORTED", "reason": "unstated"},
                {"field_name": "aliases[1]", "verdict": "NOT_SUPPORTED", "reason": "a readout"}]}]},
        corrections={"results": [{"assay_id": "FACS", "corrections": [
            {"field": "sample_type", "action": "REPLACED", "previous": "PBMC",
             "blind_answer": "whole blood"},
            {"field": "aliases", "action": "REAFFIRMED"}]}]}))

    out = capsys.readouterr().out
    assert "name_in_paper: NOT_SUPPORTED — a product  → round 3: not correctable" in out
    assert "sample_type: NOT_SUPPORTED — unstated  → round 3: REPLACED" in out
    assert "aliases[1]: NOT_SUPPORTED — a readout  → round 3: REAFFIRMED" in out
