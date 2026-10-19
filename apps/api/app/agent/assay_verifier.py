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
  * `check_alias_verbatim` does the same for each alias, so the judge is never asked whether
    a string is in the paper -- a question it answered wrongly 36 times in 39 -- only whether
    the wording names this assay.
  * `proposed_fields` decides what there is to verify at all. An entry with no non-null
    field beyond its name costs one call, not zero, because the name still needs judging.

As in claim_validator, the record verdict is *derived* from the field verdicts rather than
taken from the model: a judge that contradicts a field and still returns ACCEPT would
otherwise hide the contradiction. The model's own answer is kept alongside as
`model_record_verdict` so the disagreement stays visible.
"""

import asyncio
import json
import logging
import re
import unicodedata
from collections.abc import Callable

from openai import AsyncOpenAI

from app.agent import assay_trace
from app.agent.assay_extractor import REVIEW_FIELD
from app.agent.claim_parser import _load_prompt, _strip_fences
from app.agent.jats_parser import sentence_sections
from app.config import settings

logger = logging.getLogger(__name__)

#: Field verdicts. NOT_REPORTED is ours, not the model's: a field the judge never answered
#: for has not been cleared, and must not read the same as one it supported.
SUPPORTED = "SUPPORTED"
NOT_SUPPORTED = "NOT_SUPPORTED"
CONTRADICTED = "CONTRADICTED"
NOT_REPORTED = "NOT_REPORTED"

_MODEL_VERDICTS = (SUPPORTED, NOT_SUPPORTED, CONTRADICTED)

#: How many per-assay calls may be in flight at once. Every call in this pass is independent
#: -- that is the design, one assay per call so the judge's attention is not spread across a
#: registry -- so the loop was pure latency. Matches claim_abstraction_v5.MAX_CONCURRENT_CALLS
#: rather than inventing a second number; assay_corrector imports this one.
MAX_CONCURRENT_CALLS = 8

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

#: Registry keys that are structure, derived values, or removed cruft -- not proposed values to
#: verify. `standard_technique_name` is the extractor's judgement of which technique produced the data, so
#: there is no span to check it against. `generate_claim` is the other judgement, and about the
#: paper as a whole rather than any one sentence: no span supports "the paper reported nothing
#: from this assay", so a judge asked to rule on it can only guess. Keeping it out is also what
#: keeps it free -- a flagged field costs a correction call each (assay_service.corrections_
#: available), so verifying it would bill up to one call per assay. `source` is derived from the
#: quote by derive_evidence_fields, which makes it a fact about the document rather than anyone's
#: claim -- verifying it would be asking the judge to second-guess arithmetic.
#: `evidence.sentence_ids` is the same value under the other half of the same derivation and is
#: listed under both evidence spellings, because proposed_fields checks the flattened name. The
#: prompt already tells the judge not to rule on it; while this set did not, every entry of an XML
#: paper came back NOT_REPORTED on it, which forced REVIEW on the record and billed one round-3
#: evidence correction per assay for a field nobody had objected to. `confidence`, `claim_role`,
#: `platform`, `measurement_role` and `parent_hint` are fields the extraction no longer produces;
#: they are listed so an older registry on disk still verifies cleanly. `additional_evidence`
#: is written by round 5 (assay_merger) and holds other entries' records, not a value anyone
#: proposed for this one.
_NOT_PROPOSED = frozenset({"confidence", "claim_role", "standard_technique_name", "generate_claim",
                           "source", "platform", "measurement_role", "parent_hint",
                           "evidence.sentence_ids", "evidence_location.sentence_ids",
                           "obi_id", "obi_label", "resource", "obi_confidence",
                           "additional_evidence", REVIEW_FIELD})

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


def has_sentence_markers(text: str) -> bool:
    """Whether the source is sentence-numbered (JATS XML) rather than a bare PDF text layer."""
    return _MARKER.search(text) is not None


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


def derive_source(entry: dict, sections: dict[str, str]) -> str | None:
    """"methods" or "results" for one entry, from where its located sentences sit. Or None.

    The extraction is not asked where the assay sits; this works it out. An entry is "methods"
    when any sentence its quote was found in lies in a `[methods]` section, and "results" when
    none do -- the same "at least one" rule check_source_section audits with, because an entry may
    legitimately quote a Methods sentence and a Results sentence together.

    None when the quote could not be placed: on a PDF text layer there are no markers to place it
    against, and inventing "methods" there would assert the stronger claim on exactly the entries
    nothing can check. contract_warnings reports a None on a route that should have produced one.
    """
    ids = [str(s) for s in (get_evidence(entry).get("sentence_ids") or [])]
    buckets = [sections[sid] for sid in ids if sid in sections]
    if not buckets:
        return None
    return "methods" if "methods" in buckets else "results"


def derive_evidence_fields(assays: dict, source_text: str) -> dict:
    """Fill in every entry's `evidence.sentence_ids` and `source` from its quote. No API call.

    Runs between extraction and verification, so the judge and the corrector both see a registry
    whose derived fields are already right. Both values were previously asked of the model and then
    overruled by exactly this arithmetic -- locate_sentence_ids for the ids, the section map for
    `source` -- which cost a correction call on every disagreement and taught the model nothing.

    Mutates `assays` in place and returns it, the way the round-3 corrector does.
    """
    sections = sentence_sections(source_text)
    for entry in assays.values():
        if not isinstance(entry, dict):
            continue
        evidence_key = next((k for k in _EVIDENCE_KEYS if isinstance(entry.get(k), dict)),
                            _EVIDENCE_KEYS[0])
        evidence = dict(entry.get(evidence_key) or {})
        quote = evidence.get("quote")
        evidence["sentence_ids"] = locate_sentence_ids(quote, source_text) if quote else []
        entry[evidence_key] = evidence
        entry["source"] = derive_source(entry, sections)
    return assays


def identity_reviews(verification: dict) -> dict[str, dict]:
    """assay_id -> {verdict, reason} for every entry whose identity the judge did not support.

    NOT_SUPPORTED and NOT_REPORTED only. CONTRADICTED identities are dropped by round 3 and
    never reach the deliverable, so there is nothing to mark; a verification that failed outright
    leaves the identity NOT_REPORTED, which is not the same as supported and is marked as such.
    The reason is the judge's reason on the name field, else the call's error, else a stock line.
    """
    reviews: dict[str, dict] = {}
    for result in verification.get("results") or []:
        verdict = result.get("assay_identity_verdict")
        if verdict not in (NOT_SUPPORTED, NOT_REPORTED):
            continue
        reason = next(
            (v.get("reason") for v in (result.get("field_verifications") or [])
             if v.get("field_name") in _NAME_KEYS and v.get("reason")),
            None,
        ) or result.get("error") or "the verifier did not support the assay identity"
        reviews[str(result.get("assay_id", ""))] = {"verdict": verdict, "reason": reason}
    return reviews


def mark_identity_reviews(assays: dict, verification: dict | None) -> dict:
    """Write REVIEW_FIELD onto every entry identity_reviews names. Mutates and returns.

    Runs right after round 2 so the mark is on the entry through correction (which deep-copies
    entries and keeps unknown keys), through the round-5 fold (assay_merger carries it) and into
    the deliverable (assay_extractor.trim_registry copies it). An entry the judge supported is
    left exactly as it was.
    """
    for key, review in identity_reviews(verification or {}).items():
        entry = assays.get(key)
        if isinstance(entry, dict):
            entry[REVIEW_FIELD] = review
    return assays


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

    The `verdict` mirrors check_quote_verbatim's so the two checks report alike; `source` is in
    _NOT_PROPOSED and never reaches the judge, so nothing here overrules anyone -- it is reported
    by quote_report. It is None on "unknown" so an entry with no ids, or one predating the field,
    is not marked wrong for a check that could not run.

    Returns `unknown` -- never a mismatch -- when the entry cites no sentence_ids, when its ids
    are absent from the map, or when `source` is missing. Most registries on disk predate both
    fields, and they must pass through quietly, the same concession check_quote_verbatim makes.
    """
    source = entry.get("source")
    if source not in ("methods", "results"):
        return {"status": "unknown", "verdict": None,
                "detail": f"source is {source!r}, nothing to check"}

    ids = [str(s) for s in (get_evidence(entry).get("sentence_ids") or [])]
    if not ids:
        return {"status": "unknown", "verdict": None, "detail": "entry cites no sentence_ids"}

    located = {sid: sections[sid] for sid in ids if sid in sections}
    if not located:
        return {"status": "unknown", "verdict": None,
                "detail": f"none of {', '.join(ids)} appear in the paper's section map"}

    buckets = sorted(set(located.values()))
    in_methods = "methods" in buckets
    aligned = in_methods if source == "methods" else not all(b == "methods" for b in buckets)

    where = ", ".join(f"{sid} in [{bucket}]" for sid, bucket in located.items())
    if aligned:
        return {"status": "aligned", "verdict": SUPPORTED,
                "detail": f"source {source!r} agrees with {where}"}
    return {
        "status": "mismatch",
        "verdict": CONTRADICTED,
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
    key is sometimes the only name there is. A canonical registry (after round 5) carries the
    wordings as a list; the first is the name, and the key there is an OBI label, which is not
    what the paper called anything.
    """
    for name_key in _NAME_KEYS:
        value = entry.get(name_key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            first = next((v for v in value if isinstance(v, str) and v.strip()), None)
            if first:
                return first
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


#: The shortest a quote's longest fragment may be, in squashed characters. Whitespace and
#: dashes are dropped before comparing, so a few-word fragment ("ELISA ... performed") matches
#: almost anywhere once the search widens to the whole document; about four words is the least
#: that pins a quote to one place. No quote in the 160 on disk falls under it.
MIN_QUOTE_CHARS = 20

#: The longest run of consecutive sentences locate_sentence_ids will try. A quote spanning more
#: than this is not an excerpt, and an unbounded search is quadratic in the paper's length.
_MAX_LOCATE_SPAN = 8


def _matches(quote: str, haystack: str) -> bool:
    """The fragment test, forgiving trailing punctuation the source does not carry."""
    return _fragments_in_order(quote, haystack) or _fragments_in_order(quote.rstrip(".,;:"), haystack)


def locate_sentence_ids(quote: str, source_text: str) -> list[str]:
    """The shortest run of consecutive `S<n>` sentences that contains `quote`, or [].

    What the ids *should* have been, recovered for free. Used when a quote is verbatim but cites
    the wrong sentences -- which a survey of the registries on disk found four times in 160, each
    a real excerpt reported as a fabrication because it spanned a sentence it did not list.
    """
    index = sentence_index(source_text)
    ids = list(index)
    squashed = [_squash(index[sid]) for sid in ids]
    for span in range(1, _MAX_LOCATE_SPAN + 1):
        for start in range(len(ids) - span + 1):
            if _matches(quote, "".join(squashed[start:start + span])):
                return ids[start:start + span]
    return []


def check_quote_verbatim(entry: dict, source_text: str) -> dict:
    """Confirm the evidence quote appears in the sentences it cites. No API call.

    The extraction contract says the quote is *copied*, not paraphrased or reconstructed,
    so a quote that is absent from the source is a fabrication rather than a judgement
    call — which is why this returns CONTRADICTED rather than deferring to the model.

    Statuses:

    * `found` — in the cited sentences, or in the document when the source has no `[S<n>]`
      markers to cite (a PDF text layer) and the entry rightly cites none.
    * `misattributed` — verbatim, but not where the entry says: it cites ids the source does not
      have, cites none although the source is numbered, or cites sentences the quote is not in.
      NOT_SUPPORTED rather than CONTRADICTED, because the words are the paper's; `located_ids`
      carries the sentences that actually hold it, so a correction can fix the citation.
    * `too_short` — no fragment reaches MIN_QUOTE_CHARS, so a match would prove nothing.
    * `missing` — nowhere in the document. A fabrication.
    * `no_quote` — nothing to check.

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
    result = {"unknown_sentence_ids": unknown, "located_ids": []}

    # Absence first: a quote the paper does not contain is a fabrication however short it is.
    if not _matches(quote, _squash(strip_markers(source_text))):
        return {**result, "status": "missing", "verdict": CONTRADICTED,
                "detail": "quote does not appear anywhere in the document"}

    longest = max((len(_squash(f)) for f in _ELLIPSIS.split(quote)), default=0)
    if longest < MIN_QUOTE_CHARS:
        return {**result, "status": "too_short", "verdict": NOT_SUPPORTED,
                "detail": f"no fragment of the quote reaches {MIN_QUOTE_CHARS} characters, "
                          "so finding it in the source would not pin it to one place"}

    trailing = "" if _fragments_in_order(quote, _squash(strip_markers(source_text))) else (
        # Excerpting a clause and closing it with a period the source does not carry is an
        # artifact of quoting, not a claim about content -- the words are still the paper's.
        ", except for trailing punctuation not in the source")

    if not index:
        # No markers to cite: a PDF text layer. The whole document is the only scope there is.
        if not sentence_ids:
            return {**result, "status": "found", "verdict": SUPPORTED,
                    "detail": f"quote found in the whole document{trailing}"}
        return {**result, "status": "misattributed", "verdict": NOT_SUPPORTED,
                "detail": f"quote is verbatim but cites {', '.join(sentence_ids)}, and this "
                          "source has no sentence markers to cite"}

    if sentence_ids and not unknown:
        cited = _squash(" ".join(index[sid] for sid in sentence_ids))
        if _matches(quote, cited):
            return {**result, "status": "found", "verdict": SUPPORTED,
                    "detail": f"quote found in sentences {', '.join(sentence_ids)}{trailing}"}

    located = locate_sentence_ids(quote, source_text)
    if unknown:
        why = f"cites {', '.join(unknown)}, which the source does not have"
    elif not sentence_ids:
        why = "cites no sentence ids"
    else:
        why = f"is not in the sentences it cites ({', '.join(sentence_ids)})"
    where = f"; it is in {', '.join(located)}" if located else ""
    return {**result, "located_ids": located, "status": "misattributed",
            "verdict": NOT_SUPPORTED, "detail": f"quote is verbatim but {why}{where}"}


#: The shortest alias the string check will vouch for. Whitespace is dropped before comparing,
#: so a one- or two-letter alias ("IF", "MS") matches inside almost any word; three characters
#: keeps the acronyms that matter ("HAI", "ICS", "PCR").
MIN_ALIAS_CHARS = 3

#: A judge's reason that objects to the *wording* of an alias rather than to what it names. The
#: string check settles wording, so such an objection over an alias that is in the text is
#: withdrawn. "does not use the term X for this assay" is deliberately not matched: that is a
#: claim about reference, which only the judge can make.
_WORDING_OBJECTION = re.compile(
    r"verbatim|does not appear|not appear|exact (?:alias|phrase|wording|form|spelling|"
    r"capitali[sz]ation|lowercase|singular)|capitali[sz]|lowercase|singular phrase",
    re.IGNORECASE)


def check_alias_verbatim(alias: object, source_text: str) -> dict:
    """Confirm an alias appears in the paper. No API call.

    The counterpart of check_quote_verbatim for `aliases[i]`. The verify prompt used to ask the
    judge whether each alias "appears verbatim in the source", and measured over the 31 stored
    runs the judge got that wrong 36 times out of 39: "Flow cytometry", "HAI", "CyTOF", "qPCR"
    and "FACS" were all reported absent from papers that contain them, and round 3 then dropped
    27 of them. Presence is a string fact, settled here the same way the quote is -- whitespace,
    dashes and case folded -- and the judge is left with the question only it can answer,
    whether the wording names this assay.

    Statuses: `found`, `missing`, `too_short` (nothing to vouch for), `no_alias`.
    """
    if not isinstance(alias, str) or not alias.strip():
        return {"status": "no_alias", "verdict": None, "detail": "no alias to check"}
    needle = _squash(alias).lower()
    if len(needle) < MIN_ALIAS_CHARS:
        return {"status": "too_short", "verdict": None,
                "detail": f"alias is under {MIN_ALIAS_CHARS} characters; presence proves nothing"}
    if needle in _squash(strip_markers(source_text)).lower():
        return {"status": "found", "verdict": SUPPORTED,
                "detail": "alias appears in the source text"}
    return {"status": "missing", "verdict": NOT_SUPPORTED,
            "detail": "alias does not appear anywhere in the source text"}


def alias_checks(entry: dict, source_text: str) -> dict[str, dict]:
    """`aliases[i]` -> check_alias_verbatim, for every alias proposed_fields enumerates."""
    return {field: check_alias_verbatim(value, source_text)
            for field, value in proposed_fields(entry) if field.startswith("aliases[")}


def _apply_alias_check(verification: dict, check: dict) -> None:
    """Settle the wording half of an alias verdict; leave the reference half to the judge.

    An alias the text does not contain is NOT_SUPPORTED whatever the judge said. One the text
    does contain keeps the judge's verdict -- "a readout, not a name" is its call -- unless that
    verdict was NOT_SUPPORTED *for the wording*, which the string check has just refuted.
    """
    if check["status"] == "missing":
        verification["verdict"] = NOT_SUPPORTED
        verification["reason"] = check["detail"]
    elif (check["status"] == "found" and verification["verdict"] == NOT_SUPPORTED
          and _WORDING_OBJECTION.search(verification.get("reason") or "")):
        verification["verdict"] = SUPPORTED
        verification["reason"] = (f"{check['detail']}; the judge's objection was to the "
                                  f"wording: {verification.get('reason') or ''}".rstrip(": "))


def proposed_fields(entry: dict) -> list[tuple[str, object]]:
    """Every non-null atomic value the extraction proposed, as (field_name, value).

    Aliases are enumerated individually — one bad alias in a list of five is a specific
    defect, and a single verdict over the whole list cannot say which one. Evidence is
    flattened for the same reason, but only `quote` survives the flattening: the ids beside it
    are derived from that quote by code, so _NOT_PROPOSED holds them back and the judge rules on
    the one part of the evidence anyone actually proposed.
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
            # Flattened names go through _NOT_PROPOSED too, so the set is the single answer to
            # "what is not sent for verification" rather than a rule the top level obeys and the
            # evidence parts quietly do not.
            if f"{evidence_key}.{sub}" in _NOT_PROPOSED:
                continue
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


def _normalize_result(assay_key: str, entry: dict, raw: dict, quote_check: dict,
                      aliases_verbatim: dict[str, dict] | None = None) -> dict:
    """Build one assay's report from the judge's answer plus the string checks.

    `assay_id` is forced to the real registry key — a per-assay call gives the model no way
    to know it beyond the echo we asked for.

    The string checks settle what a string can settle and nothing more. A quote the paper does
    not contain, or cites wrongly, is marked down whatever the judge said. A quote the paper
    does contain keeps the judge's verdict: the prompt asks it to rule NOT_SUPPORTED when a
    verbatim quote "establishes nothing about this assay being performed", and the check used to
    overwrite that ruling with SUPPORTED. Only a judge that never answered for the quote is given
    the string check's SUPPORTED, since presence is then the one thing known about it.
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

    # The string check outranks the judge on quote verbatimness: it is not an opinion. It can
    # only lower a verdict, though -- see the docstring.
    if quote_check["verdict"] is not None:
        evidence_key = next(
            (k for k in _EVIDENCE_KEYS if isinstance(entry.get(k), dict)), _EVIDENCE_KEYS[0]
        )
        for verification in verifications:
            if verification["field_name"] != f"{evidence_key}.quote":
                continue
            if quote_check["verdict"] != SUPPORTED or verification["verdict"] == NOT_REPORTED:
                verification["verdict"] = quote_check["verdict"]
                verification["reason"] = quote_check["detail"]

    for verification in verifications:
        check = (aliases_verbatim or {}).get(verification["field_name"])
        if check:
            _apply_alias_check(verification, check)

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
    aliases_verbatim = alias_checks(entry, source_text)

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
        assay_trace.record("verify", assay_key, reply=raw)
        parsed = json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - any failure becomes a per-assay error report
        logger.warning("%s: verification call failed - %s", assay_key, exc)
        assay_trace.record("verify", assay_key, error=f"{type(exc).__name__}: {exc}")
        return _error_result(assay_key, entry, quote_check, f"{type(exc).__name__}: {exc}")

    # An empty reply is a failed call, not a verdict. Scoring it as {} used to turn every field
    # NOT_REPORTED and the record REVIEW, which reads as the judge having looked and objected.
    if parsed is None:
        return _error_result(assay_key, entry, quote_check, "verifier returned an empty reply")

    if not isinstance(parsed, dict):
        return _error_result(
            assay_key, entry, quote_check,
            f"verifier returned {type(parsed).__name__}, not an object",
        )

    return _normalize_result(assay_key, entry, parsed, quote_check, aliases_verbatim)


async def verify_registry(
    assays: dict,
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
    limit: int | None = None,
    max_concurrency: int = MAX_CONCURRENT_CALLS,
    on_item: Callable[[int, int, dict], None] | None = None,
) -> list[dict]:
    """Verify every entry in an assays.json mapping, one call each.

    The calls run concurrently, bounded by `max_concurrency`. They are independent by
    construction -- each judges one entry against the same unchanging paper and writes
    nothing -- so the previous sequential loop bought nothing but wall-clock. `gather`
    preserves argument order, so `results` is still in registry order however the calls
    interleave; the progress lines are the one thing that arrives out of order, and they
    carry the assay name precisely because the counter no longer identifies it.

    `on_item(done, total, result)` fires beside each of those lines, for a caller that is
    watching this round somewhere other than a terminal. It is additive: the print stays, so
    the CLI is unchanged, and omitting the callback is exactly today's behaviour. The same
    out-of-order caveat applies -- a listener that assumes `done` identifies the assay will be
    wrong, which is why the whole result is handed over.

    verify_assay never raises, so no call can cancel its siblings.
    """
    keys = list(assays)
    if limit is not None:
        keys = keys[:limit]

    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    done = 0

    async def _verify_one(key: str) -> dict:
        nonlocal done
        async with semaphore:
            result = await verify_assay(key, assays[key], source_text, paper_title,
                                        client, model)
        done += 1
        print(f"  [{done}/{len(keys)}] {key}: {result['record_verdict']} "
              f"(identity {result['assay_identity_verdict']})")
        if on_item is not None:
            on_item(done, len(keys), result)
        return result

    print(f"Verifying {len(keys)} assay(s), up to {max(1, max_concurrency)} at a time...")
    return list(await asyncio.gather(*(_verify_one(key) for key in keys)))


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
        "quotes_misattributed": sum(
            1 for r in results
            if (r.get("quote_check") or {}).get("status") in ("misattributed", "too_short")
        ),
        "quotes_absent": sum(
            1 for r in results if (r.get("quote_check") or {}).get("status") == "no_quote"
        ),
        "field_issues": field_issues,
    }


def build_report(results: list[dict]) -> dict:
    """Assemble the assays_verification.json payload."""
    return {"summary": build_summary(results), "results": results}
