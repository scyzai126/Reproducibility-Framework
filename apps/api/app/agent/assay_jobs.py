"""In-memory registry of assay runs, so a paid run outlives the request that started it.

A full run is five rounds and upwards of twenty model calls; it routinely takes longer than the
frontend's proxy will hold a connection open. So POST /agent/assays/runs starts the chain on a
task and returns an id, and the browser polls. That also means a run keeps going when the tab is
closed -- which is the honest behaviour, because the calls are being paid for either way.

**State lives in this process and nowhere else.** It dies with the server, and `uvicorn --reload`
restarts on every backend edit, so losing a job mid-run is the normal case in development rather
than an edge one. That is deliberate, not an oversight: the durable record of a run is the
registry directory it writes, and GET /agent/assays/registry reads that back for free. A lost job
costs its caller the progress display, never the result. The same fact rules out multiple
workers -- with two, half the polls would 404.

Nothing here calls a model. This module sequences and records; app.agent.assay_service does the
work, and it does it in one place so a run started from the API writes exactly the files a run
started from scripts/run_assay_pipeline.py writes.
"""

import asyncio
import copy
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: Terminal states. A job in one of these is finished with, and never changes again -- which is
#: what lets `prune` evict it and what lets a poller stop.
TERMINAL = ("done", "error", "cancelled")

#: The rounds, in the order assay_service runs them. Named here so a caller can lay out five rows
#: before the first event arrives, rather than growing the list as rounds report.
ROUND_NAMES = ("extract", "verify", "correct", "obi", "canonicalize")

#: How many finished jobs to remember. Enough that a poller which was asleep still finds its
#: result; small enough that a long-lived dev server does not accumulate whole registries in RAM.
MAX_JOBS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    """One run: what it was approved to cost, where it has got to, and what it produced."""

    id: str
    pubmed_id: str
    study_accession: str
    state: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    #: The estimate this run was approved against, kept so a surprising bill can be compared
    #: with what the user was shown rather than with what we would guess now.
    estimate: dict | None = None
    acknowledged_calls: int | None = None
    #: Set when the estimate moved between the caller seeing it and the run starting. Recorded,
    #: never blocking: rounds 2 and 3 were always approximate, so a mismatch is information.
    estimate_drift: dict | None = None
    progress: dict = field(default_factory=lambda: {"rounds": {}, "calls": 0, "current": None})
    result: dict | None = None
    error: str | None = None
    cancel_requested: bool = False


_JOBS: "OrderedDict[str, Job]" = OrderedDict()
#: Strong references to the running tasks. asyncio only holds a weak one, so a task that nothing
#: else keeps can be garbage-collected mid-run -- which would look exactly like a run that
#: silently stopped after paying for three rounds.
_TASKS: dict[str, asyncio.Task] = {}


def create(pubmed_id: str, study_accession: str, *, estimate: dict | None = None,
           acknowledged_calls: int | None = None, estimate_drift: dict | None = None) -> Job:
    """Register a run. Does not start it -- `start` attaches the task."""
    job = Job(id=uuid.uuid4().hex, pubmed_id=pubmed_id, study_accession=study_accession,
              estimate=estimate, acknowledged_calls=acknowledged_calls,
              estimate_drift=estimate_drift)
    _JOBS[job.id] = job
    prune()
    return job


