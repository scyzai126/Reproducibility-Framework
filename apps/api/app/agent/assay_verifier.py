"""Independently verify an extracted assay registry against the paper it came from.

The input is the `assays.json` an extraction step produced (normally
scripts/run_assay_extract.py) plus the sentence-numbered text of the same paper. The output is a
per-field verdict — SUPPORTED / NOT_SUPPORTED / CONTRADICTED — and a record-level
ACCEPT / REVIEW / REJECT for each assay.

**This verifies; it never corrects.** A wrong `platform` is reported as CONTRADICTED and
left alone: supplying the right value is a different job, and doing it here would make the
verifier an extractor with the extraction still in view. `assays.json` is never rewritten;
verdicts go to their own file, exactly as app.agent.claim_validator does for claims.

Independence is the whole premise, which is why this is an API call and not something the
extracting model does to its own output. The failure being guarded against — a `platform`
or `sample_type` inferred from what the technique usually runs on, an assay named only in
the Introduction — is invisible in the registry, because a fabricated field reads exactly
like an extracted one. A judge that shared the extractor's context would share its reasons.

Two checks run before any money is spent:

  * `check_quote_verbatim` confirms the evidence quote actually appears in the sentences it
    cites. This is a pure string comparison — no API call — and it catches a reconstructed
    or fabricated quote for free.
  * `proposed_fields` decides what there is to verify at all. An entry with no non-null
    field beyond its name costs one call, not zero, because the name still needs judging.

As in claim_validator, the record verdict is *derived* from the field verdicts rather than
taken from the model: a judge that contradicts a field and still returns ACCEPT would
otherwise hide the contradiction. The model's own answer is kept alongside as
`model_record_verdict` so the disagreement stays visible.
"""

import json
import logging
import re
import unicodedata

from openai import AsyncOpenAI

from app.agent.claim_parser import _load_prompt, _strip_fences
from app.config import settings

logger = logging.getLogger(__name__)

#: Field verdicts. NOT_REPORTED is ours, not the model's: a field the judge never answered
#: for has not been cleared, and must not read the same as one it supported.
SUPPORTED = "SUPPORTED"
NOT_SUPPORTED = "NOT_SUPPORTED"
CONTRADICTED = "CONTRADICTED"
NOT_REPORTED = "NOT_REPORTED"

_MODEL_VERDICTS = (SUPPORTED, NOT_SUPPORTED, CONTRADICTED)

ACCEPT = "ACCEPT"
REVIEW = "REVIEW"
REJECT = "REJECT"

#: The `[S<n>] ` markers number_sentences inserts. It used to be mirrored here rather than
#: imported, because it lived in .claude/skills and apps/api must not depend on that; it now
#: lives in app.agent.jats_parser, so there is one copy again. The capturing group is this
#: module's own need -- sentence_index reads the number out of it.
_MARKER = re.compile(r"\[S(\d+)\] ")

#: Typographic quote characters folded to their ASCII form before comparing.
_QUOTE_FOLD = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'",
                             "\u201c": '"', "\u201d": '"', "\u201e": '"',
                             "\u2032": "'", "\u2033": '"'})

#: Registry keys that are structure or removed cruft, not proposed values to verify.
#: `confidence` and `claim_role` are old-schema fields the current skill dropped on purpose.
_NOT_PROPOSED = frozenset({"confidence", "claim_role", "normalized_name",
                           "obi_id", "obi_label", "resource", "obi_confidence"})

#: Name and evidence each moved between schema versions. Older registries on disk use the
#: right-hand spellings, so both are read and reported under whichever the entry carries.
_NAME_KEYS = ("name_in_paper", "original_name")
_EVIDENCE_KEYS = ("evidence", "evidence_location")


