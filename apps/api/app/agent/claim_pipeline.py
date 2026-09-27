"""Claim abstraction v9: the five v8 passes run once, then verify -> correct, as assays do.

    1. extract       claim_abstraction_v5.abstract_claims_from_document(runs=1)   5 calls
                     (passes 1-2 one call each at temperature 0, passes 3-5 unchanged)
    2. free checks   inside claim_verifier: verbatim quotes, vocabulary, polarity, head
    3. verify        claim_verifier.verify_claims                                1 per claim
    4. drop          claim_verifier.drop_rejected -- REJECT leaves the set, recoverable
    5. correct       claim_corrector.correct_claims                1 per flagged field group
    6. filter        claim_filter on the CORRECTED claim_types                         free

The existing path (scripts/run_claim_doc.py, 5 samples per pass) is untouched, so the two can
be scored against the same benchmark. Prompts for steps 3 and 5 live in prompts/claims_v9/.
"""

from pathlib import Path

from openai import AsyncOpenAI

from app.agent.claim_abstraction_v5 import (
    CLAIMS_OUTPUT_FIELDS,
    CLAIMS_OUTPUT_SOURCE_KEYS,
    UsageTracker,
    abstract_claims_from_document,
)
from app.agent.claim_corrector import build_report as build_correction_report
from app.agent.claim_corrector import correct_claims
from app.agent.claim_filter import filter_claims_for_downstream
from app.agent.claim_verifier import build_report as build_verification_report
from app.agent.claim_verifier import drop_rejected, verify_claims
from app.agent.jats_parser import article_title, number_sentences, parse_jats_xml
from app.config import settings

#: claims.json fields. v8's writer drops `polarity`; v9 keeps it, because claim_filter reports
#: it and every verifier since has needed it.
OUTPUT_FIELDS = CLAIMS_OUTPUT_FIELDS + ("polarity",)

EXTRACTION_CALLS = 5


def paper_source_text(xml_text: str, fallback_title: str = "") -> tuple[str, str]:
    """(title, sentence-numbered text) -- the same parse the assay passes read."""
    parsed = parse_jats_xml(xml_text)
    if not parsed or not parsed.strip():
        raise ValueError("the XML yielded no text")
    return (article_title(xml_text) or fallback_title), number_sentences(parsed)


def project(claims: dict) -> dict:
    """Reduce each claim to OUTPUT_FIELDS for claims.json, remapping `assay`."""
    return {
        key: {f: claim.get(CLAIMS_OUTPUT_SOURCE_KEYS.get(f, f)) for f in OUTPUT_FIELDS}
        for key, claim in claims.items()
    }


async def run_claim_pipeline(
    xml_path: Path,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Run all six steps over one JATS paper. Returns every artifact the CLI writes."""
    xml_text = Path(xml_path).read_text(encoding="utf-8")
    title, source_text = paper_source_text(xml_text, Path(xml_path).stem)

    print(f"[1/5] extract: five v8 passes, one call each ({EXTRACTION_CALLS} calls)")
    extracted, audit = await abstract_claims_from_document(xml_text, client, model, runs=1)

    tracker = UsageTracker()
    print(f"[2/5] verify: {len(extracted)} claim(s), one call each")
    results = await verify_claims(extracted, source_text, title, client, model, tracker=tracker)

    print("[3/5] drop REJECTed claims")
    kept, rejected = drop_rejected(extracted, results)

    print("[4/5] correct flagged fields, blind")
    corrected, records, cleared = await correct_claims(
        kept, results, source_text, title, client, model, tracker=tracker)

    print("[5/5] filter on corrected claim_types")
    filtered, dropped_counts, polarity = filter_claims_for_downstream(project(corrected))

    usage = audit["token_usage"]
    extra = tracker.summary()
    usage = {
        "by_pass": {**usage["by_pass"], **extra["by_pass"]},
        "total": {k: usage["total"][k] + extra["total"][k] for k in usage["total"]},
    }
    return {
        "precorrection": extracted,
        "verification": build_verification_report(results),
        "corrections": build_correction_report(records),
        "claims": corrected,
        "claim_filtered": filtered,
        "filter_dropped": dropped_counts,
        "filter_polarity": polarity,
        "not_a_claim": audit["not_a_claim"] + rejected + cleared,
        "audit": {**audit, "token_usage": usage},
    }
