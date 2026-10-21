"""Round 5's judge: whether entries that share an OBI term are one measurement.

A shared term used to be the fold rule on its own -- "two entries are one assay when they share
an OBI term" -- and on the 31-paper `stability` run that rule was wrong more often than right:
**12 of its 18 folds merged different measurements** the extractor had correctly split. Six of
them folded an ICS or stimulation assay into the paper's immunophenotyping; the others folded a
supernatant cytokine ELISA into a serum IgG ELISA (SDY1260), an IgM-capture ELISA into an
inhibition ELISA, a B-cell ELISPOT into a cytokine ELISPOT, phosphoflow into subset frequencies
and DC-activation flow into ASC flow. One OBI term covers every flow cytometry experiment a paper
runs, and most papers run several.

Nothing already on the record could tell the right folds from the wrong ones. The
`standard_technique_name` was the same in both -- it is the instrument, and one instrument runs
many assays, which is why it was dropped as a fold link before this. The picker's
`obi_granularity` was tried next and reverted: BROAD/EXACT is not stable between runs (SDY2189's
two FRNT write-ups came back EXACT once and BROAD the next time, splitting one assay in two), and
the wrong folds it was meant to stop had been mapped EXACT anyway. What does tell them apart is
the identity rule the extraction prompt already states -- technique + analyte + specimen -- read
over the two records together, which is a judgement, not a lookup. So it is asked.

One call per candidate group: the entries that share a term (`assay_merger.fold_candidates`),
shown as records -- key, wordings, technique, aliases, specimen, readouts, section, quote -- and
nothing else. The judge does not see the paper: the question is whether the records describe one
measurement, and the records are what round 5 is about to merge. It answers with a partition of
the group's keys. `assay_merger.canonical_groups` folds each set of that partition and keeps the
sets apart from one another.

**A failed call never folds.** The partition for a group whose call failed, or whose answer was
not a partition of its members, is `None`, and the merger then keeps every member of that group
as its own entry (`judge_failed`). The alternative -- fold as before when the judge cannot be
heard -- would make a transport error the one thing that still produced the 12-of-18 mistake. A
fold is irreversible once the registry is written, because the folded member's key is gone and
its fields sit inside another entry's `additional_evidence`; a split is not, since the two
entries are still there to be folded on the next pass. So the extractor's split stands until a
judge confirms otherwise. A label absent from the partition altogether means "not judged", and
the merger folds it as it always did -- that is the path `run_assay_merge.py` takes without
`--judge`, and the one every caller that never asks a judge is on.

Conventions are assay_verifier.verify_assay's: temperature 0, fences stripped, the reply kept in
the run's trace under the round's name, and nothing raised past the record.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.agent import assay_trace
from app.agent.assay_extractor import EXTRACTION_SEED, paper_names
from app.agent.assay_verifier import MAX_CONCURRENT_CALLS
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.config import settings

logger = logging.getLogger(__name__)

#: The trace round these replies are kept under: round 5's own name, so assays_raw.json groups
#: them where a reader of the run looks for round 5, keyed by the OBI label judged.
ROUND = "canonicalize"

#: What the judge is shown per member, in this order. The identity rule reads technique,
#: analyte and specimen; `readouts` is where the analyte usually is, `section` and `quote` are
#: what says whether a write-up had its own stimulation or staining step, and `aliases` carries
#: the second wording that proves two entries are the same one named twice.
CANDIDATE_FIELDS = ("key", "name_in_paper", "standard_technique_name", "aliases", "sample_type",
                    "readouts", "section", "quote")


def candidate(key: str, entry: dict) -> dict:
    """One member as the judge sees it: CANDIDATE_FIELDS, read with .get() throughout.

    `evidence` falls back to `evidence_location`, the old schema's name for it, for the same
    reason contract_warnings tolerates it: `run_assay_merge.py --judge` runs over registries on
    disk, some of which predate the current schema, and a judge shown no section and no quote
    for one member would be deciding on half the record.
    """
    evidence = entry.get("evidence") or entry.get("evidence_location") or {}
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        "key": key,
        "name_in_paper": paper_names(entry) or [key],
        "standard_technique_name": entry.get("standard_technique_name"),
        "aliases": entry.get("aliases") if isinstance(entry.get("aliases"), list) else [],
        "sample_type": entry.get("sample_type"),
        "readouts": entry.get("readouts"),
        "section": evidence.get("section"),
        "quote": evidence.get("quote"),
    }


def build_prompt(label: str, members: list[str], assays: dict) -> str:
    """Render judge_fold.txt for one candidate group. No paper text: the records are the case."""
    records = json.dumps([candidate(key, assays[key]) for key in members], indent=2,
                         ensure_ascii=False)
    return (
        _load_prompt("judge_fold.txt")
        .replace("{obi_label}", label)
        .replace("{candidates}", records)
    )


def parse_partition(raw_groups: object, members: list[str]) -> tuple[list[list[str]] | None, str | None]:
    """Check that an answer is a partition of exactly `members`, and normalise it.

    Returns (sets, None) or (None, error). A set the judge invented a member for, left one out
    of, or named twice is not a partition, and acting on it would lose or duplicate an entry --
    so the whole answer is refused and the group is left unfolded, as a failed call is.

    Normalised so the same verdict always yields the same registry: members within a set are
    ordered by registry index and the sets by their first member's index, which puts the anchor
    (the group's first entry, whose fields survive a fold) in the first set. The judge's own
    ordering is a formatting accident, not a finding.
    """
    if not isinstance(raw_groups, list) or not raw_groups:
        return None, f"fold judge returned {type(raw_groups).__name__}, not a list of groups"
    for group in raw_groups:
        if (not isinstance(group, list) or not group
                or not all(isinstance(key, str) for key in group)):
            return None, "fold judge returned a group that is not a non-empty list of keys"
    index = {key: i for i, key in enumerate(members)}
    flat = [key for group in raw_groups for key in group]
    unknown = [key for key in flat if key not in index]
    if unknown:
        return None, f"fold judge named keys that are not in the group: {unknown}"
    repeated = sorted({key for key in flat if flat.count(key) > 1}, key=index.get)
    if repeated:
        return None, f"fold judge placed keys in more than one group: {repeated}"
    missing = [key for key in members if key not in flat]
    if missing:
        return None, f"fold judge left keys out of every group: {missing}"
    sets = [sorted(group, key=index.get) for group in raw_groups]
    sets.sort(key=lambda group: index[group[0]])
    return sets, None


async def judge_fold(
    label: str,
    members: list[str],
    assays: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Ask whether one candidate group is one measurement. One LLM call, one group.

    Returns `{label, members, groups, reason, error}`: `groups` is the normalised partition, or
    None with `error` set when the call failed, the reply was empty or not an object, or the
    answer was not a partition of `members`. Never raises -- a group the judge could not rule on
    is a finding on the round (`judge_failed`), not a lost paper.
    """
    record = {"label": label, "members": list(members), "groups": None, "reason": None,
              "error": None}
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_prompt(label, members, assays)}],
            temperature=0,
            # Seeded like extraction and the OBI pick: a fold is irreversible, so the same
            # registry should get the same partition on a re-run as far as the provider allows.
            seed=EXTRACTION_SEED,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        assay_trace.record(ROUND, label, reply=raw)
        parsed = json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - any failure becomes a per-group error record
        logger.warning("%s: fold judge call failed - %s", label, exc)
        assay_trace.record(ROUND, label, error=f"{type(exc).__name__}: {exc}")
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    # An empty reply is a failed call, not a verdict -- the line the verifier and the corrector
    # both draw. Read as {} it would be "no groups", which parse_partition refuses anyway, but
    # the error should say what happened rather than what it looked like.
    if parsed is None:
        record["error"] = "fold judge returned an empty reply"
        return record
    if not isinstance(parsed, dict):
        record["error"] = f"fold judge returned {type(parsed).__name__}, not an object"
        return record

    reason = parsed.get("reason")
    record["reason"] = reason if isinstance(reason, str) and reason.strip() else None
    groups, error = parse_partition(parsed.get("groups"), list(members))
    if error:
        record["error"] = error
        return record
    record["groups"] = groups
    return record


async def judge_fold_groups(
    groups: list[dict],
    assays: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    max_concurrency: int = MAX_CONCURRENT_CALLS,
) -> tuple[dict[str, list[list[str]] | None], list[dict]]:
    """Judge every candidate group of a registry. One call per group, concurrent.

    `groups` are `assay_merger.fold_candidates` records (`obi_label`, `members`). Returns
    `(partition, records)`: the partition is keyed by label -- a list of sets where the judge
    answered, **`None` where the call failed** -- and is what `canonical_groups` takes; the
    records carry each group's reason or error for the merge report and the CLI.

    Bounded by `max_concurrency` and gathered in group order, as correct_registry gathers its
    field calls: the calls are independent, each reads its own records and writes nothing, and
    `gather` keeps the records in the order the groups were given however the calls interleave.
    No groups means no call.
    """
    if not groups:
        return {}, []
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(group: dict) -> dict:
        async with semaphore:
            return await judge_fold(group["obi_label"], list(group["members"]), assays,
                                    client, model)

    records = list(await asyncio.gather(*(_one(group) for group in groups)))
    partition = {record["label"]: record["groups"] for record in records}
    return partition, records
