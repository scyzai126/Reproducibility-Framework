"""Run claim extraction against a PDF using extract_claims pdf_noassay.txt, fed
with a pre-built assay registry mapped to OBI ontology terms (assays_OBI.json).

Each output claim carries an "assay" object {name_in_paper, obi_id, obi_label}
naming the registry entry it belongs to.

Usage:
    python run_claims_with_obi.py <pdf_path> <study_dir>

Reads:
    <study_dir>/assays_OBI.json  - assay registry with obi_id/obi_label (from run_obi_map.py)

Writes:
    <study_dir>/claims_with_obi.json
    <study_dir>/abstract_unmatched_findings_with_obi.json  (only if non-empty)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.agent.pdf_direct import _pdf_file_content
from app.config import settings


def _build_registry_for_prompt(assays_obi: dict) -> dict:
    """Trim the full assays_OBI.json down to what the claims prompt needs."""
    registry = {}
    for name, v in assays_obi.items():
        registry[name] = {
            "name_in_paper": v.get("name_in_paper") or name,
            "obi_id": v.get("obi_id"),
            "obi_label": v.get("obi_label"),
        }
    return registry


async def extract_claims_with_obi(
    pdf_bytes: bytes, filename: str, registry: dict, client
) -> tuple[dict, list]:
    template = _load_prompt("extract_claims pdf_noassay.txt")
    system_prompt = template.replace("{assays}", json.dumps(registry, indent=2, ensure_ascii=False))

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


async def main(pdf_path: Path, study_dir: Path) -> None:
    assays_obi_path = study_dir / "assays_OBI.json"
    assays_obi = json.loads(assays_obi_path.read_text(encoding="utf-8"))
    registry = _build_registry_for_prompt(assays_obi)
    print(f"Loaded assay-OBI registry: {list(registry.keys())}")

    pdf_bytes = pdf_path.read_bytes()
    print(f"PDF loaded: {len(pdf_bytes):,} bytes")

    client = _get_client()

    print(f"Extracting claims with {settings.OPENAI_MODEL} (assay+OBI registry supplied)...")
    claims, abstract_unmatched = await extract_claims_with_obi(pdf_bytes, pdf_path.name, registry, client)
    print(f"  claims found: {len(claims)}")
    print(f"  abstract findings with no Results/Figure/Table support: {len(abstract_unmatched)}")

    out_path = study_dir / "claims_with_obi.json"
    out_path.write_text(json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {out_path.name}")

    unmatched_path = study_dir / "abstract_unmatched_findings_with_obi.json"
    if abstract_unmatched:
        unmatched_path.write_text(json.dumps(abstract_unmatched, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  saved {unmatched_path.name}")

    print(f"\nDone. Files written to {study_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python run_claims_with_obi.py <pdf_path> <study_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
