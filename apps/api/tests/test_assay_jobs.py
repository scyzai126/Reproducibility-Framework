"""The job registry: what a run reports while it is going, and what it refuses to forget.

Nothing here starts a real run. What is under test is the bookkeeping -- the running call total,
the double-spend guard, and the rule that a terminal job never changes again -- because that
bookkeeping is what a caller reads a bill off.
"""

import asyncio

import pytest

from app.agent import assay_jobs


@pytest.fixture(autouse=True)
def clean_registry():
    assay_jobs.reset()
    yield
    assay_jobs.reset()


def _running(pubmed_id: str = "111", study_accession: str = "SDY1") -> assay_jobs.Job:
    job = assay_jobs.create(pubmed_id, study_accession)
    job.state = "running"
    return job


# ── recording a run ───────────────────────────────────────────────────────────

def test_a_new_job_is_queued_and_has_spent_nothing():
    job = assay_jobs.create("111", "SDY1", estimate={"total_calls": 12}, acknowledged_calls=12)

    snapshot = assay_jobs.snapshot(job.id)

    assert snapshot["state"] == "queued"
    assert snapshot["progress"] == {"rounds": {}, "calls": 0, "current": None}
    assert snapshot["acknowledged_calls"] == 12


def test_progress_events_accumulate_into_one_view_per_round():
    """Round 2 reports many times; the job keeps one row for it, not a log."""
    job = _running()

    assay_jobs.record_progress(job.id, {"round": "verify", "state": "running",
                                        "done": 1, "total": 3})
    assay_jobs.record_progress(job.id, {"round": "verify", "state": "running",
                                        "done": 2, "total": 3, "item": "ELISA"})

    verify = assay_jobs.snapshot(job.id)["progress"]["rounds"]["verify"]
    assert (verify["done"], verify["total"], verify["item"]) == (2, 3, "ELISA")


def test_the_running_call_total_is_the_sum_of_the_rounds_not_a_separate_tally():
    """Two different sums of the same calls would be two different bills, so there is one."""
    job = _running()

    assay_jobs.record_progress(job.id, {"round": "extract", "state": "done", "calls": 1})
    assay_jobs.record_progress(job.id, {"round": "verify", "state": "done", "calls": 8})
    assay_jobs.record_progress(job.id, {"round": "correct", "state": "done", "calls": 3})

    assert assay_jobs.snapshot(job.id)["progress"]["calls"] == 12


def test_the_round_in_flight_is_named_while_it_runs_and_cleared_when_it_ends():
    job = _running()

    assay_jobs.record_progress(job.id, {"round": "obi", "state": "running", "total": 4})
    assert assay_jobs.snapshot(job.id)["progress"]["current"] == "obi"

    assay_jobs.record_progress(job.id, {"round": "obi", "state": "done", "calls": 6})
    assert assay_jobs.snapshot(job.id)["progress"]["current"] is None


def test_an_event_naming_no_round_is_ignored_rather_than_stored_under_none():
    job = _running()

    assay_jobs.record_progress(job.id, {"state": "running"})

    assert assay_jobs.snapshot(job.id)["progress"]["rounds"] == {}


# ── finishing ─────────────────────────────────────────────────────────────────

def test_finishing_quotes_the_call_count_the_report_itself_carries():
    """The number a user is shown at the end comes from the finished report, not from the
    events -- a dropped event must not quietly discount the bill."""
    job = _running()
    assay_jobs.record_progress(job.id, {"round": "extract", "state": "done", "calls": 1})

    assay_jobs.finish(job.id, {"meta": {"llm_calls": 17}, "assays": {}})

    snapshot = assay_jobs.snapshot(job.id)
    assert snapshot["state"] == "done"
    assert snapshot["progress"]["calls"] == 17
    assert snapshot["finished_at"]


