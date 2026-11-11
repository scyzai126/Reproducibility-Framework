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

`--map` runs round 4 first -- **the one thing here that costs**: 2-3 calls per assay name the OBI
vocabulary does not carry verbatim. It is the recovery path when a pipeline run's OBI round
failed, and it maps `assays_corrected.json` when there is one (the registry round 4 reads),
else `assays.json`. `--map --dry-run` prints the call count without calling anything.

`--judge` runs round 6 after the fold -- **paid, one call per fold round 5 refused on readouts
or sample type**: SAME folds the pair, anything else keeps it apart with the model's reason on
the REVIEW line. `--judge --dry-run` lists the pairs and the call count without calling.

`assays_merges.json` is always written, with a `key_map` from every key the extractor used to
the key it is delivered under -- composed with the stored one, so canonicalizing twice still
maps the original wordings. Earlier fold records are kept when this pass folds nothing new.

Usage:
    python3 scripts/run_assay_merge.py <registry_dir> [--dry-run] [--map] [--judge]
    python3 scripts/run_assay_merge.py --all [--dry-run] [--map] [--judge]

Example:
    python3 scripts/run_assay_merge.py data/31paper_assays/assay_result_v1/24336226_SDY1260 --dry-run

Reads  : <registry_dir>/{assays.json,assays_OBI.json,assays_corrected.json (with --map)}
Writes : <registry_dir>/{assays.json,assays_OBI.json,assays_benchmark.json,assays_merges.json}
"""

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_extractor import trim_registry
from app.agent.assay_fold_judge import adjudicate, judgeable, reconcile_report
from app.agent.assay_merger import (
    blocked_folds,
    build_merge_report,
    canonical_groups,
    canonicalize_registry,
    compose_key_maps,
    key_map,
)
from app.agent.assay_service import REGISTRY_ROOT, obi_misses, obi_query_calls


#: Folders a registry may hold that carry a full file set of their own — a pre-remap snapshot,
#: not a registry to process. `obi_701_k20` is the 2026-11-10 vocabulary switch's backup.
_BACKUP_DIRS = frozenset({"obi_701_k20"})


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _load(registry_dir: Path, remap: bool = False) -> tuple[dict, dict | None]:
    """(registry, OBI mapping). With `remap`, the registry round 4 reads and no mapping."""
    registry = _read(registry_dir / "assays.json")
    if registry is None:
        raise SystemExit(f"no assays.json in {registry_dir}")
    if remap:
        return _read(registry_dir / "assays_corrected.json") or registry, None
    return registry, _read(registry_dir / "assays_OBI.json")


def dry_run(registry_dir: Path, remap: bool = False, judge: bool = False) -> int:
    """Print what canonicalizing would change. Returns the number of entries that would fold."""
    assays, obi = _load(registry_dir, remap)
    if remap:
        missed = obi_misses(assays)
        calls = sum(obi_query_calls(key, assays[key]) for key in missed)
        print(f"{registry_dir.name}: --map would cost {calls} call(s) "
              f"({len(assays) - len(missed)} of {len(assays)} match the vocabulary for free)")
        for key in missed:
            print(f"    needs embedding + LLM: {key}")
        return 0
    groups = canonical_groups(assays, obi)
    folds = [g for g in groups if len(g["members"]) > 1]
    print(f"{registry_dir.name}: {len(assays)} entry(ies) → {len(groups)}, keyed by OBI term")
    for group in folds:
        print(f"    {group['key']}   <=  {', '.join(group['members'])}")
    blocked = blocked_folds(groups)
    for record in blocked:
        print(f"    REVIEW  not folded  {record['member']} kept apart from "
              f"{record['kept_apart_from']} ({record.get('obi_id') or 'no term'}): "
              f"{record['reason']}")
    if judge:
        asked = [r for r in blocked if judgeable(r)]
        print(f"    --judge would cost {len(asked)} call(s): one per fold refused on readouts "
              f"or sample type")
    return len(assays) - len(groups)


def _print_usage(grouped: dict, registry_dir: Path) -> None:
    """What the paid round just run was billed for, in the full pipeline's format -- and one
    row in the corpus-wide ledger, since a mapping or judging pass costs like any run."""
    from app.agent import assay_ledger, assay_trace
    from app.config import settings
    summary = assay_trace.usage_summary(grouped)
    if summary["by_round"]:
        print("  usage:")
        for line in assay_trace.format_usage(summary, settings.OPENAI_MODEL):
            print(f"    {line}")
    name = registry_dir.name.removesuffix("_pdf")
    pmid, _, sdy = name.partition("_")
    assay_ledger.record_run(pmid, sdy, registry_dir, grouped, settings.OPENAI_MODEL)


def canonicalize_one(registry_dir: Path, remap: bool = False, judge: bool = False) -> None:
    """Canonicalize this registry and rewrite the files that are keyed together."""
    assays, obi = _load(registry_dir, remap)
    stored = _read(registry_dir / "assays_merges.json") or {}
    if remap:
        # Imported here, not at the top: it is the one paid step, and a plain canonicalize
        # should not even load the client.
        from app.agent import assay_trace
        from app.agent.assay_obi_mapper import enrich_assays_with_obi
        # The picks are kept like a full run keeps them, merged into the file the full run wrote.
        trace = assay_trace.start()
        try:
            obi = enrich_assays_with_obi(assays)
        finally:
            assay_trace.stop()
        trace.write(registry_dir / assay_trace.RAW_FILE)
        _print_usage(trace.as_json(), registry_dir)
        # A fresh mapping of the pre-canonical registry: nothing earlier to compose with.
        stored = {}
        for key, entry in obi.items():
            if entry.get("resource") == "error":
                print(f"  OBI ERROR  {key}: {entry.get('obi_error')}")
            elif not entry.get("obi_id"):
                print(f"  UNMAPPED  {key}: no OBI term")
    if obi is None:
        print(f"{registry_dir.name}: no assays_OBI.json; pass --map to run the OBI round first")
        return

    keys = compose_key_maps(stored.get("key_map"), key_map(assays, obi))
    blocked = blocked_folds(canonical_groups(assays, obi))
    merged, obi_out, folds = canonicalize_registry(assays, obi)
    # Folds found by an earlier pass are findings too; a second pass over an already-folded
    # registry finds none, and used to delete the only record of the first. The same for the
    # folds a pass refused.
    report = build_merge_report(list(stored.get("results") or []) + folds, keys,
                                list(stored.get("blocked") or []) + blocked)
    if judge and any(judgeable(r) for r in blocked):
        # Round 6, paid: the replies join the raw file like round 4's do.
        from app.agent import assay_trace
        trace = assay_trace.start()
        try:
            merged, obi_out, judged_folds, judged_blocked = adjudicate(merged, obi_out)
        finally:
            assay_trace.stop()
        trace.write(registry_dir / assay_trace.RAW_FILE)
        _print_usage(trace.as_json(), registry_dir)
        keys, judged_folds, blocked = reconcile_report(keys, blocked, judged_folds, judged_blocked)
        folds = folds + judged_folds
        report = build_merge_report(list(stored.get("results") or []) + folds, keys,
                                    list(stored.get("blocked") or []) + blocked)
    print(f"{registry_dir.name}: {len(assays)} → {len(merged)} entry(ies)")
    for record in folds:
        print(f"  MERGED  {', '.join(record['folded'])} → {record['key']} "
              f"({record.get('obi_id') or 'no term'})")
        if record.get("judged"):
            print(f"      JUDGED  SAME: {record['judged'].get('reason')}")
    for record in blocked:
        print(f"  REVIEW  not folded  {record['member']} kept apart from "
              f"{record['kept_apart_from']} ({record.get('obi_id') or 'no term'}): "
              f"{record['reason']}")
        if record.get("judged"):
            print(f"      JUDGED  {record['judged'].get('verdict')}: "
                  f"{record['judged'].get('reason')}")

    # Only these four: the pipeline's other files describe rounds this script did not re-run,
    # and rewriting them from a registry they were not derived from would misreport those rounds.
    for name, payload in (("assays.json", merged), ("assays_OBI.json", obi_out),
                          ("assays_benchmark.json", trim_registry(merged)),
                          ("assays_merges.json", report)):
        (registry_dir / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("registry_dir", nargs="?", help="Folder containing assays.json")
    parser.add_argument("--all", action="store_true",
                        help=f"Every registry under --root (default: "
                             f"{REGISTRY_ROOT.relative_to(_REPO_ROOT)})")
    parser.add_argument("--root", type=Path, default=None,
                        help="Registry root for --all. Without it --all walks REGISTRY_ROOT and "
                             "IGNORES any positional path, which is easy to mistake for 'every "
                             "registry under the folder I named'.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change; write nothing")
    parser.add_argument("--map", action="store_true",
                        help="Run the OBI round first (paid: 2-3 calls per vocabulary miss)")
    parser.add_argument("--judge", action="store_true",
                        help="Run round 6 after the fold (paid: 1 call per fold refused on "
                             "readouts or sample type)")
    args = parser.parse_args()

    if args.all:
        root = args.root or (Path(args.registry_dir) if args.registry_dir else REGISTRY_ROOT)
        if not root.is_dir():
            raise SystemExit(f"not a directory: {root}")
        print(f"--all over {root}")
        # A registry's own backup folder holds a full set of files, so it looks like a registry.
        targets = sorted(d for d in root.iterdir()
                         if d.is_dir() and d.name not in _BACKUP_DIRS
                         and (d / "assays.json").exists())
    elif args.registry_dir:
        targets = [Path(args.registry_dir)]
    else:
        raise SystemExit("pass a registry directory or --all")

    if args.dry_run:
        total = sum(dry_run(target, args.map, args.judge) for target in targets)
        print(f"\n{len(targets)} registry(ies), {total} entry(ies) would fold."
              "\n--dry-run: nothing written.")
        return

    for target in targets:
        canonicalize_one(target, args.map, args.judge)


if __name__ == "__main__":
    main()
