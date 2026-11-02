"""Adjudicate round 5's blocked folds on the stored v3 registries: one call per pair, on copies.

Round 5 refused 22 folds across assay_result_v3, 14 on `readouts` and 6 on `sample_type`. No
string rule moves them (the vote's lenient match releases 1 of 14), and dropping the `readouts`
leg would fold pairs the curated benchmark lists as two rows. `assay_fold_judge.adjudicate` asks
the model about each pair whose only differing leg is `readouts` or `sample_type` -- 20 pairs,
the 2 that differ on the technique are never sent -- and folds a pair only on a literal SAME.

Nothing is written in place. Each registry's `assays.json`, `assays_OBI.json` and
`assays_merges.json` are copied under runs/<registry>/ and adjudicated there, with every reply
under `judge` in runs/<registry>/assays_raw.json. Score the result against the benchmark with
`scripts/compare_assay_benchmark_v2.py --registry-dir experiment/fold_adjudication/runs`, and
read the verdicts in run_<date>.txt: a SAME on a pair the benchmark keeps apart (SDY1328's two
ELISAs, SDY212's phospho-flow, SDY1640's intracellular cytokine staining) is a reason not to
wire the step into the pipeline, whatever the score.

    python3 experiment/fold_adjudication/run.py --dry-run     # which pairs, how many calls
    python3 experiment/fold_adjudication/run.py               # one call per listed pair
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))

from app.agent.assay_fold_judge import adjudicate, judged_pairs  # noqa: E402
from app.agent.assay_merger import blocked_folds, build_merge_report, canonical_groups  # noqa: E402

V3 = _REPO_ROOT / "data" / "31paper_assays" / "assay_result_v3"
RUNS = Path(__file__).with_name("runs")


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _registries() -> list[Path]:
    return sorted(p for p in V3.iterdir()
                  if (p / "assays.json").exists() and (p / "assays_OBI.json").exists())


def dry_run() -> None:
    total = sent = 0
    for registry_dir in _registries():
        assays, obi = _read(registry_dir / "assays.json"), _read(registry_dir / "assays_OBI.json")
        blocked = blocked_folds(canonical_groups(assays, obi))
        asked = judged_pairs(assays, obi)
        total += len(blocked)
        sent += len(asked)
        for record in blocked:
            mark = "ASK " if record in asked else "skip"
            print(f"{mark}  {registry_dir.name}: {record['member']} vs {record['anchor']}"
                  f" ({record.get('obi_id') or 'no term'}): {record['reason'][:110]}")
    print(f"\n{total} blocked fold(s), {sent} would be asked = {sent} call(s)"
          f" ({sent / max(len(_registries()), 1):.2f} per paper). --dry-run: nothing called.")


def run() -> None:
    from app.agent import assay_trace
    lines: list[str] = []
    out = lambda s="": (print(s), lines.append(s))  # noqa: E731
    out(f"fold adjudication on {V3.relative_to(_REPO_ROOT)}, run {_dt.date.today().isoformat()}")
    out()
    n_same = n_diff = 0
    for registry_dir in _registries():
        target = RUNS / registry_dir.name
        target.mkdir(parents=True, exist_ok=True)
        for name in ("assays.json", "assays_OBI.json", "assays_merges.json", "assays_benchmark.json"):
            if (registry_dir / name).exists():
                shutil.copy(registry_dir / name, target / name)
        assays, obi = _read(target / "assays.json"), _read(target / "assays_OBI.json")
        if not judged_pairs(assays, obi):
            continue
        trace = assay_trace.start()
        try:
            merged, obi_out, folds, blocked = adjudicate(assays, obi)
        finally:
            assay_trace.stop()
        trace.write(target / "assays_raw.json")
        for record in folds:
            n_same += 1
            out(f"SAME       {registry_dir.name}: {record['folded'][0]} -> {record['key']}: "
                f"{record['judged']['reason']}")
        for record in blocked:
            if "judged" not in record:
                continue
            n_diff += 1
            out(f"DIFFERENT  {registry_dir.name}: {record['member']} vs {record['anchor']}: "
                f"{record['judged']['reason']}")
        stored = _read(target / "assays_merges.json") or {}
        report = build_merge_report(list(stored.get("results") or []) + folds,
                                    stored.get("key_map"), blocked)
        from app.agent.assay_extractor import trim_registry
        for name, payload in (("assays.json", merged), ("assays_OBI.json", obi_out),
                              ("assays_benchmark.json", trim_registry(merged)),
                              ("assays_merges.json", report)):
            (target / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    out()
    out(f"{n_same} SAME (folded on the copy), {n_diff} DIFFERENT (kept apart)")
    log = Path(__file__).with_name(f"run_{_dt.date.today().isoformat()}.txt")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {log.relative_to(_REPO_ROOT)} and {RUNS.relative_to(_REPO_ROOT)}/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry_run() if args.dry_run else run()


if __name__ == "__main__":
    main()