def get(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def start(job_id: str, task: asyncio.Task) -> None:
    """Attach the running task and mark the job started."""
    job = _JOBS.get(job_id)
    if job is None:
        return
    job.state, job.started_at = "running", _now()
    _TASKS[job_id] = task
    task.add_done_callback(lambda _t: _TASKS.pop(job_id, None))


def active_for(pubmed_id: str, study_accession: str) -> Job | None:
    """A run already under way for this paper, if there is one.

    The double-spend guard. Two tabs, a double-click, or a refresh-then-run would otherwise
    bill the same paper twice for the same answer, and this is the only mistake on the page
    that costs money rather than time.
    """
    for job in reversed(_JOBS.values()):
        if (job.pubmed_id, job.study_accession) == (pubmed_id, study_accession) \
                and job.state not in TERMINAL:
            return job
    return None


def latest_for(pubmed_id: str, study_accession: str) -> Job | None:
    """The most recent run for this paper, finished or not."""
    for job in reversed(_JOBS.values()):
        if (job.pubmed_id, job.study_accession) == (pubmed_id, study_accession):
            return job
    return None


def record_progress(job_id: str, event: dict) -> None:
    """Fold one assay_service progress event into the job's live view.

    The running call total is recomputed from the per-round counts rather than accumulated,
    so the number a poller sees mid-run is the same arithmetic `rounds` reports at the end --
    two different sums of the same calls would be two different bills.

    A terminal job ignores further events: a cancelled run's in-flight round can still report
    after the task was cancelled, and letting it reopen the job would resurrect it.
    """
    job = _JOBS.get(job_id)
    if job is None or job.state in TERMINAL:
        return

    name = event.get("round")
    if not name:
        return
    round_state = {k: v for k, v in event.items() if k != "round"}
    job.progress["rounds"][name] = {**job.progress["rounds"].get(name, {}), **round_state}
    job.progress["current"] = name if event.get("state") == "running" else None
    job.progress["calls"] = sum(
        int(r.get("calls") or 0) for r in job.progress["rounds"].values())


def finish(job_id: str, result: dict) -> None:
    job = _JOBS.get(job_id)
    if job is None or job.state in TERMINAL:
        return
    job.state, job.finished_at, job.result = "done", _now(), result
    # From the finished report, not from the events: this is the number that gets quoted.
    job.progress["calls"] = int((result.get("meta") or {}).get("llm_calls") or
                                job.progress["calls"])
    job.progress["current"] = None


def fail(job_id: str, message: str) -> None:
    job = _JOBS.get(job_id)
    if job is None or job.state in TERMINAL:
        return
    job.state, job.finished_at, job.error = "error", _now(), message
    job.progress["current"] = None


def mark_cancelled(job_id: str) -> None:
    """Terminal, but not a refund: `progress.calls` keeps what was already spent."""
    job = _JOBS.get(job_id)
    if job is None or job.state in TERMINAL:
        return
    job.state, job.finished_at = "cancelled", _now()
    job.progress["current"] = None


def request_cancel(job_id: str) -> bool:
    """Ask a running job to stop. False when there is nothing left to stop.

    Cancels the task as well as setting the flag -- a chain waiting on a model call will not
    look at a flag. Calls already sent are already billed; this stops the ones that have not
    been sent yet, and leaves every file the run has written in place.
    """
    job = _JOBS.get(job_id)
    if job is None or job.state in TERMINAL:
        return False
    job.cancel_requested = True
    task = _TASKS.get(job_id)
    if task is not None:
        task.cancel()
    return True


def snapshot(job_id: str) -> dict | None:
    """A JSON-safe copy of the job. Mutating it cannot reach the job it came from."""
    job = _JOBS.get(job_id)
    if job is None:
        return None
    return {
        "id": job.id,
        "pubmed_id": job.pubmed_id,
        "study_accession": job.study_accession,
        "state": job.state,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "estimate": copy.deepcopy(job.estimate),
        "acknowledged_calls": job.acknowledged_calls,
        "estimate_drift": copy.deepcopy(job.estimate_drift),
        "progress": copy.deepcopy(job.progress),
        "result": copy.deepcopy(job.result),
        "error": job.error,
        "cancel_requested": job.cancel_requested,
    }


def prune(max_jobs: int = MAX_JOBS) -> None:
    """Forget the oldest finished runs. A job still going is never forgotten."""
    while len(_JOBS) > max_jobs:
        for job_id, job in _JOBS.items():
            if job.state in TERMINAL:
                del _JOBS[job_id]
                break
        else:
            return


def reset() -> None:
    """Tests only."""
    _JOBS.clear()
    _TASKS.clear()
