"""PDF-direct pipeline: send raw PDF bytes straight to the model (no local page
rendering) and let the API's own PDF handling do the reading.

Two-step extraction:
    1. extract_assays_from_pdf_direct  - assay discovery only (extract_assays_pdf.txt)
    2. extract_claims_from_pdf_direct  - claim extraction given a known assay
       registry (extract_claims_pdf.txt)
"""

import base64
import json

from openai import AsyncOpenAI

from app.config import settings
from app.agent.claim_parser import _load_prompt, _strip_fences


def _pdf_file_content(pdf_bytes: bytes, filename: str) -> dict:
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    return {
        "type": "file",
        "file": {
            "filename": filename,
            "file_data": f"data:application/pdf;base64,{b64}",
        },
    }


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
    pdf_bytes: bytes, filename: str, assays: dict, client: AsyncOpenAI
) -> tuple[dict, list]:
    """Send raw PDF bytes + a pre-built assay registry to the model and extract claims."""
    template = _load_prompt("extract_claims_pdf.txt")
    system_prompt = template.replace("{assays}", json.dumps(assays, indent=2, ensure_ascii=False))

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
