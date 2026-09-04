"""The corrector repairs only what a verification flagged, and only from a blind re-read."""

import pytest

from app.agent.assay_corrector import (
    CLEARED,
    REAFFIRMED,
    REPLACED,
    UNCHANGED,
    apply_correction,
    build_prompt,
    decide,
    drop_rejected,
    field_group,
    flagged_alias_indices,
    flagged_groups,
    promote_registry,
    rejected_assays,
    uncorrectable_flags,
)

_SOURCE = "[S1] Cells were analyzed on the LSRII flow cytometer (BD). [S2] PBMCs were thawed."


def _entry(**over) -> dict:
    entry = {
        "name_in_paper": "flow cytometry",
        "aliases": ["FACS analysis", "Flow cytometry"],
        "platform": "NextSeq 2000",
        "sample_type": "PBMCs",
        "readouts": "cell frequencies",
        "source": "methods",
        "evidence": {"section": "Methods", "sentence_ids": ["S1"],
                     "quote": "Cells were analyzed on the LSRII flow cytometer (BD)."},
    }
    entry.update(over)
    return entry


def _verification(*fields) -> dict:
    return {"field_verifications": [
        {"field_name": name, "verdict": verdict, "reason": "..."} for name, verdict in fields
    ]}


# ── what gets flagged ─────────────────────────────────────────────────────────

def test_alias_indices_collapse_into_one_question():
    """aliases[0] and aliases[3] are one rule failing, so they cost one call, not two."""
    groups = flagged_groups(_verification(
        ("aliases[0]", "NOT_SUPPORTED"), ("aliases[3]", "NOT_SUPPORTED"),
    ))
    assert groups == ["aliases"]


def test_supported_fields_are_not_reopened():
    groups = flagged_groups(_verification(
        ("platform", "SUPPORTED"), ("sample_type", "CONTRADICTED"),
    ))
    assert groups == ["sample_type"]


def test_not_supported_is_flagged_even_when_the_record_says_accept():
    """derive_record_verdict ignores NOT_SUPPORTED, so triggering on the record would
    skip exactly the fields this pass exists to repair."""
    result = {"record_verdict": "ACCEPT",
              **_verification(("aliases[2]", "NOT_SUPPORTED"))}
    assert flagged_groups(result) == ["aliases"]


def test_evidence_quote_and_ids_are_one_question():
    groups = flagged_groups(_verification(
        ("evidence.quote", "CONTRADICTED"), ("evidence.sentence_ids", "NOT_SUPPORTED"),
    ))
    assert groups == ["evidence"]


def test_assay_identity_is_reported_not_corrected():
    result = _verification(("name_in_paper", "CONTRADICTED"))
    assert field_group("name_in_paper") is None
    assert flagged_groups(result) == []
    assert [f["field_name"] for f in uncorrectable_flags(result)] == ["name_in_paper"]


# ── the three-way vote ────────────────────────────────────────────────────────

def test_matching_blind_answer_reaffirms_the_original():
    assert decide("PBMCs", "pbmcs ") == REAFFIRMED


def test_differing_blind_answer_replaces():
    assert decide("NextSeq 2000", "LSRII flow cytometer (BD)") == REPLACED


def test_null_blind_answer_clears_a_value_that_was_there():
    assert decide("NextSeq 2000", None) == CLEARED


def test_null_blind_answer_over_an_already_empty_field_changes_nothing():
    assert decide(None, None) == UNCHANGED


# ── applying it ───────────────────────────────────────────────────────────────

def test_a_cleared_platform_becomes_null_rather_than_a_guess():
    entry = _entry()
    record = apply_correction(entry, "platform", None, _SOURCE)

    assert record["action"] == CLEARED
    assert record["previous"] == "NextSeq 2000"
    assert entry["platform"] is None


