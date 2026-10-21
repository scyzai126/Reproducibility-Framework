#!/usr/bin/env python3
"""Round 5 on its own: key a finished registry by its OBI terms, folding what collides.

`run_assay_pipeline.py` runs this round at the end of every fresh paper. This script exists for
the registries built before the round did: it reads a finished `assays.json` + `assays_OBI.json`
off disk and canonicalizes them in place. **Without `--judge` it calls nothing** -- the OBI term
is already on disk, and every group of entries sharing a term folds, as the round did before the
fold judge existed -- so backfilling a paper is free where re-extracting it would be ~20 calls.
That free path is also the one the judge's measurement was made on: 12 of its 18 folds across
the 31-paper run had merged different measurements, so a registry canonicalized this way carries
the folds the judge exists to stop. `--judge` is the opt-in that makes the pipeline's one call
per candidate group (prompts/judge_fold.txt) and folds only what the judge calls one measurement;
the rest keep the term under `<label> — <wording>` (printed `KEPT APART`), and a group the judge
could not rule on folds nothing (printed `FOLD JUDGE FAILED`). `--dry-run --judge` prints the
candidate groups and the call count without calling anything.

It does NOT re-extract, re-verify or re-correct. The registry it writes is the one on disk, keyed
by OBI label, with every wording in `name_in_paper` and every folded write-up in
`additional_evidence` -- the only difference a paper run before round 5 existed should have.

`--dry-run` prints what would change without writing.

`--map` runs round 4 first -- **the other thing here that costs**: 2-3 calls per assay name the
OBI vocabulary does not carry verbatim. It is the recovery path when a pipeline run's OBI round
failed. With no `assays_OBI.json` on disk it maps every entry of `assays_corrected.json` when
there is one (the registry round 4 reads), else `assays.json`. With a mapping on disk it
re-maps **only the entries whose lookup failed** (`resource: error`, or missing from the
mapping) and keeps the rest -- a round that lost one entry to a timeout used to be re-paid in
full. `--map-all` maps every entry again. `--map --dry-run` prints the call count without
calling anything.

`assays_merges.json` is always written, with a `key_map` from every key the extractor used to
the key it is delivered under -- composed with the stored one, so canonicalizing twice still
maps the original wordings. Earlier fold records are kept when this pass folds nothing new.

Usage:
    python3 scripts/run_assay_merge.py <registry_dir> [--dry-run] [--map | --map-all] [--judge]
    python3 scripts/run_assay_merge.py --all [--dry-run] [--map | --map-all] [--judge]

Example:
    python3 scripts/run_assay_merge.py data/31paper_assays/assay_result_v1/24336226_SDY1260 --dry-run

Reads  : <registry_dir>/{assays.json,assays_OBI.json,assays_corrected.json (with --map)}
Writes : <registry_dir>/{assays.json,assays_OBI.json,assays_benchmark.json,assays_merges.json}
         and, with --map or --judge, the replies into <registry_dir>/assays_raw.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_extractor import KEY_SEP, trim_registry
from app.agent.assay_merger import (
    build_merge_report,
    canonical_groups,
    canonicalize_registry,
    compose_key_maps,
    fold_candidates,
    judge_failed,
    kept_apart,
    key_map,
    review_unfolded,
)
from app.agent.assay_service import REGISTRY_ROOT, obi_misses, obi_query_calls


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _load(registry_dir: Path, remap: bool = False,
          remap_all: bool = False) -> tuple[dict, dict | None]:
    """(registry, OBI mapping).

    With `remap` and no mapping on disk -- or `remap_all` -- the registry is the one round 4
    reads (`assays_corrected.json` when there is one) and the mapping is None: every entry gets
    mapped. With a mapping on disk, `remap` returns the registry and mapping as they are, and
    `remap_targets` picks the entries whose lookup failed.
    """
    registry = _read(registry_dir / "assays.json")
    if registry is None:
        raise SystemExit(f"no assays.json in {registry_dir}")
    stored = _read(registry_dir / "assays_OBI.json")
    if remap and (remap_all or stored is None):
        return _read(registry_dir / "assays_corrected.json") or registry, None
    return registry, stored


def remap_targets(assays: dict, obi: dict | None) -> list[str]:
    """The entries `--map` runs round 4 on: every one when there is no mapping, else those
    whose lookup failed (`resource: error`) or that the mapping does not carry.

    An entry the picker declined (`unresolved`) is not one: it was asked and answered, and
    asking again is `--map-all`'s job. Nor is a mapped one -- the point is to finish a round
    that lost an entry to a timeout without paying for the entries it kept.
    """
    if obi is None:
        return list(assays)
    return [key for key in assays
            if key not in obi or (obi.get(key) or {}).get("resource") == "error"]


def dry_run(registry_dir: Path, remap: bool = False, judge: bool = False,
            remap_all: bool = False) -> int:
    """Print what canonicalizing would change. Returns the number of entries that would fold --
    with `judge`, the most that could, since which of them do is the judge's answer."""
    assays, obi = _load(registry_dir, remap, remap_all)
    if remap:
        targets = remap_targets(assays, obi)
        missed = obi_misses({key: assays[key] for key in targets})
        calls = sum(obi_query_calls(key, assays[key]) for key in missed)
        print(f"{registry_dir.name}: --map would cost {calls} call(s) for {len(targets)} of "
              f"{len(assays)} entry(ies) ({len(targets) - len(missed)} match the vocabulary "
              "for free)")
        for key in missed:
            print(f"    needs embedding + LLM: {key}")
        return 0
    groups = canonical_groups(assays, obi)
    folds = [g for g in groups if len(g["members"]) > 1]
    print(f"{registry_dir.name}: {len(assays)} entry(ies) → {len(groups)}, keyed by OBI term")
    if judge:
        # Named as what they are -- groups the judge will be asked about -- not as folds.
        candidates = fold_candidates(assays, obi)
        for group in candidates:
            print(f"    candidate group {group['key']}: {', '.join(group['members'])}")
        print(f"    {len(candidates)} candidate group(s) to judge → {len(candidates)} call(s)")
    else:
        for group in folds:
            print(f"    {group['key']}   <=  {', '.join(group['members'])}")
    for group in groups:
        if group["alone"] == "review":
            print(f"    REVIEW UNFOLDED  {group['key']}: keeps its own entry; "
                  "identity not supported by the judge")
    return len(assays) - len(groups)


