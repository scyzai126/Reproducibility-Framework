import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.claim_corrector import (
    CLEARED,
    REAFFIRMED,
    REPLACED,
    UNCHANGED,
    apply_correction,
    build_prompt,
    build_report,
    correct_claims,
    decide,
    flagged_groups,
)

SOURCE = (
    "## Results [results]\n"
    "[S1] IgG was higher at week 4 than at week 2 in the intradermal group.\n"
    "[S2] There was no difference between the two groups.\n"
    "## Methods [methods]\n"
    "[S3] IgG was measured by ELISA in serum.\n"
)

CLAIM = {
    "claim": "ELISA analysis of plasma from 12 adults showed higher IgG at week 4 than week 2.",
    "claim_type": "group_difference",
    "polarity": "affirm",
    "assay": "ELISA",
    "sample_type": "plasma",
    "sources": [{"type": "text", "section": "Results",
                 "quote": "IgG was higher at week 4 than at week 2 in the intradermal group."}],
}


def _verdicts(**flags) -> dict:
    """A verification result with the named fields flagged NOT_SUPPORTED."""
    return {
        "claim_id": "claim_1",
        "record_verdict": "REVIEW",
        "field_verifications": [
            {"field_name": f, "verdict": flags.get(f, "SUPPORTED"), "reason": "r"}
            for f in ("finding", "claim_type", "polarity", "assay", "sample_type",
                      "head_metadata", "sources[0].quote")
        ],
    }


def _mock_client(*payloads) -> MagicMock:
    responses = []
    for payload in payloads:
        message = MagicMock()
        message.content = json.dumps(payload)
        resp = MagicMock()
        resp.choices = [MagicMock(message=message)]
        resp.usage = None
        responses.append(resp)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)
    return client


def test_decide_three_ways_plus_unchanged():
    assert decide("serum", "Serum") == REAFFIRMED
    assert decide("plasma", "serum") == REPLACED
    assert decide("plasma", None) == CLEARED
    assert decide(None, None) == UNCHANGED


def test_only_flagged_groups_are_reopened_and_head_is_report_only():
    result = _verdicts(claim_type="NOT_SUPPORTED", head_metadata="CONTRADICTED",
                       **{"sources[0].quote": "NOT_SUPPORTED"})
    assert flagged_groups(result) == ["claim_type", "sources"]


@pytest.mark.parametrize("group,hidden", [
    ("claim_type", "group_difference"),
    ("polarity", '"affirm"'),
    ("sample_type", "plasma"),
    ("finding", "higher IgG at week 4 than week 2"),
])
def test_blind_prompt_never_contains_the_disputed_value(group, hidden):
    # Only the claim-specific locator is checked: the question itself legitimately lists every
    # type, both polarities, and example specimens as answer options.
    prompt = build_prompt(CLAIM, group, SOURCE, "t")
    locator = prompt.split("## The finding", 1)[1].split("## The question", 1)[0]
    assert hidden not in locator


def test_finding_replaced_keeps_the_head():
    claim = dict(CLAIM)
    record = apply_correction(claim, "finding", "showed higher IgG at week 4 than at week 2 in the "
                              "intradermal group", ["S1"], SOURCE)
    assert record["action"] == REPLACED
    assert claim["claim"].startswith("ELISA analysis of plasma from 12 adults showed higher IgG")
    assert claim["claim"].count("showed") == 1


def test_sample_type_replaced_also_rewrites_the_head():
    claim = dict(CLAIM)
    apply_correction(claim, "sample_type", "serum", ["S3"], SOURCE)
    assert claim["sample_type"] == "serum"
    assert claim["claim"].startswith("ELISA analysis of serum from")


def test_off_vocabulary_type_is_not_written():
    claim = dict(CLAIM)
    record = apply_correction(claim, "claim_type", "within_group_change", [], SOURCE)
    assert record["action"] == UNCHANGED and claim["claim_type"] == "group_difference"


def test_replacement_quote_must_be_verbatim():
    claim = dict(CLAIM)
    record = apply_correction(claim, "sources", "IgG soared.", ["S1"], SOURCE, [0])
    assert record["action"] == UNCHANGED
    assert "rejected" in record["note"]


@pytest.mark.asyncio
async def test_correct_claims_applies_answers_and_clears_unstated_findings():
    claims = {"claim_1": CLAIM, "claim_2": {**CLAIM, "claim": "ELISA analysis showed baseline differed."}}
    results = [_verdicts(claim_type="NOT_SUPPORTED"),
               {**_verdicts(finding="NOT_SUPPORTED"), "claim_id": "claim_2"}]
    client = _mock_client(
        {"value": "induction_vs_reference", "sentence_ids": ["S1"]},
        {"value": None, "sentence_ids": []},
    )
    corrected, records, cleared = await correct_claims(claims, results, SOURCE, "t", client,
                                                       max_concurrency=1)
    assert corrected["claim_1"]["claim_type"] == "induction_vs_reference"
    assert claims["claim_1"]["claim_type"] == "group_difference"  # input not mutated
    assert "claim_2" not in corrected
    assert cleared[0]["claim_id"] == "claim_2"
    assert build_report(records)["summary"]["actions"] == {REPLACED: 1, CLEARED: 1}
