"""Map a study's assays.json to OBI ontology terms using a given standard vocabulary.

Matching chain (stops at first hit): exact match on name_in_paper, exact match on
normalized_name, then embedding top-10 + LLM pick — restricted to the vocabulary
in --terms.

Usage:
    python run_obi_map.py <study_dir> [--terms data/obi_immuno_assay_terms.json]

Example:
    python run_obi_map.py data/claims/new_26_studies/23601689_SDY180_pdf \\
        --terms data/obi_immuno_assay_terms.json

Reads  : <study_dir>/assays.json
Writes : <study_dir>/assays_OBI.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from app.agent.assay_obi_mapper import enrich_assays_with_obi

REPO_ROOT = Path(__file__).parent
DEFAULT_TERMS = REPO_ROOT / "data" / "obi_assay_terms.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("study_dir", help="Folder containing assays.json")
    parser.add_argument("--terms", default=str(DEFAULT_TERMS), help="OBI terms JSON to use as the standard vocabulary")
    args = parser.parse_args()

    study_dir = Path(args.study_dir)
    assays_path = study_dir / "assays.json"
    out_path = study_dir / "assays_OBI.json"
    terms_path = Path(args.terms)

    assays = json.loads(assays_path.read_text(encoding="utf-8"))
    print(f"{len(assays)} assays in {assays_path}")
    print(f"Standard vocabulary: {terms_path}")

    enriched = enrich_assays_with_obi(assays, terms_path=terms_path)

    counts = {"exact": 0, "embedding": 0, "unresolved": 0}
    for name, v in enriched.items():
        resource = v.get("resource", "unresolved")
        if resource in ("exact_original", "exact_normalized"):
            counts["exact"] += 1
        elif resource == "embedding_llm":
            counts["embedding"] += 1
        else:
            counts["unresolved"] += 1
        print(f"  {name} → {v.get('obi_id')} | {v.get('obi_label')} ({resource})")

    out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nexact={counts['exact']} embedding={counts['embedding']} unresolved={counts['unresolved']}")
    print(f"Written → {out_path}")


if __name__ == "__main__":
    main()
