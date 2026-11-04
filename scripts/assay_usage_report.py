#!/usr/bin/env python3
"""Sum the assay usage ledger by month: what the extraction spent, in tokens and dollars.

The ledger (data/assay_usage_ledger.csv) gets one row per paid run from the pipeline itself
(assay_service.assay_report) and from run_assay_merge.py's paid passes. This script only reads
it. No API call.

Usage:
    python3 scripts/assay_usage_report.py                   # one line per month
    python3 scripts/assay_usage_report.py --month 2026-11   # that month's rows, one per run
    python3 scripts/assay_usage_report.py --backfill data/31paper_assays/assay_result_v4
        # add rows for registries whose assays_raw.json carries usage but are not in the
        # ledger yet (runs made before the ledger existed), dated by the raw file's mtime
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.agent import assay_ledger  # noqa: E402


def print_months(rows: list[dict]) -> None:
    if not rows:
        print(f"ledger is empty: {assay_ledger.LEDGER_PATH}")
        return
    print(f"{'month':7} {'runs':>5} {'papers':>6} {'calls':>6} {'prompt':>11} {'cached':>11} "
          f"{'completion':>10} {'usd':>8}")
    total_usd = 0.0
    for m in assay_ledger.monthly_summary(rows):
        flag = f"  ({m['unpriced']} unpriced)" if m["unpriced"] else ""
        print(f"{m['month']:7} {m['runs']:5} {m['papers']:6} {m['calls']:6} "
              f"{m['prompt_tokens']:11,} {m['cached_tokens']:11,} {m['completion_tokens']:10,} "
              f"{m['usd']:8.2f}{flag}")
        total_usd += m["usd"]
    print(f"{'total':7} {len(rows):5} {'':6} {sum(r['calls'] for r in rows):6} "
          f"{sum(r['prompt_tokens'] for r in rows):11,} "
          f"{sum(r['cached_tokens'] for r in rows):11,} "
          f"{sum(r['completion_tokens'] for r in rows):10,} {total_usd:8.2f}")


def print_runs(rows: list[dict], month: str) -> None:
    picked = [r for r in rows if (r.get("date") or "").startswith(month)]
    if not picked:
        print(f"no runs in {month}")
        return
    print(f"{'date':19} {'pmid':9} {'study':8} {'calls':>5} {'prompt':>9} {'cached':>9} "
          f"{'compl':>6} {'usd':>6}  registry")
    for r in picked:
        usd = f"{r['usd']:.2f}" if r["usd"] is not None else "?"
        print(f"{r['date']:19} {r['pubmed_id']:9} {r['study_accession']:8} {r['calls']:5} "
              f"{r['prompt_tokens']:9,} {r['cached_tokens']:9,} {r['completion_tokens']:6,} "
              f"{usd:>6}  {r['registry_dir']}")
    usd_total = sum(r["usd"] or 0 for r in picked)
    print(f"{month}: {len(picked)} run(s), ${usd_total:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", metavar="YYYY-MM", default="",
                        help="list that month's runs instead of the monthly totals")
    parser.add_argument("--backfill", type=Path, metavar="REGISTRY_ROOT", default=None,
                        help="add rows for registries under this folder that are not in the "
                             "ledger yet")
    args = parser.parse_args()

    if args.backfill is not None:
        added = assay_ledger.backfill(args.backfill)
        for row in added:
            print(f"  added  {row['registry_dir']}  {row['calls']} call(s)  ${row['usd'] or '?'}")
        print(f"{len(added)} row(s) added to {assay_ledger.LEDGER_PATH.relative_to(REPO_ROOT)}")

    rows = assay_ledger.read_rows()
    if args.month:
        print_runs(rows, args.month)
    else:
        print_months(rows)
