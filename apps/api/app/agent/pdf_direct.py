"""PDF-direct pipeline: send raw PDF bytes straight to the model (no local page
rendering) and let the API's own PDF handling do the reading.

Independent extraction (run concurrently, reconciled afterward by
app.agent.assay_claim_linker):
    1. extract_assays_from_pdf_direct  - assay discovery (extract_assays_pdf.txt)
    2. extract_claims_from_pdf_direct  - claim extraction (extract_claims_pdf.txt),
       self-names its own assay per claim, does not see the assay registry
"""

import asyncio
import base64
import json

from openai import AsyncOpenAI

from app.config import settings
from app.agent.assay_claim_linker import attach_assay_links, reconcile_claims_with_assays
from app.agent.assay_obi_mapper import enrich_assays_with_obi
from app.agent.claim_parser import _load_prompt, _strip_fences, load_prompt_with_claim_types


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


async def extract_assays_from_pdf_direct(pdf_bytes: bytes, filename: str, client: AsyncOpenAI) -> dict:
    """Send raw PDF bytes to the model and extract the assay registry only."""
    system_prompt = _load_prompt("extract_assays_pdf.txt")

    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    _pdf_file_content(pdf_bytes, filename),
                    {"type": "text", "text": "Identify the assays used in this paper as instructed."},
                ],
            },
        ],
        temperature=0,
    )

    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    result: dict = json.loads(raw)
    return result.get("assays", {})


async def extract_claims_from_pdf_direct(
    pdf_bytes: bytes, filename: str, client: AsyncOpenAI
) -> tuple[dict, list]:
    """Send raw PDF bytes to the model and extract claims independently — each claim
    self-names its own assay; it does not see the assay registry from step 1."""
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
    result: dict = json.loads(raw)
    abstract_unmatched = result.pop("abstract_unmatched_findings", [])
    claims = {k: v for k, v in result.items() if k.startswith("claim_")}
    return claims, abstract_unmatched


async def extract_step1_from_pdf_direct(pdf_bytes: bytes, filename: str, client: AsyncOpenAI) -> dict:
    """Run the full parallel assay+claim extraction pipeline against a PDF and return a
    step1_json-shaped dict — {"assays": {...}, "claim_1": {"claim": ..., "sources": [...]},
    ...} — suitable for injection as `step1_claims`/`cached_step1` into the shared
    _run_paper_pipeline -> parse_paper_claims_from_text machinery (same contract as
    extract_claims_from_pdf_images' output for the vision pipeline).

    Runs assay discovery and claim extraction concurrently (independent passes),
    reconciles them (exact/alias match, then a paper-grounded validation call for the
    rest), and OBI-enriches the final registry — see app.agent.assay_claim_linker.
    """
    assays, (claims, _abstract_unmatched) = await asyncio.gather(
        extract_assays_from_pdf_direct(pdf_bytes, filename, client),
        extract_claims_from_pdf_direct(pdf_bytes, filename, client),
    )

    paper_content = [
        _pdf_file_content(pdf_bytes, filename),
        {"type": "text", "text": "Validate the candidate assay-claim pairings against this paper as instructed."},
    ]
    resolved, merged_assays, unlinked_claims = await reconcile_claims_with_assays(
        claims, assays, paper_content, client
    )

    final_assays = enrich_assays_with_obi(merged_assays)

    # Every extracted claim carries forward, including any the linker left unlinked --
    # reconciliation resolves which assay a claim belongs to, it does not judge the claim.
    linked = attach_assay_links(claims, resolved, merged_assays, unlinked_claims)

    step1_json: dict = {"assays": final_assays}
    for claim_key, claim in linked.items():
        step1_json[claim_key] = {"claim": claim.get("claim", ""), "sources": claim.get("sources", [])}

    return step1_json
