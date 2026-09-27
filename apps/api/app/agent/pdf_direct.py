"""PDF-direct pipeline: send raw PDF bytes straight to the model (no local page
rendering) and let the API's own PDF handling do the reading.

One extraction pass: extract_claims_from_pdf_direct (extract_claims_pdf.txt) pulls the
claims, each naming the assay that generated it. The assay registry is then derived from
those names by app.agent.assay_registry -- there is no separate assay-discovery call and
nothing left to reconcile.
"""

import base64
import json

from openai import AsyncOpenAI

from app.config import settings
from app.agent.assay_obi_mapper import enrich_assays_with_obi
from app.agent.assay_registry import registry_from_claims
from app.agent.claim_parser import _strip_fences, load_prompt_with_claim_types


def _pdf_file_content(pdf_bytes: bytes, filename: str) -> dict:
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    return {
        "type": "file",
        "file": {
            "filename": filename,
            "file_data": f"data:application/pdf;base64,{b64}",
        },
    }


def _build_claims_prompt() -> str:
    """Assemble the claim-extraction prompt, injecting the claim_type vocabulary.

    Shares its substitution with the accuracy judge (validate_claims.txt), which audits the
    claim_type this prompt assigns — the two must read the same vocabulary file.
    """
    return load_prompt_with_claim_types("extract_claims_pdf.txt")


async def extract_claims_from_pdf_direct(
    pdf_bytes: bytes, filename: str, client: AsyncOpenAI
) -> tuple[dict, list]:
    """Send raw PDF bytes to the model and extract claims — each claim names the assay
    that generated it."""
    system_prompt = _build_claims_prompt()

    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    _pdf_file_content(pdf_bytes, filename),
                    {"type": "text", "text": "Extract assay-based claims from this paper as instructed."},
                ],
            },
        ],
        temperature=0,
    )

    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    result: dict = json.loads(raw, strict=False)
    abstract_unmatched = result.pop("abstract_unmatched_findings", [])
    claims = {k: v for k, v in result.items() if k.startswith("claim_")}
    return claims, abstract_unmatched


async def extract_step1_from_pdf_direct(pdf_bytes: bytes, filename: str, client: AsyncOpenAI) -> dict:
    """Run claim extraction against a PDF and return a step1_json-shaped dict —
    {"assays": {...}, "claim_1": {"claim": ..., "sources": [...]}, ...} — suitable for
    injection as `step1_claims`/`cached_step1` into the shared _run_paper_pipeline ->
    parse_paper_claims_from_text machinery (same contract as
    extract_claims_from_pdf_images' output for the vision pipeline).

    The registry is folded up from the assay each claim named for itself and then
    OBI-enriched — see app.agent.assay_registry.
    """
    claims, _abstract_unmatched = await extract_claims_from_pdf_direct(pdf_bytes, filename, client)

    final_assays = enrich_assays_with_obi(registry_from_claims(claims))

    step1_json: dict = {"assays": final_assays}
    for claim_key, claim in claims.items():
        step1_json[claim_key] = {"claim": claim.get("claim", ""), "sources": claim.get("sources", [])}

    return step1_json
