"""Run classify_groups (step 2) on an existing claims file and write groups output."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.claim_parser import _get_client, _load_prompt, _strip_fences

STUDY = "SDY1119"
CLAIMS_PATH = Path("data/claims/new_26_studies/claims_LLM_SDY1119.json")
OUT_PATH = Path("data/claims/new_26_studies/groups_LLM_SDY1119.json")
MODEL = "gpt-4o"


async def main():
    raw_claims = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))

    # Keep only claim + sources — strip any old groups fields
    claims = {
        k: {"claim": v["claim"], "sources": v["sources"]}
        for k, v in raw_claims.items()
        if k.startswith("claim_")
    }
    print(f"Loaded {len(claims)} claims from {CLAIMS_PATH}")

    client = _get_client()
    template = _load_prompt("classify_groups.txt")

    print(f"Running classify_groups on {len(claims)} claims sequentially…")
    groups_json = {}
    for i, key in enumerate(claims, 1):
        single = {key: claims[key]}
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
        val.setdefault("sources", claims[key]["sources"])
        groups_json[key] = val
        print(f"  [{i}/{len(claims)}] {key} done")
        await asyncio.sleep(3)  # stay under 30k TPM
    print(f"  done — {len(groups_json)} structured claims")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(groups_json, indent=2, ensure_ascii=False))
    print(f"Written → {OUT_PATH}")


asyncio.run(main())
