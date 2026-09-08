"""Run the group-structuring step (classify_groups.txt) against an existing
claims_noassay.json file, producing claims_groups.json.

Usage:
    python scripts/run_groups_noassay.py <claims_json_path> <out_dir>
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences
from app.config import settings


async def run_group_step(claims: dict, client) -> dict:
    template = _load_prompt("classify_groups.txt")
    groups: dict = {}
    claim_keys = [k for k in claims if k.startswith("claim_")]
    print(f"Structuring {len(claim_keys)} claims...")
    for i, key in enumerate(claim_keys, 1):
        single = {
            key: {
                "claim": claims[key]["claim"],
                "claim_type": claims[key].get("claim_type"),
                "sources": claims[key].get("sources", []),
            }
        }
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
        # claim_type and assay_method are carried through from the input claims rather than
        # asked of the model: claim_filter already selected on claim_type, so a re-derived
        # one could disagree with the filter that let the claim through, and the assay is
        # already settled upstream as `assay_method_in_paper` — re-extracting it from the
        # claim sentence would let the wording drift from the registry the OBI mapping is
        # built on. The model may echo either field back, so discard those before merging:
        # `**val` would otherwise override the inherited values and quietly break the chain.
        val.pop("claim_type", None)
        val.pop("assay_method", None)
        groups[key] = {
            "claim_type": claims[key].get("claim_type"),
            "assay_method": claims[key].get("assay_method_in_paper"),
            **val,
        }
        print(f"  [{i}/{len(claim_keys)}] {key} done")
    return groups


async def main(claims_path: Path, out_dir: Path) -> None:
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(claims)} claims from {claims_path.name}")

    client = _get_client()
    groups = await run_group_step(claims, client)

    out_path = out_dir / "claims_groups.json"
    out_path.write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/run_groups_noassay.py <claims_json_path> <out_dir>")
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
