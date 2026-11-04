"""Repair the fields an assay verification pass refused to support.

Input is the triple a verification run leaves behind: the `assays.json` an extraction
produced, the `assays_verification.json` a judge produced from it, and the sentence-numbered
text of the same paper. Output is a corrected registry plus a per-field record of what was
changed and why.

**Corrections are blind.** The correcting model is never shown the disputed value or the
verifier's complaint — it is asked what the paper says for that field and answers from the
text alone. Showing it the rejected string would anchor it: a model handed
`sample_type: "PBMCs" — CONTRADICTED` edits that string, where a model asked "what specimen
does the text state" reads the paper. The difference shows up most in the answer
that matters: `null`. `sample_type` is the field extraction invents most readily, so
"the paper does not say" is very often the right repair, and an anchored corrector almost
never produces it -- it supplies another plausible guess.

Because the correction is blind, disagreement becomes a three-way vote rather than a
deference. The blind answer either matches the original (the verifier was wrong, and the
value is REAFFIRMED), differs from it (REPLACED), or comes back null (CLEARED).

Only fields the verifier actually flagged are re-extracted. A field it marked SUPPORTED is
not reopened -- re-asking it buys nothing and risks losing a value that was already correct.

`assay_identity` is deliberately not correctable. If the judge says the technique was never
performed, or is an endpoint rather than a procedure, the repair is to drop the entry, not to
rename it -- that is a human's call, and it is reported rather than acted on.

The registry on disk is never modified. The corrected registry is a new file, and every
change carries its provenance, so an extracted value and a repaired one stay distinguishable.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.agent.assay_verifier import (
    CONTRADICTED,
    MAX_CONCURRENT_CALLS,
    REJECT,
    SUPPORTED,
    check_quote_verbatim,
    get_name,
    has_sentence_markers,
    name_field,
)
from app.agent import assay_trace
from app.agent.assay_extractor import paper_cache_key
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.config import settings

logger = logging.getLogger(__name__)

REAFFIRMED = "REAFFIRMED"
REPLACED = "REPLACED"
CLEARED = "CLEARED"
UNCHANGED = "UNCHANGED"

#: What to ask for each correctable field. The wording mirrors the extraction contract in
#: apps/api/app/prompts/extract_assays.txt, so a blind re-read is held to the same
#: standard as the original pass rather than a looser one.
_QUESTIONS = {
    "sample_type": (
        "What tissue or specimen does the paper state THIS assay was performed on (e.g. whole "
        "blood, PBMCs, serum, plasma)? Answer null if the paper never states the specimen for "
        "this assay -- do not answer with the study's main specimen unless the text ties it to "
        "this assay."
    ),
    "readouts": (
        "What does the paper state THIS assay measures, detects, profiles, or evaluates? "
        "Summarise the measured quantities in your own words -- what the instrument measured, "
        "not what the authors concluded from it. Answer null if the paper never says."
    ),
    "aliases": (
        "What other exact wordings does the paper use for THIS assay itself? Set `value` to a "
        "JSON list of strings, each appearing verbatim in the source text -- the list goes "
        "inside the `value` field, do not return it on its own. An instrument, chip, or kit "
        "name is NOT an alias -- exclude product names, except a brand name that is the "
        "field's standard name for a technique (Luminex, CyTOF, ELISpot, TaqMan). Set `value` "
        "to an empty list if the paper only ever uses one wording."
    ),
    "evidence": (
        "Which sentence or sentences establish that THIS assay was actually performed in this "
        "study? Answer with a short quote copied verbatim from those sentences -- not a "
        "paraphrase. Prefer the Methods sentence that describes the procedure over an abstract "
        "or Results sentence that only reports its outcome. Do not quote a sentence that cites "
        "someone else's use of the technique."
    ),
}

#: Verifier field names map onto the question groups above. `aliases[0]`, `aliases[3]` and so
#: on are one question. `evidence.sentence_ids` is kept in the evidence group for an older
#: verification report on disk that still carries such a verdict; a current one cannot, because
#: the ids are derived rather than proposed.
_ALIAS_PREFIX = "aliases["
_EVIDENCE_SUFFIXES = (".quote", ".sentence_ids")

#: Reported, never corrected -- see the module docstring.
_IDENTITY_FIELDS = ("name_in_paper", "original_name")


def field_group(field_name: str) -> str | None:
    """Map one verifier field name onto the question that would re-extract it.

    Returns None for a field no blind question can repair: the assay's identity, and
    anything a future schema adds that this module has no question for.
    """
    if field_name in _IDENTITY_FIELDS:
        return None
    if field_name.startswith(_ALIAS_PREFIX):
        return "aliases"
    if field_name.endswith(_EVIDENCE_SUFFIXES):
        return "evidence"
    return field_name if field_name in _QUESTIONS else None


def flagged_groups(result: dict) -> list[str]:
    """The question groups this assay's verdicts call for, in a stable order.

    Driven by *field* verdicts rather than the record verdict, because the record verdict
    cannot see them: assay_verifier.derive_record_verdict only lets CONTRADICTED and
    NOT_REPORTED pull a record below ACCEPT, so an entry can read ACCEPT while carrying
    NOT_SUPPORTED fields. Triggering on the record would skip exactly those.
    """
    groups: list[str] = []
    for verification in result.get("field_verifications") or []:
        if verification.get("verdict") == SUPPORTED:
            continue
        group = field_group(verification.get("field_name", ""))
        if group and group not in groups:
            groups.append(group)
    return [g for g in _QUESTIONS if g in groups]


def flagged_alias_indices(result: dict) -> set[int]:
    """Which `aliases[i]` positions the verifier declined to support.

    Aliases are the one group where the question is asked once but the verdicts are per
    element, so a blind answer must not be allowed to prune positions the judge supported:
    the blind read phrases things its own way, and "flagged fields only" means an alias it
    happens to word differently is not this pass's to remove.
    """
    indices: set[int] = set()
    for verification in result.get("field_verifications") or []:
        name = verification.get("field_name", "")
        if verification.get("verdict") == SUPPORTED or not name.startswith(_ALIAS_PREFIX):
            continue
        try:
            indices.add(int(name[len(_ALIAS_PREFIX):].rstrip("]")))
        except ValueError:
            continue
    return indices


def uncorrectable_flags(result: dict) -> list[dict]:
    """Non-SUPPORTED verdicts no blind question can repair, for reporting to a human."""
    return [
        {"field_name": v.get("field_name", ""), "verdict": v.get("verdict"),
         "reason": v.get("reason", "")}
        for v in (result.get("field_verifications") or [])
        if v.get("verdict") != SUPPORTED and not field_group(v.get("field_name", ""))
    ]


def _locator(entry: dict, group: str) -> str:
    """A line identifying which assay is meant, without leaking the disputed value.

    The evidence quote is the natural locator -- except when evidence is what is being
    re-extracted, where quoting it back would defeat the point of asking blind.
    """
    if group == "evidence":
        return ""
    quote = ((entry.get("evidence") or entry.get("evidence_location") or {}).get("quote") or "")
    return f"A sentence from the paper describing it: \"{quote}\"" if quote else ""


def build_prompt(entry: dict, group: str, source_text: str, paper_title: str) -> str:
    """Render correct_assay_field.txt for one assay and one question."""
    return (
        _load_prompt("correct_assay_field.txt")
        .replace("{assay_name}", get_name("", entry) or "(unnamed)")
        .replace("{locator}", _locator(entry, group))
        .replace("{question}", _QUESTIONS[group])
        .replace("{paper_title}", paper_title)
        .replace("{source_text}", source_text)
    )


def _normalize(value: object) -> object:
    """Fold a value to the form two answers must share to count as the same answer."""
    if isinstance(value, str):
        return " ".join(value.split()).strip().lower()
    if isinstance(value, list):
        return sorted(_normalize(v) for v in value if isinstance(v, str))
    return value


def _current(entry: dict, group: str) -> object:
    """The entry's existing value for a question group."""
    if group == "evidence":
        evidence = entry.get("evidence") or entry.get("evidence_location") or {}
        return evidence.get("quote")
    return entry.get(group)


