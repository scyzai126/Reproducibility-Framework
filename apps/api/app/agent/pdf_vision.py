"""PDF-to-vision pipeline: render PDF pages as images and extract claims via GPT-4o vision."""

import base64
import json
from pathlib import Path

import fitz  # pymupdf
from openai import AsyncOpenAI

from app.config import settings

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_MAX_PAGES = 20
_DPI = 150


def pdf_to_images(pdf_bytes: bytes, dpi: int = _DPI, max_pages: int = _MAX_PAGES) -> list[str]:
    """Render each PDF page as a PNG and return a list of base64-encoded strings.

    Args:
        pdf_bytes: raw PDF file content
        dpi: render resolution (150 gives good text quality at reasonable token cost)
        max_pages: cap to stay within OpenAI's per-request image limit

    Returns:
        List of base64-encoded PNG strings, one per page (up to max_pages).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    images: list[str] = []
    for page in doc:
        if len(images) >= max_pages:
            break
        pixmap = page.get_pixmap(matrix=matrix)
        png_bytes = pixmap.tobytes("png")
        images.append(base64.b64encode(png_bytes).decode("utf-8"))
    return images


async def extract_claims_from_pdf_images(
    pdf_bytes: bytes,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> tuple[dict, dict]:
    """Convert PDF pages to images and extract assay list + claims via vision.

    Returns:
        (assays, claims) where:
          assays = {"CyTOF": {"sample_type": "...", "readouts": "..."}, ...}
          claims = {"claim_1": {"claim": "...", "sources": [...]}, ...}
    """
    system_prompt = (_PROMPTS_DIR / "extract_claims_vision.txt").read_text(encoding="utf-8").strip()
    images = pdf_to_images(pdf_bytes)

    content: list[dict] = [
        {"type": "text", "text": f"The following {len(images)} image(s) are rendered pages of a scientific paper PDF, in order. Extract assay-based claims as instructed."},
    ]
    for b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
                "detail": "high",
            },
        })

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )

    raw = (resp.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    result = json.loads(raw)
    assays = result.pop("assays", {})
    claims = {k: v for k, v in result.items() if k.startswith("claim_")}
    return assays, claims
