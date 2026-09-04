"""Extract a paper's assay registry in one LLM call.

The same job the `extract-assay-methods` skill does by reading, expressed as a prompt so the
agent can run it when a user asks for a paper's assays. The skill remains the authority on
the rules; prompts/extract_assays.txt is those rules written for a model that gets one shot
at the paper instead of an interactive read.

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

#: The seven-field contract, in the order the skill documents them. Anything else a model
#: returns is dropped: `confidence` and `claim_role` are the two it reaches for unprompted,
#: and both were removed from this schema on purpose.
ENTRY_FIELDS = ("name_in_paper", "aliases", "platform", "sample_type", "readouts",
                "source", "evidence")

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
    the same string. `source` is defaulted to "methods" only when the model omitted it
    entirely -- an invented value is not silently corrected to a valid one, because that
    would hide the classification pass going wrong.
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
        "source": source if source in _SOURCE_VALUES else ("methods" if source is None else source),
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
    """
    warnings: list[str] = []
    for key, entry in registry.items():
        evidence = entry["evidence"]
        if not evidence["quote"]:
            warnings.append(f"{key}: no evidence quote")
        if not evidence["sentence_ids"]:
            warnings.append(f"{key}: evidence cites no sentence_ids")
        if entry["source"] not in _SOURCE_VALUES:
            warnings.append(f"{key}: source is {entry['source']!r}, not 'methods' or 'results'")
        if entry["name_in_paper"] != key:
            warnings.append(f"{key}: name_in_paper is {entry['name_in_paper']!r}, not the key")
    return warnings


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
