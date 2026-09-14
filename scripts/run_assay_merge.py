#!/usr/bin/env python3
"""Round 5 on its own: key a finished registry by its OBI terms, folding what collides.

`run_assay_pipeline.py` runs this round at the end of every fresh paper. This script exists for
the registries built before the round did: it reads a finished `assays.json` + `assays_OBI.json`
off disk and canonicalizes them in place. **It calls nothing** -- the OBI term is already on disk,
and the rule is "same term, same assay" -- so backfilling a paper is free where re-extracting it
would be ~20 calls.

It does NOT re-extract, re-verify or re-correct. The registry it writes is the one on disk, keyed
by OBI label, with every wording in `name_in_paper` and every folded write-up in
`additional_evidence` -- the only difference a paper run before round 5 existed should have.

`--dry-run` prints what would change without writing.

Usage:
    python3 scripts/run_assay_merge.py <registry_dir> [--dry-run]
    python3 scripts/run_assay_merge.py --all [--dry-run]

Example:
    python3 scripts/run_assay_merge.py data/claims/assay_registries/24336226_SDY1260 --dry-run

Reads  : <registry_dir>/{assays.json,assays_OBI.json}
Writes : <registry_dir>/{assays.json,assays_OBI.json,assays_benchmark.json,assays_merges.json}
"""

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_extractor import trim_registry
from app.agent.assay_merger import build_merge_report, canonical_groups, canonicalize_registry

REGISTRY_ROOT = _REPO_ROOT / "data" / "claims" / "assay_registries"


def _load(registry_dir: Path) -> tuple[dict, dict | None]:
    registry_path = registry_dir / "assays.json"
    if not registry_path.exists():
        raise SystemExit(f"no assays.json in {registry_dir}")
    obi_path = registry_dir / "assays_OBI.json"
    return (json.loads(registry_path.read_text(encoding="utf-8")),
            json.loads(obi_path.read_text(encoding="utf-8")) if obi_path.exists() else None)


def dry_run(registry_dir: Path) -> int:
    """Print what canonicalizing would change. Returns the number of entries that would fold."""
    assays, obi = _load(registry_dir)
    groups = canonical_groups(assays, obi)
    folds = [g for g in groups if len(g["members"]) > 1]
    print(f"{registry_dir.name}: {len(assays)} entry(ies) → {len(groups)}, keyed by OBI term")
    for group in folds:
        print(f"    {group['key']}   <=  {', '.join(group['members'])}")
    return len(assays) - len(groups)


def canonicalize_one(registry_dir: Path) -> None:
    """Canonicalize this registry and rewrite the three files that are keyed together."""
    assays, obi = _load(registry_dir)
    if obi is None:
        print(f"{registry_dir.name}: no assays_OBI.json; run scripts/run_obi_map.py first")
        return

    merged, obi_out, folds = canonicalize_registry(assays, obi)
    report = build_merge_report(folds)
    print(f"{registry_dir.name}: {len(assays)} → {len(merged)} entry(ies)")
    for record in folds:
        print(f"  MERGED  {', '.join(record['folded'])} → {record['key']} "
              f"({record.get('obi_id') or 'no term'})")

    # Only these three: the pipeline's other files describe rounds this script did not re-run,
    # and rewriting them from a registry they were not derived from would misreport those rounds.
    (registry_dir / "assays.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (registry_dir / "assays_OBI.json").write_text(
        json.dumps(obi_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (registry_dir / "assays_benchmark.json").write_text(
        json.dumps(trim_registry(merged), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    merges_path = registry_dir / "assays_merges.json"
    if folds:
        merges_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    elif merges_path.exists():
        # A stale file from an earlier run would read as this run's findings.
        merges_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("registry_dir", nargs="?", help="Folder containing assays.json")
    parser.add_argument("--all", action="store_true",
                        help=f"Every registry under {REGISTRY_ROOT.relative_to(_REPO_ROOT)}")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change; write nothing")
    args = parser.parse_args()

    if args.all:
        targets = sorted(d for d in REGISTRY_ROOT.iterdir()
                         if d.is_dir() and (d / "assays.json").exists())
    elif args.registry_dir:
        targets = [Path(args.registry_dir)]
    else:
        raise SystemExit("pass a registry directory or --all")

    if args.dry_run:
        total = sum(dry_run(target) for target in targets)
        print(f"\n{len(targets)} registry(ies), {total} entry(ies) would fold."
              "\n--dry-run: nothing written.")
        return

    for target in targets:
        canonicalize_one(target)


if __name__ == "__main__":
    main()
