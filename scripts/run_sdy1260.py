"""Run full two-step pipeline for SDY1260 and write claims + groups JSON."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import (
    _fetch_paper_text,
    _get_client,
    _load_prompt,
    _strip_fences,
)

STUDY = "SDY1260"
PAPER_URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC3946932/"
ASSAY_METHODS = ["ELISA", "Flow Cytometry", "Luminex xMAP", "Transcription profiling by array"]
OUT_DIR = Path("data/claims/new_26_studies")
CLAIMS_PATH = OUT_DIR / f"claims_LLM_{STUDY}.json"
GROUPS_PATH = OUT_DIR / f"groups_LLM_{STUDY}.json"
MODEL = "gpt-4o"


async def main():
    print("Fetching paper text…")
    paper_text = _fetch_paper_text(PAPER_URL)
    print(f"  {len(paper_text):,} chars")

    client = _get_client()
    assay_list = ", ".join(ASSAY_METHODS)

    # ── Step 1: extract claims ────────────────────────────────────────────────
    print("Step 1: extracting claims…")
    step1_system = _load_prompt("extract_claims.txt").replace("{assay_methods}", assay_list)
    resp1 = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": step1_system},
            {"role": "user", "content": paper_text},
        ],
        temperature=0,
    )
    raw1 = _strip_fences((resp1.choices[0].message.content or "").strip())
    claims = json.loads(raw1)
    print(f"  got {len(claims)} claims")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CLAIMS_PATH.write_text(json.dumps(claims, indent=2, ensure_ascii=False))
    print(f"  Written → {CLAIMS_PATH}")

    # ── Step 2: classify groups ───────────────────────────────────────────────
    print("Step 2: classifying groups…")
    template = _load_prompt("classify_groups.txt")
    claim_keys = [k for k in claims if k.startswith("claim_")]
    groups: dict = {}

    for i, key in enumerate(claim_keys, 1):
        single = {key: {"claim": claims[key]["claim"], "sources": claims[key]["sources"]}}
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
        groups[key] = val
        print(f"  [{i}/{len(claim_keys)}] {key} done")
        await asyncio.sleep(3)

    GROUPS_PATH.write_text(json.dumps(groups, indent=2, ensure_ascii=False))
    print(f"  Written → {GROUPS_PATH}")
    print("Done.")


asyncio.run(main())
