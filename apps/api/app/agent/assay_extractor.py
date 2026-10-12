"""Extract a paper's assay registry in one LLM call.

Driven by scripts/run_assay_extract.py when a user asks for a paper's assays.
prompts/extract_assays.txt is the authority on the rules -- what counts as an entry, how
entries are named, when Results may add one, and what each field may say -- written for a
model that gets one shot at the paper instead of an interactive read.

This is NOT the full-paper assay pass that app.agent.assay_registry's docstring describes as
removed. That one existed to be reconciled against the claims, and it is gone because every
claim now names its own assay. This produces the *independent* registry — the one
assay_verifier judges, assay_corrector repairs, and load_verified_registry hands to
resolve_experiment_accession as sample_type/readouts context. Nothing here feeds
claim extraction.

The output is validated on the way out rather than trusted. A model that returns extra fields,
or an entry with no evidence, has broken the contract every downstream step relies on: the
ten-field shape is what assay_obi_mapper and query_builder read, and `evidence.quote` is
what check_quote_verbatim compares character by character. Extra keys are dropped and missing
ones defaulted, so a partially malformed answer costs its bad fields rather than the paper.
"""

import json
import logging

from openai import AsyncOpenAI

from app.agent.claim_parser import _load_prompt, _strip_fences
from app.config import settings

logger = logging.getLogger(__name__)

#: The seven-field contract, in the order extract_assays.txt documents them. Anything else a
#: model returns is dropped: `confidence` and `claim_role` are the two it reaches for
#: unprompted, and both were removed from this schema on purpose.
#:
#: `normalized_name` is the odd one out, and deliberately so: every other field records
#: something the paper states, while this one records which *technique* the assay is -- a
#: judgement the model makes while reading the paper, often in words the paper never uses.
#: That is the point. Papers name assays after protocol sections ("Surface and intracellular
#: cytokine staining"), acronyms ("CBA") and study aims ("Direct ex vivo PBMC immune cell
#: phenotyping"), none of which retrieve the OBI term they belong to. Because it asserts
#: nothing about the text it is excluded from verification -- see assay_verifier._NOT_PROPOSED.
#:
#: `source` and `evidence.sentence_ids` are in the contract but are NOT asked of the model. Both
#: are derived from the quote after extraction by assay_verifier.derive_evidence_fields, because
#: both already were: locate_sentence_ids recovered the ids a quote really came from, and
#: check_source_section re-derived the section and overruled the model on it. Asking for a value
#: the code computes anyway bought nothing and cost a correction call whenever the answers
#: differed -- 12 such defects across the 38 registries on disk.
#:
#: `platform`, `measurement_role` and `parent_hint` were removed. `platform` fed no step that
#: needed it -- the OBI resolver never read it -- while costing verification and correction calls.
#: `measurement_role` was meant to narrow the deliverable to what a paper reported, but nothing
#: filtered on it, the verifier was told to skip it and the corrector had no question for it, so a
#: wrong value was unreachable; `parent_hint` existed only to point a `sub_step` at its parent.
#:
#: `generate_claim` is asked again on purpose, and is the nearest thing to `measurement_role`
#: above -- so read this before deleting it citing that paragraph. It is here to be compared
#: against the curated `generate_claim` in data/benchmark_assay/, which is why it rides into the
#: deliverable rather than staying in assays.json. It is deliberately NOT a filter: nothing drops
#: a `false` entry, because extract_assays.txt rules that an assay the paper performed is an entry
#: whether or not the paper concluded from it, and that rule is what the recall score rests on.
#: Like `normalized_name` it is a judgement rather than a value copied from a span, so it is
#: excluded from verification -- see assay_verifier._NOT_PROPOSED.
ENTRY_FIELDS = ("name_in_paper", "normalized_name", "aliases", "sample_type",
                "readouts", "generate_claim", "source", "evidence")

