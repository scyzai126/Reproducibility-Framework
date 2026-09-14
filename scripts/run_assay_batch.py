"""Run the four-round assay pipeline over every paper in a JATS XML directory.

One `assays_OBI_<pmid>.json` per paper, written flat into data/claims/assay_registries so the
whole corpus reads as one directory listing. Each paper's own `<pmid>_<SDY>/` directory is left
exactly as the pipeline wrote it -- the flat file is a *copy*, not a move, so the verification
and correction trail survives. It cost money to produce and cannot be regenerated without
paying again.

**This is the expensive one.** Every paper pays all four rounds -- 1 extract + 1 per assay
verified + 1 per flagged field + 2 per assay name the OBI vocabulary does not carry verbatim --
and nothing is reused between papers. Thirty papers is upwards of 600 calls. Run --dry-run
first; it makes no API call.

Papers run **sequentially**. assay_verifier already fans out 8-wide inside a single paper, so
stacking papers on top of that buys little and invites rate limits, and interleaved progress
from thirty papers is unreadable when something goes wrong.

**Resumable by default.** A paper whose flat file already exists is skipped, so an interruption
at paper 28 does not cost the first 27 again. Pass --force to re-run regardless -- which is what
you want after editing a prompt, since the pipeline itself never reuses anything.

Usage:
    python3 scripts/run_assay_batch.py [--xml-dir data/JAT_XML] [--dry-run] [--force]
                                       [--only PMID [PMID ...]]

Example:
    python3 scripts/run_assay_batch.py --dry-run
    python3 scripts/run_assay_batch.py --only 26682988
"""

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agent.assay_service import (
    REGISTRY_ROOT,
    _display_path,
    assay_report,
    registry_dir,
)
from app.agent.claim_parser import _get_client
from run_assay_pipeline import _obi_misses, report_result, split_registry_dir

#: Assays per paper where no previous registry exists to count. The median across the twelve
#: papers in this corpus that do have one. Reported as an estimate, never as a figure.
_ASSUMED_ASSAYS = 7

#: Share of assay names that miss the OBI vocabulary's exact match, measured over the 156
#: distinct names on disk (131/156). Only used to size papers with no registry yet.
_OBI_MISS_RATE = 0.84

XML_DIR = _REPO_ROOT / "data" / "JAT_XML"


def discover(xml_dir: Path, only: list[str]) -> list[tuple[str, str, Path]]:
    """(pmid, sdy, xml_path) for each paper, in filename order.

    split_registry_dir is reused rather than re-deriving the split: the XML scheme is
    `<SDY>_<pmid>` and the registry scheme is `<pmid>_<SDY>`, and it identifies the halves by
    which one starts with "SDY" rather than by position.

    The suffix is dropped before it is handed over. That function reads `.name`, having been
    written for directories, so a path passed whole yields a pmid of "26682988.xml" -- which
    then names a registry directory `26682988.xml_SDY1119` and travels into every file under it.
    """
    papers = []
    for xml_path in sorted(xml_dir.glob("*.xml")):
        try:
            pmid, sdy = split_registry_dir(xml_path.with_suffix(""))
        except SystemExit:
            print(f"  SKIPPED  {xml_path.name}: not a <SDY>_<pmid> filename")
            continue
        if only and pmid not in only:
            continue
        papers.append((pmid, sdy, xml_path))
    return papers


def flat_path(pmid: str) -> Path:
    """Where this paper's deliverable lands: one flat file per paper, named by pmid."""
    return REGISTRY_ROOT / f"assays_OBI_{pmid}.json"


def estimate(pmid: str, sdy: str) -> tuple[int, bool]:
    """(calls, exact) for one paper. Reads disk only.

    Exact when a registry from a previous run is there to count assays and unmatched names in.
    Otherwise the corpus median stands in and the answer is explicitly an estimate -- rounds 2
    and 4 both scale with the assay count, which is not knowable before round 1 has run.
    """
    registry_path = registry_dir(pmid, sdy) / "assays.json"
    if registry_path.exists():
        try:
            assays = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            assays = None
        if isinstance(assays, dict) and assays:
            # 1 extract + 1 per assay verified + 2 per OBI miss. Round 3 is the one this cannot
            # size from a registry alone -- it needs the verification -- so it is folded into
            # the same per-assay guess used below.
            correct = round(0.55 * len(assays))
            return 1 + len(assays) + correct + 2 * len(_obi_misses(assays)), True
    n = _ASSUMED_ASSAYS
    return 1 + n + round(0.55 * n) + round(2 * _OBI_MISS_RATE * n), False


