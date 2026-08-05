import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import claim_parser
from app.agent.claim_parser import CLAIM_TYPES_PLACEHOLDER, load_prompt_with_claim_types
from app.agent.claim_validator import (
    CHECK_NAMES,
    CLOSED_BOOK_CHECKS,
    METADATA_CHECK,
    build_report,
    build_summary,
    metadata_entries,
    validate_claim,
    validate_claims_file,
)


def _checks(**overrides) -> dict:
    """All closed-book checks passing, with the named ones overridden to fail."""
    checks = {name: {"status": "pass", "reason": "ok"} for name in CLOSED_BOOK_CHECKS}
    for name, reason in overrides.items():
        checks[name] = {"status": "fail", "reason": reason}
    return checks


def _mock_client(*payloads) -> MagicMock:
    """A client whose successive calls return the given payloads (dict → JSON, str → raw)."""
    responses = []
    for payload in payloads:
        message = MagicMock()
        message.content = payload if isinstance(payload, str) else json.dumps(payload)
        resp = MagicMock()
        resp.choices = [MagicMock(message=message)]
        responses.append(resp)

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)
    return client


#: A claim_filtered.json entry — a verbatim slice of claims.json, so no group structure.
_ENTRY = {
    "claim": "ELISA analysis of serum showed IgG rose by day 30 compared to baseline (day 0).",
    "claim_type": "induction_vs_reference",
    "assay": {"name_in_paper": "ELISA"},
    "sources": [{"type": "text", "section": "Results", "quote": "IgG rose by day 30."}],
}


@pytest.mark.asyncio
async def test_all_checks_pass_yields_accurate():
    client = _mock_client({"claim_id": "claim_1", "checks": _checks()})

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "accurate"
    assert result["issues"] == []
    assert set(result["checks"]) == set(CLOSED_BOOK_CHECKS)


@pytest.mark.asyncio
async def test_any_failed_check_yields_needs_revision_and_issues():
    client = _mock_client({
        "claim_id": "claim_1",
        "checks": _checks(grounding="Adds a comparator no quote states."),
    })

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "needs_revision"
    assert result["issues"] == ["grounding: Adds a comparator no quote states."]


@pytest.mark.asyncio
async def test_verdict_is_derived_not_trusted():
    """A judge that fails a check but self-reports "accurate" must not hide the failure."""
    client = _mock_client({
        "claim_id": "claim_1",
        "checks": _checks(claim_type="Labelled group_difference; the quote states an association."),
        "verdict": "accurate",
        "issues": [],
    })

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "needs_revision"
    assert result["issues"] == ["claim_type: Labelled group_difference; the quote states an association."]


@pytest.mark.asyncio
async def test_claim_id_is_forced_to_the_real_key():
    client = _mock_client({"claim_id": "claim_99", "checks": _checks()})

    result = await validate_claim("claim_4", _ENTRY, client)

    assert result["claim_id"] == "claim_4"


@pytest.mark.asyncio
async def test_bare_status_strings_are_tolerated():
    client = _mock_client({
        "claim_id": "claim_1",
        "checks": {**{n: "pass" for n in CLOSED_BOOK_CHECKS}, "grounding": "fail"},
    })

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "needs_revision"
    assert result["issues"] == ["grounding"]


@pytest.mark.asyncio
async def test_fenced_json_is_parsed():
    body = json.dumps({"claim_id": "claim_1", "checks": _checks()})
    client = _mock_client(f"```json\n{body}\n```")

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "accurate"


@pytest.mark.asyncio
async def test_missing_check_is_inconclusive_not_accurate():
    """A check the judge never reported has not cleared the claim."""
    checks = _checks()
    del checks["claim_type"]
    client = _mock_client({"claim_id": "claim_1", "checks": checks})

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["checks"]["claim_type"]["status"] == "unknown"
    assert result["verdict"] == "inconclusive"
    assert result["issues"] == ["claim_type: not reported by the judge"]


@pytest.mark.asyncio
async def test_unrecognised_status_is_inconclusive():
    checks = _checks()
    checks["claim_type"] = {"status": "maybe", "reason": "hard to say"}
    client = _mock_client({"claim_id": "claim_1", "checks": checks})

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["checks"]["claim_type"]["status"] == "unknown"
    assert result["verdict"] == "inconclusive"


@pytest.mark.asyncio
async def test_a_failure_outranks_a_missing_check():
    checks = _checks(grounding="Unsupported comparator.")
    del checks["claim_type"]
    client = _mock_client({"claim_id": "claim_1", "checks": checks})

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "needs_revision"
    assert result["issues"] == [
        "grounding: Unsupported comparator.",
        "claim_type: not reported by the judge",
    ]


@pytest.mark.asyncio
async def test_malformed_response_records_an_error_result():
    client = _mock_client("not json at all")

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "error"
    assert result["claim_id"] == "claim_1"
    assert "JSONDecodeError" in result["issues"][0]


@pytest.mark.asyncio
async def test_api_exception_records_an_error_result():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("rate limited"))

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "error"
    assert result["issues"] == ["RuntimeError: rate limited"]


