"""Run the PDF vision pipeline on a local PDF file.

Usage:
    python scripts/run_vision_paper.py <pdf_path> <pubmed_id> <study_id>

Example:
    python scripts/run_vision_paper.py data/pdf/SDY1119_26682988.pdf 26682988 SDY1119

Output files are written to:
    data/claims/new_26_studies/<pubmed_id>_<study_id>/
        assay.json    - assay types inferred by vision
        claims.json   - step 1: raw claim sentences + sources
        groups.json   - step 2: structured groups + comparisons
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from openai import AsyncOpenAI
from app.agent.pdf_vision import extract_claims_from_pdf_images
from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.config import settings

OUT_BASE = Path(__file__).parent / "data" / "claims" / "new_26_studies"
MODEL = settings.OPENAI_MODEL


async def run_step2(claims: dict, client: AsyncOpenAI) -> dict:
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    print(f"Step 2: structuring {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key].get("sources", [])}}
        prompt = template.replace("{claims}", json.dumps(single, indent=2))
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        result: dict = json.loads(raw)
        val = result.get(key, {})
        val.setdefault("claim", claims[key]["claim"])
        val.setdefault("sources", claims[key].get("sources", []))
        # claim_type is carried through from the input claims rather than asked of the
        # model: claim_filter already selected on this value, so a re-derived one could
        # disagree with the filter that let the claim through.
        groups[key] = {"claim_type": claims[key].get("claim_type"), **val}
        print(f"  [{i}/{len(claim_keys)}] {key} done")
    return groups


async def main(pdf_path: Path, pubmed_id: str, study_id: str) -> None:
    out_dir = OUT_BASE / f"{pubmed_id}_{study_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Step 1: vision extraction
    print("Step 1: sending PDF pages to vision model...")
    assays, claims = await extract_claims_from_pdf_images(pdf_bytes, client, model=MODEL)
    print(f"  assays found: {list(assays.keys())}")
    print(f"  claims found: {len([k for k in claims if k.startswith('claim_')])}")

    (out_dir / "assay.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved assay.json")

    (out_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved claims.json")

    # Step 2: classify groups
    groups = await run_step2(claims, client)
    (out_dir / "groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved groups.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python scripts/run_vision_paper.py <pdf_path> <pubmed_id> <study_id>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
