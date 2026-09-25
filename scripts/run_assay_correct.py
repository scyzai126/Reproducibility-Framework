"""Blind-re-extract the assay fields a verification pass refused to support.

Reads <registry_dir>/assays.json and <registry_dir>/assays_verification.json, and writes
assays_corrected.json (a clean registry, same ten-field shape) plus assays_corrections.json
(what changed, and what it was before). The input registry is never modified -- an extracted
value and a repaired one have to stay distinguishable, which they would not be if this wrote
back in place.

Run run_assay_verify.py first: without a verification report there is nothing flagged, and
this script has nothing to do.

Corrections are blind. The correcting model is not shown the disputed value or the verifier's
complaint, only the paper and a question -- see app.agent.assay_corrector for why.

Cost is one call per flagged FIELD, not per assay. --dry-run prints what would be re-extracted
and calls nothing, which is the free way to see the bill first.

Nothing downstream reads assays_corrected.json -- app.agent.assay_registry.load_verified_registry
reads assays.json, so corrections have no effect until they are promoted. Review the diff, then:

    python scripts/run_assay_correct.py <registry_dir> --promote

which moves the corrected registry into place and keeps the pre-correction version beside it as
assays_precorrection.json. Promotion is a separate invocation on purpose: a corrected value is a
third model's opinion, and it should reach the resolver because someone read it, not because a
script ran.

Usage:
    python scripts/run_assay_correct.py <registry_dir> [--xml PATH] [--dry-run | --promote]

Example:
    python scripts/run_assay_correct.py data/claims/assay_registries/26682988_SDY1119 --dry-run
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_corrector import (
    build_report,
    correct_registry,
    drop_rejected,
    flagged_groups,
    promote_registry,
    uncorrectable_flags,
)
from app.agent.claim_parser import _get_client
from run_assay_verify import locate_xml, paper_text


def _load(path: Path, what: str) -> dict:
    if not path.exists():
        print(f"No {path.name} in {path.parent} -- run {what} first.")
        sys.exit(1)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not loaded:
        print(f"{path} holds nothing usable")
        sys.exit(1)
    return loaded


def report_plan(assays: dict, verification: dict) -> int:
    """Print what would be re-extracted, and what will only be reported. No API call."""
    by_id = {r.get("assay_id"): r for r in (verification.get("results") or [])}
    total = 0
    for key in assays:
        result = by_id.get(key, {})
        groups = flagged_groups(result)
        skipped = uncorrectable_flags(result)
        total += len(groups)
        verdict = result.get("record_verdict", "?")
        if not groups and not skipped:
            print(f"  clean    {key} ({verdict})")
            continue
        print(f"  {len(groups)} field(s) {key} ({verdict}): {', '.join(groups) or '-'}")
        for flag in skipped:
            print(f"           reported only: {flag['field_name']} {flag['verdict']} -- {flag['reason']}")
    return total


def promote(registry_dir: Path) -> None:
    """Install assays_corrected.json as the registry the pipeline reads.

    The move itself lives in app.agent.assay_corrector.promote_registry, so this command and
    the HTTP route install a registry the same way.
    """
    try:
        result = promote_registry(registry_dir)
    except FileNotFoundError as exc:
        print(f"{exc} -- run the correction first.")
        sys.exit(1)

    if result["snapshot_written"]:
        print(f"  kept the pre-correction registry as {result['snapshot']}")
    print(f"  promoted {result['promoted']} -> assays.json")
    print("\nThe resolver now reads the corrected values. Re-run run_assay_verify.py to "
          "check them, and note assays_verification.json still describes the old registry.")


async def main(registry_dir: Path, xml_path: Path | None, dry_run: bool,
               keep_rejected: bool = False) -> None:
    assays = _load(registry_dir / "assays.json", "the extraction")
    verification = _load(registry_dir / "assays_verification.json", "scripts/run_assay_verify.py")

    total = report_plan(assays, verification)
    print(f"\n{total} flagged field(s) -- costs {total} call(s).")
    if dry_run:
        print("--dry-run: nothing called.")
        return
    if not total:
        print("Nothing flagged; no corrected registry written.")
        return

    if xml_path is None:
        xml_path = locate_xml(registry_dir)
    if xml_path is None or not xml_path.exists():
        print(f"No paper XML found for {registry_dir.name}. Pass --xml PATH.")
        sys.exit(1)
    title, source_text = paper_text(xml_path)

    kept, dropped = (assays, {}) if keep_rejected else drop_rejected(assays, verification)
    for key, info in dropped.items():
        print(f"  dropped  {key}: {info['reason']}")

    corrected, records = await correct_registry(
        kept, verification, source_text, title, _get_client()
    )
    if dropped:
        (registry_dir / "assays_rejected.json").write_text(
            json.dumps(dropped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (registry_dir / "assays_corrected.json").write_text(
        json.dumps(corrected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = build_report(records)
    (registry_dir / "assays_corrections.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = report["summary"]
    print(f"\n{summary['fields_re_extracted']} field(s) re-extracted: "
          + ", ".join(f"{n} {a.lower()}" for a, n in sorted(summary["actions"].items())))
    if summary["reported_not_corrected"]:
        print(f"  {summary['reported_not_corrected']} flag(s) reported but not corrected "
              f"(assay identity is not repairable by re-extraction)")
    print(f"  saved assays_corrected.json and assays_corrections.json")
    print("\nReview assays_corrections.json, then promote with:"
          f"\n    python scripts/run_assay_correct.py {registry_dir} --promote")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry_dir", type=Path, help="directory containing assays.json")
    parser.add_argument("--xml", type=Path, default=None, help="paper JATS XML")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print what would be re-extracted; makes no API call")
    parser.add_argument("--keep-rejected", action="store_true",
                        help="keep assays the verifier rejected instead of setting them aside")
    mode.add_argument("--promote", action="store_true",
                      help="install assays_corrected.json as assays.json; makes no API call")
    args = parser.parse_args()
    if args.promote:
        promote(args.registry_dir)
    else:
        asyncio.run(main(args.registry_dir, args.xml, args.dry_run, args.keep_rejected))
