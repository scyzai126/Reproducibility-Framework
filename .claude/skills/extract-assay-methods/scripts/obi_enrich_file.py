"""Enrich an assays.json file (in the format this skill outputs) with OBI
ontology mappings, using this repo's existing OBI matching chain:

  1. Exact match on name_in_paper   -> resource: exact_original,  confidence: "high"
  2. Exact match on normalized_name -> resource: exact_normalized, confidence: "high"
  3. Embedding top-10 + LLM pick    -> resource: embedding_llm,   confidence: <similarity float>

This only works when run from inside the claim_reprodue_agent repo: it imports
apps/api/app/agent/assay_obi_mapper.py and needs OPENAI_API_KEY set in the
environment plus this skill's references/obi_assay_terms.json and
references/obi_assay_embeddings.json. If any of that isn't available, OBI
mapping isn't possible in the current environment -- skip this step and say so.

Usage:
  python scripts/obi_enrich_file.py <path/to/assays.json> [output_path]

If output_path is omitted, writes <input>_OBI.json alongside the input.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from app.agent.assay_obi_mapper import enrich_assays_with_obi


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/obi_enrich_file.py <path/to/assays.json> [output_path]")
        sys.exit(1)

    in_path = Path(sys.argv[1])
    assays = json.loads(in_path.read_text(encoding="utf-8"))

    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else in_path.with_name(f"{in_path.stem}_OBI.json")

    print(f"Mapping {len(assays)} assay(s) to OBI terms...")
    enriched = enrich_assays_with_obi(assays)

    counts = {"exact": 0, "embedding": 0, "unresolved": 0}
    for v in enriched.values():
        resource = v.get("resource", "unresolved")
        if resource in ("exact_original", "exact_normalized"):
            counts["exact"] += 1
        elif resource == "embedding_llm":
            counts["embedding"] += 1
        else:
            counts["unresolved"] += 1

    out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"exact={counts['exact']} embedding={counts['embedding']} unresolved={counts['unresolved']} -> {out_path}")


if __name__ == "__main__":
    main()