def _squash(text: str) -> str:
    """Reduce text to the form a faithful quote and its source must share.

    Three normalizations, each for a real artifact measured across this corpus, which
    together took the false-fabrication count from 36 of 156 entries down to 1:

    * **whitespace, dropped entirely.** The JATS parser *inserts* spaces around inline
      markup, so a faithfully copied "(Figure 4)" meets a source reading "( Figure 4 )".
      Collapsing runs of whitespace does not fix that; ignoring it does, and costs nothing,
      because a fabricated quote differs in its words rather than its spacing.
    * **dashes, dropped.** Papers mix U+2010 HYPHEN, U+2013 EN DASH, U+2014 EM DASH and
      plain U+002D in the same sentence, and a model retyping "real-time RT-PCR" picks the
      ASCII one. Removing them rather than unifying them also absorbs line-break
      hyphenation the parser preserves ("ana-lysed"), where it is the *source* that is
      mangled and the quote that is faithful -- a mismatch the check would otherwise blame
      on the extractor. Four of the six remaining failures were one of these two.
    * **NFKC plus quote folding**, for ligatures, full-width forms, and the curly/straight
      apostrophe split.

    What survives is the sequence of letters, digits and words -- which is what "copied,
    not reconstructed" actually means, and what a fabrication would get wrong."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join("" if unicodedata.category(c) == "Pd" else c for c in text)
    text = text.translate(_QUOTE_FOLD)
    return re.sub(r"\s+", "", text)


def strip_markers(text: str) -> str:
    """Remove every `[S<n>] ` marker, restoring the parser's original text."""
    return _MARKER.sub("", text)


def sentence_index(source_text: str) -> dict[str, str]:
    """Map each `S<n>` id to its sentence text, markers removed.

    A sentence runs from its own marker to the next one, so the span may include a section
    heading that fell between them. That is deliberately generous: this index backs a
    "does the quote appear here" check, where over-inclusion risks missing a fabrication
    and under-inclusion would flag honest quotes as fabricated.
    """
    matches = list(_MARKER.finditer(source_text))
    index: dict[str, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source_text)
        index[f"S{match.group(1)}"] = strip_markers(source_text[match.end():end]).strip()
    return index


def check_source_section(entry: dict, sections: dict[str, str]) -> dict:
    """Confirm `source` agrees with the section the entry's evidence actually sits in.

    The free counterpart to check_quote_verbatim, and the reason `source` is auditable at all.
    The extraction decides whether a technique is established in Methods; `sections` -- from
    jats_parser.sentence_sections -- says where the cited sentences really are. When they
    disagree, either the classification pass mis-read the paper's structure or the evidence
    points at the wrong sentence, and both matter: `source` is what the two-pass design records
    about itself.

    An entry is aligned when `source: "methods"` and at least one cited sentence is in a
    `methods` section, or `source: "results"` and at least one is outside every `methods`
    section. "At least one", not "all": an entry may legitimately quote a Methods sentence and
    a Results sentence together, and only a claim with no support anywhere is wrong.

    Reports; never rewrites. An entry admitted as NEW_ASSAY correctly carries "results", so a
    mismatch is a signal for a human rather than a value to correct automatically.

    Returns `unknown` -- never a mismatch -- when the entry cites no sentence_ids, when its ids
    are absent from the map, or when `source` is missing. Most registries on disk predate both
    fields, and they must pass through quietly, the same concession check_quote_verbatim makes.
    """
    source = entry.get("source")
    if source not in ("methods", "results"):
        return {"status": "unknown", "detail": f"source is {source!r}, nothing to check"}

    ids = [str(s) for s in (get_evidence(entry).get("sentence_ids") or [])]
    if not ids:
        return {"status": "unknown", "detail": "entry cites no sentence_ids"}

    located = {sid: sections[sid] for sid in ids if sid in sections}
    if not located:
        return {"status": "unknown",
                "detail": f"none of {', '.join(ids)} appear in the paper's section map"}

    buckets = sorted(set(located.values()))
    in_methods = "methods" in buckets
    aligned = in_methods if source == "methods" else not all(b == "methods" for b in buckets)

    where = ", ".join(f"{sid} in [{bucket}]" for sid, bucket in located.items())
    if aligned:
        return {"status": "aligned", "detail": f"source {source!r} agrees with {where}"}
    return {
        "status": "mismatch",
        "detail": f"source is {source!r} but its evidence sits in {'/'.join(buckets)} ({where})",
    }


def get_evidence(entry: dict) -> dict:
    """Read the evidence object under whichever key this entry's schema uses."""
    for key in _EVIDENCE_KEYS:
        value = entry.get(key)
        if isinstance(value, dict):
            return value
    return {}


