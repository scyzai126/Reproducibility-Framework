#!/usr/bin/env python3
"""Run the five-round assay pipeline over the ImmPort corpus on the external drive, in tranches.

Papers: every row of "HIPC papers/papers_xml.csv" (scripts/download_immport_xml.py), read from
"HIPC papers/xml/<SDY>_<pmid>.xml". Results: "HIPC result/<pmid>_<SDY>/", the standard files
run_assay_pipeline.py writes, with assays_benchmark.json -- the deliverable -- written last.
Each paper is one assay_service.assay_report call: the voted extract -> verify -> correct ->
map -> canonicalize chain, nothing new, so a registry built here is the same files the
single-paper CLI and the web UI produce.

**This is the expensive one: ~25 calls and ~$0.40 a paper, ~$430 for the corpus.** Run
`run --dry-run` first (free) and get a go-ahead before every paid tranche.

**Tranches.** `--limit N` runs the first N papers not yet done, in papers_xml.csv order. A paper
whose assays_benchmark.json exists is skipped, so each invocation continues where the last one
stopped; Ctrl-C loses only the papers in flight, whose folders have no marker. `--max-usd X`
stops launching papers once this run's ledger spend crosses X.

**Parallel papers.** `--parallel P` (default 4) keeps P papers in flight in one process. Each
paper already fans its verify and correct calls out 8-wide, so P papers are up to 8*P
concurrent requests; the OpenAI client is built with max_retries=5 so the SDK's own backoff
absorbs rate limiting. Every paper records its usage in its own trace (a ContextVar copied into
each task) and writes only inside its own folder, so papers do not touch each other. Each
paper's report -- the WARNING / REVIEW / JUDGED / REJECT / DROPPED / MINORITY / VOTE / MERGED
lines CLAUDE.md says to report, never summarise -- is printed whole by the main loop when the
paper finishes, under its own banner, and kept in "HIPC result/logs/<pmid>.log".

**Benchmark papers are copied, not re-run.** A paper with a finished XML-based registry under
data/31paper_assays/<--reuse-benchmark> (assay_result_v3 by default) is copied into the result
folder; the XML on the drive is a copy of the one that registry cites, so its quotes still
match. --no-reuse-benchmark runs them like any other paper.

Usage:
    python3 scripts/run_immport_assays.py run [--limit N] [--parallel P] [--only PMID ...]
                                              [--force] [--dry-run] [--max-usd X]
                                              [--paper-timeout S] [--reuse-benchmark VERSION]
                                              [--no-reuse-benchmark]
    python3 scripts/run_immport_assays.py status [--failed] [--flags]

Both take --papers-dir and --result-dir (defaults: the drive) and refuse to run if either is
missing, rather than creating a result folder somewhere the drive is not.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import AsyncOpenAI  # noqa: E402

from app.agent import assay_ledger, assay_service, immport_corpus  # noqa: E402
from app.agent.assay_registry import CORPUS_ROOT  # noqa: E402
from app.agent.assay_service import assay_report  # noqa: E402
from app.config import settings  # noqa: E402
from run_assay_pipeline import report_result  # noqa: E402

DEFAULT_PARALLEL = 4
DEFAULT_PAPER_TIMEOUT_S = 1800
DEFAULT_BENCHMARK_VERSION = "assay_result_v3"


def point_pipeline_at(papers_dir: Path, result_dir: Path) -> None:
    """Re-root assay_service so every paper reads from the drive and writes to the drive.

    Both registry roots, not one: registry_dir checks REGISTRY_ROOT (the benchmark version
    folder by default) before CACHE_ROOT, so leaving it alone would send a benchmark paper's
    run into data/31paper_assays and overwrite the registry there. PDF_ROOT points at a folder
    that does not exist, which turns the PDF fallback off: this corpus is XML.
    """
    assay_service.XML_ROOT = papers_dir / immport_corpus.XML_DIR_NAME
    assay_service.PDF_ROOT = result_dir / "no_pdf"
    assay_service.REGISTRY_ROOT = result_dir
    assay_service.CACHE_ROOT = result_dir


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


class Runs:
    """The per-paper record on the drive (assay_runs.csv): single writer, rewritten whole."""

    def __init__(self, result_dir: Path):
        self.path = result_dir / immport_corpus.RUNS_NAME
        self.rows: dict[str, dict] = {r["pmid"]: r for r in immport_corpus.read_csv(self.path)}

    def set(self, paper: dict, status: str, **fields) -> dict:
        row = {"pmid": paper["pmid"], "primary_sdy": paper["primary_sdy"],
               "study_accessions": paper["study_accessions"], "status": status,
               "registry_dir": "", "calls": "", "usd": "", "seconds": "", "flags": "",
               "error": "", "finished_at": datetime.now().replace(microsecond=0).isoformat()}
        row.update({k: ("" if v is None else v) for k, v in fields.items()})
        self.rows[paper["pmid"]] = row
        immport_corpus.write_csv(self.path, list(self.rows.values()), immport_corpus.RUN_COLUMNS)
        return row


def is_finished(result_dir: Path, paper: dict, runs: "Runs") -> bool:
    """Done on disk, or recorded done: a paper the extractor found no assays in gets no
    assays_benchmark.json (the chain stops after round 1), so the run record is the only
    place that says it finished. Without this it would be re-run on every tranche."""
    if immport_corpus.done_marker(result_dir, paper["pmid"], paper["primary_sdy"]).exists():
        return True
    row = runs.rows.get(paper["pmid"])
    return bool(row) and row.get("status") in ("done", "reused")


def queue_papers(papers: list[dict], result_dir: Path, only: list[str], force: bool,
                 reuse_version: str | None, runs: "Runs") -> tuple[list[dict], list[tuple[dict, Path]], int]:
    """`(to_run, to_copy, skipped)` in papers_xml.csv order."""
    to_run, to_copy, skipped = [], [], 0
    for paper in papers:
        pmid, sdy = paper["pmid"], paper["primary_sdy"]
        if only and pmid not in only:
            continue
        if is_finished(result_dir, paper, runs) and not force:
            skipped += 1
            continue
        source = (immport_corpus.benchmark_registry(pmid, paper["studies"],
                                                    CORPUS_ROOT / reuse_version)
                  if reuse_version else None)
        if source is not None:
            to_copy.append((paper, source))
        else:
            to_run.append(paper)
    return to_run, to_copy, skipped


def ledger_rows_under(result_dir: Path, since: str = "") -> list[dict]:
    """Ledger rows this corpus wrote (registry_dir under the result folder), optionally only
    those dated at or after `since` (ISO)."""
    out = []
    for row in assay_ledger.read_rows():
        if not immport_corpus._under(row.get("registry_dir", ""), result_dir):
            continue
        if since and (row.get("date") or "") < since:
            continue
        out.append(row)
    return out


def _newest_row(rows: list[dict], pmid: str) -> dict | None:
    mine = [r for r in rows if r.get("pubmed_id") == pmid]
    return max(mine, key=lambda r: r.get("date") or "") if mine else None


def dry_run(to_run: list[dict], to_copy: list, skipped: int, result_dir: Path,
            parallel: int, runs: Runs) -> None:
    cost = immport_corpus.cost_per_paper(assay_ledger.read_rows(), under=result_dir)
    secs = immport_corpus.seconds_per_paper(list(runs.rows.values()))
    n = len(to_run)
    print(f"  to run           : {n}")
    print(f"  copy (benchmark) : {len(to_copy)}")
    print(f"  skip (done)      : {skipped}")
    print(f"  cost             : ~${n * cost['median']:,.0f} at ${cost['median']:.2f}/paper median"
          f" (up to ~${n * cost['max']:,.0f} at the ${cost['max']:.2f} max), from "
          f"{cost['n']} ledger row(s)" + ("" if cost["n"] else " -- the dated default"))
    hours = n * secs / max(1, parallel) / 3600
    print(f"  wall-clock       : ~{hours:.1f} h at --parallel {parallel} "
          f"({secs:.0f} s/paper measured{'' if secs != immport_corpus.DEFAULT_SECONDS_PER_PAPER else ', default'})")
    print("\n--dry-run: nothing called, nothing written.")


async def run(args: argparse.Namespace) -> int:
    papers_dir, result_dir = args.papers_dir, args.result_dir
    papers = immport_corpus.read_xml_papers(papers_dir)
    if not papers:
        print(f"No {immport_corpus.PAPERS_XML_NAME} under {papers_dir}; run "
              "scripts/download_immport_xml.py first.", file=sys.stderr)
        return 1
    point_pipeline_at(papers_dir, result_dir)
    runs = Runs(result_dir)
    reuse = None if args.no_reuse_benchmark else args.reuse_benchmark
    to_run, to_copy, skipped = queue_papers(papers, result_dir, args.only, args.force, reuse,
                                            runs)
    if args.limit > 0:
        to_run = to_run[:args.limit]
    print(f"{len(papers)} papers with XML in {papers_dir}; results in {result_dir}\n")

    if args.dry_run:
        dry_run(to_run, to_copy, skipped, result_dir, args.parallel, runs)
        return 0

    log_dir = result_dir / immport_corpus.RESULT_LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)

    for paper, source in to_copy:
        target = result_dir / f"{paper['pmid']}_{paper['primary_sdy']}"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        row = _newest_row(assay_ledger.read_rows(), paper["pmid"])
        runs.set(paper, "reused", registry_dir=_display(target),
                 calls=row["calls"] if row else "", usd=row["usd"] if row else "")
        print(f"REUSED  {paper['pmid']}  <- {_display(source)}")

    if not to_run:
        print("\nNothing to run.")
        return 0

    started = datetime.now().replace(microsecond=0).isoformat()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=5, timeout=600)
    sem = asyncio.Semaphore(max(1, args.parallel))
    stop = {"reason": ""}

    def spent() -> float:
        return sum(r["usd"] or 0.0 for r in ledger_rows_under(result_dir, since=started))

    async def one(paper: dict) -> tuple[str, dict, object, float]:
        async with sem:
            if args.max_usd and spent() >= args.max_usd:
                stop["reason"] = f"--max-usd {args.max_usd} reached"
                return ("stopped", paper, None, 0.0)
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    assay_report(paper["pmid"], paper["primary_sdy"], client,
                                 verify=True, correct=True),
                    timeout=args.paper_timeout)
                return ("done", paper, result, time.monotonic() - t0)
            except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001 - one paper, not the tranche
                return ("failed", paper, exc, time.monotonic() - t0)

    done: list[dict] = []
    failed: list[tuple[dict, str]] = []
    stopped = 0
    calls = 0
    flagged: list[tuple[dict, dict, Path]] = []
    total = len(to_run)

    tasks = [asyncio.create_task(one(p)) for p in to_run]
    try:
        for index, fut in enumerate(asyncio.as_completed(tasks), 1):
            status, paper, payload, secs = await fut
            pmid, sdy = paper["pmid"], paper["primary_sdy"]
            folder = result_dir / f"{pmid}_{sdy}"
            if status == "stopped":
                stopped += 1
                continue
            banner = f"\n{'=' * 78}\n[{index}/{total}] {sdy}_{pmid}  ({secs / 60:.1f} min)\n{'=' * 78}"
            buffer = io.StringIO()
            if status == "done":
                with contextlib.redirect_stdout(buffer):
                    try:
                        report_result(payload)
                    except Exception as exc:  # noqa: BLE001 - reporting must not lose the run
                        print(f"  ERROR  report_result raised {type(exc).__name__}: {exc}")
                text = buffer.getvalue()
                counts = immport_corpus.count_report_lines(text)
                row = _newest_row(ledger_rows_under(result_dir, since=started), pmid)
                calls += payload["meta"]["llm_calls"]
                runs.set(paper, "done", registry_dir=_display(folder),
                         calls=payload["meta"]["llm_calls"], usd=row["usd"] if row else "",
                         seconds=f"{secs:.0f}", flags=immport_corpus.format_flags(counts))
                done.append(paper)
                if counts:
                    flagged.append((paper, counts, log_dir / f"{pmid}.log"))
            else:
                text = f"  FAILED  {pmid}: {type(payload).__name__}: {payload}\n"
                runs.set(paper, "failed", registry_dir=_display(folder), seconds=f"{secs:.0f}",
                         error=f"{type(payload).__name__}: {payload}")
                failed.append((paper, f"{type(payload).__name__}: {payload}"))
            print(banner + "\n" + text, end="")
            (log_dir / f"{pmid}.log").write_text(banner + "\n" + text, encoding="utf-8")
    except (KeyboardInterrupt, asyncio.CancelledError):
        for task in tasks:
            task.cancel()
        print("\nInterrupted: papers in flight have no assays_benchmark.json and will be "
              "re-run next time.")
        raise

    usd = spent()
    this_run = list(runs.rows.values())
    summary = immport_corpus.summarize_runs([r for r in this_run if r["pmid"] in
                                             {p["pmid"] for p in done}])
    lines = [f"{len(done)} done, {len(to_copy)} reused, {len(failed)} failed, {stopped} not "
             f"started{' (' + stop['reason'] + ')' if stop['reason'] else ''}, {skipped} "
             f"skipped as done; {calls} call(s), ${usd:,.2f} this run (ledger), "
             f"{immport_corpus.seconds_per_paper(this_run):.0f} s/paper median at "
             f"--parallel {args.parallel}"]
    if summary["flags"]:
        lines.append("flags: " + ", ".join(f"{k} {v}" for k, v in summary["flags"].items()))
    for paper, reason in failed:
        lines.append(f"  FAILED  {paper['pmid']}: {reason}")
    for paper, counts, log in flagged:
        lines.append(f"  FLAGGED {paper['pmid']}: " + immport_corpus.format_flags(counts)
                     + f"  -> {log}")
    lines.append(f"  deliverables: {result_dir}/<pmid>_<SDY>/assays_benchmark.json")
    text = "\n".join(lines)
    print(f"\n{'=' * 78}\n{text}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (log_dir / f"tranche_{stamp}.txt").write_text(text + "\n", encoding="utf-8")
    return 0


def status(args: argparse.Namespace) -> int:
    papers = immport_corpus.read_xml_papers(args.papers_dir)
    runs = Runs(args.result_dir)
    rows = list(runs.rows.values())
    pmids = {p["pmid"] for p in papers}
    on_disk = {p["pmid"] for p in papers if is_finished(args.result_dir, p, runs)}
    summary = immport_corpus.summarize_runs(rows)
    failed = [r for r in rows if r["status"] == "failed" and r["pmid"] not in on_disk]
    ledger = ledger_rows_under(args.result_dir)
    cost = immport_corpus.cost_per_paper(assay_ledger.read_rows(), under=args.result_dir)
    pending = len(pmids - on_disk)
    print(f"papers with XML : {len(papers)}")
    print(f"finished        : {len(on_disk)}  (done {summary['by_status'].get('done', 0)}, "
          f"reused {summary['by_status'].get('reused', 0)})")
    print(f"failed          : {len(failed)}")
    print(f"pending         : {pending}")
    spent = sum(r["usd"] or 0.0 for r in ledger)
    print(f"spend           : ${spent:,.2f} over {len(ledger)} run(s); median "
          f"${cost['median']:.2f}/paper ({cost['n']} row(s)); remaining ~${pending * cost['median']:,.0f}")
    if summary["flags"]:
        print("flags           : " + ", ".join(f"{k} {v}" for k, v in summary["flags"].items()))
    if args.failed:
        for r in failed:
            print(f"  FAILED  {r['pmid']}: {r['error']}")
    if args.flags:
        for r in rows:
            if r.get("flags"):
                print(f"  FLAGGED {r['pmid']}: {r['flags']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "status"):
        p = sub.add_parser(name)
        p.add_argument("--papers-dir", type=Path, default=immport_corpus.PAPERS_DIR)
        p.add_argument("--result-dir", type=Path, default=immport_corpus.RESULT_DIR)
        if name == "run":
            p.add_argument("--limit", type=int, default=0, metavar="N",
                           help="run at most N papers this tranche (0 = all pending)")
            p.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, metavar="P",
                           help=f"papers in flight at once (default {DEFAULT_PARALLEL})")
            p.add_argument("--only", nargs="+", default=[], metavar="PMID")
            p.add_argument("--force", action="store_true",
                           help="re-run papers whose assays_benchmark.json exists")
            p.add_argument("--dry-run", action="store_true",
                           help="report count, cost and hours; call nothing")
            p.add_argument("--max-usd", type=float, default=0.0, metavar="X",
                           help="stop launching papers once this run's ledger spend reaches X")
            p.add_argument("--paper-timeout", type=float, default=DEFAULT_PAPER_TIMEOUT_S,
                           metavar="S", help="a paper still running after S seconds is failed")
            p.add_argument("--reuse-benchmark", default=DEFAULT_BENCHMARK_VERSION,
                           metavar="VERSION",
                           help="copy finished registries from data/31paper_assays/VERSION")
            p.add_argument("--no-reuse-benchmark", action="store_true")
        else:
            p.add_argument("--failed", action="store_true", help="list failed papers")
            p.add_argument("--flags", action="store_true", help="list flagged papers")
    args = parser.parse_args(argv)

    for label, path in (("papers", args.papers_dir), ("result", args.result_dir)):
        if not path.is_dir():
            print(f"The {label} directory does not exist: {path}\nMount the drive and run again.",
                  file=sys.stderr)
            return 1
    if args.command == "status":
        return status(args)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
