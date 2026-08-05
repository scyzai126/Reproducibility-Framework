"""Judge each claim in claim_filtered.json for accuracy, in two passes.

The input is the downstream-actionable subset of claims.json (see app.agent.claim_filter),
so this runs *before* group classification: a claim that fails here is caught without ever
paying a classify_groups call on it.

**Closed-book pass** — the judge sees only what is already inside the claim entry: the
claim sentence, its `claim_type` label, and the verbatim Results/caption quotes it was
drawn from. The paper is not opened, so the `sources` array is the sole ground truth. One
call per claim; three checks (see prompts/validate_claims.txt):
    grounding        - every asserted fact appears in the sources
    comparator_form  - no group split invented out of a correlation
    claim_type       - the assigned label is the right one for the assertion

**Metadata pass** — the three checks above deliberately ignore the contextual metadata in
every claim's head ("[Assay] analysis of [tissue] from [N] ..."), because that metadata
comes from Methods and Methods is never a citable source, so it can never appear in
`sources`. It is audited here instead, open-book against the PDF, as a fourth `metadata`
check (see prompts/validate_claim_metadata.txt). Claims are batched by head sentence —
heads repeat heavily across a paper — so this costs a handful of calls, not one per claim.
It runs only when a PDF is supplied; without one the `metadata` key is absent entirely
rather than silently counted as a pass.

A claim is `accurate` only when every check that ran explicitly passed. Anything else is
kept visible rather than folded into a pass: `needs_revision` (a check failed),
`inconclusive` (the judge did not report on some check), or `error` (the call failed).

Nothing is dropped or rewritten — verdicts are written to their own file and the
extraction output is left untouched. Repairing `needs_revision` claims is a separate step.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.agent.claim_parser import _load_prompt, _strip_fences, load_prompt_with_claim_types
from app.agent.pdf_direct import _pdf_file_content
from app.config import settings

logger = logging.getLogger(__name__)

CLOSED_BOOK_CHECKS = (
    "grounding",
    "comparator_form",
    "claim_type",
)

METADATA_CHECK = "metadata"

#: Every check that can appear in a report. `metadata` only appears when a PDF was given.
CHECK_NAMES = CLOSED_BOOK_CHECKS + (METADATA_CHECK,)

#: Heads per metadata call. Small enough that the judge's attention is not spread thin
#: across a whole paper, large enough that the PDF is not re-uploaded for every claim.
_METADATA_BATCH_SIZE = 10


def _finalize(claim_key: str, checks: dict[str, dict]) -> dict:
    """Derive `verdict` and `issues` from a set of checks.

    Verdict is derived, never trusted from the model — a judge that fails a check and
    still reports "accurate" would otherwise hide the failure. A check reported unreadably
    or not at all is `unknown`, which makes the claim `inconclusive`: an audit that skipped
    a check has not cleared the claim, so it must not read the same as one that passed.
    """
    issues = [
        f"{name}: {check['reason']}".rstrip(": ")
        for name, check in checks.items()
        if check["status"] == "fail"
    ]
    issues += [
        f"{name}: not reported by the judge"
        for name, check in checks.items()
        if check["status"] == "unknown"
    ]

    statuses = [check["status"] for check in checks.values()]
    if "fail" in statuses:
        # A named defect outranks a missing answer: there is something concrete to repair.
        verdict = "needs_revision"
    elif "unknown" in statuses:
        verdict = "inconclusive"
    else:
        verdict = "accurate"

    return {"claim_id": claim_key, "checks": checks, "verdict": verdict, "issues": issues}


def _read_check(raw_checks: dict, name: str) -> dict:
    """Read one check out of a judge response, tolerating a bare "pass"/"fail" string."""
    entry = raw_checks.get(name)
    if isinstance(entry, dict):
        status = entry.get("status")
        reason = entry.get("reason", "")
    else:
        status = entry if isinstance(entry, str) else None
        reason = ""
    return {
        "status": status if status in ("pass", "fail") else "unknown",
        "reason": reason or "",
    }


def _normalize_result(claim_key: str, raw: dict) -> dict:
    """Coerce a closed-book judge response into the report contract.

    `claim_id` is forced to the real key, since a per-claim call gives the model no way to
    know it beyond the echo we asked for.
    """
    raw_checks = raw.get("checks") or {}
    checks = {name: _read_check(raw_checks, name) for name in CLOSED_BOOK_CHECKS}
    return _finalize(claim_key, checks)


def _error_result(claim_key: str, message: str) -> dict:
    """Report shape for a claim whose judge call failed outright."""
    return {
        "claim_id": claim_key,
        "checks": {name: {"status": "unknown", "reason": ""} for name in CLOSED_BOOK_CHECKS},
        "verdict": "error",
        "issues": [message],
    }


async def validate_claim(
    claim_key: str,
    entry: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Judge one claim_filtered.json entry. One LLM call, one claim.

    The prompt carries the claim_type vocabulary the extraction step was given, so the
    `claim_type` check audits the label against the same list that produced it.

    Never raises: an API or parse failure is recorded as a `verdict: "error"` report so a
    single bad claim cannot lose a whole paper's worth of verdicts.
    """
    template = load_prompt_with_claim_types("validate_claims.txt")
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


