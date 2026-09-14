"""Enrich assay.json files with OBI ontology mappings.

Reads  : data/claims/new_26_studies/<study>/assay.json
Writes : data/claims/new_26_studies/<study>/assay_OBI.json

Usage:
  python scripts/map_assays_obi.py                  # all studies
  python scripts/map_assays_obi.py 20078211_SDY1293  # single study
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STUDIES_DIR = REPO_ROOT / "data" / "claims" / "new_26_studies"

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from app.agent.assay_obi_mapper import enrich_assays_with_obi


def process_study(study_dir: Path) -> None:
    assay_path = study_dir / "assay.json"
    out_path = study_dir / "assay_OBI.json"

    if not assay_path.exists():
        print(f"  [{study_dir.name}] no assay.json — skipping")
        return

    assays = json.loads(assay_path.read_text(encoding="utf-8"))
    print(f"  [{study_dir.name}] {len(assays)} assays…", end=" ", flush=True)

    enriched = enrich_assays_with_obi(assays)

    counts = {"exact": 0, "embedding": 0, "unresolved": 0}
    for v in enriched.values():
        resource = v.get("resource", "unresolved")
        if resource == "exact_original":
            counts["exact"] += 1
        elif resource == "embedding_llm":
            counts["embedding"] += 1
        else:
            counts["unresolved"] += 1

    out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False))
    print(f"exact={counts['exact']} embedding={counts['embedding']} unresolved={counts['unresolved']} → assay_OBI.json")


def main() -> None:
    if len(sys.argv) > 1:
        study_dirs = [STUDIES_DIR / sys.argv[1]]
    else:
        study_dirs = sorted(p for p in STUDIES_DIR.iterdir() if p.is_dir())

    print(f"Processing {len(study_dirs)} study folder(s)…\n")
    for study_dir in study_dirs:
        process_study(study_dir)
    print("\nDone.")


if __name__ == "__main__":
    main()
