"""Verify each extracted claim against the paper it came from — the claim-side twin of
app.agent.assay_verifier.

Input is the full in-memory claim set `claim_abstraction_v5.abstract_claims_from_document`
returns (every field pass 2 wrote, `polarity` included) plus the sentence-numbered text of the
same paper. Output is a per-field verdict — SUPPORTED / NOT_SUPPORTED / CONTRADICTED — and a
record-level ACCEPT / REVIEW / REJECT for each claim. Prompt: prompts/claims_v9/verify_claim.txt.

**This verifies; it never corrects** (see app.agent.claim_corrector for the repair).

Why it is not app.agent.claim_validator. That judge reads the slim claims.json, which drops
`polarity` on write, so on SDY1364 it failed 15 of 15 claims on polarity alone; and it is
closed-book, so it failed correct claims for naming the groups a quote calls "the two groups".
This one keeps the full claim and reads the whole paper, as the assay verifier does.

Free checks run first and outrank the judge, because they are facts rather than opinions:
  * every `sources[].quote` must appear verbatim in the paper (assay_verifier.check_quote_verbatim)
  * `claim_type` must be in the claim_types.txt vocabulary
  * `polarity` must be `affirm` or `null`
  * the claim must carry its mandatory head (contain "showed")

The record verdict is derived from the field verdicts, never taken from the model — the model's
own answer is kept alongside as `model_record_verdict`.
"""

import asyncio
import json
import logging
import re

from openai import AsyncOpenAI

from app.agent.assay_verifier import (
    ACCEPT,
    CONTRADICTED,
    MAX_CONCURRENT_CALLS,
    NOT_REPORTED,
    NOT_SUPPORTED,
    REJECT,
    REVIEW,
    SUPPORTED,
    check_quote_verbatim,
)
from app.agent.claim_parser import _load_prompt, _strip_fences, load_prompt_with_claim_types
from app.config import settings

logger = logging.getLogger(__name__)

VERIFY_PROMPT = "claims_v9/verify_claim.txt"

_MODEL_VERDICTS = (SUPPORTED, NOT_SUPPORTED, CONTRADICTED)

HEAD_MARKER = "showed"

POLARITIES = ("affirm", "null")

#: The not_a_claim reasons prompt v8 allows, plus the two this verifier adds for the errors the
#: SDY1364 run actually produced: a finding read off the data, and a Methods sentence.
NOT_A_CLAIM_REASONS = (
    "cited-background",
    "definition",
    "external-import",
    "interpretation",
    "not-executable",
    "not-stated-in-words",
    "methods-statement",
)

_TYPE_ROW = re.compile(r"^\|\s*`(\w+)`\s*\|", re.MULTILINE)


def claim_type_vocabulary() -> tuple[str, ...]:
    """The closed claim_type vocabulary, read from the table in claim_types.txt.

    Read, not copied, so the free check and the prompt the extractor was given cannot drift.
    """
    # The table's header row is "| `claim_type` | asserts | cues |" -- the column name, not a type.
    return tuple(t for t in _TYPE_ROW.findall(_load_prompt("claim_types.txt")) if t != "claim_type")


def split_head(claim: str) -> tuple[str, str]:
    """(head up to and including "showed", finding after it). No head -> ("", whole sentence)."""
    index = claim.find(HEAD_MARKER)
    if index == -1:
        return "", claim.strip()
    end = index + len(HEAD_MARKER)
    return claim[:end].strip(), claim[end:].strip()


def text_sources(claim: dict) -> list[tuple[int, dict]]:
    """(index into `sources`, entry) for every source that carries a quote."""
    return [
        (i, s) for i, s in enumerate(claim.get("sources") or [])
        if isinstance(s, dict) and isinstance(s.get("quote"), str) and s["quote"].strip()
    ]


def proposed_fields(claim: dict) -> list[tuple[str, object]]:
    """Every value the judge is asked about, as (field_name, value).

    `claim_type` and `polarity` are always listed, even when missing: both are mandatory, so an
    absent one is a defect to report, not an optional field to skip. `assay` and `sample_type`
    are listed only when proposed — the extractor is told to leave them null when unstated.
    """
    head, finding = split_head(claim.get("claim") or "")
    fields: list[tuple[str, object]] = [
        ("finding", finding),
        ("claim_type", claim.get("claim_type")),
        ("polarity", claim.get("polarity")),
    ]
    for key in ("assay", "sample_type"):
        if claim.get(key) not in (None, ""):
            fields.append((key, claim[key]))
    if head:
        fields.append(("head_metadata", head))
    fields += [(f"sources[{i}].quote", s["quote"]) for i, s in text_sources(claim)]
    return fields