def decide(current: object, blind: object) -> str:
    """Classify a blind answer against the value already on file."""
    empty_current, empty_blind = current in (None, "", []), blind in (None, "", [])
    if empty_current and empty_blind:
        # Nothing was proposed and nothing was found: there is no value to affirm.
        return UNCHANGED
    if _normalize(current) == _normalize(blind):
        return REAFFIRMED
    return CLEARED if empty_blind else REPLACED


def apply_correction(entry: dict, group: str, blind: object, source_text: str,
                     flagged_aliases: set[int] | None = None) -> dict:
    """Write one blind answer into a copy of the entry, returning what it did.

    A REPLACED evidence quote is re-checked verbatim before it lands. The correcting model
    was told to copy rather than paraphrase, and check_quote_verbatim settles that for free;
    a quote that fails is rejected outright rather than trading one bad quote for another.
    """
    # Evidence is compared quote to quote. _current reads the quote string while the blind
    # answer is {"quote", "sentence_ids"}, and comparing the two directly meant an identical
    # re-extraction was never REAFFIRMED and an empty one never CLEARED.
    compared = (blind or {}).get("quote") if group == "evidence" and isinstance(blind, dict) \
        else blind
    action = decide(_current(entry, group), compared)
    record = {"field": group, "action": action,
              "previous": _current(entry, group), "blind_answer": blind}

    if action in (REAFFIRMED, UNCHANGED):
        return record

    if group == "evidence":
        if action == CLEARED:
            # An assay with no quotable support is a finding for a human, not something to
            # silently blank -- evidence is the entry's only traceability.
            record["action"] = UNCHANGED
            record["note"] = "no quotable evidence found; left as-is for review"
            return record
        quote, ids = (blind or {}).get("quote"), (blind or {}).get("sentence_ids") or []
        probe = {"evidence": {"quote": quote, "sentence_ids": ids}}
        check = check_quote_verbatim(probe, source_text)
        if check["status"] == "misattributed" and (
                check["located_ids"] or not has_sentence_markers(source_text)):
            # Verbatim, cited wrongly. The ids the model wrote are not trusted -- they are
            # replaced by the sentences the quote was actually found in, which is free and
            # exact. On a source with no markers that is [], which is the only honest answer.
            ids = check["located_ids"]
            record["note"] = f"sentence_ids set to where the quote was found: {check['detail']}"
        elif check["status"] != "found":
            record["action"] = UNCHANGED
            record["note"] = f"replacement quote rejected: {check['detail']}"
            return record
        evidence_key = "evidence" if "evidence" in entry else (
            "evidence_location" if "evidence_location" in entry else "evidence")
        evidence = dict(entry.get(evidence_key) or {})
        evidence["quote"], evidence["sentence_ids"] = quote, ids
        entry[evidence_key] = evidence
        return record

    if group == "aliases":
        # Only a FLAGGED position may be dropped, and only when the blind read did not
        # confirm it. An alias the judge supported is untouchable here even if the blind
        # answer worded it differently -- pruning those was a measured regression, losing
        # "fluorescence-activated cell sorting (FACS) measurements" on SDY1119. Adding
        # aliases the blind read found is likewise out of scope: that is expansion.
        flagged = flagged_aliases if flagged_aliases is not None else set()
        # A bare string is one alias, not a list of its characters: iterating "FACS" as-is read
        # it as four one-letter aliases and dropped the flagged "FACS" it had just confirmed.
        answered = [blind] if isinstance(blind, str) else (blind if isinstance(blind, list) else [])
        confirmed = {_normalize(a) for a in answered if isinstance(a, str)}
        previous = entry.get("aliases") or []
        kept = [a for i, a in enumerate(previous)
                if i not in flagged or _normalize(a) in confirmed]
        record["action"] = REAFFIRMED if kept == previous else REPLACED
        record["previous"] = previous
        record["dropped"] = [a for a in previous if a not in kept]
        entry["aliases"] = kept
        return record

    entry[group] = None if action == CLEARED else blind
    return record


