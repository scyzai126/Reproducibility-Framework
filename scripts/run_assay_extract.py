"""Run only the assay-discovery step of the PDF-direct pipeline.

Sends the raw PDF straight to the model using extract_assays_pdf.txt and
writes just the assay registry — no claim extraction, no group classification.

Usage:
    python scripts/run_assay_extract.py <pdf_path> <out_dir>

Example:
    python scripts/run_assay_extract.py data/pdf/SDY1260_24336226.pdf data/claims/new_26_studies/24336226_SDY1260_pdf

Output files:
    assays.json - assay registry (original_name, sample_type, readouts, confidence)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client
from app.agent.pdf_direct import extract_assays_from_pdf_direct
from app.config import settings


async def main(pdf_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()
    print(f"Identifying assays with {settings.OPENAI_MODEL}...")
    assays = await extract_assays_from_pdf_direct(pdf_bytes, pdf_path.name, client)
    print(f"  assays found: {list(assays.keys())}")

    (out_dir / "assays.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved assays.json in {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/run_assay_extract.py <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
