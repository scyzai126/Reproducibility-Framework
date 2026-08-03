import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.claim_validator import (
    CHECK_NAMES,
    build_report,
    build_summary,
    validate_claim,
    validate_groups_file,
)


def _checks(**overrides) -> dict:
    """All five checks passing, with the named ones overridden to fail."""
    checks = {name: {"status": "pass", "reason": "ok"} for name in CHECK_NAMES}
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


_ENTRY = {
    "claim": "ELISA analysis of serum showed IgG rose by day 30 compared to baseline (day 0).",
    "sources": [{"type": "text", "section": "Results", "quote": "IgG rose by day 30."}],
    "groups": [{"group_id": 0}, {"group_id": 1}],
    "comparison": [{"contrast": [0, 1], "finding": "IgG rose"}],
}


@pytest.mark.asyncio
async def test_all_checks_pass_yields_accurate():
    client = _mock_client({"claim_id": "claim_1", "checks": _checks()})

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "accurate"
    assert result["issues"] == []
    assert set(result["checks"]) == set(CHECK_NAMES)


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
        "checks": _checks(structural="Contrast index 3 has no matching group_id."),
        "verdict": "accurate",
        "issues": [],
    })

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["verdict"] == "needs_revision"
    assert result["issues"] == ["structural: Contrast index 3 has no matching group_id."]


@pytest.mark.asyncio
async def test_claim_id_is_forced_to_the_real_key():
    client = _mock_client({"claim_id": "claim_99", "checks": _checks()})

    result = await validate_claim("claim_4", _ENTRY, client)

    assert result["claim_id"] == "claim_4"


@pytest.mark.asyncio
async def test_bare_status_strings_are_tolerated():
    client = _mock_client({
        "claim_id": "claim_1",
        "checks": {**{n: "pass" for n in CHECK_NAMES}, "grounding": "fail"},
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
async def test_missing_check_is_unknown_not_a_failure():
    checks = _checks()
    del checks["completeness"]
    client = _mock_client({"claim_id": "claim_1", "checks": checks})

    result = await validate_claim("claim_1", _ENTRY, client)

    assert result["checks"]["completeness"]["status"] == "unknown"
    assert result["verdict"] == "accurate"


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
    groups = {"claim_1": _ENTRY, "claim_2": _ENTRY, "claim_3": _ENTRY}
    client = _mock_client(
        {"claim_id": "claim_1", "checks": _checks()},
        "garbage",
        {"claim_id": "claim_3", "checks": _checks(grounding="Unsupported.")},
    )

    results = await validate_groups_file(groups, client)

    assert [r["verdict"] for r in results] == ["accurate", "error", "needs_revision"]


@pytest.mark.asyncio
async def test_non_claim_keys_are_skipped_and_limit_is_honoured():
    groups = {"summary": {}, "claim_1": _ENTRY, "claim_2": _ENTRY}
    client = _mock_client({"claim_id": "claim_1", "checks": _checks()})

    results = await validate_groups_file(groups, client, limit=1)

    assert [r["claim_id"] for r in results] == ["claim_1"]
    assert client.chat.completions.create.await_count == 1


def test_build_summary_tallies_verdicts_and_per_check_failures():
    results = [
        {"verdict": "accurate", "checks": _checks()},
        {"verdict": "needs_revision", "checks": _checks(grounding="x")},
        {"verdict": "needs_revision", "checks": _checks(grounding="y", completeness="z")},
        {"verdict": "error", "checks": {n: {"status": "unknown"} for n in CHECK_NAMES}},
    ]

    summary = build_summary(results)

    assert summary["total"] == 4
    assert summary["accurate"] == 1
    assert summary["needs_revision"] == 2
    assert summary["errors"] == 1
    assert summary["fail_counts"]["grounding"] == 2
    assert summary["fail_counts"]["completeness"] == 1
    assert summary["fail_counts"]["structural"] == 0


def test_build_report_wraps_summary_and_results():
    results = [{"verdict": "accurate", "checks": _checks()}]

    report = build_report(results)

    assert report["results"] == results
    assert report["summary"]["total"] == 1
