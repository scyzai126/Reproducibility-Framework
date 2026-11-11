#!/usr/bin/env python3
"""Run the assay pipeline on the ABCD papers that have a PDF and no JATS XML.

The papers with XML run through scripts/run_immport_assays.py, pointed at the ABCD folders:

    python3 scripts/run_immport_assays.py run --no-reuse-benchmark \
        --papers-dir "/Volumes/Extreme SSD/ABCD papers" --result-dir "/Volumes/Extreme SSD/ABCD result"

That runner turns the PDF route off (its corpus is XML), so the handful of papers listed in
papers_pdf.csv (scripts/download_abcd_papers.py) run here instead: one
assay_service.assay_report per paper -- the same voted chain, nothing new -- reported by
run_assay_pipeline.report_result and kept in "<result>/logs/<pmid>.log". Results land in
"<result>/<pmid>_<label>_pdf/", the name assay_service.registry_dir gives a PDF-built registry.

Sequential: there are at most eight of them. A paper whose assays_benchmark.json exists is
skipped unless --force.

**--dry-run makes no API call** and prints each paper's estimate. Run it first and get a
go-ahead before the paid run.

Usage:
    python3 scripts/run_abcd_pdf_assays.py [--papers-dir DIR] [--result-dir DIR]
                                           [--only PMID ...] [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import AsyncOpenAI  # noqa: E402

from app.agent import assay_service, immport_corpus  # noqa: E402
from app.agent.assay_service import assay_report  # noqa: E402
from app.config import settings  # noqa: E402
from download_abcd_papers import PAPERS_DIR, PAPERS_PDF_NAME, PDF_DIR_NAME, RESULT_DIR  # noqa: E402
from run_assay_pipeline import _dry_run, report_result  # noqa: E402


def point_pipeline_at(papers_dir: Path, result_dir: Path) -> None:
    """Read papers from the ABCD folders and write registries to the ABCD result folder."""
    assay_service.XML_ROOT = papers_dir / immport_corpus.XML_DIR_NAME
    assay_service.PDF_ROOT = papers_dir / PDF_DIR_NAME
    assay_service.REGISTRY_ROOT = result_dir
    assay_service.CACHE_ROOT = result_dir


def is_finished(pmid: str, label: str) -> bool:
    return (assay_service.registry_dir(pmid, label) / "assays_benchmark.json").exists()


async def run(papers: list[dict], result_dir: Path) -> int:
    log_dir = result_dir / immport_corpus.RESULT_LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=5, timeout=600)
    failed = 0
    for index, paper in enumerate(papers, 1):
        pmid, label = paper["pmid"], paper["primary_sdy"]
        started = time.monotonic()
        buffer = io.StringIO()
        try:
            result = await assay_report(pmid, label, client, verify=True, correct=True)
            with contextlib.redirect_stdout(buffer):
                report_result(result)
        except Exception as exc:  # noqa: BLE001 - one paper, not the batch
            failed += 1
            buffer.write(f"  FAILED  {pmid}: {type(exc).__name__}: {exc}\n")
        minutes = (time.monotonic() - started) / 60
        banner = f"\n{'=' * 78}\n[{index}/{len(papers)}] {label}_{pmid} [pdf]  ({minutes:.1f} min)\n{'=' * 78}"
        text = banner + "\n" + buffer.getvalue()
        print(text, end="")
        (log_dir / f"{pmid}.log").write_text(text, encoding="utf-8")
    print(f"\n{len(papers) - failed} done, {failed} failed.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--papers-dir", type=Path, default=PAPERS_DIR)
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    parser.add_argument("--only", nargs="+", default=[], metavar="PMID")
    parser.add_argument("--force", action="store_true",
                        help="re-run papers whose assays_benchmark.json exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="print each paper's estimate; call nothing")
    args = parser.parse_args(argv)

    for label, path in (("papers", args.papers_dir), ("result", args.result_dir)):
        if not path.is_dir():
            print(f"The {label} directory does not exist: {path}", file=sys.stderr)
            return 1
    point_pipeline_at(args.papers_dir, args.result_dir)
    rows = immport_corpus.read_csv(args.papers_dir / PAPERS_PDF_NAME)
    papers = [r for r in rows if not args.only or r["pmid"] in args.only]
    todo = [r for r in papers if args.force or not is_finished(r["pmid"], r["primary_sdy"])]
    print(f"{len(rows)} paper(s) in {PAPERS_PDF_NAME}; {len(todo)} to run, "
          f"{len(papers) - len(todo)} skipped as done.\n")
    if args.dry_run:
        for paper in todo:
            _dry_run(paper["pmid"], paper["primary_sdy"])
            print()
        return 0
    if not todo:
        print("Nothing to run.")
        return 0
    return asyncio.run(run(todo, args.result_dir))


if __name__ == "__main__":
    raise SystemExit(main())
