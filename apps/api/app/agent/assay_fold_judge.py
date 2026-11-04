"""Adjudicate the folds round 5 refused: one call per blocked pair, SAME or DIFFERENT.

Round 5 (`assay_merger`) folds two entries on one OBI term only when the identity triple --
`standard_technique_name`, `sample_type`, `readouts` -- does not conflict, and compares `readouts`
by exact string because it is a sentence the model wrote. Measured on assay_result_v3 (31 papers)
that refused 22 folds, 14 of them on `readouts`; carrying the round-1 vote's lenient match
(containment or token Jaccard >= 0.5) over to the fold released exactly 1 of the 14. The leg is
binary, so no string threshold is on offer -- and dropping the leg is wrong, because the pairs it
keeps apart are mostly real: SDY1328's anti-CTB and anti-diphtheria ELISAs, SDY212's subset
frequencies and STAT phosphorylation, SDY1640's immunophenotyping and intracellular cytokine
staining, each two rows in the curated benchmark. The one or two wording-only pairs (SDY1291's
"gene expression" against "gene and exon-level RNA expression") are what this module recovers.

`adjudicate` takes a canonicalized registry and its mapping, finds the blocked folds again, and
asks the model about each pair whose only differing leg is `readouts` or `sample_type`. A pair
that differs on the technique is never sent: the technique is the instrument, and two
instruments are two measurements by the extraction's own rule. A `SAME` verdict folds the member
onto its anchor through `assay_merger.merge_entries`, so nothing is discarded -- the member's
write-up moves to `additional_evidence` -- and the fold record carries the verdict and reason
under `judged`. A `DIFFERENT` verdict leaves the pair apart and appends the reason to the blocked
record, so `REVIEW  not folded` now says why in the model's words. A reply that is neither is
treated as DIFFERENT with the raw reply as its reason: an unparsed answer must not fold anything.

Cost: one call per judged pair -- 20 over the v3 corpus, about 0.65 per paper against the
pipeline's ~21. Every reply is recorded under `judge` in assays_raw.json. `adjudicate` takes the
judge as a parameter so a test, and a dry run, never reach the network.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from openai import OpenAI

from app.agent import assay_trace
from app.agent.assay_extractor import paper_names
from app.agent.assay_merger import blocked_folds, canonical_groups, merge_entries
from app.config import settings

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

#: The legs a pair may differ on and still be asked about. The technique is not one: it is the
#: instrument, and the extraction's rule is that two instruments are two measurements.
JUDGED_LEGS = frozenset({"readouts", "sample_type"})

_REPLY = re.compile(r"\s*\**\s*(same|different)\s*\**\s*[:\-—–]?\s*(.*)", re.IGNORECASE | re.DOTALL)

Judge = Callable[[str, dict, str, dict, str], dict]


def judgeable(record: dict) -> bool:
    """Whether a blocked-fold record's reason names a leg this module adjudicates."""
    reason = str(record.get("reason") or "")
    return any(reason.startswith(f"{leg} differs") for leg in JUDGED_LEGS)


def _name(entry: dict) -> str:
    names = paper_names(entry)
    return names[0] if names else ""


def _field(entry: dict, name: str) -> str:
    return " ".join(str(entry.get(name) or "").split()) or "not given"


def build_judge_prompt(anchor: dict, member: dict, obi_label: str) -> str:
    """Render judge_fold.txt for one pair. Split out so a test can read it without the network."""
    text = (_PROMPTS_DIR / "judge_fold.txt").read_text(encoding="utf-8")
    for role, entry in (("anchor", anchor), ("member", member)):
        evidence = entry.get("evidence") or {}
        text = (text
                .replace(f"{{{role}_name}}", _name(entry) or "not given")
                .replace(f"{{{role}_technique}}", _field(entry, "standard_technique_name"))
                .replace(f"{{{role}_sample}}", _field(entry, "sample_type"))
                .replace(f"{{{role}_readouts}}", _field(entry, "readouts"))
                .replace(f"{{{role}_quote}}", " ".join(str(evidence.get("quote") or "").split())))
    return text.replace("{obi_label}", obi_label or "no term")


def parse_judge_reply(reply: str) -> tuple[str | None, str]:
    """("SAME" | "DIFFERENT" | None, reason). None for anything that is not one of the two."""
    match = _REPLY.fullmatch(reply.strip().strip("`'\""))
    if not match:
        return None, reply.strip()
    return match.group(1).upper(), " ".join(match.group(2).split())