def get_name(key: str, entry: dict) -> str:
    """The assay's name, falling back to the registry key when no name field is present.

    The claims-derived registries on disk carry only `sample_type` and `readouts`, so the
    key is sometimes the only name there is.
    """
    for name_key in _NAME_KEYS:
        value = entry.get(name_key)
        if isinstance(value, str) and value.strip():
            return value
    return key


def name_field(entry: dict) -> str:
    """Which spelling of the name field this entry uses, for reporting verdicts under it."""
    for name_key in _NAME_KEYS:
        if isinstance(entry.get(name_key), str) and entry[name_key].strip():
            return name_key
    return _NAME_KEYS[0]


#: An elision inside a quote: "Expression profiles of 594 genes ... were found to change".
#: Excerpting the middle of a sentence is a quoting convention, not a claim about content,
#: so the fragments are checked individually rather than as one string.
_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|\u2026)\s*")


def _fragments_in_order(quote: str, haystack: str) -> bool:
    """Whether every elided fragment of `quote` appears in `haystack`, in order.

    In order, not merely present: two spans found back-to-front are not a faithful excerpt,
    and accepting them would trade this check's false positive for a false negative. A quote
    with no elision is a single fragment, which reduces to the plain substring test.
    """
    cursor = 0
    for fragment in _ELLIPSIS.split(quote):
        squashed = _squash(fragment)
        if not squashed:
            continue
        found = haystack.find(squashed, cursor)
        if found < 0:
            return False
        cursor = found + len(squashed)
    return True


def check_quote_verbatim(entry: dict, source_text: str) -> dict:
    """Confirm the evidence quote appears in the sentences it cites. No API call.

    The extraction contract says the quote is *copied*, not paraphrased or reconstructed,
    so a quote that is absent from the source is a fabrication rather than a judgement
    call — which is why this returns CONTRADICTED rather than deferring to the model.

    When the entry cites no `sentence_ids` (every registry currently on disk predates that
    field), the search falls back to the whole document. That still catches an invented
    quote; it just cannot catch one lifted from an unrelated part of the paper, which is
    left to the judge.

    A quote that elides its own middle ("A ... B") is checked fragment by fragment, in order:
    excerpting is a quoting convention rather than a fabrication, and comparing the joined
    string instead produced the one false MISSING in a 156-entry corpus survey.
    """
    evidence = get_evidence(entry)
    quote = evidence.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return {"status": "no_quote", "verdict": None, "detail": "entry cites no quote"}

    sentence_ids = [str(s) for s in (evidence.get("sentence_ids") or [])]
    index = sentence_index(source_text)
    unknown = [sid for sid in sentence_ids if sid not in index]

    if sentence_ids and not unknown:
        haystack = _squash(" ".join(index[sid] for sid in sentence_ids))
        scope = f"sentences {', '.join(sentence_ids)}"
    else:
        haystack = _squash(strip_markers(source_text))
        scope = "the whole document" if not sentence_ids else (
            f"the whole document ({', '.join(unknown)} not in the source)"
        )

    if _fragments_in_order(quote, haystack):
        status, detail = "found", f"quote found in {scope}"
    elif _fragments_in_order(quote.rstrip(".,;:"), haystack):
        # Excerpting a clause and closing it with a period the source does not carry is an
        # artifact of quoting, not a claim about content -- the words are still the paper's.
        # Reported, because the contract says copied, but not treated as a fabrication.
        status = "found"
        detail = f"quote found in {scope}, except for trailing punctuation not in the source"
    else:
        status, detail = "missing", f"quote does not appear in {scope}"

    return {
        "status": status,
        "verdict": SUPPORTED if status == "found" else CONTRADICTED,
        "detail": detail,
        "unknown_sentence_ids": unknown,
    }