@pytest.mark.asyncio
async def test_non_object_response_records_an_error_result():
    client = _mock_client("[1, 2, 3]")

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "error"
    assert "not an object" in result["issues"][0]


@pytest.mark.asyncio
async def test_one_bad_claim_does_not_abort_the_loop():
    claims = {"claim_1": _ENTRY, "claim_2": _ENTRY, "claim_3": _ENTRY}
    client = _mock_client(
        {"claim_id": "claim_1", "checks": _checks()},
        "garbage",
        {"claim_id": "claim_3", "checks": _checks(grounding="Unsupported.")},
    )

    results = await validate_claims_file(claims, client)

    assert [r["verdict"] for r in results] == ["accurate", "error", "needs_revision"]


@pytest.mark.asyncio
async def test_non_claim_keys_are_skipped_and_limit_is_honoured():
    claims = {"summary": {}, "claim_1": _ENTRY, "claim_2": _ENTRY}
    client = _mock_client({"claim_id": "claim_1", "checks": _checks()})

    results = await validate_claims_file(claims, client, limit=1)

    assert [r["claim_id"] for r in results] == ["claim_1"]
    assert client.chat.completions.create.await_count == 1


def test_build_summary_tallies_verdicts_and_per_check_failures():
    results = [
        {"verdict": "accurate", "checks": _checks()},
        {"verdict": "needs_revision", "checks": _checks(grounding="x")},
        {"verdict": "needs_revision", "checks": _checks(grounding="y", comparator_form="z")},
        {"verdict": "inconclusive", "checks": {**_checks(), "claim_type": {"status": "unknown"}}},
        {"verdict": "error", "checks": {n: {"status": "unknown"} for n in CLOSED_BOOK_CHECKS}},
    ]

    summary = build_summary(results)

    assert summary["total"] == 5
    assert summary["accurate"] == 1
    assert summary["needs_revision"] == 2
    assert summary["inconclusive"] == 1
    assert summary["errors"] == 1
    assert summary["fail_counts"]["grounding"] == 2
    assert summary["fail_counts"]["comparator_form"] == 1
    assert summary["fail_counts"]["claim_type"] == 0


def test_build_report_wraps_summary_and_results():
    results = [{"verdict": "accurate", "checks": _checks()}]

    report = build_report(results)

    assert report["results"] == results
    assert report["summary"]["total"] == 1


def test_claims_sharing_a_head_collapse_into_one_metadata_entry():
    """Heads repeat heavily within a paper — that is what keeps the metadata pass to a
    handful of PDF-carrying calls instead of one per claim."""
    head = "ELISA analysis of serum from 40 healthy adults at day 0 and day 30 showed"
    claims = {
        "claim_1": {"claim": f"{head} IgG rose by day 30."},
        "claim_2": {"claim": f"{head} IgA was unchanged at day 30."},
        "claim_3": {"claim": "HAI analysis of plasma from 12 donors showed titers rose."},
    }

    entries = metadata_entries(claims, ["claim_1", "claim_2", "claim_3"])

    assert len(entries) == 2
    assert entries[0] == {"head": head, "claims": ["claim_1", "claim_2"]}
    assert entries[1]["claims"] == ["claim_3"]


def test_a_claim_without_a_head_marker_still_reaches_the_metadata_pass():
    """A malformed claim missing "showed" falls back to the whole sentence rather than
    being silently dropped from the audit."""
    claims = {"claim_1": {"claim": "IgG rose by day 30."}}

    entries = metadata_entries(claims, ["claim_1"])

    assert entries == [{"head": "IgG rose by day 30.", "claims": ["claim_1"]}]


def test_the_judge_prompt_carries_the_claim_type_vocabulary():
    """The `claim_type` check is unjudgeable without the vocabulary, and it must be the
    same list the extraction step assigned the label from."""
    prompt = load_prompt_with_claim_types("validate_claims.txt")

    assert CLAIM_TYPES_PLACEHOLDER not in prompt
    assert "Claim type — label the assertion" in prompt
    assert "precedence ladder" in prompt
    for claim_type in ("induction_vs_reference", "group_difference", "extremum", "association"):
        assert claim_type in prompt


def test_the_judge_fails_an_extremum_without_a_candidate_set():
    """The judge is the only enforcement of the candidate-set rule -- it is prose the
    extractor may ignore, so the audit must be able to name the mislabel."""
    prompt = load_prompt_with_claim_types("validate_claims.txt")

    assert "Fail an `extremum` label when the claim does not name **three or more**" in prompt
    assert "A superlative needs a candidate set." in prompt


def test_a_judge_prompt_without_the_placeholder_raises(monkeypatch):
    """An unsubstituted template is still a valid prompt — the judge would rate claim_type
    with no vocabulary to rate it against. Fail before spending the call."""
    monkeypatch.setattr(claim_parser, "_load_prompt", lambda name: "a prompt with no placeholder")

    with pytest.raises(ValueError, match="missing the"):
        load_prompt_with_claim_types("validate_claims.txt")