def judge_fold(anchor_key: str, anchor: dict, member_key: str, member: dict, obi_label: str,
               model: str = settings.OPENAI_MODEL) -> dict:
    """Ask the model whether `member` is the same measurement as `anchor`. One call.

    Returns {"verdict": "SAME" | "DIFFERENT", "reason": str}. An unparsed reply is DIFFERENT,
    with the raw reply as the reason, and is logged: nothing folds on an answer nobody gave.
    """
    prompt = build_judge_prompt(anchor, member, obi_label)
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    reply = (resp.choices[0].message.content or "").strip()
    assay_trace.record("judge", f"{member_key} vs {anchor_key}", reply=reply,
                       **assay_trace.usage_kw(resp))
    verdict, reason = parse_judge_reply(reply)
    if verdict is None:
        logger.warning("fold judge reply not understood, kept apart: %r", reply[:120])
        return {"verdict": "DIFFERENT", "reason": f"reply not understood: {reason}"}
    return {"verdict": verdict, "reason": reason}


def judged_pairs(assays: dict, obi: dict | None) -> list[dict]:
    """The blocked folds this module would ask about, as `blocked_folds` records."""
    return [r for r in blocked_folds(canonical_groups(assays, obi)) if judgeable(r)]


def adjudicate(assays: dict, obi: dict | None, judge: Judge = judge_fold
               ) -> tuple[dict, dict | None, list[dict], list[dict]]:
    """Judge every blocked fold on a canonicalized registry. Returns
    (assays, obi, folds, blocked): the registry with every SAME pair folded, the mapping
    without the folded keys, the folds made (each with `judged`), and every blocked record
    that remains -- a DIFFERENT verdict with its reason appended, or a pair never sent.

    The registry is expected canonicalized (`canonicalize_registry`), so the anchor and the
    member are both keys of `assays` and the member's key is the suffixed one.
    """
    merged = dict(assays)
    obi_out = dict(obi) if obi is not None else None
    folds: list[dict] = []
    blocked: list[dict] = []
    for record in blocked_folds(canonical_groups(assays, obi)):
        anchor_key, member_key = record["anchor"], record["member"]
        if not judgeable(record) or anchor_key not in merged or member_key not in merged:
            blocked.append(dict(record))
            continue
        verdict = judge(anchor_key, merged[anchor_key], member_key, merged[member_key],
                        record.get("obi_label") or "")
        if verdict.get("verdict") != "SAME":
            blocked.append({**record, "judged": verdict})
            continue
        merged[anchor_key] = merge_entries(merged[anchor_key], [merged.pop(member_key)])
        if obi_out is not None:
            obi_out.pop(member_key, None)
            mapped = dict(obi_out.get(anchor_key) or {})
            if mapped:
                mapped["name_in_paper"] = merged[anchor_key].get("name_in_paper")
                obi_out[anchor_key] = mapped
        folds.append({"key": anchor_key, "obi_id": record.get("obi_id"),
                      "obi_label": record.get("obi_label"), "members": [anchor_key, member_key],
                      "folded": [member_key], "judged": verdict})
    return merged, obi_out, folds, blocked


def reconcile_report(keys: dict[str, str], blocked: list[dict], judged_folds: list[dict],
                     judged_blocked: list[dict]) -> tuple[dict[str, str], list[dict], list[dict]]:
    """Round 5's report, carried through the judge's verdicts. Returns (keys, folds, blocked).

    Round 5 records a blocked fold by the extractor's wordings (`member` "commercially available
    kit", `anchor` "GM1-ELISA"), and `adjudicate` re-finds the same pair on the canonical
    registry, where the member is "enzyme-linked immunosorbent assay (2)". A reader wants the
    wording, so each verdict is attached to round 5's own record, found through `key_map`. A
    SAME verdict's fold is written by the wordings it folded, and every wording that mapped to
    the folded key now maps to the survivor -- the key_map is the only join from the earlier
    files to the registry, and a stale entry there would point at a key that no longer exists.
    """
    keys = dict(keys)
    by_canonical: dict[str, dict] = {}
    for record in blocked:
        by_canonical.setdefault(keys.get(record["member"], record["member"]), record)

    folds: list[dict] = []
    for fold in judged_folds:
        member_key = fold["folded"][0]
        wordings = [k for k, v in keys.items() if v == member_key] or [member_key]
        anchor_wordings = [k for k, v in keys.items() if v == fold["key"]] or [fold["key"]]
        for wording in wordings:
            keys[wording] = fold["key"]
        folds.append({**fold, "members": anchor_wordings + wordings, "folded": wordings})

    out: list[dict] = []
    for record in judged_blocked:
        original = by_canonical.get(record["member"])
        merged = dict(original) if original is not None else dict(record)
        if "judged" in record:
            merged["judged"] = record["judged"]
        out.append(merged)
    return keys, folds, out
