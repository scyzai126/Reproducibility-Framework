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
