"""Run assay discovery via extract_assays_xml.txt: JATS-parsed text + the PDF pages
containing each figure/table, attached as images.

Usage:
    python scripts/run_assays_xml.py <jats_text_path> <pdf_path> <out_path>

Example:
    python scripts/run_assays_xml.py \\
        data/claims/SDY1119_26682988_jats_figures/jats_text.txt \\
        data/pdf/26papers/SDY1119_26682988.pdf \\
        data/claims/SDY1119_26682988_jats_xml/assays_xml.json
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client
from app.agent.pdf_vision import extract_assays_from_jats_xml
from app.config import settings


async def main(jats_text_path: Path, pdf_path: Path, out_path: Path) -> None:
    paper_text = jats_text_path.read_text(encoding="utf-8")
    pdf_bytes = pdf_path.read_bytes()
    print(f"JATS text: {len(paper_text)} chars from {jats_text_path}")
    print(f"PDF: {len(pdf_bytes):,} bytes from {pdf_path}")

    client = _get_client()
    print(f"Extracting assays with {settings.OPENAI_MODEL}...")
    assays = await extract_assays_from_jats_xml(paper_text, pdf_bytes, client)
    print(f"  assays found: {list(assays.keys())}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python scripts/run_assays_xml.py <jats_text_path> <pdf_path> <out_path>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
