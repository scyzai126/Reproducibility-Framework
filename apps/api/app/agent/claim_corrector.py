"""Repair the claim fields a verification pass refused to support — the claim-side twin of
app.agent.assay_corrector. Prompt: prompts/claims_v9/correct_claim_field.txt.

**Corrections are blind.** The correcting model is never shown the disputed value or the
verifier's complaint; it is asked what the paper says and answers from the text alone. The
blind answer then either matches the value on file (REAFFIRMED — the verifier was wrong),
differs (REPLACED), or comes back null (CLEARED). A field with nothing on file and nothing
found is UNCHANGED.

Only flagged fields are re-asked. A field the verifier SUPPORTED is never reopened.

What each group's answer does:
  finding      REPLACED -> the claim sentence keeps its head and gets the new finding;
               CLEARED  -> the paper states no such finding: the claim moves to not_a_claim
  claim_type   REPLACED -> new type (it may now fall outside claim_filter's kept set)
  polarity     REPLACED -> new polarity
  assay,       REPLACED -> the field, and the old wording inside the head, are rewritten;
  sample_type  CLEARED  -> the field is nulled (the head is left as written, and reported)
  sources      REPLACED -> the flagged quotes are replaced by one verbatim-checked quote;
               CLEARED  -> left as-is for a human: sources are the claim's only traceability
  head_metadata          never corrected, only reported, like an assay's identity

Every call reads the claim as extraction left it, and nothing is written until all have
returned, so the calls can run concurrently and the result does not depend on their order.
"""

import asyncio
import json
import logging
import re

from openai import AsyncOpenAI

from app.agent.assay_verifier import MAX_CONCURRENT_CALLS, SUPPORTED, check_quote_verbatim
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.agent.claim_verifier import (
    POLARITIES,
    claim_type_vocabulary,
    split_head,
    text_sources,
)
from app.agent.jats_parser import CAPTIONS, sentence_sections
from app.config import settings

logger = logging.getLogger(__name__)

CORRECT_PROMPT = "claims_v9/correct_claim_field.txt"

REAFFIRMED = "REAFFIRMED"
REPLACED = "REPLACED"
CLEARED = "CLEARED"
UNCHANGED = "UNCHANGED"

_QUESTIONS = {
    "finding": (
        "What finding do the authors state, in words, in the sentences quoted above? Write it as "
        "the clause that would follow \"showed\" in a sentence such as \"ELISA analysis of serum "
        "showed ...\": the measured quantity, the direction or the absence of an effect, the "
        "groups or reference compared, and the timepoint, each only if the text states it. Answer "
        "null if these sentences state no finding in words."
    ),
    "claim_type": (
        "Which ONE claim_type from this vocabulary names the operation a verifier would run to "
        "check this finding: {vocabulary}? Judge the operation, not whether the finding is "
        "positive or negative: a stated absence keeps the type of the operation. A change within "
        "one group across timepoints is induction_vs_reference, not group_difference. Answer with "
        "the type name only."
    ),
    "polarity": (
        "Do the quoted sentences report this effect as present, or report its absence (\"no "
        "significant difference\", \"did not correlate\", \"was not\")? Answer exactly \"affirm\" "
        "for present or \"null\" for absent."
    ),
    "assay": (
        "Which wet-lab measurement technique produced the data behind this finding? Answer with the "
        "paper's own most specific name for the technique (Methods may be used). Answer null if the "
        "paper never ties a technique to this finding."
    ),
    "sample_type": (
        "What tissue or specimen was measured to produce this finding (e.g. PBMCs, serum, plasma, "
        "whole blood)? Answer in the paper's own wording (Methods may be used). Answer null if the "
        "paper never states the specimen for this measurement."
    ),
    "sources": (
        "Which sentence in the Results text or a figure/table legend states this finding? Set "
        "`value` to a quote copied verbatim from that sentence — not a paraphrase — and list its "
        "sentence id. Answer null if no sentence states it."
    ),
}

#: Fields the verifier can flag that no blind question repairs. Reported for a human.
_REPORT_ONLY = ("head_metadata", "head")

_SOURCE_FIELD = re.compile(r"^sources\[(\d+)\]\.quote$")


def field_group(field_name: str) -> str | None:
    """Map a verifier field name onto the question that re-extracts it (None = report only)."""
    if _SOURCE_FIELD.match(field_name):
        return "sources"
    return field_name if field_name in _QUESTIONS else None


def flagged_groups(result: dict) -> list[str]:
    """The question groups this claim's field verdicts call for, in a stable order."""
    groups = {
        field_group(v.get("field_name", ""))
        for v in result.get("field_verifications") or []
        if v.get("verdict") != SUPPORTED
    }
    return [g for g in _QUESTIONS if g in groups]


