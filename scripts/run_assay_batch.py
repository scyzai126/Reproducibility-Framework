"""Run the five-round assay pipeline over every paper in the corpus.

Every paper with a JATS XML under --xml-dir, plus every PDF-only paper under data/pdf -- the
same set the web UI offers (assay_service.available_papers), since the pipeline falls back to a
paper's PDF when it has no XML. Each paper's deliverable is its own
`<pmid>_<SDY>/assays_benchmark.json`, exactly as run_assay_pipeline.py writes it. There is no
flat copy: the copies this script used to write were never refreshed by run_assay_merge.py, and
drifted from the registries they were copied from.

**This is the expensive one.** Every paper pays all five rounds -- 1 extract + 1 per assay
verified + 1 per flagged field + 2-3 per assay name the OBI vocabulary does not carry verbatim --
and nothing is reused between papers. Thirty papers is upwards of 600 calls. Run --dry-run
first; it makes no API call, and prices each paper with the same assay_service.estimate_run the
single-paper CLI and the web cost gate use.

Papers run **sequentially**. assay_verifier already fans out 8-wide inside a single paper, so
stacking papers on top of that buys little and invites rate limits, and interleaved progress
from thirty papers is unreadable when something goes wrong.

**Resumable by default.** A paper whose assays_benchmark.json already exists is skipped, so an
interruption at paper 28 does not cost the first 27 again -- the pipeline writes that file last,
and only when every round ran, so its presence means the paper finished: a run whose OBI round
failed writes no deliverable, is listed under the failures as NOT DELIVERED, and is run again on
resume (or finished without re-paying by run_assay_merge.py --map). Pass --force to re-run
regardless -- which is what you want after editing a prompt, since the pipeline itself never
reuses anything.

`--result-version NAME` writes every paper under `data/31paper_assays/NAME/` instead of the
configured result folder (each paper's folder is created there first), the way the single-paper
CLI's flag of the same name does -- for a fresh pass of the corpus beside the last one.

Usage:
    python3 scripts/run_assay_batch.py [--xml-dir data/JAT_XML] [--dry-run] [--force]
                                       [--only PMID [PMID ...]] [--result-version NAME]

Example:
    python3 scripts/run_assay_batch.py --dry-run
    python3 scripts/run_assay_batch.py --only 26682988
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agent import assay_service
from app.agent.assay_service import (
    PDF_ROOT,
    REGISTRY_ROOT,
    PaperNotFoundError,
    _display_path,
    assay_report,
    estimate_run,
    registry_dir,
    split_stem,
)
from app.agent.claim_parser import _get_client
from run_assay_pipeline import report_result, use_result_version

XML_DIR = _REPO_ROOT / "data" / "JAT_XML"


def discover(xml_dir: Path, only: list[str],
             pdf_dir: Path | None = None) -> list[tuple[str, str, Path]]:
    """(pmid, sdy, source_path) for each paper: every XML, then each PDF with no XML.

    split_stem identifies the halves by which one starts with "SDY" rather than by position,
    because the XML scheme is `<SDY>_<pmid>` and the registry scheme `<pmid>_<SDY>`. It is
    handed the stem, never the filename -- a pmid of "26682988.xml" would name a registry
    directory `26682988.xml_SDY1119` and travel into every file under it.
    """
    papers, seen = [], set()
    sources = [(path, "xml") for path in sorted(xml_dir.glob("*.xml"))]
    pdf_dir = PDF_ROOT if pdf_dir is None else pdf_dir
    if pdf_dir.exists():
        sources += [(path, "pdf") for path in sorted(pdf_dir.rglob("*.pdf"))]
    for path, kind in sources:
        split = split_stem(path.stem)
        if split is None:
            if kind == "xml":
                print(f"  SKIPPED  {path.name}: not a <SDY>_<pmid> filename")
            continue
        if split in seen:
            continue  # a PDF of a paper that has XML: the pipeline reads the XML
        seen.add(split)
        if only and split[0] not in only:
            continue
        papers.append((*split, path))
    return papers


def done_path(pmid: str, sdy: str) -> Path:
    """The file whose presence means this paper finished: the pipeline writes it last."""
    return registry_dir(pmid, sdy) / "assays_benchmark.json"


def estimate(pmid: str, sdy: str) -> int | None:
    """The paper's projected calls, from estimate_run; None when no earlier run sizes it."""
    try:
        return estimate_run(pmid, sdy)["total_calls"]
    except PaperNotFoundError:
        return None


