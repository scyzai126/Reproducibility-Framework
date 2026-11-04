"""The run's trace: every reply kept, nothing recorded when nobody is listening."""

import asyncio
import json

import pytest

from app.agent import assay_trace


@pytest.fixture(autouse=True)
def _no_leaked_trace():
    assay_trace.stop()
    yield
    assay_trace.stop()


def test_record_is_a_no_op_without_a_trace():
    """The standalone scripts and every existing test call the rounds with no trace active."""
    assay_trace.record("verify", "ELISA", reply="{}")

    assert assay_trace.active() is None


def test_records_are_grouped_by_round_key_and_field():
    trace = assay_trace.start()
    assay_trace.record("extract", reply='{"ELISA": {}}', source_kind="xml")
    assay_trace.record("verify", "ELISA", reply='{"record_verdict": "ACCEPT"}')
    assay_trace.record("correct", "ELISA", field="sample_type", reply='{"value": null}')
    assay_trace.record("correct", "ELISA", field="aliases", error="TimeoutError: slow")
    assay_trace.record("obi", "ELISA", reply="1 exact", candidates=["1. OBI:0000661 | ELISA"])

    assert trace.as_json() == {
        "extract": {"reply": '{"ELISA": {}}', "source_kind": "xml"},
        "verify": {"ELISA": {"reply": '{"record_verdict": "ACCEPT"}'}},
        "correct": {"ELISA": {"sample_type": {"reply": '{"value": null}'},
                              "aliases": {"error": "TimeoutError: slow"}}},
        "obi": {"ELISA": {"reply": "1 exact", "candidates": ["1. OBI:0000661 | ELISA"]}},
    }


def test_stop_ends_recording_but_keeps_what_was_taken():
    trace = assay_trace.start()
    assay_trace.record("verify", "A", reply="x")
    assay_trace.stop()
    assay_trace.record("verify", "B", reply="y")

    assert list(trace.as_json()["verify"]) == ["A"]


@pytest.mark.asyncio
async def test_the_trace_follows_gathered_tasks_and_worker_threads():
    """Round 2 fans out with gather and round 4 runs in to_thread; both must land in the same
    trace without being handed it."""
    trace = assay_trace.start()

    async def _verify(key: str) -> None:
        assay_trace.record("verify", key, reply=key)

    await asyncio.gather(_verify("A"), _verify("B"))
    await asyncio.to_thread(assay_trace.record, "obi", "A", reply="1 exact")

    assert set(trace.as_json()["verify"]) == {"A", "B"}
    assert trace.as_json()["obi"] == {"A": {"reply": "1 exact"}}


def test_write_merges_into_an_existing_file_round_by_round(tmp_path):
    """run_assay_merge.py --map re-runs round 4 alone and must not erase rounds 1-3."""
    path = tmp_path / "assays_raw.json"
    first = assay_trace.start()
    assay_trace.record("extract", reply="{}", source_kind="xml")
    assay_trace.record("obi", "A", reply="none", candidates=[])
    first.write(path)

    second = assay_trace.start()
    assay_trace.record("obi", "A", reply="2 broad", candidates=["1. x", "2. y"])
    second.write(path)

    stored = json.loads(path.read_text())
    assert stored["extract"] == {"reply": "{}", "source_kind": "xml"}
    assert stored["obi"]["A"]["reply"] == "2 broad"


def test_write_survives_an_unreadable_existing_file(tmp_path):
    path = tmp_path / "assays_raw.json"
    path.write_text("not json")
    trace = assay_trace.start()
    assay_trace.record("extract", reply="{}", source_kind="pdf")

    trace.write(path)

    assert json.loads(path.read_text())["extract"]["source_kind"] == "pdf"


# ── token usage ───────────────────────────────────────────────────────────────

from types import SimpleNamespace as _NS  # noqa: E402


def _resp(prompt=1000, cached=400, completion=50, reasoning=20, details=True):
    usage = _NS(prompt_tokens=prompt, completion_tokens=completion,
                total_tokens=prompt + completion)
    if details:
        usage.prompt_tokens_details = _NS(cached_tokens=cached)
        usage.completion_tokens_details = _NS(reasoning_tokens=reasoning)
    return _NS(usage=usage)