def _head(claim: str) -> str:
    """The claim's contextual-metadata head — everything up to and including "showed".

    Every claim is required to open with one (extract_claims_pdf.txt), but a malformed
    claim that lacks it falls back to the whole sentence rather than being dropped from
    the audit.
    """
    marker = "showed"
    index = claim.find(marker)
    return claim[: index + len(marker)].strip() if index != -1 else claim.strip()


def metadata_entries(claims: dict, claim_keys: list[str]) -> list[dict]:
    """Group claims by head sentence into the metadata pass's input entries.

    The head *is* the metadata being audited — assay, tissue, N, cohort, age, day schedule
    are all stated in it verbatim. Claims sharing a head therefore share everything this
    pass looks at, so the head text is sent once with the keys that carry it, and the judge
    returns a verdict per key.
    """
    entries: dict[str, dict] = {}
    for key in claim_keys:
        entry = claims.get(key) or {}
        head = _head(entry.get("claim", ""))
        entries.setdefault(head, {"head": head, "claims": []})["claims"].append(key)
    return list(entries.values())


async def validate_metadata_batch(
    entries: list[dict],
    pdf_bytes: bytes,
    filename: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict[str, dict]:
    """Audit one batch of head entries against the PDF. One call.

    Never raises: a failed batch returns `{}`, leaving those claims' metadata check
    `unknown` rather than losing the closed-book verdicts already collected for them.
    """
    template = _load_prompt("validate_claim_metadata.txt")
    prompt = template.replace("{claims}", json.dumps(entries, indent=2, ensure_ascii=False))

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        _pdf_file_content(pdf_bytes, filename),
                        {
                            "type": "text",
                            "text": "Audit the contextual metadata of these claims against this paper as instructed.",
                        },
                    ],
                },
            ],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        parsed = json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 - a failed batch degrades to "unknown", not a crash
        logger.warning("metadata validation batch failed - %s", exc)
        return {}

    if not isinstance(parsed, dict):
        logger.warning("metadata judge returned %s, not an object", type(parsed).__name__)
        return {}

    return {
        key: _read_check(parsed, key)
        for key in (k for entry in entries for k in entry["claims"])
        if key in parsed
    }



async def validate_metadata(
    claims: dict,
    claim_keys: list[str],
    pdf_bytes: bytes,
    filename: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    batch_size: int = _METADATA_BATCH_SIZE,
) -> dict[str, dict]:
    """Audit the contextual metadata of every claim against the paper.

    Costs ceil(distinct heads / batch_size) calls, each carrying the PDF — far fewer than
    one per claim, since heads repeat heavily within a paper.
    """
    entries = metadata_entries(claims, claim_keys)
    batches = [entries[i : i + batch_size] for i in range(0, len(entries), batch_size)]
    print(
        f"Validating metadata for {len(claim_keys)} claims "
        f"({len(entries)} distinct heads, {len(batches)} calls)..."
    )

    results = await asyncio.gather(
        *(validate_metadata_batch(batch, pdf_bytes, filename, client, model) for batch in batches)
    )

    merged: dict[str, dict] = {}
    for batch_result in results:
        merged.update(batch_result)
    return merged


