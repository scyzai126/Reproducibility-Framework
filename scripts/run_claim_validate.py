"""Judge the accuracy of every claim in an already-extracted study directory.

Reads <study_dir>/groups.json and writes <study_dir>/claims_validation.json. No PDF is
opened and no extraction is re-run — the judge works closed-book against the quotes already
recorded in each claim's `sources`.

Costs one LLM call per claim. Use --limit to smoke-test the prompt on a few claims before
paying for a whole paper.

Usage:
    python scripts/run_claim_validate.py <study_dir> [--limit N]

Example:
    python scripts/run_claim_validate.py data/claims/SDY1669_PMC7665312_pdf --limit 3
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.agent.claim_parser import _get_client
from app.agent.claim_validator import build_report, validate_groups_file


async def main(study_dir: Path, limit: int | None) -> None:
    groups_path = study_dir / "groups.json"
    if not groups_path.exists():
        print(f"No groups.json in {study_dir}")
        sys.exit(1)

    groups = json.loads(groups_path.read_text(encoding="utf-8"))
    total = len([k for k in groups if k.startswith("claim_")])
    if limit is not None:
        print(f"{total} claims in {groups_path.name}; validating the first {limit}.")
    else:
        print(f"{total} claims in {groups_path.name}; this costs {total} LLM calls.")

    results = await validate_groups_file(groups, _get_client(), limit=limit)
    report = build_report(results)

    out_path = study_dir / "claims_validation.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = report["summary"]
    print(
        f"\n{summary['accurate']}/{summary['total']} accurate, "
        f"{summary['needs_revision']} need revision, {summary['errors']} errors"
    )
    print(f"  fail counts: {summary['fail_counts']}")
    print(f"  saved {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_dir", type=Path, help="directory containing groups.json")
    parser.add_argument("--limit", type=int, default=None, help="validate only the first N claims")
    args = parser.parse_args()
    asyncio.run(main(args.study_dir, args.limit))
