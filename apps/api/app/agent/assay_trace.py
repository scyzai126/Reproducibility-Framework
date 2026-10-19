"""Keep every model reply a pipeline run paid for, so a bad run can be read instead of re-bought.

The assay chain spends 3 + N + F + O calls on a paper and, until this module, kept none of the
replies: each round parsed its answer, wrote what it derived, and dropped the text. Every defect
found in the two reviews of the chain had to be reconstructed from those derived files, and
whether a given alias objection or OBI pick was the model's or the parser's could not be told
without paying for the run again.

A `Trace` is a list of records held in a ContextVar. `assay_service.assay_report` starts one and
writes it to `<registry_dir>/assays_raw.json` after every round (and before it gives up on a
round 1 with too few replies to vote over); each round calls `record(...)`
with the reply it got. Outside a trace `record` is a no-op, so the standalone scripts and every
existing test are unaffected, and the ContextVar carries into the `asyncio.gather` tasks of
round 2 and the `asyncio.to_thread` of round 4 without any of them being told.

Only the reply is kept, never the prompt: each prompt carries the whole paper, and the prompts
are files in apps/api/app/prompts that can be re-rendered from the registry. The OBI round also
keeps the numbered candidate lines the picker saw, because those are retrieval's output and are
otherwise gone the moment the pick is parsed.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from pathlib import Path

#: The file a run's trace is written to, beside the registry.
RAW_FILE = "assays_raw.json"

#: Rounds whose reply is one per run rather than one per assay -- when recorded with no key.
#: assay_service records each of its N extractions under "run1", "run2", ..., which then group
#: like any other round.
_SINGLE = frozenset({"extract"})


class Trace:
    """The replies of one run, in the order they arrived."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def add(self, round_: str, key: str = "", **fields: object) -> None:
        self.records.append({"round": round_, "key": key, **fields})

    def as_json(self) -> dict:
        """Group by round, then by assay key, then by field when a round has one.

        `extract` is a single reply per run. `verify` and `obi` are one per assay. `correct` is
        one per assay per field. A record that arrives twice for one slot overwrites the first,
        which is what a retry should do.
        """
        out: dict = {}
        for record in self.records:
            payload = {k: v for k, v in record.items() if k not in ("round", "key", "field")}
            round_ = record["round"]
            if round_ in _SINGLE and not record.get("key"):
                out[round_] = payload
                continue
            slot = out.setdefault(round_, {})
            if record.get("field"):
                slot.setdefault(record["key"], {})[record["field"]] = payload
            else:
                slot[record["key"]] = payload
        return out

    def write(self, path: Path) -> None:
        """Write the grouped trace, keeping any round an earlier write to `path` already holds.

        Merged rather than replaced so `run_assay_merge.py --map`, which re-runs round 4 alone,
        can add its `obi` block to a file the full run wrote without losing rounds 1-3.
        """
        path = Path(path)
        existing: dict = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                existing = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                existing = {}
        existing.update(self.as_json())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


_ACTIVE: ContextVar[Trace | None] = ContextVar("assay_trace", default=None)


def start() -> Trace:
    """Begin recording in this context. The previous trace, if any, is replaced."""
    trace = Trace()
    _ACTIVE.set(trace)
    return trace


def stop() -> None:
    """Stop recording in this context. Records already taken stay on the Trace object."""
    _ACTIVE.set(None)


def active() -> Trace | None:
    return _ACTIVE.get()


def record(round_: str, key: str = "", **fields: object) -> None:
    """Add one reply to the active trace; nothing happens when no trace is active."""
    trace = _ACTIVE.get()
    if trace is not None:
        trace.add(round_, key, **fields)