def merge_metadata(results: list[dict], metadata_by_claim: dict[str, dict]) -> list[dict]:
    """Fold metadata verdicts into closed-book results, re-deriving verdict and issues.

    A claim the metadata pass never answered for gets `unknown` — the same treatment as a
    closed-book check the judge skipped, and for the same reason: it was not cleared.
    """
    merged: list[dict] = []
    for result in results:
        checks = dict(result.get("checks") or {})
        checks[METADATA_CHECK] = metadata_by_claim.get(
            result["claim_id"], {"status": "unknown", "reason": ""}
        )
        if result.get("verdict") == "error":
            # The closed-book call itself failed; a metadata verdict does not redeem it.
            merged.append({**result, "checks": checks})
            continue
        merged.append(_finalize(result["claim_id"], checks))
    return merged


async def validate_claims_file(
    claims: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    limit: int | None = None,
    pdf_bytes: bytes | None = None,
    filename: str = "paper.pdf",
) -> list[dict]:
    """Judge every claim_* entry in a claim_filtered.json mapping.

    The closed-book pass runs one claim per call — a whole-paper batch would split the
    judge's attention across claims and dilute the per-claim checks. The metadata pass then
    runs only if `pdf_bytes` is given; without it the report carries the closed-book checks
    alone and says so, rather than implying metadata was cleared.
    """
    claim_keys = [k for k in claims if k.startswith("claim_")]
    if limit is not None:
        claim_keys = claim_keys[:limit]

    results: list[dict] = []
    print(f"Validating {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        result = await validate_claim(key, claims[key], client, model)
        results.append(result)
        detail = f" ({', '.join(result['issues'])})" if result["issues"] else ""
        print(f"  [{i}/{len(claim_keys)}] {key}: {result['verdict']}{detail}")

    if pdf_bytes is None:
        return results

    metadata_by_claim = await validate_metadata(
        claims, claim_keys, pdf_bytes, filename, client, model
    )
    results = merge_metadata(results, metadata_by_claim)
    for result in results:
        check = result["checks"][METADATA_CHECK]
        if check["status"] != "pass":
            print(f"  {result['claim_id']} metadata: {check['status']} - {check['reason']}")
    return results


def build_summary(results: list[dict]) -> dict:
    """Aggregate verdicts plus a per-check fail tally across all claims.

    The tally is the actionable part: a check failing across many claims points at a line
    in extract_claims_pdf.txt or classify_groups.txt to fix, rather than at one bad claim.

    `metadata` is tallied only when the metadata pass actually ran — a zero on a check that
    never ran would read like a clean bill of health.
    """
    metadata_checked = any(METADATA_CHECK in (r.get("checks") or {}) for r in results)
    names = CHECK_NAMES if metadata_checked else CLOSED_BOOK_CHECKS

    fail_counts = {name: 0 for name in names}
    for result in results:
        for name, check in (result.get("checks") or {}).items():
            if name in fail_counts and check.get("status") == "fail":
                fail_counts[name] += 1

    verdicts = [r.get("verdict") for r in results]
    return {
        "total": len(results),
        "accurate": verdicts.count("accurate"),
        "needs_revision": verdicts.count("needs_revision"),
        "inconclusive": verdicts.count("inconclusive"),
        "errors": verdicts.count("error"),
        "metadata_checked": metadata_checked,
        "fail_counts": fail_counts,
    }


def build_report(results: list[dict]) -> dict:
    """Assemble the claims_validation.json payload."""
    return {"summary": build_summary(results), "results": results}
