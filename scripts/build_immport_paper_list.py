#!/usr/bin/env python3
"""List every paper ImmPort links to a study, one row per PubMed ID, on the external drive.

Reads the local ImmPort mirror's `study_pubmed` table and writes two CSVs:

    papers_all.csv       pmid, study_accessions (every study, ';'-separated), primary_sdy, n_studies
    papers_unusable.csv  the table rows that do not name a paper ("TBD", a PMC id, ...), with why

A PubMed ID that several studies cite appears once, with all of them. The lists are the input
to the next steps -- fetching full text from PubMed Central and splitting the corpus into papers
with XML and papers that need a PDF -- which are separate scripts.

Free: one database read. No model calls, no network.

Usage:
    python3 scripts/build_immport_paper_list.py [--out-dir "/Volumes/Extreme SSD/HIPC papers"]

The output directory must already exist. It is an external drive by default, and a drive that
is not mounted should stop the script, not send the list to a freshly created folder under
/Volumes that vanishes behind the real one when the drive comes back.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent import immport_corpus  # noqa: E402


async def build(out_dir: Path) -> dict:
    from app.database import async_session, engine  # engine built at import: only when running

    try:
        async with async_session() as session:
            rows = await immport_corpus.study_pubmed_rows(session)
    finally:
        # Close the pool inside the loop; a connection collected after asyncio.run has closed
        # the loop prints an "Event loop is closed" traceback over the summary.
        await engine.dispose()

    grouped, unusable = immport_corpus.group_papers(rows)
    immport_corpus.write_csv(out_dir / immport_corpus.PAPERS_ALL_NAME,
                             immport_corpus.paper_rows(grouped), immport_corpus.PAPER_COLUMNS)
    immport_corpus.write_csv(out_dir / immport_corpus.PAPERS_UNUSABLE_NAME,
                             unusable, immport_corpus.UNUSABLE_COLUMNS)
    return immport_corpus.summary(rows, grouped, unusable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=immport_corpus.PAPERS_DIR,
                        help="existing directory to write the lists into "
                             f"(default: {immport_corpus.PAPERS_DIR})")
    args = parser.parse_args()

    if not args.out_dir.is_dir():
        print(f"Output directory does not exist: {args.out_dir}\n"
              "Mount the drive (or pass --out-dir) and run again.", file=sys.stderr)
        return 1

    counts = asyncio.run(build(args.out_dir))
    print(f"study_pubmed rows read : {counts['rows']}")
    print(f"usable PubMed IDs      : {counts['usable_pmids']}  "
          f"(across {counts['studies']} studies; {counts['shared_pmids']} shared by more than "
          f"one study, at most {counts['max_studies_per_pmid']})")
    print(f"unusable rows          : {counts['unusable_rows']}")
    print(f"\n  {args.out_dir / immport_corpus.PAPERS_ALL_NAME}")
    print(f"  {args.out_dir / immport_corpus.PAPERS_UNUSABLE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
