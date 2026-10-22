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


def test_a_repicked_term_is_a_line_of_its_own(cli, capsys):
    cli.report_result(_result(rounds={"canonicalize": {
        "source": "canonical", "calls": 1, "assays": 2, "groups_merged": 0, "entries_folded": 0,
        "folds_blocked": 0,
        "repicked": {"ICS": {"from": "flow cytometry assay", "to": "cytokine assay"}}}}))

    assert "REPICKED  ICS: flow cytometry assay (BROAD) → cytokine assay" in capsys.readouterr().out