async def correct_field(
    entry: dict,
    group: str,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    assay_key: str = "",
) -> tuple[object, str | None]:
    """Ask the paper what this field says. One LLM call. Returns (value, error).

    `assay_key` only labels the reply in the run's trace (assay_trace); the prompt never sees it.
    """
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user",
                       "content": build_prompt(entry, group, source_text, paper_title)}],
            temperature=0,
            prompt_cache_key=paper_cache_key(source_text),
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        assay_trace.record("correct", assay_key, field=group, reply=raw,
                           **assay_trace.usage_kw(resp))
        parsed = json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - one bad field must not cost the whole paper
        logger.warning("blind re-extraction of %s failed - %s", group, exc)
        assay_trace.record("correct", assay_key, field=group, error=f"{type(exc).__name__}: {exc}")
        return None, f"{type(exc).__name__}: {exc}"

    # An empty reply is a failed call, not an answer. Read as `{}` it became `value: None`,
    # which decide() scores as CLEARED -- a specimen the paper states, wiped because one call
    # returned nothing. The verifier draws the same line for the same reason.
    if parsed is None:
        return None, "corrector returned an empty reply"

    # A bare list is the aliases answer, unwrapped. The prompt asks for {"value": ...} and the
    # aliases question then says "a JSON list of strings", so a model that follows the question
    # literally returns the list itself -- and rejecting it discarded a call already paid for.
    # Measured across every corrections file on disk: 12 of 41 alias re-extractions (29%), in 12
    # separate papers, and every single ERROR in the corpus. Those entries kept the unsupported
    # aliases the verifier had flagged, because the one pass that repairs them threw its answer
    # away.
    #
    # Aliases only. `evidence` must keep failing here: its sentence_ids come from a sibling key,
    # not from `value`, so a coerced bare answer would yield {"quote": None, "sentence_ids": []}
    # -> CLEARED -> remapped to UNCHANGED, which reads as "checked, nothing to change" when
    # nothing was checked. A bare list for a scalar field is not an answer at all.
    if isinstance(parsed, list) and group == "aliases":
        parsed = {"value": parsed}

    if not isinstance(parsed, dict):
        return None, f"corrector returned {type(parsed).__name__}, not an object"

    value = parsed.get("value")
    if group == "evidence":
        value = {"quote": value if isinstance(value, str) else None,
                 "sentence_ids": [str(s) for s in (parsed.get("sentence_ids") or [])]}
    return value, None