def proposed_fields(entry: dict) -> list[tuple[str, object]]:
    """Every non-null atomic value the extraction proposed, as (field_name, value).

    Aliases are enumerated individually — one bad alias in a list of five is a specific
    defect, and a single verdict over the whole list cannot say which one. Evidence is
    flattened to its parts for the same reason: the quote and the sentence ids fail
    independently.
    """
    fields: list[tuple[str, object]] = []
    for key, value in entry.items():
        if key in _NOT_PROPOSED or key in _EVIDENCE_KEYS or value in (None, "", []):
            continue
        if key == "aliases" and isinstance(value, list):
            fields += [(f"aliases[{i}]", alias) for i, alias in enumerate(value) if alias]
        else:
            fields.append((key, value))

    evidence_key = next((k for k in _EVIDENCE_KEYS if isinstance(entry.get(k), dict)), None)
    if evidence_key:
        for sub in ("quote", "sentence_ids"):
            value = entry[evidence_key].get(sub)
            if value not in (None, "", []):
                fields.append((f"{evidence_key}.{sub}", value))
    return fields


def _read_verification(raw: dict) -> dict:
    """Coerce one field_verifications item into the report contract."""
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
    """Stand-in for a proposed field the judge never answered for."""
    return {
        "field_name": field_name,
        "proposed_value": value,
        "verdict": NOT_REPORTED,
        "evidence_sentence_ids": [],
        "evidence_text": None,
        "reason": "not reported by the verifier",
    }


def derive_record_verdict(identity_verdict: str, verifications: list[dict]) -> str:
    """Derive ACCEPT / REVIEW / REJECT from the field verdicts.

    Never taken from the model: a verifier that contradicts a field and still returns
    ACCEPT would hide the contradiction, which is the same reason claim_validator._finalize
    derives its verdict rather than trusting one.

    A missing optional detail never reaches REJECT — the extraction contract asks for `null`
    on an unstated field, so absence is compliance, not a defect. But a field the judge
    skipped does reach REVIEW: "predominantly supported" cannot be asserted over a field
    nobody answered for.

    NOT_SUPPORTED reaches REVIEW too, and that is not the absence case above: `proposed_fields`
    never yields a null field, so every NOT_SUPPORTED verdict is about a value the extraction
    actually proposed and the judge then declined to support. Leaving such a record at ACCEPT
    is how a registry reports itself clean while carrying unsupported values — measured on
    SDY1119, which read 4/4 ACCEPT over two unsupported aliases.
    """
    if identity_verdict == CONTRADICTED:
        return REJECT
    verdicts = [v["verdict"] for v in verifications]
    unresolved = {CONTRADICTED, NOT_SUPPORTED, NOT_REPORTED}
    if identity_verdict != SUPPORTED or unresolved.intersection(verdicts):
        return REVIEW
    return ACCEPT


def _normalize_result(
    assay_key: str, entry: dict, raw: dict, quote_check: dict
) -> dict:
    """Build one assay's report from the judge's answer plus the deterministic quote check.

    `assay_id` is forced to the real registry key — a per-assay call gives the model no way
    to know it beyond the echo we asked for.
    """
    by_name = {
        v["field_name"]: v
        for v in (_read_verification(r) for r in (raw.get("field_verifications") or [])
                  if isinstance(r, dict))
    }

    verifications = [
        by_name.get(field, _missing_verification(field, value))
        for field, value in proposed_fields(entry)
    ]

    # The string check outranks the judge on quote verbatimness: it is not an opinion.
    if quote_check["verdict"] is not None:
        evidence_key = next(
            (k for k in _EVIDENCE_KEYS if isinstance(entry.get(k), dict)), _EVIDENCE_KEYS[0]
        )
        for verification in verifications:
            if verification["field_name"] == f"{evidence_key}.quote":
                verification["verdict"] = quote_check["verdict"]
                verification["reason"] = quote_check["detail"]

    identity_key = name_field(entry)
    identity = raw.get("assay_identity_verdict")
    if identity not in _MODEL_VERDICTS:
        # Fall back to the name's own field verdict before giving up on it entirely.
        identity = by_name.get(identity_key, {}).get("verdict", NOT_REPORTED)

    model_verdict = raw.get("record_verdict")
    return {
        "assay_id": assay_key,
        "assay_name": get_name(assay_key, entry),
        "assay_identity_verdict": identity,
        "field_verifications": verifications,
        "quote_check": quote_check,
        "conflict_detected": bool(raw.get("conflict_detected")),
        "record_verdict": derive_record_verdict(identity, verifications),
        "model_record_verdict": model_verdict if model_verdict in (ACCEPT, REVIEW, REJECT) else None,
    }


