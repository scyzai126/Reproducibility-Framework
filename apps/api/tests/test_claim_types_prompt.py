"""Tests for the claim_type vocabulary injection in the claim-extraction prompt.

The vocabulary lives in its own prompt fragment (claim_types.txt) so it can be edited
without touching extract_claims_pdf.txt. These tests guard the seam between the two:
that the fragment is actually injected, that the closed vocabulary survives the
assembly, and that a missing placeholder fails loudly instead of silently shipping a
prompt with no claim_type instructions.
"""

import pytest

from app.agent import claim_parser
from app.agent.claim_parser import CLAIM_TYPES_PLACEHOLDER
from app.agent.pdf_direct import _build_claims_prompt

CLAIM_TYPES = [
    "induction_vs_reference",
    "group_difference",
    "extremum",
    "trajectory_segment",
    "response_difference",
    "magnitude_comparison",
    "association",
    "prediction",
    "dependency",
    "descriptive",
]

#: Retired: an absence is a `polarity`, not a type of its own. A claim reporting one keeps
#: the type that names the operation, because the verifier runs it either way.
RETIRED_CLAIM_TYPES = ["null_result"]


def test_placeholder_is_consumed():
    assert CLAIM_TYPES_PLACEHOLDER not in _build_claims_prompt()


@pytest.mark.parametrize("claim_type", CLAIM_TYPES)
def test_every_vocabulary_value_reaches_the_assembled_prompt(claim_type):
    assert claim_type in _build_claims_prompt()


@pytest.mark.parametrize("claim_type", RETIRED_CLAIM_TYPES)
def test_retired_types_are_gone_from_the_vocabulary(claim_type):
    """A retired type left in the table would still be assignable, and the filter and the
    judge would then disagree about what a negative finding should carry."""
    assert claim_type not in _build_claims_prompt()


def test_polarity_replaces_the_retired_null_result_type():
    prompt = _build_claims_prompt()
    assert "polarity" in prompt
    assert "affirm" in prompt


def test_vocabulary_is_injected_not_merely_referenced():
    """The fragment's own body must be present, not just the field name."""
    prompt = _build_claims_prompt()
    assert "Claim type — label the assertion" in prompt
    assert "precedence ladder" in prompt
    assert "one predicate or two" in prompt.lower()


def test_claim_type_is_required_by_the_output_schema():
    prompt = _build_claims_prompt()
    assert "`claim_type` (exactly one value from the Claim type vocabulary above)" in prompt
    assert '"claim_type": "induction_vs_reference"' in prompt


def test_missing_placeholder_raises(monkeypatch):
    """A template without the placeholder is still a valid prompt — the model would
    return untyped claims after a full-paper call. Fail before spending it."""
    monkeypatch.setattr(
        claim_parser, "_load_prompt", lambda name: "a prompt with no placeholder"
    )
    with pytest.raises(ValueError, match="missing the"):
        _build_claims_prompt()


def test_split_rule_references_claim_type():
    """Claim-grouping rule 2 must carry the operational test, or the vocabulary is
    decorative and never drives splitting."""
    prompt = _build_claims_prompt()
    assert "Two assertions carrying different `claim_type` values" in prompt


def test_shared_claim_type_does_not_imply_merging():
    """A differing claim_type is a sufficient split trigger, not a necessary one.
    Without this, a multi-phase time course collapses -- the decline and persistence
    halves of one sentence are both trajectory_segment but must stay separate."""
    prompt = _build_claims_prompt()
    assert "A shared `claim_type` does not mean the assertions merge." in prompt
    assert "*sufficient* trigger to split, not a necessary one" in prompt


def test_null_polarity_covers_embedded_negatives():
    """"but not X" attaches an absence to a positive finding. Observed failing in the
    SDY80 run, where such a claim was labelled prediction and the negative vanished.

    The split survives the move from `null_result` to `polarity`; what changed is that both
    halves now carry the same type and differ only in polarity."""
    prompt = _build_claims_prompt()
    assert "but not X" in prompt
    assert "whereas … did not" in prompt
    assert "`prediction` (affirm) + `prediction` (null) → two claims" in prompt


def test_variability_is_descriptive_not_trajectory():
    """A within- vs between-subject variance claim asserts spread, not a time course."""
    prompt = _build_claims_prompt()
    assert "Variability is not a trajectory." in prompt
    assert "low within-subject variability" in prompt
    assert "it is never `trajectory_segment`" in prompt


def test_extremum_requires_a_candidate_set():
    """Cue words alone triple-match extremum / trajectory_segment / association. Observed
    on SDY80 ("maximum fold-change"), SDY1294 ("most strongly associated with"), and
    SDY404 claim_7 -- where extremum outranking trajectory_segment would mislabel it."""
    prompt = _build_claims_prompt()
    assert "A superlative needs a candidate set." in prompt
    assert "necessary, not sufficient" in prompt
    assert "Two candidates is not an extremum." in prompt


def test_candidate_set_test_precedes_the_ladder():
    """The ladder puts extremum above trajectory_segment, so a time-course claim carrying
    one superlative cue would be pulled up into extremum if the candidate-set test were
    just another tie-break."""
    prompt = _build_claims_prompt()
    assert "This test runs **before** the precedence ladder, not inside it." in prompt


def test_dedup_pass_cannot_collapse_legitimately_split_claims():
    """One Results sentence routinely supports many claims. The de-dup pass must merge
    only assay-wording duplicates, never claims split per rule 1 or rule 2."""
    prompt = _build_claims_prompt()
    assert "Final de-duplication pass — assay-wording duplicates only:" in prompt
    assert "Sharing a source is normal and is never by itself grounds to merge." in prompt
    assert "must be left alone by this pass" in prompt


def test_multi_phase_worked_example_is_present():
    """The 4-assertions x 2-arms expansion has no other exemplar in the prompt."""
    prompt = _build_claims_prompt()
    assert "4 assertions × 2 groups = 8 claims" in prompt
    assert "is not a fifth assertion" in prompt
