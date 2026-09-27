import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.claim_verifier import (
    ACCEPT,
    CONTRADICTED,
    NOT_REPORTED,
    NOT_SUPPORTED,
    REJECT,
    REVIEW,
    SUPPORTED,
    build_prompt,
    build_report,
    claim_type_vocabulary,
    derive_record_verdict,
    drop_rejected,
    free_checks,
    proposed_fields,
    split_head,
    verify_claim,
    verify_claims,
)

SOURCE = (
    "## Results [results]\n"
    "[S1] IgG rose by day 30 compared with baseline.\n"
    "[S2] There was no difference between the two groups.\n"
    "## Methods [methods]\n"
    "[S3] IgG was measured by ELISA in serum.\n"
)

CLAIM = {
    "claim": "ELISA analysis of serum from 24 adults showed IgG rose by day 30 compared to baseline.",
    "claim_type": "induction_vs_reference",
    "polarity": "affirm",
    "assay": "ELISA",
    "sample_type": "serum",
    "sources": [
        {"type": "text", "section": "Results", "quote": "IgG rose by day 30 compared with baseline."},
        {"type": "figure", "ref": "Figure 1"},
    ],
}


def _mock_client(*payloads) -> MagicMock:
    responses = []
    for payload in payloads:
        message = MagicMock()
        message.content = payload if isinstance(payload, str) else json.dumps(payload)
        resp = MagicMock()
        resp.choices = [MagicMock(message=message)]
        resp.usage = None
        responses.append(resp)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)
    return client


def _all_supported(claim: dict, identity: str = SUPPORTED, **overrides) -> dict:
    return {
        "claim_identity_verdict": identity,
        "field_verifications": [
            {"field_name": f, "proposed_value": v, "verdict": overrides.get(f, SUPPORTED), "reason": "r"}
            for f, v in proposed_fields(claim)
        ],
        "record_verdict": ACCEPT,
    }


def test_vocabulary_is_read_from_claim_types_without_the_header():
    vocab = claim_type_vocabulary()
    assert "induction_vs_reference" in vocab and "descriptive" in vocab
    assert "claim_type" not in vocab


def test_split_head_keeps_showed_in_the_head():
    head, finding = split_head(CLAIM["claim"])
    assert head.endswith("showed")
    assert finding.startswith("IgG rose")


def test_proposed_fields_always_lists_type_and_polarity_and_only_quoted_sources():
    claim = {**CLAIM, "polarity": None, "sample_type": None}
    names = [f for f, _ in proposed_fields(claim)]
    assert names[:3] == ["finding", "claim_type", "polarity"]
    assert "sample_type" not in names
    assert "sources[0].quote" in names and "sources[1].quote" not in names  # figure ref has no quote


def test_free_checks_flag_invented_quote_bad_type_missing_polarity_and_head():
    claim = {
        "claim": "IgG rose.",
        "claim_type": "made_up",
        "polarity": None,
        "sources": [{"type": "text", "quote": "IgG rose sharply in every subject."}],
    }
    checks = free_checks(claim, SOURCE, claim_type_vocabulary())
    assert checks["sources[0].quote"]["verdict"] == CONTRADICTED
    assert checks["claim_type"]["verdict"] == CONTRADICTED
    assert checks["polarity"]["verdict"] == NOT_SUPPORTED
    assert "head" in checks


def test_free_checks_pass_a_clean_claim():
    assert free_checks(CLAIM, SOURCE, claim_type_vocabulary()) == {}


def test_record_verdict_is_derived_not_trusted():
    fields = [{"verdict": SUPPORTED}, {"verdict": NOT_SUPPORTED}]
    assert derive_record_verdict(SUPPORTED, fields) == REVIEW
    assert derive_record_verdict(CONTRADICTED, [{"verdict": SUPPORTED}]) == REJECT
    assert derive_record_verdict(SUPPORTED, [{"verdict": SUPPORTED}]) == ACCEPT
    assert derive_record_verdict(NOT_REPORTED, [{"verdict": SUPPORTED}]) == REVIEW


def test_prompt_puts_paper_before_claim_and_substitutes_vocabulary():
    prompt = build_prompt("claim_1", CLAIM, SOURCE, "A paper")
    assert "{claim_types}" not in prompt
    assert prompt.index("[S1] IgG rose") < prompt.index('"fields_to_verify"')


@pytest.mark.asyncio
async def test_model_accept_is_overruled_by_a_contradicted_field():
    raw = _all_supported(CLAIM, polarity=CONTRADICTED)  # model still says ACCEPT
    result = await verify_claim("claim_1", CLAIM, SOURCE, "t", _mock_client(raw))
    assert result["record_verdict"] == REVIEW
    assert result["model_record_verdict"] == ACCEPT


@pytest.mark.asyncio
async def test_free_check_outranks_the_judge_on_a_quote():
    claim = {**CLAIM, "sources": [{"type": "text", "quote": "IgG fell by day 30."}]}
    result = await verify_claim("claim_1", claim, SOURCE, "t", _mock_client(_all_supported(claim)))
    quote = next(v for v in result["field_verifications"] if v["field_name"] == "sources[0].quote")
    assert quote["verdict"] == CONTRADICTED
    assert result["record_verdict"] == REVIEW


@pytest.mark.asyncio
async def test_skipped_field_is_not_reported_and_blocks_accept():
    raw = _all_supported(CLAIM)
    raw["field_verifications"] = [v for v in raw["field_verifications"] if v["field_name"] != "assay"]
    result = await verify_claim("claim_1", CLAIM, SOURCE, "t", _mock_client(raw))
    assay = next(v for v in result["field_verifications"] if v["field_name"] == "assay")
    assert assay["verdict"] == NOT_REPORTED
    assert result["record_verdict"] == REVIEW


@pytest.mark.asyncio
async def test_failed_call_becomes_error_record():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    result = await verify_claim("claim_1", CLAIM, SOURCE, "t", client)
    assert result["record_verdict"] == "ERROR"
    assert "boom" in result["error"]


@pytest.mark.asyncio
async def test_reject_moves_claim_to_not_a_claim_with_its_reason():
    claims = {"claim_1": CLAIM, "claim_2": {**CLAIM, "claim": "ELISA analysis showed baseline was higher."}}
    reject = {**_all_supported(claims["claim_2"], identity=CONTRADICTED),
              "not_a_claim_reason": "not-stated-in-words"}
    results = await verify_claims(claims, SOURCE, "t", _mock_client(_all_supported(CLAIM), reject),
                                  max_concurrency=1)
    kept, dropped = drop_rejected(claims, results)
    assert list(kept) == ["claim_1"]
    assert dropped[0]["claim_id"] == "claim_2"
    assert dropped[0]["reason"] == "not-stated-in-words"
    assert dropped[0]["entry"] == claims["claim_2"]
    report = build_report(results)["summary"]
    assert (report["accept"], report["reject"]) == (1, 1)