def dry_run(papers: list[tuple[str, str, Path]], force: bool) -> None:
    """What the batch would cost. No API call."""
    total = pending = 0
    for pmid, sdy, xml_path in papers:
        calls, exact = estimate(pmid, sdy)
        done = flat_path(pmid).exists() and not force
        mark = "skip (done)" if done else ("exact" if exact else "est.")
        print(f"  {xml_path.stem:26s} {'' if done else calls:>4} call(s)  {mark}")
        if not done:
            total += calls
            pending += 1
    print(f"\n{pending} paper(s) to run, {len(papers) - pending} already done.")
    print(f"Projected: ~{total} calls (range roughly {int(total * 0.7)}-{int(total * 1.4)}).")
    print("Rounds 2-4 all scale with the assay count, which round 1 decides, so the total is a "
          "shape\nestimate rather than a quote.\n\n--dry-run: nothing called.")


async def run_one(pmid: str, sdy: str, client) -> dict:
    """One paper, end to end, then copy its OBI map to the flat deliverable path."""
    result = await assay_report(pmid, sdy, client, verify=True, correct=True)
    report_result(result)

    source = registry_dir(pmid, sdy) / "assays_OBI.json"
    if not source.exists():
        # Round 4 failed soft; report_result already said so. The paper's other files are on
        # disk, so run_obi_map.py can finish it without re-paying for rounds 1-3.
        print(f"  NO OBI FILE  {pmid}: round 4 produced nothing to copy")
        return result

    destination = flat_path(pmid)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    print(f"  -> {_display_path(destination)}")
    return result


async def main(xml_dir: Path, only: list[str], force: bool, dry: bool) -> None:
    if not xml_dir.is_dir():
        raise SystemExit(f"No such directory: {xml_dir}")

    papers = discover(xml_dir, only)
    if not papers:
        raise SystemExit(f"No papers matched under {xml_dir}")
    print(f"{len(papers)} paper(s) under {xml_dir}\n")

    if dry:
        dry_run(papers, force)
        return

    client = _get_client()
    done, skipped, failed, calls = [], [], [], 0

    for index, (pmid, sdy, xml_path) in enumerate(papers, 1):
        if flat_path(pmid).exists() and not force:
            skipped.append(pmid)
            print(f"[{index}/{len(papers)}] {xml_path.stem}: SKIPPED, "
                  f"{flat_path(pmid).name} exists (--force to re-run)")
            continue

        print(f"\n{'=' * 78}\n[{index}/{len(papers)}] {xml_path.stem}\n{'=' * 78}")
        try:
            result = await run_one(pmid, sdy, client)
        except Exception as exc:  # noqa: BLE001 - see below
            # One paper must not cost the other 29. Every earlier paper's files are already on
            # disk, and every later one is independent of this failure.
            failed.append((pmid, f"{type(exc).__name__}: {exc}"))
            print(f"  FAILED  {pmid}: {type(exc).__name__}: {exc}")
            continue
        done.append(pmid)
        calls += result["meta"]["llm_calls"]

    print(f"\n{'=' * 78}\n{len(done)} done, {len(skipped)} skipped, {len(failed)} failed; "
          f"{calls} call(s) spent this run")
    for pmid, reason in failed:
        print(f"  FAILED  {pmid}: {reason}")
    print(f"  deliverables: {_display_path(REGISTRY_ROOT)}/assays_OBI_<pmid>.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml-dir", type=Path, default=XML_DIR,
                        help="directory of <SDY>_<pmid>.xml papers")
    parser.add_argument("--only", nargs="+", default=[], metavar="PMID",
                        help="run just these PubMed ids")
    parser.add_argument("--force", action="store_true",
                        help="re-run papers whose flat OBI file already exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the projected call count; makes no API call")
    args = parser.parse_args()
    asyncio.run(main(args.xml_dir, args.only, args.force, args.dry_run))
