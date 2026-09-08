"""Extract a paper's assay registry in one LLM call.

Driven by scripts/run_assay_extract.py when a user asks for a paper's assays.
prompts/extract_assays.txt is the authority on the rules -- what counts as an entry, how
entries are named, when Results may add one, and what each field may say -- written for a
model that gets one shot at the paper instead of an interactive read.

This is NOT the full-paper assay pass that app.agent.assay_registry's docstring describes as
removed. That one existed to be reconciled against the claims, and it is gone because every
claim now names its own assay. This produces the *independent* registry — the one
assay_verifier judges, assay_corrector repairs, and load_verified_registry hands to
resolve_experiment_accession as platform/sample_type/readouts context. Nothing here feeds
claim extraction.

The output is validated on the way out rather than trusted. A model that returns eight fields,
or an entry with no evidence, has broken the contract every downstream step relies on: the
seven-field shape is what assay_obi_mapper and query_builder read, and `evidence.quote` is
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
ENTRY_FIELDS = ("name_in_paper", "aliases", "platform", "sample_type", "readouts",
                "source", "evidence")

#: What the finished registry is projected onto for `assays_benchmark.json`: the assay's name,
#: its aliases, and its evidence source kept as both the label and the traceability. The other
#: three fields stay in `assays.json` because the pipeline needs them -- the verifier rules on
#: a specimen, the corrector repairs one, and merge_verified hands them to claim resolution.
#: Trimming the deliverable is a reading concern; trimming the schema broke all three.
TRIMMED_FIELDS = ("name_in_paper", "aliases", "source", "evidence")

_EVIDENCE_FIELDS = ("section", "sentence_ids", "quote")

_SOURCE_VALUES = ("methods", "results")


class AssayExtractionError(RuntimeError):
    """The model returned something that is not an assay registry at all."""


def _clean_evidence(raw: object) -> dict:
    """Coerce one entry's evidence to {section, sentence_ids, quote}."""
    raw = raw if isinstance(raw, dict) else {}
    ids = raw.get("sentence_ids")
    return {
        "section": raw.get("section") or None,
        "sentence_ids": [str(s) for s in ids] if isinstance(ids, list) else [],
        "quote": raw.get("quote") if isinstance(raw.get("quote"), str) else None,
    }


def clean_entry(key: str, raw: dict) -> dict:
    """Reduce one model-returned entry to the seven-field contract.

    `name_in_paper` falls back to the registry key, which is what the skill says the key is:
    the same string.

    An omitted `source` becomes None, not "methods". Defaulting it to "methods" asserted the
    stronger claim -- that the paper established the technique in its Methods section -- on
    exactly the entries where the model declined to say, and the papers where the model is
    least sure are the ones with no heading named "Methods" or "Results" at all. None is
    outside _SOURCE_VALUES, so contract_warnings surfaces it rather than the registry
    recording a provenance nobody asserted. An invented value is likewise not corrected to a
    valid one, because that would hide the classification pass going wrong.
    """
    aliases = raw.get("aliases")
    source = raw.get("source")
    return {
        "name_in_paper": raw.get("name_in_paper") if isinstance(raw.get("name_in_paper"), str)
                         and raw["name_in_paper"].strip() else key,
        "aliases": [a for a in aliases if isinstance(a, str) and a.strip()]
                   if isinstance(aliases, list) else [],
        "platform": raw.get("platform") or None,
        "sample_type": raw.get("sample_type") or None,
        "readouts": raw.get("readouts") or None,
        "source": source if isinstance(source, str) and source.strip() else None,
        "evidence": _clean_evidence(raw.get("evidence")),
    }


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
    return {key: clean_entry(key, entry)
            for key, entry in parsed.items() if isinstance(entry, dict)}


def contract_warnings(registry: dict) -> list[str]:
    """Contract violations worth telling a human about, without failing the extraction.

    None of these are recoverable here -- fixing them means re-extracting or repairing, which
    are other passes' jobs. They are surfaced so a bad run is visible immediately rather than
    at OBI-mapping time.

    Every field is read with .get(), because this also runs on registries loaded from disk
    rather than freshly cleaned (assay_service serves a cached assays.json through here). Most
    stored registries predate the current schema -- they carry `evidence_location`,
    `claim_role` and `confidence` instead of `evidence` and `source` -- and subscripting would
    raise KeyError on the cached path, turning a stale registry into a 500. Reporting the
    missing fields is the honest answer: those entries really do lack the evidence quote and
    sentence ids that downstream steps need.
    """
    warnings: list[str] = []
    for key, entry in registry.items():
        evidence = entry.get("evidence") or {}
        if not evidence.get("quote"):
            warnings.append(f"{key}: no evidence quote")
        if not evidence.get("sentence_ids"):
            warnings.append(f"{key}: evidence cites no sentence_ids")
        if entry.get("source") not in _SOURCE_VALUES:
            warnings.append(f"{key}: source is {entry.get('source')!r}, not 'methods' or 'results'")
        # `[]` is a valid answer -- plenty of assays are named one way only. A non-list is not:
        # a correction round that cleared the field to null, or an extraction that returned a
        # bare string, both read as "no aliases" downstream instead of as the defect they are.
        if not isinstance(entry.get("aliases"), list):
            warnings.append(f"{key}: aliases is {entry.get('aliases')!r}, not a list")
        if entry.get("name_in_paper") != key:
            warnings.append(f"{key}: name_in_paper is {entry.get('name_in_paper')!r}, not the key")
    return warnings


def trim_registry(registry: dict) -> dict:
    """Project a finished registry onto TRIMMED_FIELDS, for `assays_benchmark.json`.

    A reading view, not a schema: `assays.json` keeps all seven fields, and every pass in the
    chain works from that. This exists because the three dropped fields answer a different
    question -- what the assay ran on and produced -- than the one the deliverable is for.

    Read with .get() and never raising, for the reason contract_warnings gives: this also runs
    over registries stored before the current schema, which carry `evidence_location` instead
    of `evidence`. Such an entry comes back with `evidence: None` rather than being skipped --
    a visible gap beats a silently missing assay.
    """
    return {
        key: {field: entry.get(field) for field in TRIMMED_FIELDS}
        for key, entry in (registry or {}).items()
        if isinstance(entry, dict)
    }


def build_prompt(source_text: str, paper_title: str) -> str:
    """Render extract_assays.txt for one paper."""
    return (
        _load_prompt("extract_assays.txt")
        .replace("{paper_title}", paper_title)
        .replace("{source_text}", source_text)
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

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssayExtractionError(f"model returned unparseable JSON: {exc}") from exc

    registry = clean_registry(parsed)
    for warning in contract_warnings(registry):
        logger.warning("assay extraction: %s", warning)
    return registry