async def correct_registry(
    assays: dict,
    verification: dict,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    max_concurrency: int = MAX_CONCURRENT_CALLS,
) -> tuple[dict, list[dict]]:
    """Re-extract every flagged field across a registry. One call per flagged field.

    The calls run concurrently, bounded by `max_concurrency`, and every one of them reads the
    entry as the extraction left it -- see the comment on the plan below.

    Returns (corrected registry, per-assay correction records). The input registry is not
    mutated -- entries are copied before anything is written to them.
    """
    by_id = {r.get("assay_id"): r for r in (verification.get("results") or [])}
    entries = {key: json.loads(json.dumps(original))  # deep copy; entries nest evidence
               for key, original in assays.items()}
    plan = [(key, group) for key in assays for group in flagged_groups(by_id.get(key, {}))]

    print(f"{len(plan)} flagged field(s) to re-extract across {len(assays)} assay(s), "
          f"up to {max(1, max_concurrency)} at a time...")

    # Every call is asked against the *unedited* entry, and nothing is written until they
    # have all come back. That is what makes them safe to run at once, and it also pins a
    # sequencing the old nested loop left to chance: `_locator` reads the evidence quote, so
    # a repaired evidence field could otherwise change the prompt of a field corrected after
    # it. `_QUESTIONS` happens to order evidence last, so this preserves today's behaviour
    # rather than changing it -- but it no longer depends on that ordering holding.
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _ask(key: str, group: str) -> tuple[object, str | None]:
        async with semaphore:
            return await correct_field(entries[key], group, source_text, paper_title,
                                       client, model, assay_key=key)

    # First call alone, the rest together: every prompt opens with the same template and full
    # paper, which OpenAI serves from its prefix cache only once one call with that prefix has
    # completed (assay_verifier.verify_registry has the reasoning).
    replies: list[tuple[object, str | None]] = []
    if plan:
        replies.append(await _ask(*plan[0]))
        replies.extend(await asyncio.gather(*(_ask(k, g) for k, g in plan[1:])))
    answers = dict(zip(plan, replies))

    # Applied in registry order, one assay at a time, so the written entry and the printed
    # log are deterministic no matter how the calls above interleaved.
    corrected: dict = {}
    records: list[dict] = []
    for key, original in assays.items():
        entry = entries[key]
        result = by_id.get(key, {})
        changes: list[dict] = []

        for group in flagged_groups(result):
            blind, error = answers[(key, group)]
            if error:
                changes.append({"field": group, "action": "ERROR", "error": error})
                print(f"  {key} / {group}: ERROR")
                continue
            change = apply_correction(entry, group, blind, source_text,
                                      flagged_alias_indices(result))
            changes.append(change)
            print(f"  {key} / {group}: {change['action']}")

        corrected[key] = entry
        if changes or result:
            records.append({
                "assay_id": key,
                "assay_name": get_name(key, original),
                "record_verdict": result.get("record_verdict"),
                "corrections": changes,
                "reported_not_corrected": uncorrectable_flags(result),
            })
    return corrected, records