def free_checks(claim: dict, source_text: str, vocabulary: tuple[str, ...]) -> dict[str, dict]:
    """The deterministic checks, as {field_name: {"verdict", "detail"}}. No API call.

    Only failures are returned with a verdict; a passing check is left to the judge's opinion
    on everything else about that field (a verbatim quote can still fail to support the claim).
    """
    checks: dict[str, dict] = {}
    for i, source in text_sources(claim):
        result = check_quote_verbatim({"evidence": {"quote": source["quote"]}}, source_text)
        if result["status"] == "missing":
            checks[f"sources[{i}].quote"] = {"verdict": CONTRADICTED, "detail": result["detail"]}

    claim_type = claim.get("claim_type")
    if claim_type not in vocabulary:
        checks["claim_type"] = {
            "verdict": CONTRADICTED if claim_type else NOT_SUPPORTED,
            "detail": f"claim_type {claim_type!r} is not in the claim_types.txt vocabulary",
        }

    polarity = claim.get("polarity")
    if polarity not in POLARITIES:
        checks["polarity"] = {
            "verdict": NOT_SUPPORTED,
            "detail": f"polarity {polarity!r} is not 'affirm' or 'null'",
        }

    if HEAD_MARKER not in (claim.get("claim") or ""):
        checks["head"] = {"verdict": NOT_SUPPORTED, "detail": "claim has no mandatory head ('showed')"}
    return checks


def _read_verification(raw: dict) -> dict:
    verdict = raw.get("verdict")
    return {
        "field_name": str(raw.get("field_name", "")),
        "proposed_value": raw.get("proposed_value"),
        "verdict": verdict if verdict in _MODEL_VERDICTS else NOT_REPORTED,
        "evidence_sentence_ids": [str(s) for s in (raw.get("evidence_sentence_ids") or [])],
        "evidence_text": raw.get("evidence_text"),
        "reason": raw.get("reason") or "",
    }


def _missing_verification(field_name: str, value: object) -> dict:
    return {
        "field_name": field_name,
        "proposed_value": value,
        "verdict": NOT_REPORTED,
        "evidence_sentence_ids": [],
        "evidence_text": None,
        "reason": "not reported by the verifier",
    }


def derive_record_verdict(identity_verdict: str, verifications: list[dict]) -> str:
    """ACCEPT / REVIEW / REJECT from the field verdicts, never from the model.

    REJECT only when the claim's identity is CONTRADICTED — it is not a claim at all. A wrong
    field is something to repair, which is REVIEW; removing a claim for a fixable field would
    lose a finding the paper does report.
    """
    if identity_verdict == CONTRADICTED:
        return REJECT
    unresolved = {CONTRADICTED, NOT_SUPPORTED, NOT_REPORTED}
    if identity_verdict != SUPPORTED or unresolved.intersection(v["verdict"] for v in verifications):
        return REVIEW
    return ACCEPT


def normalize_result(claim_key: str, claim: dict, raw: dict, checks: dict[str, dict]) -> dict:
    """One claim's report from the judge's answer plus the free checks, which outrank it."""
    by_name = {
        v["field_name"]: v
        for v in (_read_verification(r) for r in (raw.get("field_verifications") or [])
                  if isinstance(r, dict))
    }
    verifications = [by_name.get(f, _missing_verification(f, v)) for f, v in proposed_fields(claim)]
    for verification in verifications:
        check = checks.get(verification["field_name"])
        if check:
            verification["verdict"] = check["verdict"]
            verification["reason"] = check["detail"]
    if "head" in checks:
        # Not a field the judge is asked about, but a claim without its head cannot be ACCEPT.
        verifications.append({**_missing_verification("head", None),
                              "verdict": checks["head"]["verdict"],
                              "reason": checks["head"]["detail"]})

    identity = raw.get("claim_identity_verdict")
    if identity not in _MODEL_VERDICTS:
        identity = NOT_REPORTED
    reason = raw.get("not_a_claim_reason")
    model_verdict = raw.get("record_verdict")
    return {
        "claim_id": claim_key,
        "claim": claim.get("claim"),
        "claim_identity_verdict": identity,
        "not_a_claim_reason": reason if reason in NOT_A_CLAIM_REASONS else None,
        "field_verifications": verifications,
        "free_checks": checks,
        "record_verdict": derive_record_verdict(identity, verifications),
        "model_record_verdict": model_verdict if model_verdict in (ACCEPT, REVIEW, REJECT) else None,
    }


