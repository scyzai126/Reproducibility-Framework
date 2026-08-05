"""Regenerate claim_filtered.json from an already-extracted study directory.

Reads <study_dir>/claims.json and writes <study_dir>/claim_filtered.json — the subset whose
claim_type is downstream-actionable (see app.agent.claim_filter). No PDF is opened and no
LLM call is made, so this is free to re-run.

run_pdf_direct.py already does this as part of a full parse; this script is for backfilling
directories extracted before the filter existed.

Usage:
    python scripts/run_claim_filter.py <study_dir>

Example:
    python scripts/run_claim_filter.py data/claims/SDY1669_PMC7665312_pdf
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_filter import DOWNSTREAM_CLAIM_TYPES, filter_claims_for_downstream


def main(study_dir: Path) -> None:
    claims_path = study_dir / "claims.json"
    if not claims_path.exists():
        print(f"No claims.json in {study_dir}")
        sys.exit(1)

    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    filtered, dropped = filter_claims_for_downstream(claims)

    out_path = study_dir / "claim_filtered.json"
    out_path.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(filtered)}/{len(claims)} claims kept ({', '.join(DOWNSTREAM_CLAIM_TYPES)})")
    if dropped:
        for claim_type, count in sorted(dropped.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  dropped {count:>3}  {claim_type}")
    print(f"  saved {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_claim_filter.py <study_dir>")
        sys.exit(1)
    main(Path(sys.argv[1]))