def build_report(records: list[dict]) -> dict:
    """Assemble the assays_corrections.json payload."""
    actions: dict[str, int] = {}
    for record in records:
        for change in record["corrections"]:
            actions[change["action"]] = actions.get(change["action"], 0) + 1
    return {
        "summary": {
            "assays": len(records),
            "fields_re_extracted": sum(len(r["corrections"]) for r in records),
            "actions": actions,
            "reported_not_corrected": sum(
                len(r["reported_not_corrected"]) for r in records
            ),
        },
        "results": records,
    }


# ── Rejected assays: removal, not repair ─────────────────────────────────────

def rejected_assays(verification: dict) -> dict[str, str]:
    """Assay id -> why the judge rejected it.

    A REJECT means the entry should not exist: the technique was never performed, or the
    name is an endpoint or a computational analysis rather than a procedure. That is not
    repairable by re-extracting a field, which is why these never reach correct_field.
    """
    rejected: dict[str, str] = {}
    for result in verification.get("results") or []:
        identity = result.get("assay_identity_verdict")
        if result.get("record_verdict") != REJECT and identity != CONTRADICTED:
            continue
        reason = next(
            (v.get("reason") for v in (result.get("field_verifications") or [])
             if v.get("field_name") in _IDENTITY_FIELDS and v.get("reason")),
            "",
        )
        rejected[result.get("assay_id", "")] = reason or "assay identity rejected"
    return rejected


def drop_rejected(assays: dict, verification: dict) -> tuple[dict, dict]:
    """Split a registry into (kept, dropped) on the judge's record verdicts.

    Modelled on claim_abstraction_v5.apply_verdicts, whose rule is the one that applies here:
    **removal is mechanical, rewriting is not.** A claim verdicted `demote_to_not_a_claim` is
    moved out; one needing a rewrite stays and carries a flag. An assay that was never
    performed is the removal case, and it is the only one this function acts on.

    `dropped` maps id -> {"entry": ..., "reason": ...}. The entry is carried along rather than
    discarded: a REJECT is one model's judgement, and a wrongly-rejected assay has to be
    recoverable from what we wrote down. Neither input is mutated.
    """
    reasons = rejected_assays(verification or {})
    kept, dropped = {}, {}
    for key, entry in (assays or {}).items():
        if key in reasons:
            dropped[key] = {"entry": entry, "reason": reasons[key]}
        else:
            kept[key] = entry
    return kept, dropped
