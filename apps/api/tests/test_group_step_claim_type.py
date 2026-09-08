"""`claim_type` is inherited end to end, never re-derived at the groups stage.

The chain is: the extractor assigns it into claims.json, claim_filter copies it verbatim
into claim_filtered.json *and selects on it*, and run_group_step stamps that same value
onto claims_groups.json. The groups stage is the one hop where a model is in the loop, so it is
the one hop where the chain can break — and it breaks silently, because a plausible-looking
wrong type reads exactly like a right one.

run_group_step is duplicated byte-for-byte across three entry points (run_groups_noassay,
run_pdf_direct, run_xml_direct). These tests drive the run_groups_noassay copy; the
duplication itself is tracked separately.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_runner():
    """Import scripts/run_groups_noassay.py, which is not an importable package."""
    path = _REPO_ROOT / "scripts" / "run_groups_noassay.py"
    spec = importlib.util.spec_from_file_location("run_groups_noassay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


_CLAIMS = {
    "claim_1": {
        "claim": (
            "Hemagglutination inhibition analysis of serum from young and elderly adults at "
            "day 0 and day 28 showed a greater increase in HAI titer in young adults compared "
            "to elderly adults."
        ),
        "claim_type": "response_difference",
        "sources": [{"type": "text", "section": "Results", "quote": "verbatim"}],
    }
}

#: What the model returns. It does not echo claim_type — the common case.
_REPLY = {
    "claim_1": {
        "comparison_strategy": "cross_sectional_longitudinal",
        "groups": [{"group_id": 0}, {"group_id": 1}],
        "comparison": [{"contrast": [0, 1], "finding": "young vs elderly at day 28"}],
    }
}


def _prompt_sent(client) -> str:
    return client.chat.completions.create.await_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_claim_type_reaches_the_prompt():
    """Without this the model re-diagnoses change-vs-level from one sentence, discarding a
    decision the extractor made with the figure legend and full panel prose in view."""
    runner = _load_runner()
    client = _mock_client(_REPLY)

    await runner.run_group_step(_CLAIMS, client)

    single = json.loads(_prompt_sent(client).split("## Input claims\n", 1)[1].split("\n\n", 1)[0])
    assert single["claim_1"]["claim_type"] == "response_difference"


@pytest.mark.asyncio
async def test_a_model_echo_never_overrides_the_inherited_type():
    """The merge is `{"claim_type": <inherited>, **val}`, so a claim_type inside `val` would
    win. Harmless while the model could not see the field; now that it can, the echo has to
    be discarded — otherwise claims_groups.json can disagree with the filter that admitted the
    claim, and nothing downstream detects it."""
    runner = _load_runner()
    echoed = {"claim_1": {**_REPLY["claim_1"], "claim_type": "group_difference"}}
    client = _mock_client(echoed)

    groups = await runner.run_group_step(_CLAIMS, client)

    assert groups["claim_1"]["claim_type"] == "response_difference"
    assert groups["claim_1"]["comparison_strategy"] == "cross_sectional_longitudinal"


@pytest.mark.asyncio
async def test_claim_type_is_the_first_key_and_claim_survives():
    """claims_groups.json entries lead with claim_type — the key order 24336226_SDY1260_v7 already
    uses — and the model's own fields are still merged in behind it."""
    runner = _load_runner()
    client = _mock_client(_REPLY)

    groups = await runner.run_group_step(_CLAIMS, client)

    assert list(groups["claim_1"])[0] == "claim_type"
    assert groups["claim_1"]["claim"] == _CLAIMS["claim_1"]["claim"]
    assert groups["claim_1"]["sources"] == _CLAIMS["claim_1"]["sources"]
