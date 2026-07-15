"""PDF-to-vision pipeline: render PDF pages as images and extract claims via GPT-4o vision."""

import base64
import json
import re
from pathlib import Path

import fitz  # pymupdf
from openai import AsyncOpenAI

from app.config import settings

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_MAX_PAGES = 20
_DPI = 150
_TOP_OF_PAGE_FRACTION = 0.15


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


def render_pages(pdf_bytes: bytes, page_indices: list[int], dpi: int = _DPI) -> dict[int, str]:
    """Render specific 0-indexed PDF pages to base64-encoded PNGs."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    images: dict[int, str] = {}
    for page_idx in page_indices:
        if page_idx < 0 or page_idx >= len(doc):
            continue
        pixmap = doc[page_idx].get_pixmap(matrix=matrix)
        images[page_idx] = base64.b64encode(pixmap.tobytes("png")).decode("utf-8")
    return images


def _extract_labels(paper_text: str, block_header: str) -> list[str]:
    """Pull labels (e.g. "Figure 1", "Table 2") out of a "--- <block_header> ---" block
    produced by jats_parser.parse_jats_xml."""
    match = re.search(
        rf"--- {re.escape(block_header)} ---\n(.*?)(?:\n--- \w+ ---|\Z)", paper_text, re.DOTALL
    )
    if not match:
        return []
    return re.findall(r"^\[(.+?)\]$", match.group(1), re.MULTILINE)


def extract_figure_labels(paper_text: str) -> list[str]:
    """Pull figure labels (e.g. "Figure 1", "Fig. 2") out of the "--- Figures ---" block."""
    return _extract_labels(paper_text, "Figures")


def extract_table_labels(paper_text: str) -> list[str]:
    """Pull table labels (e.g. "Table 1") out of the "--- Tables ---" block."""
    return _extract_labels(paper_text, "Tables")


def _page_blocks(page) -> list[tuple[float, str]]:
    """Return (y0, text) for each non-empty text block on the page, in reading order."""
    return [(block[1], block[4].strip()) for block in page.get_text("blocks") if block[4].strip()]


def find_label_pages(pdf_bytes: bytes, labels: list[str]) -> dict[str, list[int]]:
    """Map each figure/table label to the 0-indexed PDF page(s) that should be rendered
    as evidence.

    For each label, prefer a page where a text block *starts with* the label — that's the
    caption itself — over a page where the label merely appears mid-paragraph (an in-text
    citation like "as shown in Figure 1" or "see Table 2"). The adjacent page is pulled in
    depending on where the caption sits, since figures and tables use opposite caption
    placement conventions:
      - Figure captions sit *below* the image. A caption near the top of the page means the
        image itself is on the *previous* page.
      - Table captions sit *above* the grid. A caption near the bottom of the page means the
        table body continues onto the *next* page.
    Both checks are applied to every label regardless of type (cheap — worst case one extra
    page image) rather than branching on figure-vs-table. Falls back to a raw substring
    match if no block-start hit is found for a label (e.g. unusual caption formatting).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_blocks: list[list[tuple[float, str]]] = []
    pages_text: list[str] = []
    page_heights: list[float] = []
    for page in doc:
        blocks = _page_blocks(page)
        pages_blocks.append(blocks)
        pages_text.append("\n".join(text for _, text in blocks))
        page_heights.append(page.rect.height or 1.0)

    n_pages = len(pages_blocks)
    result: dict[str, list[int]] = {}
    for label in labels:
        norm_label = re.sub(r"\s+", " ", label or "").strip()
        if not norm_label:
            continue

        matched_pages: list[int] = []
        for page_idx, blocks in enumerate(pages_blocks):
            caption = next((b for b in blocks if b[1].startswith(norm_label)), None)
            if caption is None:
                continue
            matched_pages.append(page_idx)
            y0, _ = caption
            fraction = y0 / page_heights[page_idx]
            if page_idx > 0 and fraction < _TOP_OF_PAGE_FRACTION:
                matched_pages.append(page_idx - 1)
            if page_idx < n_pages - 1 and fraction > 1 - _TOP_OF_PAGE_FRACTION:
                matched_pages.append(page_idx + 1)
            break

        if not matched_pages:
            for page_idx, text in enumerate(pages_text):
                if norm_label in text:
                    matched_pages.append(page_idx)
                    break

        if matched_pages:
            result[label] = sorted(set(matched_pages))
    return result