def flagged_source_indices(result: dict) -> list[int]:
    """Which `sources[i]` the verifier declined to support."""
    indices = []
    for v in result.get("field_verifications") or []:
        match = _SOURCE_FIELD.match(v.get("field_name", ""))
        if match and v.get("verdict") != SUPPORTED:
            indices.append(int(match.group(1)))
    return sorted(indices)


def reported_not_corrected(result: dict) -> list[dict]:
    return [
        {"field_name": v.get("field_name"), "verdict": v.get("verdict"), "reason": v.get("reason", "")}
        for v in result.get("field_verifications") or []
        if v.get("verdict") != SUPPORTED and field_group(v.get("field_name", "")) is None
    ]


def _locator(claim: dict, group: str) -> str:
    """Identify the finding without leaking the disputed value.

    The source quotes identify it for every group except `sources` itself, where the quotes are
    what is disputed; the finding identifies it there. The finding is also shown for claim_type
    and polarity, which cannot be answered without knowing what effect is meant — but the
    current type and polarity never are.
    """
    _, finding = split_head(claim.get("claim") or "")
    quotes = "\n".join(f"- \"{s['quote']}\"" for _, s in text_sources(claim))
    if group == "sources":
        return f"The finding, as another reader summarised it: {finding}"
    if group == "finding":
        return f"Sentences from the paper that report it:\n{quotes}"
    if group in ("claim_type", "polarity"):
        return f"The finding: {finding}\n\nSentences from the paper that report it:\n{quotes}"
    return f"Sentences from the paper that report it:\n{quotes}"


def build_prompt(claim: dict, group: str, source_text: str, paper_title: str) -> str:
    question = _QUESTIONS[group]
    if group == "claim_type":
        question = question.replace("{vocabulary}", ", ".join(claim_type_vocabulary()))
    return (
        _load_prompt(CORRECT_PROMPT)
        .replace("{paper_title}", paper_title)
        .replace("{source_text}", source_text)
        .replace("{locator}", _locator(claim, group))
        .replace("{question}", question)
    )


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split()).strip().lower().rstrip(".")
    return value


def current_value(claim: dict, group: str, source_indices: list[int] | None = None) -> object:
    """The value on file for a question group."""
    if group == "finding":
        return split_head(claim.get("claim") or "")[1]
    if group == "sources":
        sources = claim.get("sources") or []
        picked = [sources[i].get("quote") for i in (source_indices or []) if i < len(sources)]
        return picked[0] if len(picked) == 1 else (picked or None)
    return claim.get(group)


def decide(current: object, blind: object) -> str:
    empty_current, empty_blind = current in (None, "", []), blind in (None, "", [])
    if empty_current and empty_blind:
        return UNCHANGED
    if _normalize(current) == _normalize(blind):
        return REAFFIRMED
    return CLEARED if empty_blind else REPLACED


def apply_correction(claim: dict, group: str, blind: object, sentence_ids: list[str],
                     source_text: str, source_indices: list[int] | None = None) -> dict:
    """Write one blind answer into `claim` (a copy owned by the caller); return what it did."""
    previous = current_value(claim, group, source_indices)
    action = decide(previous, blind)
    record = {"field": group, "action": action, "previous": previous, "blind_answer": blind}
    if action in (REAFFIRMED, UNCHANGED):
        return record

    if group == "finding":
        if action == REPLACED:
            head, _ = split_head(claim.get("claim") or "")
            finding = str(blind).strip()
            if finding.lower().startswith("showed "):
                finding = finding[len("showed "):]
            claim["claim"] = f"{head} {finding}".strip() if head else finding
        return record  # CLEARED is acted on by the caller: the claim leaves the set

    if group == "claim_type":
        if blind not in claim_type_vocabulary():
            record.update(action=UNCHANGED, note=f"blind answer {blind!r} is not in the vocabulary")
            return record
        claim["claim_type"] = blind
        return record

    if group == "polarity":
        if blind not in POLARITIES:
            record.update(action=UNCHANGED, note=f"blind answer {blind!r} is not affirm/null")
            return record
        claim["polarity"] = blind
        return record

    if group in ("assay", "sample_type"):
        old = claim.get(group)
        claim[group] = None if action == CLEARED else blind
        if action == REPLACED and isinstance(old, str) and old:
            head, finding = split_head(claim.get("claim") or "")
            if old.lower() in head.lower():
                new_head = re.sub(re.escape(old), str(blind), head, count=1, flags=re.IGNORECASE)
                claim["claim"] = f"{new_head} {finding}".strip()
            else:
                record["note"] = "the old wording is not in the head; head left as written"
        elif action == CLEARED:
            record["note"] = "field cleared; head left as written for review"
        return record

    if group == "sources":
        if action == CLEARED:
            record.update(action=UNCHANGED, note="no quotable sentence found; left for review")
            return record
        check = check_quote_verbatim({"evidence": {"quote": blind, "sentence_ids": sentence_ids}},
                                     source_text)
        if check["status"] != "found":
            record.update(action=UNCHANGED, note=f"replacement quote rejected: {check['detail']}")
            return record
        sections = sentence_sections(source_text)
        bucket = next((sections.get(s) for s in sentence_ids if s in sections), None)
        section = "Results" if bucket in (None, "results") else (
            "caption" if bucket == CAPTIONS else bucket.capitalize())
        drop = set(source_indices or [])
        kept = [s for i, s in enumerate(claim.get("sources") or []) if i not in drop]
        claim["sources"] = [{"type": "text", "section": section, "quote": blind}] + kept
        return record

    return record


