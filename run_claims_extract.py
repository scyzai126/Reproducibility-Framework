"""Run the claims + groups steps of the PDF-direct pipeline against an
existing assay registry (assays.json), without re-running assay discovery.

Usage:
    python run_claims_extract.py <pdf_path> <out_dir>

Example:
    python run_claims_extract.py data/pdf/SDY1260_24336226.pdf data/claims/new_26_studies/24336226_SDY1260_pdf

Reads:
    <out_dir>/assays.json           - existing assay registry (not regenerated)

Output files:
    claims.json                      - Step 1: claims + sources (extract_claims_pdf.txt)
    abstract_unmatched_findings.json - Abstract findings with no Results/Figure/Table support (only written if non-empty)
    groups.json                      - Step 2: claims structured into groups + comparisons (classify_groups.txt)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_direct import extract_claims_from_pdf_direct
from app.config import settings


async def run_group_step(claims: dict, client) -> dict:
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
    assays_path = out_dir / "assays.json"
    assays = json.loads(assays_path.read_text(encoding="utf-8"))
    print(f"Loaded existing assay registry: {list(assays.keys())}")

    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()

    print(f"Step 1: extracting claims with {settings.OPENAI_MODEL}...")
    claims, abstract_unmatched = await extract_claims_from_pdf_direct(pdf_bytes, pdf_path.name, assays, client)
    print(f"  claims found: {len(claims)}")
    print(f"  abstract findings with no Results/Figure/Table support: {len(abstract_unmatched)}")

    (out_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims.json")

    unmatched_path = out_dir / "abstract_unmatched_findings.json"
    if abstract_unmatched:
        unmatched_path.write_text(json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  saved abstract_unmatched_findings.json")
    elif unmatched_path.exists():
        unmatched_path.unlink()

    groups = await run_group_step(claims, client)
    (out_dir / "groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved groups.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python run_claims_extract.py <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