def find_evidence_pages(pdf_bytes: bytes, paper_text: str) -> dict[str, list[int]]:
    """Find the PDF page(s) for every figure and table label mentioned in the JATS text."""
    labels = extract_figure_labels(paper_text) + extract_table_labels(paper_text)
    return find_label_pages(pdf_bytes, labels)


def _jats_and_figures_content(paper_text: str, pdf_bytes: bytes) -> list[dict]:
    """Build the user-message content: JATS text + the PDF pages containing each
    figure/table, attached as images."""
    evidence_pages = find_evidence_pages(pdf_bytes, paper_text)
    page_indices = sorted({idx for pages in evidence_pages.values() for idx in pages})
    images = render_pages(pdf_bytes, page_indices)

    content: list[dict] = [{"type": "text", "text": paper_text}]
    if images:
        content.append({
            "type": "text",
            "text": (
                f"The following {len(images)} image(s) are the PDF pages containing this "
                "paper's figures and tables, in page order — use them alongside the text "
                "above to read chart/plot data and table grids that the flattened caption/"
                "body text doesn't fully capture."
            ),
        })
        for page_idx in sorted(images):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{images[page_idx]}",
                    "detail": "high",
                },
            })
    return content


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    return raw


async def extract_claims_from_jats_and_figures(
    paper_text: str,
    pdf_bytes: bytes,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> tuple[dict, dict]:
    """Step 1 claim extraction from JATS-parsed text, with the PDF pages that actually
    contain each figure/table attached as images so the model can read chart/plot data and
    dense table grids that the flattened caption/body text alone doesn't capture.

    Returns:
        (assays, claims) — same contract as extract_claims_from_pdf_images.
    """
    system_prompt = (_PROMPTS_DIR / "extract_claims.txt").read_text(encoding="utf-8").strip()
    content = _jats_and_figures_content(paper_text, pdf_bytes)

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )

    result = json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))
    assays = result.pop("assays", {})
    claims = {k: v for k, v in result.items() if k.startswith("claim_")}
    return assays, claims


async def extract_assays_from_jats_xml(
    paper_text: str,
    pdf_bytes: bytes,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> dict:
    """Step 1 assay discovery via extract_assays_xml.txt: JATS-parsed text + figure/table
    page images, as the source for a step-2 extract_claims_from_jats_xml call.

    Returns:
        assays registry dict — same contract as extract_assays_from_pdf_direct.
    """
    system_prompt = (_PROMPTS_DIR / "extract_assays_xml.txt").read_text(encoding="utf-8").strip()
    content = _jats_and_figures_content(paper_text, pdf_bytes)

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )

    result = json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))
    return result.get("assays", {})


async def extract_claims_from_jats_xml(
    paper_text: str,
    pdf_bytes: bytes,
    assays: dict,
    client: AsyncOpenAI,
    model: str = settings.OPENAI_MODEL,
) -> tuple[dict, list]:
    """Claim extraction via extract_claims_XML.txt: JATS-parsed text + figure/table page
    images, given a pre-built (e.g. OBI-mapped) assay registry from a prior discovery step.

    Returns:
        (claims, abstract_unmatched_findings) — same contract as extract_claims_from_pdf_direct.
    """
    template = (_PROMPTS_DIR / "extract_claims_XML.txt").read_text(encoding="utf-8").strip()
    system_prompt = template.replace("{assays}", json.dumps(assays, indent=2, ensure_ascii=False))
    content = _jats_and_figures_content(paper_text, pdf_bytes)

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )

    result = json.loads(_strip_fences((resp.choices[0].message.content or "").strip()))
    abstract_unmatched = result.pop("abstract_unmatched_findings", [])
    claims = {k: v for k, v in result.items() if k.startswith("claim_")}
    return claims, abstract_unmatched


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