async def correct_field(claim: dict, group: str, source_text: str, paper_title: str,
                        client: AsyncOpenAI, model: str = settings.OPENAI_MODEL,
                        tracker=None) -> tuple[object, list[str], str | None]:
    """Ask the paper one question. Returns (value, sentence_ids, error)."""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user",
                       "content": build_prompt(claim, group, source_text, paper_title)}],
            temperature=0,
        )
        if tracker is not None:
            tracker.record("correct", getattr(resp, "usage", None))
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        parsed = json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 - one bad field must not cost the whole paper
        logger.warning("blind re-extraction of %s failed - %s", group, exc)
        return None, [], f"{type(exc).__name__}: {exc}"
    if not isinstance(parsed, dict):
        return None, [], f"corrector returned {type(parsed).__name__}, not an object"
    value = parsed.get("value")
    if isinstance(value, str):
        value = value.strip() or None
    return value, [str(s) for s in (parsed.get("sentence_ids") or [])], None


async def correct_claims(
    claims: dict,
    results: list[dict],
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    max_concurrency: int = MAX_CONCURRENT_CALLS,
    tracker=None,
) -> tuple[dict, list[dict], list[dict]]:
    """Re-extract every flagged field. One call per flagged group.

    Returns (corrected claims, correction records, not_a_claim entries for CLEARED findings).
    The input claims are not mutated.
    """
    by_id = {r.get("claim_id"): r for r in results}
    entries = {k: json.loads(json.dumps(v)) for k, v in claims.items()}
    plan = [(k, g) for k in claims for g in flagged_groups(by_id.get(k, {}))]
    print(f"{len(plan)} flagged field(s) to re-extract across {len(claims)} claim(s)...")

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _ask(key: str, group: str):
        async with semaphore:
            return await correct_field(claims[key], group, source_text, paper_title,
                                       client, model, tracker)

    answers = dict(zip(plan, await asyncio.gather(*(_ask(k, g) for k, g in plan))))

    corrected: dict = {}
    records: list[dict] = []
    cleared: list[dict] = []
    for key, original in claims.items():
        claim = entries[key]
        result = by_id.get(key, {})
        changes: list[dict] = []
        finding_cleared = False
        for group in flagged_groups(result):
            value, ids, error = answers[(key, group)]
            if error:
                changes.append({"field": group, "action": "ERROR", "error": error})
                print(f"  {key} / {group}: ERROR")
                continue
            change = apply_correction(claim, group, value, ids, source_text,
                                      flagged_source_indices(result))
            changes.append(change)
            print(f"  {key} / {group}: {change['action']}")
            if group == "finding" and change["action"] == CLEARED:
                finding_cleared = True

        if finding_cleared:
            cleared.append({"claim_id": key, "text": original.get("claim", ""),
                            "reason": "not-stated-in-words", "entry": original,
                            "from": "correction"})
        else:
            corrected[key] = claim
        if changes or reported_not_corrected(result):
            records.append({
                "claim_id": key,
                "record_verdict": result.get("record_verdict"),
                "corrections": changes,
                "reported_not_corrected": reported_not_corrected(result),
            })
    return corrected, records, cleared


def build_report(records: list[dict]) -> dict:
    """Assemble claims_corrections.json."""
    actions: dict[str, int] = {}
    for record in records:
        for change in record["corrections"]:
            actions[change["action"]] = actions.get(change["action"], 0) + 1
    return {
        "summary": {
            "claims": len(records),
            "fields_re_extracted": sum(len(r["corrections"]) for r in records),
            "actions": actions,
            "reported_not_corrected": sum(len(r["reported_not_corrected"]) for r in records),
        },
        "results": records,
    }