def error_result(claim_key: str, claim: dict, checks: dict[str, dict], message: str) -> dict:
    """Report shape for a claim whose verifier call failed outright."""
    return {
        "claim_id": claim_key,
        "claim": claim.get("claim"),
        "claim_identity_verdict": NOT_REPORTED,
        "not_a_claim_reason": None,
        "field_verifications": [_missing_verification(f, v) for f, v in proposed_fields(claim)],
        "free_checks": checks,
        "record_verdict": "ERROR",
        "model_record_verdict": None,
        "error": message,
    }


def build_prompt(claim_key: str, claim: dict, source_text: str, paper_title: str) -> str:
    """Render verify_claim.txt. The paper comes before the claim so the prefix cache covers it
    across every claim of the same paper."""
    candidate = {
        claim_key: {k: claim.get(k) for k in
                    ("claim", "claim_type", "polarity", "assay", "sample_type", "sources")},
        "fields_to_verify": [{"field_name": f, "proposed_value": v} for f, v in proposed_fields(claim)],
    }
    return (
        load_prompt_with_claim_types(VERIFY_PROMPT)
        .replace("{paper_title}", paper_title)
        .replace("{source_text}", source_text)
        .replace("{candidate}", json.dumps(candidate, indent=2, ensure_ascii=False))
    )


async def verify_claim(
    claim_key: str,
    claim: dict,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    vocabulary: tuple[str, ...] | None = None,
    tracker=None,
) -> dict:
    """Verify one claim. One LLM call. Never raises: a failure becomes an ERROR report."""
    checks = free_checks(claim, source_text, vocabulary or claim_type_vocabulary())
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user",
                       "content": build_prompt(claim_key, claim, source_text, paper_title)}],
            temperature=0,
        )
        if tracker is not None:
            tracker.record("verify", getattr(resp, "usage", None))
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        parsed = json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 - one bad claim must not cost the whole paper
        logger.warning("%s: verification call failed - %s", claim_key, exc)
        return error_result(claim_key, claim, checks, f"{type(exc).__name__}: {exc}")

    if not isinstance(parsed, dict):
        return error_result(claim_key, claim, checks,
                            f"verifier returned {type(parsed).__name__}, not an object")
    return normalize_result(claim_key, claim, parsed, checks)


async def verify_claims(
    claims: dict,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    max_concurrency: int = MAX_CONCURRENT_CALLS,
    tracker=None,
) -> list[dict]:
    """Verify every claim, one call each, concurrently. Results come back in claim order."""
    vocabulary = claim_type_vocabulary()
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(key: str) -> dict:
        async with semaphore:
            result = await verify_claim(key, claims[key], source_text, paper_title, client,
                                        model, vocabulary, tracker)
        print(f"  {key}: {result['record_verdict']}")
        return result

    print(f"Verifying {len(claims)} claim(s), up to {max(1, max_concurrency)} at a time...")
    return list(await asyncio.gather(*(_one(k) for k in claims)))


def drop_rejected(claims: dict, results: list[dict]) -> tuple[dict, list[dict]]:
    """Split claims into (kept, not_a_claim entries) on REJECT. Removal is mechanical; the
    rejected claim travels with its reason, so a wrong REJECT stays recoverable."""
    rejected = {r["claim_id"]: r for r in results if r.get("record_verdict") == REJECT}
    kept, dropped = {}, []
    for key, claim in claims.items():
        if key in rejected:
            dropped.append({
                "claim_id": key,
                "text": claim.get("claim", ""),
                "reason": rejected[key].get("not_a_claim_reason") or "rejected by verifier",
                "entry": claim,
                "from": "verification",
            })
        else:
            kept[key] = claim
    return kept, dropped


def build_report(results: list[dict]) -> dict:
    """Assemble claims_verification.json: record verdicts plus a per-field issue tally."""
    field_issues: dict[str, dict[str, int]] = {}
    for result in results:
        for v in result.get("field_verifications") or []:
            if v["verdict"] == SUPPORTED:
                continue
            name = re.sub(r"\[\d+\]", "[]", v["field_name"])
            field_issues.setdefault(name, {})
            field_issues[name][v["verdict"]] = field_issues[name].get(v["verdict"], 0) + 1
    verdicts = [r.get("record_verdict") for r in results]
    return {
        "summary": {
            "total": len(results),
            "accept": verdicts.count(ACCEPT),
            "review": verdicts.count(REVIEW),
            "reject": verdicts.count(REJECT),
            "errors": verdicts.count("ERROR"),
            "field_issues": field_issues,
        },
        "results": results,
    }
