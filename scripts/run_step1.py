"""One-off script: run extract_claims step 1 for SDY1669 and write step1.json."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import (
    get_assay_methods,
    parse_paper_claims_step1_only,
    _fetch_paper_text,
    _get_client,
    _load_prompt,
    _strip_fences,
)
from app.config import settings

STUDY = "SDY2189"
PAPER_URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC8761119/"
OUT_PATH = Path("data/claims/SDY2189_PMC8761119/claims.json")


async def main():
    print("Fetching paper text…")
    paper_text = _fetch_paper_text(PAPER_URL)
    print(f"  {len(paper_text):,} chars")

    assay_methods = get_assay_methods(STUDY)
    print(f"  assay methods: {assay_methods}")

    print("Running extract_claims (step 1)…")
    # Use gpt-4o as fallback if gpt-5.4 hits biology safety filter
    client = _get_client()
    assay_list = ", ".join(assay_methods)
    step1_system = _load_prompt("extract_claims.txt").replace("{assay_methods}", assay_list)
    resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": step1_system},
            {"role": "user", "content": paper_text},
        ],
        temperature=0,
    )
    import json as _json
    raw = _strip_fences((resp.choices[0].message.content or "").strip())
    result = _json.loads(raw)
    print(f"  got {len(result)} claims")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Written → {OUT_PATH}")


asyncio.run(main())
