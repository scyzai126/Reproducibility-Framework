"""Judge each structured claim in groups.json for accuracy against its own recorded sources.

This is a closed-book audit: the judge sees only what is already inside the groups.json
entry — the claim sentence, the verbatim Results/caption quotes it was drawn from, and the
groups/comparison/ranking structure derived from it. The paper itself is never re-opened,
so the `sources` array is the sole ground truth.

Five checks run per claim (see prompts/validate_claims.txt):
    grounding                 - every asserted fact appears in the sources
    comparator_form           - no group split invented out of a correlation
    completeness              - no stated relationship silently dropped
    timepoint_group_coverage  - every named timepoint/population has a group
    structural                - contrast indices resolve, no duplicate comparisons,
                                ranking scope matches what is ranked

Nothing is dropped or rewritten — verdicts are written to their own file and the
extraction output is left untouched. Repairing `needs_revision` claims is a separate step.
"""

import json
import logging

from openai import AsyncOpenAI

from app.agent.claim_parser import _load_prompt, _strip_fences
from app.config import settings

logger = logging.getLogger(__name__)

CHECK_NAMES = (
    "grounding",
    "comparator_form",
    "completeness",
    "timepoint_group_coverage",
    "structural",
)


def _normalize_result(claim_key: str, raw: dict) -> dict:
    """Coerce a judge response into the report contract.

    The model is asked for the full shape, but `verdict` and `issues` are derived here
    rather than trusted — a model that fails a check and still reports "accurate" would
    otherwise hide the failure. `claim_id` is likewise forced to the real key, since a
    per-claim call gives the model no way to know it beyond the echo we asked for.
    """
    checks: dict[str, dict] = {}
    raw_checks = raw.get("checks") or {}
    for name in CHECK_NAMES:
        entry = raw_checks.get(name)
        if isinstance(entry, dict):
            status = entry.get("status")
            reason = entry.get("reason", "")
        else:
            # Tolerate a bare "pass"/"fail" string in place of the object.
            status = entry if isinstance(entry, str) else None
            reason = ""
        checks[name] = {
            "status": status if status in ("pass", "fail") else "unknown",
            "reason": reason or "",
        }

    issues = [
        f"{name}: {check['reason']}".rstrip(": ")
        for name, check in checks.items()
        if check["status"] == "fail"
    ]
    verdict = "needs_revision" if issues else "accurate"

    return {"claim_id": claim_key, "checks": checks, "verdict": verdict, "issues": issues}


def _error_result(claim_key: str, message: str) -> dict:
    """Report shape for a claim whose judge call failed outright."""
    return {
        "claim_id": claim_key,
        "checks": {name: {"status": "unknown", "reason": ""} for name in CHECK_NAMES},
        "verdict": "error",
        "issues": [message],
    }


async def validate_claim(
    claim_key: str,
    entry: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Judge one groups.json entry. One LLM call, one claim.

    Never raises: an API or parse failure is recorded as a `verdict: "error"` report so a
    single bad claim cannot lose a whole paper's worth of verdicts.
    """
    template = _load_prompt("validate_claims.txt")
    payload = {claim_key: entry}
    prompt = template.replace("{claim}", json.dumps(payload, indent=2, ensure_ascii=False))

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        parsed = json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 - any failure becomes a per-claim error report
        logger.warning("%s: validation call failed - %s", claim_key, exc)
        return _error_result(claim_key, f"{type(exc).__name__}: {exc}")

    if not isinstance(parsed, dict):
        return _error_result(claim_key, f"judge returned {type(parsed).__name__}, not an object")

    return _normalize_result(claim_key, parsed)


async def validate_groups_file(
    groups: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    limit: int | None = None,
) -> list[dict]:
    """Judge every claim_* entry in a groups.json mapping, sequentially.

    One claim per call, mirroring run_group_step — a whole-paper batch would split the
    judge's attention across claims and dilute the per-claim checks.
    """
    claim_keys = [k for k in groups if k.startswith("claim_")]
    if limit is not None:
        claim_keys = claim_keys[:limit]

    results: list[dict] = []
    print(f"Validating {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        result = await validate_claim(key, groups[key], client, model)
        results.append(result)
        detail = f" ({', '.join(result['issues'])})" if result["issues"] else ""
        print(f"  [{i}/{len(claim_keys)}] {key}: {result['verdict']}{detail}")
    return results


def build_summary(results: list[dict]) -> dict:
    """Aggregate verdicts plus a per-check fail tally across all claims.

    The tally is the actionable part: a check failing across many claims points at a line
    in extract_claims_pdf.txt or classify_groups.txt to fix, rather than at one bad claim.
    """
    fail_counts = {name: 0 for name in CHECK_NAMES}
    for result in results:
        for name, check in (result.get("checks") or {}).items():
            if name in fail_counts and check.get("status") == "fail":
                fail_counts[name] += 1

    verdicts = [r.get("verdict") for r in results]
    return {
        "total": len(results),
        "accurate": verdicts.count("accurate"),
        "needs_revision": verdicts.count("needs_revision"),
        "errors": verdicts.count("error"),
        "fail_counts": fail_counts,
    }


def build_report(results: list[dict]) -> dict:
    """Assemble the claims_validation.json payload."""
    return {"summary": build_summary(results), "results": results}
