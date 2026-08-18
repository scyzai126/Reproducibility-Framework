"""Score an experiment arm's claims.json against the SDY1260 gold standard.

An LLM judge maps every extracted claim onto a gold assertion id (or NONE), and labels it:
    correct      - states the gold assertion, right group/timepoint/direction
    duplicate    - restates a gold assertion already claimed by an earlier claim
    merged       - correctly covers >1 gold assertion in one claim (lists all ids)
    granularity  - under-split (chains two gold assertions that should be separate)
    distorted    - maps to a gold assertion but gets group, timepoint, or direction wrong
    unsupported  - asserts something no gold assertion covers and no quote supports

From the mapping the script computes recall over gold, precision over claims, and the
per-tier breakdown.

Usage:
    python scripts/exp_score.py data/experiments/sdy1260_prompt_ab/arm_A
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _strip_fences
from app.config import settings

GOLD = Path(__file__).resolve().parent.parent / "data" / "experiments" / "sdy1260_prompt_ab" / "gold_standard.json"

JUDGE_PROMPT = """You are scoring an automated claim extractor against a hand-built gold standard for one paper.

You receive (1) the GOLD ASSERTIONS — the distinct assertions the paper actually makes, each with an id,
and (2) the EXTRACTED CLAIMS produced by the extractor.

For every extracted claim, decide which gold assertion(s) it states, and label it:

- `correct`      — states one gold assertion with the right group, timepoint and direction. Give the id.
- `merged`       — correctly covers more than one gold assertion in a single claim, and the gold standard
                   permits that merge (the gold entries are marked `merge_ok` with each other, or they
                   share one assertion across several targets). List every id it covers.
- `granularity`  — chains two or more gold assertions that the gold standard keeps separate
                   (e.g. "induced a response, peaked at day 30, and lasted longer"). List every id.
- `duplicate`    — states a gold assertion that an EARLIER extracted claim already stated. Give the id and
                   the earlier claim key in `duplicate_of`. Judge on the assertion, not on wording or on
                   which panel it was filed under: the same finding filed under Figure 1 and again under
                   Table 1 is a duplicate.
- `distorted`    — maps to a gold assertion but gets the group, timepoint, target or direction wrong, or
                   flips polarity (asserts an effect the paper reported as absent, or vice versa).
                   Give the id and say what is wrong in `note`.
- `unsupported`  — asserts something no gold assertion covers. Set `gold_ids` to []. In `note`, say whether
                   it looks like (a) a real assertion the gold standard missed, (b) a raw data reading the
                   authors never stated in words, or (c) a study-design/method statement rather than a finding.

Judge on substance, not wording. A claim that says the same thing in different words is `correct`.
Be strict about polarity: a gold assertion marked `"polarity": "null"` is a stated ABSENCE, and a claim
asserting the effect is present is `distorted`, not `correct`.

Return JSON only, no prose, no fences:

{"mappings": [
  {"claim_key": "claim_1", "gold_ids": ["G01"], "label": "correct", "duplicate_of": null, "note": ""}
]}

Every extracted claim must appear exactly once in `mappings`."""


def compact_gold(gold: dict) -> str:
    lines = []
    for a in gold["assertions"]:
        flags = []
        if a.get("optional"):
            flags.append("OPTIONAL")
        if a.get("merge_ok"):
            flags.append(f"merge_ok_with={a['merge_with']}")
        tail = f"  [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"{a['id']} (tier {a['tier']}) [{a['claim_type']}/{a['polarity']}] "
            f"panel={a['panel']} groups={a['groups']} :: {a['assertion']}{tail}"
        )
    return "\n".join(lines)


def compact_claims(claims: dict) -> str:
    lines = []
    for k, v in claims.items():
        lines.append(
            f"{k} [{v.get('claim_type')}/{v.get('polarity')}] panel={v.get('panel')} "
            f"groups={v.get('groups')} :: {v.get('claim')}"
        )
    return "\n".join(lines)


def summarise(gold: dict, claims: dict, mappings: list[dict]) -> dict:
    by_id = {a["id"]: a for a in gold["assertions"]}
    labels = Counter(m["label"] for m in mappings)

    # A gold assertion counts as found when some claim maps to it with a credit-earning label.
    CREDIT = {"correct", "merged", "granularity"}
    found: set[str] = set()
    for m in mappings:
        if m["label"] in CREDIT:
            found.update(m.get("gold_ids") or [])

    tiers: dict[int, dict] = {}
    for tier in (1, 2):
        ids = {i for i, a in by_id.items() if a["tier"] == tier}
        optional = {i for i in ids if by_id[i].get("optional")}
        required = ids - optional
        hit = found & required
        tiers[tier] = {
            "gold_required": len(required),
            "found": len(hit),
            "recall": round(len(hit) / len(required), 3) if required else None,
            "missed": sorted(required - found),
            "optional_found": sorted(found & optional),
        }

    good = labels["correct"] + labels["merged"]
    return {
        "claims_extracted": len(claims),
        "labels": dict(labels),
        "precision_strict": round(good / len(claims), 3) if claims else 0.0,
        "precision_lenient": round((good + labels["granularity"]) / len(claims), 3) if claims else 0.0,
        "tiers": tiers,
        "overall_recall_required": round(
            (tiers[1]["found"] + tiers[2]["found"])
            / (tiers[1]["gold_required"] + tiers[2]["gold_required"]),
            3,
        ),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm_dir", type=Path)
    ap.add_argument("--model", default=settings.OPENAI_MODEL)
    args = ap.parse_args()

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    claims = json.loads((args.arm_dir / "claims.json").read_text(encoding="utf-8"))
    print(f"Scoring {args.arm_dir.name}: {len(claims)} claims vs {len(gold['assertions'])} gold assertions")

    client = _get_client()
    resp = await client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": (
                    f"GOLD ASSERTIONS:\n{compact_gold(gold)}\n\n"
                    f"EXTRACTED CLAIMS:\n{compact_claims(claims)}"
                ),
            },
        ],
        temperature=0,
    )
    mappings = json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))["mappings"]

    missing = set(claims) - {m["claim_key"] for m in mappings}
    if missing:
        print(f"  WARNING: judge skipped {len(missing)} claims: {sorted(missing)[:5]}")

    report = {"arm": args.arm_dir.name, "summary": summarise(gold, claims, mappings), "mappings": mappings}
    (args.arm_dir / "score.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    s = report["summary"]
    print(f"\n  labels: {s['labels']}")
    print(f"  precision strict {s['precision_strict']}  lenient {s['precision_lenient']}")
    for tier in (1, 2):
        t = s["tiers"][tier]
        print(f"  tier {tier}: recall {t['recall']}  ({t['found']}/{t['gold_required']})  missed {t['missed']}")
    print(f"  overall recall {s['overall_recall_required']}")
    print(f"\nWritten to {args.arm_dir}/score.json")


if __name__ == "__main__":
    asyncio.run(main())