def dry_run(papers: list[tuple[str, str, Path]], force: bool) -> None:
    """What the batch would cost. No API call."""
    total = pending = unknown = 0
    for pmid, sdy, path in papers:
        done = done_path(pmid, sdy).exists() and not force
        calls = None if done else estimate(pmid, sdy)
        if done:
            mark, shown = "skip (done)", ""
        elif calls is None:
            mark, shown = "never run: cannot be sized", "?"
            unknown += 1
        else:
            mark, shown = "~", calls
            total += calls
        print(f"  {path.stem:26s} {shown:>4} call(s)  {mark}")
        pending += not done
    print(f"\n{pending} paper(s) to run, {len(papers) - pending} already done.")
    print(f"Projected: ~{total} calls for the {pending - unknown} that have run before"
          + (f", plus {unknown} that cannot be sized until round 1 has run on them "
             "(roughly 20-40 calls each)" if unknown else "") + ".")
    print("Rounds 2-4 all scale with the assay count, which round 1 decides, so the total is a "
          "shape\nestimate rather than a quote.\n\n--dry-run: nothing called.")


async def run_one(pmid: str, sdy: str, client) -> dict:
    """One paper, end to end, reported in full."""
    result = await assay_report(pmid, sdy, client, verify=True, correct=True)
    report_result(result)
    if result["meta"].get("benchmark_path"):
        print(f"  -> {_display_path(done_path(pmid, sdy))}")
    return result


async def main(xml_dir: Path, only: list[str], force: bool, dry: bool,
               result_version: str = "") -> None:
    if not xml_dir.is_dir():
        raise SystemExit(f"No such directory: {xml_dir}")

    papers = discover(xml_dir, only)
    if not papers:
        raise SystemExit(f"No papers matched under {xml_dir}")
    print(f"{len(papers)} paper(s) under {xml_dir}\n")
    if result_version.strip():
        # Every paper's folder is created under the version first, so done_path and
        # registry_dir resolve there rather than treating the paper as new (-> the cache).
        for pmid, sdy, _path in papers:
            use_result_version(result_version.strip(), pmid, sdy)

    if dry:
        dry_run(papers, force)
        return

    client = _get_client()
    done, skipped, failed, calls = [], [], [], 0

    for index, (pmid, sdy, path) in enumerate(papers, 1):
        if done_path(pmid, sdy).exists() and not force:
            skipped.append(pmid)
            print(f"[{index}/{len(papers)}] {path.stem}: SKIPPED, "
                  f"{done_path(pmid, sdy).name} exists (--force to re-run)")
            continue

        print(f"\n{'=' * 78}\n[{index}/{len(papers)}] {path.stem}\n{'=' * 78}")
        try:
            result = await run_one(pmid, sdy, client)
        except Exception as exc:  # noqa: BLE001 - see below
            # One paper must not cost the other 29. Every earlier paper's files are already on
            # disk, and every later one is independent of this failure.
            failed.append((pmid, f"{type(exc).__name__}: {exc}"))
            print(f"  FAILED  {pmid}: {type(exc).__name__}: {exc}")
            continue
        calls += result["meta"]["llm_calls"]
        if not result["meta"].get("benchmark_path"):
            # The chain returned but round 4 did not run, so the pipeline withheld the
            # deliverable: rounds 1-3 are on disk and the paper is not done. Listed with the
            # failures so the summary says which papers a resume will pick up again, rather
            # than counting it done and losing it among the skips next time.
            failed.append((pmid, "OBI mapping did not run; no assays_benchmark.json written. "
                                 "Rounds 1-3 are on disk: run_assay_merge.py --map, or resume"))
            print(f"  NOT DELIVERED  {pmid}: OBI mapping did not run; will run again on resume")
            continue
        done.append(pmid)

    print(f"\n{'=' * 78}\n{len(done)} done, {len(skipped)} skipped, {len(failed)} failed; "
          f"{calls} call(s) spent this run")
    for pmid, reason in failed:
        print(f"  FAILED  {pmid}: {reason}")
    root = assay_service.REGISTRY_ROOT if result_version.strip() else REGISTRY_ROOT
    print(f"  deliverables: {_display_path(root)}/<pmid>_<SDY>/assays_benchmark.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml-dir", type=Path, default=XML_DIR,
                        help="directory of <SDY>_<pmid>.xml papers")
    parser.add_argument("--only", nargs="+", default=[], metavar="PMID",
                        help="run just these PubMed ids")
    parser.add_argument("--force", action="store_true",
                        help="re-run papers whose assays_benchmark.json already exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the projected call count; makes no API call")
    parser.add_argument("--result-version", metavar="NAME", default="",
                        help="write under data/31paper_assays/NAME/ instead of the configured "
                             "result folder (e.g. assay_result_v3); folders are created")
    args = parser.parse_args()
    asyncio.run(main(args.xml_dir, args.only, args.force, args.dry_run, args.result_version))