#: What the finished registry is projected onto for `assays_benchmark.json`: the assay's name,
#: its aliases, whether the paper drew a finding from it, and its evidence source kept as both the
#: label and the traceability. The other fields stay in `assays.json` because the pipeline needs
#: them -- the verifier rules on a specimen, the corrector repairs one, and merge_verified hands
#: them to claim resolution. Trimming the deliverable is a reading concern; trimming the schema
#: broke all three. `generate_claim` is here rather than there because the file this projects to is
#: the one held against the curated benchmark, which carries the same field.
TRIMMED_FIELDS = ("name_in_paper", "aliases", "generate_claim", "source", "evidence")

#: A further field, written only by round 5 (app.agent.assay_merger) and only on an entry that
#: absorbed another: the merged-away write-up's own record, so folding two entries into one never
#: costs a quote. Deliberately outside ENTRY_FIELDS -- clean_entry runs on model output, which is
#: never allowed to assert a merge -- and carried into the deliverable only where it exists, so an
#: unmerged entry's trimmed record stays exactly what it was before the round existed.
MERGED_FIELD = "additional_evidence"


def paper_names(entry: dict) -> list[str]:
    """Every wording an entry records for itself, whatever schema it is in.

    `name_in_paper` is a single string as the model returns it and a list once round 5 has folded
    an entry into it, and both spellings live on disk: a registry written before that round
    existed is still a registry. Every reader of a *finished* registry goes through this.
    """
    value = entry.get("name_in_paper")
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


_EVIDENCE_FIELDS = ("section", "sentence_ids", "quote")

_SOURCE_VALUES = ("methods", "results")


class AssayExtractionError(RuntimeError):
    """The model returned something that is not an assay registry at all."""


def _clean_evidence(raw: object) -> dict:
    """Coerce one entry's evidence to {section, sentence_ids, quote}.

    `sentence_ids` always starts empty. The model is not asked for it and a volunteered answer is
    dropped: the ids are located from the quote afterwards, which is exact, so accepting a guess
    would only give the pipeline a worse value to overwrite.
    """
    raw = raw if isinstance(raw, dict) else {}
    return {
        "section": raw.get("section") or None,
        "sentence_ids": [],
        "quote": raw.get("quote") if isinstance(raw.get("quote"), str) else None,
    }


def clean_entry(key: str, raw: dict) -> dict:
    """Reduce one model-returned entry to the contract.

    `name_in_paper` falls back to the registry key, which is what the skill says the key is:
    the same string.

    `source` is left as None here even if the model volunteered one. It is not asked for any
    more and is derived from the quote afterwards, so accepting a stray answer would let an
    unasked-for judgement outrank the document. `evidence.sentence_ids` is emptied by
    _clean_evidence for the same reason.

    `generate_claim` has no fallback either: an entry the model left unanswered stays None rather
    than defaulting to False, so "the paper drew nothing from this assay" and "nobody said" are
    still distinguishable downstream.
    """
    aliases = raw.get("aliases")
    return {
        "name_in_paper": raw.get("name_in_paper") if isinstance(raw.get("name_in_paper"), str)
                         and raw["name_in_paper"].strip() else key,
        # Never falls back to the key. An omitted normalization means the model declined to
        # name a technique, and echoing the paper's wording back would turn that silence into
        # a claim -- one the OBI mapper would then trust as an exact-match key.
        "normalized_name": raw.get("normalized_name")
                           if isinstance(raw.get("normalized_name"), str)
                           and raw["normalized_name"].strip() else None,
        "aliases": [a for a in aliases if isinstance(a, str) and a.strip()]
                   if isinstance(aliases, list) else [],
        "sample_type": raw.get("sample_type") or None,
        "readouts": raw.get("readouts") or None,
        # A real boolean or nothing. "true", "yes" and 1 are answers in a shape the contract does
        # not define, and reading one as True would turn a formatting slip into a finding the paper
        # may not report. `isinstance` is the check that says so: `1 in (True, False)` is True.
        "generate_claim": raw.get("generate_claim")
                          if isinstance(raw.get("generate_claim"), bool) else None,
        "source": None,
        "evidence": _clean_evidence(raw.get("evidence")),
    }


