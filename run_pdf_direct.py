"""Run the PDF-direct pipeline: send the raw PDF bytes straight to the model
(no local page rendering) and let the API's own PDF handling do the reading.

Usage:
    python run_pdf_direct.py <pdf_path> <out_dir>

Example:
    python run_pdf_direct.py data/pdf/SDY1260_24336226.pdf data/claims/new_26_studies/24336226_SDY1260_pdf

Output files:
    assays.json                     - Step 1: assay registry (extract_assays_pdf.txt)
    claims.json                     - Step 2: claims + sources (extract_claims_pdf.txt)
    abstract_unmatched_findings.json - Abstract findings with no Results/Figure/Table support (only written if non-empty)
    groups.json                     - Step 3: claims structured into groups + comparisons (classify_groups.txt)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_direct import extract_assays_from_pdf_direct, extract_claims_from_pdf_direct
from app.config import settings


async def run_step2(claims: dict, client) -> dict:
    """Structure each claim into comparison_strategy + groups + comparison via classify_groups.txt."""
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    print(f"Step 2: structuring {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key].get("sources", [])}}
        prompt = template.replace("{claims}", json.dumps(single, indent=2))
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = _strip_fences((resp.choices[0].message.content or "").strip())
        result: dict = json.loads(raw)
        val = result.get(key, {})
        val.setdefault("claim", claims[key]["claim"])
        val.setdefault("sources", claims[key].get("sources", []))
        groups[key] = val
        print(f"  [{i}/{len(claim_keys)}] {key} done")
    return groups


async def main(pdf_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()

    print(f"Step 1: identifying assays with {settings.OPENAI_MODEL}...")
    assays = await extract_assays_from_pdf_direct(pdf_bytes, pdf_path.name, client)
    print(f"  assays found: {list(assays.keys())}")

    print(f"Step 2: extracting claims with {settings.OPENAI_MODEL}...")
    claims, abstract_unmatched = await extract_claims_from_pdf_direct(pdf_bytes, pdf_path.name, assays, client)
    print(f"  claims found: {len(claims)}")
    print(f"  abstract findings with no Results/Figure/Table support: {len(abstract_unmatched)}")

    (out_dir / "assays.json").write_text(json.dumps(assays, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved assays.json")

    (out_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims.json")

    if abstract_unmatched:
        (out_dir / "abstract_unmatched_findings.json").write_text(
            json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("  saved abstract_unmatched_findings.json")

    groups = await run_step2(claims, client)
    (out_dir / "groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved groups.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python run_pdf_direct.py <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
