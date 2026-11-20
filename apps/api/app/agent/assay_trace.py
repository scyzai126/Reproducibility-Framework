"""Keep every model reply a pipeline run paid for, so a bad run can be read instead of re-bought.

The assay chain spends EXTRACTIONS + N + F + O calls on a paper and, until this module, kept
none of the replies: each round parsed its answer, wrote what it derived, and dropped the text. Every defect
found in the two reviews of the chain had to be reconstructed from those derived files, and
whether a given alias objection or OBI pick was the model's or the parser's could not be told
without paying for the run again.

A `Trace` is a list of records held in a ContextVar. `assay_service.assay_report` starts one and
writes it to `<registry_dir>/assays_raw.json` after every round; each round calls `record(...)`
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


# ── token usage ───────────────────────────────────────────────────────────────
#
# Each record may carry a `usage` dict beside its reply: what the call was billed for, read
# off the response. Until it was recorded, the chain's cost was known only in calls -- a
# char-count estimate over the v3 corpus put a paper at $0.36-$1.47, but could not see the two
# numbers that decide the real bill: how much of each prompt OpenAI served from its prefix
# cache (a tenth of the input price) and how many reasoning tokens the model billed as output
# (six times the input price) without ever showing them. The summary is derived from the
# records rather than stored, so a run that adds a round later (run_assay_merge.py --map) needs
# no merge logic and any assays_raw.json on disk can be summed by a reader.

#: The fields kept per call, in the order a reader expects them. `cached` is the part of
#: `prompt` served from the prefix cache (already counted in `prompt`, billed at a discount);
#: `reasoning` is the part of `completion` the model spent thinking (already counted in
#: `completion`, never shown). A fake client with no `usage` attribute records nothing.
USAGE_FIELDS = ("prompt", "cached", "completion", "reasoning")

#: OpenAI list price, standard tier, USD per million tokens, as published 2026-11-04. Only an
#: estimate at print time: the API does not return a price, and the table goes stale the day
#: the price changes. A model missing here gets tokens printed and no dollar figure.
LIST_PRICE_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.50, "cached": 0.25, "output": 15.00},
    # Anthropic list price, 2026-11-03. A cache write bills at 1.25x input and is priced
    # here as plain input, so the estimate runs slightly low.
    "claude-opus-5-5": {"input": 4.00, "cached": 0.20, "output": 20.00},
    "claude-fable-5-2": {"input": 8.00, "cached": 0.20, "output": 40.00},
}
LIST_PRICE_DATE = "2026-11-04"


def usage_fields(resp: object) -> dict[str, int]:
    """The tokens one response was billed for, or {} when the response carries no usage.

    Read with getattr defaults throughout: the SDK's usage object omits the `*_details` blocks
    on some models, and every test fake omits `usage` altogether. An absent block counts as 0,
    not as a failure -- a call that cannot be sized must still be recorded with its reply.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    return {
        "prompt": int(getattr(usage, "prompt_tokens", 0) or 0),
        "cached": int(getattr(prompt_details, "cached_tokens", 0) or 0),
        "completion": int(getattr(usage, "completion_tokens", 0) or 0),
        "reasoning": int(getattr(completion_details, "reasoning_tokens", 0) or 0),
    }


def _payloads(grouped: dict) -> list[tuple[str, dict]]:
    """Every (round, payload) in a grouped trace, whatever its nesting.

    `extract` without a key is one payload; `verify` and `obi` nest one per assay; `correct`
    nests assay → field. A payload is told from a nesting level by having a `reply` or an
    `error` -- the two things every record carries one of.
    """
    found: list[tuple[str, dict]] = []

    def _walk(round_: str, node: object) -> None:
        if not isinstance(node, dict):
            return
        if "reply" in node or "error" in node:
            found.append((round_, node))
            return
        for child in node.values():
            _walk(round_, child)

    for round_, node in grouped.items():
        _walk(round_, node)
    return found


def usage_summary(grouped: dict) -> dict:
    """Per-round and total token counts over a grouped trace (`Trace.as_json()` or the file).

    `calls` counts every record, with or without `usage`, so a failed call and a call made
    through a fake client are still in the count; the token columns sum only what was recorded.
    """
    empty = lambda: {"calls": 0, **{f: 0 for f in USAGE_FIELDS}}  # noqa: E731
    by_round: dict[str, dict[str, int]] = {}
    total = empty()
    for round_, payload in _payloads(grouped):
        bucket = by_round.setdefault(round_, empty())
        bucket["calls"] += 1
        total["calls"] += 1
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        for f in USAGE_FIELDS:
            n = int(usage.get(f, 0) or 0)
            bucket[f] += n
            total[f] += n
    return {"by_round": by_round, "total": total}


def estimate_usd(totals: dict, model: str) -> float | None:
    """What `totals` (a `usage_summary` bucket) cost at `model`'s list price, or None.

    Uncached prompt tokens at the input price, cached ones at the cached price, every completion
    token -- reasoning included, since the API counts it there -- at the output price.
    """
    price = LIST_PRICE_USD_PER_MTOK.get(model)
    if price is None:
        return None
    prompt = int(totals.get("prompt", 0) or 0)
    cached = min(int(totals.get("cached", 0) or 0), prompt)
    completion = int(totals.get("completion", 0) or 0)
    return ((prompt - cached) * price["input"] + cached * price["cached"]
            + completion * price["output"]) / 1_000_000


def format_usage(summary: dict, model: str) -> list[str]:
    """The lines a run prints for its usage: one per round, then the total with a price."""
    def _line(label: str, b: dict) -> str:
        return (f"{label:8} {b['calls']:3} call(s)  {b['prompt']:>9,} prompt "
                f"({b['cached']:,} cached)  {b['completion']:>7,} completion "
                f"({b['reasoning']:,} reasoning)")
    lines = [_line(r, b) for r, b in summary["by_round"].items()]
    total = summary["total"]
    usd = estimate_usd(total, model)
    tail = (f"  ≈ ${usd:.2f} at {model} list price ({LIST_PRICE_DATE})"
            if usd is not None else "")
    lines.append(_line("total", total) + tail)
    return lines


def usage_kw(resp: object) -> dict:
    """`{"usage": ...}` for a response that carries usage, else {} -- for `record(**usage_kw(resp))`.

    The key is left out rather than set to {} so a record from a fake client, or from an
    SDK that returned no usage, reads exactly as it did before usage was recorded.
    """
    fields = usage_fields(resp)
    return {"usage": fields} if fields else {}