def test_a_terminal_job_ignores_events_that_arrive_after_it():
    """A cancelled run's in-flight round can still report; letting it through would resurrect
    a job a caller has already been told is over."""
    job = _running()
    assay_jobs.mark_cancelled(job.id)

    assay_jobs.record_progress(job.id, {"round": "verify", "state": "done", "calls": 9})
    assay_jobs.finish(job.id, {"meta": {"llm_calls": 99}})

    snapshot = assay_jobs.snapshot(job.id)
    assert snapshot["state"] == "cancelled"
    assert snapshot["progress"]["rounds"] == {}


def test_cancelling_keeps_what_the_run_already_spent():
    """Stopping is not a refund, and a UI that reported 0 calls would say it was."""
    job = _running()
    assay_jobs.record_progress(job.id, {"round": "extract", "state": "done", "calls": 1})
    assay_jobs.record_progress(job.id, {"round": "verify", "state": "done", "calls": 8})

    assay_jobs.mark_cancelled(job.id)

    assert assay_jobs.snapshot(job.id)["progress"]["calls"] == 9


def test_a_failure_is_recorded_rather_than_raised_into_nobody():
    job = _running()

    assay_jobs.fail(job.id, "assay extraction failed: bad JSON")

    snapshot = assay_jobs.snapshot(job.id)
    assert snapshot["state"] == "error"
    assert "bad JSON" in snapshot["error"]


# ── the double-spend guard ────────────────────────────────────────────────────

def test_a_paper_with_a_run_under_way_reports_it():
    """The only mistake on this page that costs money rather than time."""
    job = _running("111", "SDY1")

    assert assay_jobs.active_for("111", "SDY1").id == job.id


def test_a_finished_run_does_not_block_the_next_one():
    job = _running("111", "SDY1")
    assay_jobs.finish(job.id, {"meta": {"llm_calls": 3}})

    assert assay_jobs.active_for("111", "SDY1") is None
    assert assay_jobs.latest_for("111", "SDY1").id == job.id


def test_another_paper_is_not_blocked_by_this_ones_run():
    _running("111", "SDY1")

    assert assay_jobs.active_for("222", "SDY2") is None


# ── cancellation ──────────────────────────────────────────────────────────────

def test_cancelling_a_finished_run_reports_that_there_was_nothing_to_stop():
    job = _running()
    assay_jobs.finish(job.id, {"meta": {"llm_calls": 1}})

    assert assay_jobs.request_cancel(job.id) is False


@pytest.mark.asyncio
async def test_cancelling_cancels_the_task_rather_than_only_setting_a_flag():
    """A chain waiting on a model call will not look at a flag."""
    started = asyncio.Event()

    async def _forever():
        started.set()
        await asyncio.sleep(60)

    job = assay_jobs.create("111", "SDY1")
    task = asyncio.create_task(_forever())
    assay_jobs.start(job.id, task)
    await started.wait()

    assert assay_jobs.request_cancel(job.id) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


# ── retention ─────────────────────────────────────────────────────────────────

def test_pruning_forgets_the_oldest_finished_runs():
    for index in range(5):
        job = assay_jobs.create(str(index), "SDY1")
        assay_jobs.finish(job.id, {"meta": {"llm_calls": 1}})

    assay_jobs.prune(max_jobs=2)

    assert len(assay_jobs._JOBS) == 2


def test_pruning_never_forgets_a_run_that_is_still_going():
    """A forgotten running job is a run still spending money that nothing can report on."""
    live = _running("live", "SDY1")
    for index in range(4):
        job = assay_jobs.create(str(index), "SDY1")
        assay_jobs.finish(job.id, {"meta": {"llm_calls": 1}})

    assay_jobs.prune(max_jobs=1)

    assert assay_jobs.get(live.id) is not None


def test_a_snapshot_cannot_reach_the_job_it_came_from():
    job = _running()
    assay_jobs.record_progress(job.id, {"round": "verify", "state": "running", "done": 1})

    snapshot = assay_jobs.snapshot(job.id)
    snapshot["progress"]["rounds"]["verify"]["done"] = 999

    assert assay_jobs.snapshot(job.id)["progress"]["rounds"]["verify"]["done"] == 1


def test_an_unknown_job_has_no_snapshot():
    assert assay_jobs.snapshot("nope") is None
