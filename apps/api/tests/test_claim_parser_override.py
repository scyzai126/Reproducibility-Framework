"""A step-1 override must not depend on the step-1 prompt existing.

The PDF-direct path extracts step 1 itself and hands it to `_run_two_step_pipeline` as an
override. The pipeline used to load `extract_claims.txt` before checking for one, so once
that prompt was retired, every PDF-direct run crashed after its step-1 calls had been paid for.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import claim_parser


def _mock_client(*payloads) -> MagicMock:
    """A client whose successive calls return the given payloads (dict → JSON)."""
    responses = []
    for payload in payloads:
        message = MagicMock()
        message.content = json.dumps(payload)
        resp = MagicMock()
        resp.choices = [MagicMock(message=message)]
        responses.append(resp)

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=responses)
    return client


@pytest.fixture
def prompts_without_step1(tmp_path, monkeypatch):
    """A prompts dir holding only the step-2 prompt, as after extract_claims.txt was retired."""
    (tmp_path / "classify_groups.txt").write_text("Structure these claims: {claims}", encoding="utf-8")
    monkeypatch.setattr(claim_parser, "_PROMPTS_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_override_runs_step2_without_step1_prompt(prompts_without_step1, monkeypatch):
    client = _mock_client({"claim_1": {"groups": []}})
    monkeypatch.setattr(claim_parser, "_get_client", lambda: client)
    override = {"claim_1": {"claim": "X rises after vaccination", "sources": []}}

    step1_json, step2_json = await claim_parser._run_two_step_pipeline(
        "", "SDY1", step1_override=override
    )

    assert step1_json is override
    assert step2_json["claim_1"]["claim"] == "X rises after vaccination"
    # One step-2 call for the one claim; no step-1 call.
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_no_override_still_needs_step1_prompt(prompts_without_step1, monkeypatch):
    client = _mock_client()
    monkeypatch.setattr(claim_parser, "_get_client", lambda: client)

    with pytest.raises(FileNotFoundError, match="extract_claims.txt"):
        await claim_parser._run_two_step_pipeline("paper text", "SDY1")
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_step2_tolerates_raw_newline_in_strings(prompts_without_step1, monkeypatch):
    """Models copy line breaks from the paper into quotes; strict JSON rejects them."""
    message = MagicMock()
    message.content = '{"claim_1": {"claim": "rises\nafter vaccination", "groups": []}}'
    resp = MagicMock()
    resp.choices = [MagicMock(message=message)]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(claim_parser, "_get_client", lambda: client)

    _, step2_json = await claim_parser._run_two_step_pipeline(
        "", "SDY1", step1_override={"claim_1": {"claim": "x", "sources": []}}
    )

    assert step2_json["claim_1"]["claim"] == "rises\nafter vaccination"