def test_a_flagged_alias_the_blind_read_did_not_confirm_is_dropped():
    entry = _entry()
    record = apply_correction(entry, "aliases", ["FACS analysis"], _SOURCE,
                              flagged_aliases={1})

    assert record["action"] == REPLACED
    assert entry["aliases"] == ["FACS analysis"]
    assert record["dropped"] == ["Flow cytometry"]


def test_an_unflagged_alias_survives_a_blind_read_that_words_it_differently():
    """Measured regression on SDY1119: pruning the whole list to the blind answer destroyed
    "fluorescence-activated cell sorting (FACS) measurements", which the judge SUPPORTED."""
    entry = _entry(aliases=["fluorescence-activated cell sorting (FACS) measurements",
                            "FACS analysis", "Flow cytometry"])
    apply_correction(entry, "aliases", ["FACS analysis", "Flow Cytometry Analysis"],
                     _SOURCE, flagged_aliases={2})

    assert entry["aliases"] == [
        "fluorescence-activated cell sorting (FACS) measurements", "FACS analysis",
    ]


def test_aliases_are_not_expanded_beyond_what_was_there():
    """The pass was scoped to flagged fields; adding new aliases would be expansion."""
    entry = _entry()
    apply_correction(entry, "aliases", ["FACS analysis", "Flow cytometry", "FACS"], _SOURCE,
                     flagged_aliases={0, 1})

    assert entry["aliases"] == ["FACS analysis", "Flow cytometry"]


def test_flagged_alias_indices_reads_only_the_unsupported_positions():
    result = {"field_verifications": [
        {"field_name": "aliases[0]", "verdict": "SUPPORTED"},
        {"field_name": "aliases[2]", "verdict": "NOT_SUPPORTED"},
        {"field_name": "platform", "verdict": "CONTRADICTED"},
    ]}

    assert flagged_alias_indices(result) == {2}


def test_a_replacement_quote_that_is_not_verbatim_is_rejected():
    entry = _entry()
    blind = {"quote": "Cells were run on a NovaSeq 6000.", "sentence_ids": ["S1"]}
    record = apply_correction(entry, "evidence", blind, _SOURCE)

    assert record["action"] == UNCHANGED
    assert "rejected" in record["note"]
    assert entry["evidence"]["quote"].startswith("Cells were analyzed")


def test_a_verbatim_replacement_quote_lands():
    entry = _entry()
    blind = {"quote": "PBMCs were thawed.", "sentence_ids": ["S2"]}
    record = apply_correction(entry, "evidence", blind, _SOURCE)

    assert record["action"] == REPLACED
    assert entry["evidence"]["quote"] == "PBMCs were thawed."
    assert entry["evidence"]["sentence_ids"] == ["S2"]


def test_evidence_is_never_blanked():
    """An entry with no quotable support is a finding for a human, not a silent deletion."""
    entry = _entry()
    record = apply_correction(entry, "evidence", {"quote": None, "sentence_ids": []}, _SOURCE)

    assert record["action"] == UNCHANGED
    assert entry["evidence"]["quote"].startswith("Cells were analyzed")


# ── blindness ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("group", ["platform", "sample_type", "readouts"])
def test_the_prompt_never_shows_the_disputed_value(group):
    """The whole premise: a corrector shown the rejected string edits the string.

    The fixture values are deliberately unlike the examples the questions carry, so a hit
    means the entry leaked rather than that the question named a common specimen."""
    entry = _entry(platform="NextSeq 2000", sample_type="bronchoalveolar lavage fluid",
                   readouts="tetramer-positive clonotype counts")
    prompt = build_prompt(entry, group, _SOURCE, "A Paper")

    assert entry[group] not in prompt
    assert "CONTRADICTED" not in prompt and "NOT_SUPPORTED" not in prompt


def test_the_evidence_question_does_not_quote_the_evidence_back():
    entry = _entry()
    prompt = build_prompt(entry, "evidence", _SOURCE, "A Paper")

    assert entry["evidence"]["quote"] not in prompt.split("ORIGINAL SOURCE TEXT")[0]


