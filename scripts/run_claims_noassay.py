"""Run claim extraction directly against a PDF using extract_claims pdf_noassay.txt
(no pre-built assay registry — the model identifies assays inline).

Usage:
    python scripts/run_claims_noassay.py <pdf_path> <out_dir>
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_direct import _pdf_file_content
from app.config import settings


async def extract_claims_noassay(pdf_bytes: bytes, filename: str, client) -> tuple[dict, list]:
    system_prompt = _load_prompt("extract_claims pdf_noassay.txt")

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


async def main(pdf_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()

    print(f"Extracting claims with {settings.OPENAI_MODEL} (no assay registry)...")
    claims, abstract_unmatched = await extract_claims_noassay(pdf_bytes, pdf_path.name, client)
    print(f"  claims found: {len(claims)}")
    print(f"  abstract findings with no Results/Figure/Table support: {len(abstract_unmatched)}")

    (out_dir / "claims_noassay.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  saved claims_noassay.json")

    if abstract_unmatched:
        (out_dir / "abstract_unmatched_findings_noassay.json").write_text(
            json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("  saved abstract_unmatched_findings_noassay.json")

    print(f"\nDone. Files written to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/run_claims_noassay.py <pdf_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
