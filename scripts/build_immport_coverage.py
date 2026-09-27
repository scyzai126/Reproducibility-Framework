#!/usr/bin/env python3
"""Precompute the Corpus tab's "In ImmPort" column and store it next to the assay table.

For every row of the corpus table (`scripts/build_assay_table.py` -> `all_assays_OBI.json`) this
asks whether ImmPort's `experiment` table records that assay for that study, using
`assay_immport.check_rows` -- the same resolver the query builder uses, so a "yes" here is one a
claim query would find. `GET /agent/assay-immport` then serves the stored file instead of
sweeping ImmPort on every page load.

**Free by default: SQL only.** `--llm` also sends each row SQL cannot place to the model, one call
per row, answered from `immport_llm_cache.json` when that row was asked before. `--llm --dry-run`
runs the free SQL pass and prints the bill -- how many rows would reach the model, and how many of
those the cache already answers -- without calling anything or writing anything.

Rerun it after the table is rebuilt: the route only serves a stored file whose (study, assay) rows
match the current table, and falls back to a live SQL-only sweep otherwise.

Usage:
    python3 scripts/build_immport_coverage.py [--llm] [--dry-run]

Reads  : <REGISTRY_ROOT>/all_assays_OBI.json, the ImmPort MySQL database, <REGISTRY_ROOT>/immport_llm_cache.json
Writes : <REGISTRY_ROOT>/assay_immport.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent import assay_immport  # noqa: E402
from app.agent.assay_service import REGISTRY_ROOT  # noqa: E402

TABLE_NAME = "all_assays_OBI.json"
COVERAGE_NAME = "assay_immport.json"


def llm_bill(report: dict, cache: dict) -> tuple[int, int]:
    """(cached, new) among the rows a SQL-only pass left absent -- what `--llm` would ask about."""
    absent = [r for r in report["rows"] if r["status"] == assay_immport.ABSENT]
    cached = sum(1 for r in absent if assay_immport._cache_key(r["study_accession"], r["assay"]) in cache)
    return cached, len(absent) - cached


def coverage_document(report: dict, use_llm: bool) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "llm": use_llm,
        "rows": report["rows"],
        "stats": report["stats"],
    }


async def sweep(rows: list[dict], use_llm: bool) -> dict:
    from app.database import async_session, engine

    try:
        async with async_session() as session:
            return await assay_immport.check_rows(session, rows, use_llm=use_llm)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm", action="store_true",
                        help="send rows SQL cannot place to the model (one call each, cached)")
    parser.add_argument("--dry-run", action="store_true",
                        help="SQL pass only; print the counts and the --llm bill, write nothing")
    args = parser.parse_args()

    table = REGISTRY_ROOT / TABLE_NAME
    if not table.exists():
        print(f"no assay table at {table} -- run scripts/build_assay_table.py first")
        return 1
    # A benchmark_only row is a curator assay we missed: nothing of ours to look up in ImmPort.
    rows = [r for r in json.loads(table.read_text(encoding="utf-8")) if not r.get("benchmark_only")]

    use_llm = args.llm and not args.dry_run
    try:
        report = asyncio.run(sweep(rows, use_llm))
    except Exception as exc:  # noqa: BLE001 -- any database failure leaves the stored file alone
        print(f"ImmPort database unreachable ({exc}); nothing written")
        return 1

    stats = report["stats"]
    print(f"{stats['total']} assays: {stats['matched']} matched, {stats['absent']} absent, "
          f"{stats['no_experiments']} in studies with no ImmPort experiments "
          f"({', '.join(stats['studies_without_experiments']) or 'none'})")

    if args.dry_run:
        if args.llm:
            cached, new = llm_bill(report, assay_immport._load_cache())
            print(f"--llm would ask about {cached + new} absent rows: {cached} answered from the "
                  f"cache (free), {new} new (one model call each)")
        print("dry run: nothing written")
        return 0

    out = REGISTRY_ROOT / COVERAGE_NAME
    out.write_text(json.dumps(coverage_document(report, use_llm), indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} ({'SQL + LLM fallback' if use_llm else 'SQL only'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