def _judge(assays: dict, obi: dict, registry_dir: Path) -> tuple[dict, list[dict]]:
    """Round 5's paid step: one call per candidate group. Returns (partition, judge records).

    Imported here, not at the top, like `--map`'s mapper: a plain canonicalize must not even
    load the client. No candidates means no client either -- the common case for a registry
    canonicalized once already, whose groups are folded or kept apart and so are singletons.
    The replies are kept the way a full run keeps them, merged into assays_raw.json, so a
    judgement made here can be read back without paying for it again.
    """
    candidates = fold_candidates(assays, obi)
    if not candidates:
        return {}, []
    from app.agent import assay_trace
    from app.agent.assay_fold_judge import judge_fold_groups
    from app.agent.claim_parser import _get_client

    trace = assay_trace.start()
    try:
        partition, records = asyncio.run(judge_fold_groups(candidates, assays, _get_client()))
    finally:
        assay_trace.stop()
    trace.write(registry_dir / assay_trace.RAW_FILE)
    return partition, records


def canonicalize_one(registry_dir: Path, remap: bool = False, judge: bool = False,
                     remap_all: bool = False) -> None:
    """Canonicalize this registry and rewrite the files that are keyed together."""
    assays, obi = _load(registry_dir, remap, remap_all)
    stored = _read(registry_dir / "assays_merges.json") or {}
    if remap:
        targets = remap_targets(assays, obi)
        if obi is None:
            # A fresh mapping of the pre-canonical registry: nothing earlier to compose with.
            stored = {}
        fresh: dict = {}
        if targets:
            # Imported here, not at the top: it is a paid step, and a plain canonicalize should
            # not even load the client.
            from app.agent import assay_trace
            from app.agent.assay_obi_mapper import enrich_assays_with_obi
            # The picks are kept like a full run keeps them, merged into the file the full run
            # wrote.
            trace = assay_trace.start()
            try:
                fresh = enrich_assays_with_obi({key: assays[key] for key in targets})
            finally:
                assay_trace.stop()
            trace.write(registry_dir / assay_trace.RAW_FILE)
        else:
            print(f"{registry_dir.name}: nothing to re-map -- no entry's lookup failed; "
                  "--map-all maps every entry again")
        # Registry order, the fresh mapping where one was made and the stored one elsewhere.
        obi = {key: fresh[key] if key in fresh else (obi or {}).get(key) for key in assays}
        for key in targets:
            entry = obi[key] or {}
            if entry.get("resource") == "error":
                print(f"  OBI ERROR  {key}: {entry.get('obi_error')}")
            elif not entry.get("obi_id"):
                print(f"  UNMAPPED  {key}: no OBI term")
    if obi is None:
        print(f"{registry_dir.name}: no assays_OBI.json; pass --map to run the OBI round first")
        return

    # `None` -- not judged -- folds every same-term group, as this script always has. The
    # judge's partition, when asked for, is threaded through every reading of the grouping so
    # the key_map, the lists and the registry all describe the same fold.
    partition: dict | None = None
    judged: list[dict] | None = None
    if judge:
        partition, judged = _judge(assays, obi, registry_dir)

    keys = compose_key_maps(stored.get("key_map"), key_map(assays, obi, partition))
    review = review_unfolded(assays, obi, partition)
    apart = kept_apart(assays, obi, partition)
    failed = judge_failed(assays, obi, partition)
    merged, obi_out, folds = canonicalize_registry(assays, obi, partition)
    # Folds found by an earlier pass are findings too; a second pass over an already-folded
    # registry finds none, and used to delete the only record of the first.
    report = build_merge_report(list(stored.get("results") or []) + folds, keys, review, apart,
                                failed, judged)
    print(f"{registry_dir.name}: {len(assays)} → {len(merged)} entry(ies)")
    for record in folds:
        print(f"  MERGED  {', '.join(record['folded'])} → {record['key']} "
              f"({record.get('obi_id') or 'no term'})")
    # The same two lines run_assay_pipeline.report_result prints, from the same records.
    by_label = {record.get("label"): record for record in judged or []}
    for key in apart:
        label = key.split(KEY_SEP, 1)[0]
        print(f"  KEPT APART  {key}: judged a different measurement from {label} "
              f"— {by_label.get(label, {}).get('reason') or 'no reason given'}")
    for label in failed:
        print(f"  FOLD JUDGE FAILED  {label}: "
              f"{by_label.get(label, {}).get('error') or 'no error recorded'}; members kept apart")
    for key in review:
        mark = merged[key].get("identity_review") or {}
        print(f"  REVIEW UNFOLDED  {key}: kept its own entry; identity {mark.get('verdict')} "
              f"— {mark.get('reason') or 'no reason given'}")

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
                        help=f"Every registry under {REGISTRY_ROOT.relative_to(_REPO_ROOT)}")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change; write nothing")
    parser.add_argument("--map", action="store_true",
                        help="Run the OBI round first (paid: 2-3 calls per vocabulary miss); "
                             "with a mapping on disk, only on entries whose lookup failed")
    parser.add_argument("--map-all", action="store_true",
                        help="Run the OBI round on every entry again, keeping nothing of the "
                             "mapping on disk (implies --map)")
    parser.add_argument("--judge", action="store_true",
                        help="Ask the fold judge before folding (paid: 1 call per group of "
                             "entries sharing a term); without it every such group folds")
    args = parser.parse_args()

    if args.all:
        targets = sorted(d for d in REGISTRY_ROOT.iterdir()
                         if d.is_dir() and (d / "assays.json").exists())
    elif args.registry_dir:
        targets = [Path(args.registry_dir)]
    else:
        raise SystemExit("pass a registry directory or --all")

    remap = args.map or args.map_all
    if args.dry_run:
        total = sum(dry_run(target, remap, args.judge, args.map_all) for target in targets)
        print(f"\n{len(targets)} registry(ies), {'at most ' if args.judge else ''}{total} "
              "entry(ies) would fold.\n--dry-run: nothing written.")
        return

    for target in targets:
        canonicalize_one(target, remap, args.judge, args.map_all)


if __name__ == "__main__":
    main()