# ── rejected assays: removal, not repair ──────────────────────────────────────

def _verification_results(*results) -> dict:
    return {"results": list(results)}


def _rejected(assay_id, reason="computational analysis, not an assay") -> dict:
    return {"assay_id": assay_id, "record_verdict": "REJECT",
            "assay_identity_verdict": "CONTRADICTED",
            "field_verifications": [{"field_name": "name_in_paper",
                                     "verdict": "CONTRADICTED", "reason": reason}]}


def _accepted(assay_id) -> dict:
    return {"assay_id": assay_id, "record_verdict": "ACCEPT",
            "assay_identity_verdict": "SUPPORTED", "field_verifications": []}


def test_rejected_assays_carry_the_reason_the_judge_gave():
    reasons = rejected_assays(_verification_results(_rejected("GSEA"), _accepted("ELISA")))

    assert reasons == {"GSEA": "computational analysis, not an assay"}


def test_a_contradicted_identity_counts_even_without_a_reject_record():
    """derive_record_verdict should already give REJECT, but the identity verdict is the
    substantive signal and must not depend on the derived one agreeing."""
    result = {**_rejected("GSEA"), "record_verdict": "REVIEW"}

    assert "GSEA" in rejected_assays(_verification_results(result))


def test_drop_rejected_keeps_everything_else_and_carries_the_entry_out():
    assays = {"GSEA": {"name_in_paper": "GSEA"}, "ELISA": {"name_in_paper": "ELISA"}}
    kept, dropped = drop_rejected(
        assays, _verification_results(_rejected("GSEA"), _accepted("ELISA")))

    assert list(kept) == ["ELISA"]
    assert dropped["GSEA"]["entry"] == {"name_in_paper": "GSEA"}
    assert dropped["GSEA"]["reason"] == "computational analysis, not an assay"


def test_drop_rejected_does_not_mutate_its_input():
    assays = {"GSEA": {"name_in_paper": "GSEA"}}
    drop_rejected(assays, _verification_results(_rejected("GSEA")))

    assert list(assays) == ["GSEA"]


def test_a_review_record_is_repaired_not_dropped():
    """REVIEW means a field is wrong, which correction fixes; only identity is fatal."""
    result = {"assay_id": "ELISA", "record_verdict": "REVIEW",
              "assay_identity_verdict": "SUPPORTED",
              "field_verifications": [{"field_name": "platform", "verdict": "NOT_SUPPORTED"}]}
    kept, dropped = drop_rejected({"ELISA": {}}, _verification_results(result))

    assert list(kept) == ["ELISA"] and dropped == {}


def test_promote_installs_the_corrected_registry_and_snapshots_the_original(tmp_path):
    (tmp_path / "assays.json").write_text('{"a": {"platform": "WRONG"}}')
    (tmp_path / "assays_corrected.json").write_text('{"a": {"platform": null}}')

    result = promote_registry(tmp_path)

    assert result["snapshot_written"] is True
    assert (tmp_path / "assays.json").read_text() == '{"a": {"platform": null}}'
    assert (tmp_path / "assays_precorrection.json").read_text() == '{"a": {"platform": "WRONG"}}'


def test_re_promoting_does_not_clobber_the_original_snapshot(tmp_path):
    """The first snapshot is the only unrepaired version there will ever be."""
    (tmp_path / "assays.json").write_text('{"a": {"platform": "WRONG"}}')
    (tmp_path / "assays_corrected.json").write_text('{"a": {"platform": null}}')
    promote_registry(tmp_path)
    (tmp_path / "assays_corrected.json").write_text('{"a": {"platform": "SECOND"}}')

    result = promote_registry(tmp_path)

    assert result["snapshot_written"] is False
    assert (tmp_path / "assays_precorrection.json").read_text() == '{"a": {"platform": "WRONG"}}'


def test_promoting_with_nothing_corrected_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        promote_registry(tmp_path)
