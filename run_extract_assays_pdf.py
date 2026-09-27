"""Test the standalone assay-extraction prompt (extract_assays_pdf.txt) against a local PDF.

Usage:
  python run_extract_assays_pdf.py --pdf data/pdf/SDY180_23601689.pdf --study SDY180
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _strip_fences
from app.agent.pdf_vision import pdf_to_images
from app.config import settings

REPO_ROOT = Path(__file__).parent
PROMPTS_DIR = REPO_ROOT / "apps" / "api" / "app" / "prompts"
OUT_DIR = REPO_ROOT / "data" / "claims"


async def extract_assays(pdf_bytes: bytes) -> dict:
    client = _get_client()
    system_prompt = (PROMPTS_DIR / "extract_assays_pdf.txt").read_text(encoding="utf-8").strip()
    images = pdf_to_images(pdf_bytes)

    content: list[dict] = [
        {"type": "text", "text": f"The following {len(images)} image(s) are rendered pages of a scientific paper PDF, in order. Extract the assay list as instructed."},
    ]
    for b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
        })

    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    return json.loads(raw)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="Path to the PDF file")
    parser.add_argument("--study", required=True, help="Study ID (e.g. SDY180)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)

    out_dir = OUT_DIR / f"{args.study}_assay_extraction_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.study}] PDF: {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")
    pdf_bytes = pdf_path.read_bytes()

    print(f"[{args.study}] Sending to vision model ({settings.OPENAI_MODEL})…")
    result = await extract_assays(pdf_bytes)

    (out_dir / "assays_raw.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    n_assays = len(result.get("assays", []))
    print(f"[{args.study}] {n_assays} assays → {out_dir.name}/assays_raw.json")
    print(f"[{args.study}] Done.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