def _keep_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """object_pairs_hook that renames a repeated key to "<key> (2)", "(3)", ... and warns.

    The registry is keyed by `name_in_paper`, and the naming rules strip names to the bare
    technique -- so two entries the prompt splits by analyte ("Luminex" antibody assay,
    "Luminex" cytokine panel) can come back under one key. Plain json.loads keeps the last and
    drops the other without a word; this keeps both so the verifier sees each.
    """
    out: dict = {}
    for key, value in pairs:
        unique, n = key, 1
        while unique in out:
            n += 1
            unique = f"{key} ({n})"
        if unique != key:
            logger.warning("assay extraction: duplicate key %r kept as %r", key, unique)
        out[unique] = value
    return out


def parse_registry_json(raw: str) -> object:
    """json.loads for a model's registry answer, keeping entries that share a key."""
    try:
        return json.loads(raw, object_pairs_hook=_keep_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise AssayExtractionError(f"model returned unparseable JSON: {exc}") from exc


def clean_registry(parsed: object) -> dict:
    """Validate and normalize a whole model answer into a registry.

    Raises AssayExtractionError when the answer is not an object at all -- there is nothing
    to salvage from a list or a string, and returning `{}` would be indistinguishable from a
    paper that genuinely describes no assay.
    """
    if not isinstance(parsed, dict):
        raise AssayExtractionError(
            f"model returned {type(parsed).__name__}, not an assay registry object"
        )
    parsed = _unwrap(parsed)
    registry = {key: clean_entry(key, entry)
                for key, entry in parsed.items() if isinstance(entry, dict)}
    if parsed and not registry:
        # Keys, but not one entry among them: a shape this function does not know. Returning {}
        # would read as "the paper describes no assay", which is exactly what must not be said
        # on the strength of a formatting slip.
        raise AssayExtractionError(
            f"model returned an object with keys {sorted(parsed)[:5]} but no assay entries"
        )
    return registry


def _unwrap(parsed: dict) -> dict:
    """`{"assays": {...}}` / `{"assays": [{...}, ...]}` -> the registry the wrapper holds.

    Only a single top-level key whose value is itself entries is unwrapped; a list is keyed by
    each entry's `name_in_paper`. Anything else is returned as it came.
    """
    if len(parsed) != 1:
        return parsed
    (value,) = parsed.values()
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        return {str(v.get("name_in_paper") or f"assay {i + 1}"): v for i, v in enumerate(value)}
    if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
        return value
    return parsed


def contract_warnings(registry: dict, *, expect_sentence_ids: bool = True) -> list[str]:
    """Contract violations worth telling a human about, without failing the extraction.

    None of these are recoverable here -- fixing them means re-extracting or repairing, which
    are other passes' jobs. They are surfaced so a bad run is visible immediately rather than
    at OBI-mapping time.

    `expect_sentence_ids=False` for a registry built from a PDF (assay_extractor_pdf), where
    `sentence_ids` is empty on every entry by contract because the source carries no `[S<n>]`
    markers to cite. Reporting that per entry would fire on all of them at once and bury the
    warnings that mean something. Every other check still runs -- a PDF entry with no quote is
    exactly as broken as an XML one.

    Every field is read with .get(), because this also runs over registries that did not come
    straight from clean_registry: run_assay_pipeline reports on the *corrected* registry, and
    correction preserves an old-schema entry's `evidence_location` rather than renaming it.
    Such entries carry `evidence_location`, `claim_role` and `confidence` instead of `evidence`
    and `source`, and subscripting would raise KeyError on them, turning a stale registry into
    a 500. Reporting the missing fields is the honest answer: those entries really do lack the
    evidence quote and sentence ids that downstream steps need.
    """
    warnings: list[str] = []
    for key, entry in registry.items():
        evidence = entry.get("evidence") or {}
        if not evidence.get("quote"):
            warnings.append(f"{key}: no evidence quote")
        # Both of these are derived from the quote, so a gap means the quote could not be placed
        # in the document -- worth reporting for the same reason a missing quote is.
        if expect_sentence_ids and not evidence.get("sentence_ids"):
            warnings.append(f"{key}: quote could not be located in any sentence")
        if expect_sentence_ids and entry.get("source") not in _SOURCE_VALUES:
            warnings.append(f"{key}: source could not be derived, it is {entry.get('source')!r}")
        # `[]` is a valid answer -- plenty of assays are named one way only. A non-list is not:
        # a correction round that cleared the field to null, or an extraction that returned a
        # bare string, both read as "no aliases" downstream instead of as the defect they are.
        if not isinstance(entry.get("aliases"), list):
            warnings.append(f"{key}: aliases is {entry.get('aliases')!r}, not a list")
        # Before round 5 the key is the assay's one wording. After it, the key is the OBI label
        # and the wordings are a list, so the check becomes "the key is one of the names, or it is
        # the term they were folded onto" -- a registry whose key is neither is the defect.
        names = paper_names(entry)
        if key not in names and not entry.get(MERGED_FIELD) and len(names) < 2:
            warnings.append(f"{key}: name_in_paper is {entry.get('name_in_paper')!r}, not the key")
    return warnings


def trim_registry(registry: dict) -> dict:
    """Project a finished registry onto TRIMMED_FIELDS, for `assays_benchmark.json`.

    A reading view, not a schema: `assays.json` keeps every field, and every pass in the chain
    works from that. This exists because the dropped fields answer a different question -- what
    the assay ran on and produced -- than the one the deliverable is for.

    Read with .get() and never raising, for the reason contract_warnings gives: this also runs
    over registries stored before the current schema, which carry `evidence_location` instead
    of `evidence`. Such an entry comes back with `evidence: None` rather than being skipped --
    a visible gap beats a silently missing assay.
    """
    trimmed = {}
    for key, entry in (registry or {}).items():
        if not isinstance(entry, dict):
            continue
        record = {field: entry.get(field) for field in TRIMMED_FIELDS}
        # Present only on a merged entry, and then it is the second write-up's evidence -- the
        # one thing a reader of the deliverable cannot reconstruct from the winner's own record.
        if entry.get(MERGED_FIELD):
            record[MERGED_FIELD] = entry[MERGED_FIELD]
        trimmed[key] = record
    return trimmed


#: Put above the paper text when no section is tagged `[methods]`. The tags are computed by
#: code, so whether a paper has a Methods section is a fact to state, not something to leave the
#: model to infer -- left to infer it, the model took the Methods-only path on a short report
#: with no Methods section (SDY1171) and returned `{}` for a paper that names its assays.
NO_METHODS_NOTE = (
    "STRUCTURE 3 APPLIES: this paper has no [methods] section -- its methods are likely in a "
    "supplement not included here. Build the inventory from the abstract, the main text and the "
    "captions, as structure 3 describes.\n\n"
)


def has_methods_section(source_text: str) -> bool:
    """Whether any heading of the tagged source text is a Methods section. Free."""
    return "[methods]" in source_text


def build_prompt(source_text: str, paper_title: str) -> str:
    """Render extract_assays.txt for one paper, stating structure 3 when there is no Methods."""
    text = source_text if has_methods_section(source_text) else NO_METHODS_NOTE + source_text
    return (
        _load_prompt("extract_assays.txt")
        .replace("{paper_title}", paper_title)
        .replace("{source_text}", text)
    )


async def extract_assays(
    source_text: str,
    paper_title: str,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Build a paper's assay registry. One LLM call for the whole paper.

    One call rather than one per section, which is the opposite of the choice
    assay_verifier makes for verification and deliberately so: verification judges each entry
    independently, while extraction has to *deduplicate across* the paper, and a model that
    only ever sees one section cannot tell that the Results paraphrase it just read is the
    Methods entry it read earlier.
    """
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": build_prompt(source_text, paper_title)}],
        temperature=0,
    )
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    if not raw:
        raise AssayExtractionError("model returned an empty response")

    parsed = parse_registry_json(raw)

    registry = clean_registry(parsed)
    # `expect_sentence_ids=False` here, not because this route lacks markers, but because
    # derive_evidence_fields has not run yet: the ids and `source` are filled in from the quote
    # after this function returns, so warning about them now would fire on every entry of every
    # paper. assay_service re-runs this check once they are derived, which is where a real gap
    # surfaces.
    for warning in contract_warnings(registry, expect_sentence_ids=False):
        logger.warning("assay extraction: %s", warning)
    return registry