def test_usage_fields_reads_the_cached_and_reasoning_details():
    assert assay_trace.usage_fields(_resp()) == {
        "prompt": 1000, "cached": 400, "completion": 50, "reasoning": 20}


def test_usage_fields_treats_missing_detail_blocks_as_zero():
    assert assay_trace.usage_fields(_resp(details=False)) == {
        "prompt": 1000, "cached": 0, "completion": 50, "reasoning": 0}


def test_a_response_without_usage_records_nothing():
    """Every test fake and some SDK paths return no usage; the reply is still recorded."""
    assert assay_trace.usage_fields(_NS()) == {}
    assert assay_trace.usage_kw(_NS()) == {}
    assert assay_trace.usage_kw(_resp()) == {"usage": assay_trace.usage_fields(_resp())}


def test_usage_rides_on_the_record_and_is_absent_when_not_given():
    trace = assay_trace.start()
    assay_trace.record("extract", "run1", reply="{}", **assay_trace.usage_kw(_resp()))
    assay_trace.record("extract", "run2", reply="{}", **assay_trace.usage_kw(_NS()))

    grouped = trace.as_json()
    assert grouped["extract"]["run1"]["usage"]["prompt"] == 1000
    assert "usage" not in grouped["extract"]["run2"]


def test_usage_summary_sums_per_round_and_counts_every_call():
    """A call without usage (failed, or made through a fake) still counts as a call."""
    grouped = {
        "extract": {"run1": {"reply": "{}", "usage": {"prompt": 100, "cached": 0,
                                                       "completion": 10, "reasoning": 2}},
                    "run2": {"reply": "{}", "usage": {"prompt": 100, "cached": 90,
                                                       "completion": 10, "reasoning": 0}}},
        "verify": {"ELISA": {"reply": "{}"}},
        "correct": {"ELISA": {"aliases": {"error": "TimeoutError: slow"},
                              "sample_type": {"reply": "{}", "usage": {"prompt": 7,
                                                                        "completion": 1}}}},
    }

    summary = assay_trace.usage_summary(grouped)

    assert summary["by_round"]["extract"] == {
        "calls": 2, "prompt": 200, "cached": 90, "completion": 20, "reasoning": 2}
    assert summary["by_round"]["verify"] == {
        "calls": 1, "prompt": 0, "cached": 0, "completion": 0, "reasoning": 0}
    assert summary["by_round"]["correct"] == {
        "calls": 2, "prompt": 7, "cached": 0, "completion": 1, "reasoning": 0}
    assert summary["total"] == {
        "calls": 5, "prompt": 207, "cached": 90, "completion": 21, "reasoning": 2}


def test_usage_summary_of_a_pre_usage_raw_file_is_calls_only():
    """A raw file written before usage was recorded still sums -- to its call count."""
    grouped = {"extract": {"reply": "{}", "source_kind": "xml"},
               "obi": {"ELISA": {"reply": "1 exact", "candidates": []}}}
    assert assay_trace.usage_summary(grouped)["total"] == {
        "calls": 2, "prompt": 0, "cached": 0, "completion": 0, "reasoning": 0}


def test_estimate_usd_bills_cached_prompt_tokens_at_the_cached_price():
    totals = {"prompt": 1_000_000, "cached": 400_000, "completion": 100_000, "reasoning": 50_000}
    price = assay_trace.LIST_PRICE_USD_PER_MTOK["gpt-5.4"]
    expected = (600_000 * price["input"] + 400_000 * price["cached"]
                + 100_000 * price["output"]) / 1_000_000

    assert assay_trace.estimate_usd(totals, "gpt-5.4") == pytest.approx(expected)
    assert assay_trace.estimate_usd(totals, "some-other-model") is None


def test_format_usage_prints_each_round_and_a_priced_total():
    summary = assay_trace.usage_summary({
        "extract": {"run1": {"reply": "{}", "usage": {"prompt": 10_000, "cached": 0,
                                                       "completion": 1_000, "reasoning": 300}}}})
    lines = assay_trace.format_usage(summary, "gpt-5.4")

    assert lines[0].startswith("extract ") and "10,000 prompt (0 cached)" in lines[0]
    assert "1,000 completion (300 reasoning)" in lines[0]
    assert lines[-1].startswith("total ") and "$" in lines[-1] and "gpt-5.4" in lines[-1]
    assert "$" not in assay_trace.format_usage(summary, "unknown-model")[-1]