def _error_result(assay_key: str, entry: dict, quote_check: dict, message: str) -> dict:
    """Report shape for an assay whose verifier call failed outright."""
    return {
        "assay_id": assay_key,
        "assay_name": get_name(assay_key, entry),
        "assay_identity_verdict": NOT_REPORTED,
        "field_verifications": [
            _missing_verification(field, value) for field, value in proposed_fields(entry)
        ],
        "quote_check": quote_check,
        "conflict_detected": False,
        "record_verdict": "ERROR",
        "model_record_verdict": None,
        "error": message,
    }


async def verify_assay(
    assay_key: str,
    entry: dict,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Verify one registry entry against the paper. One LLM call, one assay.

    One call per assay rather than one per registry, for the reason claim_validator gives
    for claims: a whole-registry batch spreads the judge's attention across entries and
    dilutes exactly the per-field scrutiny this pass exists to apply.

    Never raises: an API or parse failure becomes a `record_verdict: "ERROR"` report, so one
    bad entry cannot cost a whole paper's verdicts.
    """
    quote_check = check_quote_verbatim(entry, source_text)

    candidate = json.dumps({assay_key: entry}, indent=2, ensure_ascii=False)
    prompt = (
        _load_prompt("verify_assays.txt")
        .replace("{paper_title}", paper_title)
        .replace("{section_name}", str(get_evidence(entry).get("section") or "not stated"))
        .replace("{source_text}", source_text)
        .replace("{candidate}", candidate)
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        parsed = json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 - any failure becomes a per-assay error report
        logger.warning("%s: verification call failed - %s", assay_key, exc)
        return _error_result(assay_key, entry, quote_check, f"{type(exc).__name__}: {exc}")

    if not isinstance(parsed, dict):
        return _error_result(
            assay_key, entry, quote_check,
            f"verifier returned {type(parsed).__name__}, not an object",
        )

    return _normalize_result(assay_key, entry, parsed, quote_check)


async def verify_registry(
    assays: dict,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    limit: int | None = None,
) -> list[dict]:
    """Verify every entry in an assays.json mapping, one call each."""
    keys = list(assays)
    if limit is not None:
        keys = keys[:limit]

    results: list[dict] = []
    print(f"Verifying {len(keys)} assay(s)...")
    for i, key in enumerate(keys, 1):
        result = await verify_assay(key, assays[key], source_text, paper_title, client, model)
        results.append(result)
        print(f"  [{i}/{len(keys)}] {key}: {result['record_verdict']} "
              f"(identity {result['assay_identity_verdict']})")
    return results


def build_summary(results: list[dict]) -> dict:
    """Aggregate record verdicts plus a per-field tally of non-SUPPORTED verdicts.

    The tally is the actionable part: one field failing across many assays points at a rule
    in the extraction prompt to fix, rather than at one bad entry.
    """
    field_issues: dict[str, dict[str, int]] = {}
    for result in results:
        for verification in result.get("field_verifications") or []:
            verdict = verification["verdict"]
            if verdict == SUPPORTED:
                continue
            # aliases[0] and aliases[3] are the same rule failing, so tally them together.
            field = re.sub(r"\[\d+\]$", "[]", verification["field_name"])
            field_issues.setdefault(field, {})
            field_issues[field][verdict] = field_issues[field].get(verdict, 0) + 1

    verdicts = [r.get("record_verdict") for r in results]
    return {
        "total": len(results),
        "accept": verdicts.count(ACCEPT),
        "review": verdicts.count(REVIEW),
        "reject": verdicts.count(REJECT),
        "errors": verdicts.count("ERROR"),
        "quotes_missing": sum(
            1 for r in results if (r.get("quote_check") or {}).get("status") == "missing"
        ),
        "quotes_absent": sum(
            1 for r in results if (r.get("quote_check") or {}).get("status") == "no_quote"
        ),
        "field_issues": field_issues,
    }


def build_report(results: list[dict]) -> dict:
    """Assemble the assays_verification.json payload."""
    return {"summary": build_summary(results), "results": results}
