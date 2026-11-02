#!/usr/bin/env python3
"""Round-5 ablation: the agent's v3 registries scored without the fold, and with the old fold.

Round 5 (`apps/api/app/agent/assay_merger.py`) re-keys a finished registry by OBI label and folds
two entries onto one term only when their measurement identity agrees. This arm builds, from the
files every v3 run left on disk, the registry as it stood before round 5 and the registry the
superseded rule would have delivered, so the fold's effect is read off the scorer rather than
argued:

    runs/unfolded/    assays_corrected.json (round 3's output, keyed by the extractor's wording)
                      with each entry's term taken from assays_OBI.json through the stored
                      key_map -- the registry before round 5. Free.
    runs/term_fold/   the old rule: every entry on one OBI term folded into the first, whatever
                      its sample or readout. Free.

The delivered v3 corpus folded 0 of its 177 entries (every pair on a shared term differed on the
identity triple), so `unfolded` scores exactly as the delivered registry and the contrast is
`term_fold`. `docs/assay_entry_grain.md` is the write-up of why that rule was dropped.

**This is an experiment arm, not a way to run a paper.** Nothing here writes under data/.

    build   runs/{unfolded,term_fold}/<registry>/{assays_benchmark.json, assays_OBI.json}
    score   comparison/<variant>{,_strict}.{json,html}
    report  comparison/summary.md

Usage, from the repo root:
    ./.venv/bin/python experiment/no_fold/build_unfolded.py build
    ./.venv/bin/python experiment/no_fold/build_unfolded.py score
    ./.venv/bin/python experiment/no_fold/build_unfolded.py report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from arms import mode_tables, read, registries, run_names, score_runs, write  # noqa: E402

RUNS_DIR = HERE / "runs"
COMPARISON_DIR = HERE / "comparison"
BENCH_FIELDS = ("name_in_paper", "aliases", "generate_claim", "source", "evidence")


def _names(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def unfolded(corrected: dict, obi: dict, key_map: dict[str, str]) -> tuple[dict, dict]:
    """The registry before round 5: every corrected entry under its own wording, with the OBI
    term its canonical key received. An entry the key_map does not place keeps no term."""
    bench: dict = {}
    out_obi: dict = {}
    for key, entry in corrected.items():
        canon = key_map.get(key)
        mapped = obi.get(canon, {}) if canon else {}
        bench[key] = {f: entry.get(f) for f in BENCH_FIELDS}
        out_obi[key] = {"obi_id": mapped.get("obi_id"), "obi_label": mapped.get("obi_label"),
                        "resource": mapped.get("resource"), "canonical_key": canon,
                        "name_in_paper": _names(entry.get("name_in_paper"))}
    return bench, out_obi


def term_fold(bench: dict, obi: dict) -> tuple[dict, dict]:
    """The superseded rule: every entry on one OBI term folds into the first, which keeps every
    member's wordings and aliases. Unmapped entries stay apart."""
    out_b: dict = {}
    out_o: dict = {}
    host_of: dict[str, str] = {}
    for key, entry in bench.items():
        term = obi.get(key, {}).get("obi_id")
        host = host_of.get(term) if term else None
        if host is None:
            out_b[key] = {**entry, "name_in_paper": _names(entry.get("name_in_paper")),
                          "aliases": list(entry.get("aliases") or [])}
            out_o[key] = {**obi.get(key, {}), "folded_from": [key]}
            if term:
                host_of[term] = key
            continue
        for n in _names(entry.get("name_in_paper")):
            if n not in out_b[host]["name_in_paper"]:
                out_b[host]["name_in_paper"].append(n)
        for a in entry.get("aliases") or []:
            if a not in out_b[host]["aliases"]:
                out_b[host]["aliases"].append(a)
        out_o[host]["folded_from"].append(key)
        out_o[host]["name_in_paper"] = out_b[host]["name_in_paper"]
    return out_b, out_o


def build(runs_dir: Path = RUNS_DIR, only: str | None = None) -> None:
    n_entries = n_folded = 0
    for d in registries(only=only):
        corrected = read(d / "assays_corrected.json")
        obi = read(d / "assays_OBI.json")
        key_map = (read(d / "assays_merges.json") if (d / "assays_merges.json").exists() else {}).get("key_map") or {}
        missing = [k for k in corrected if k not in key_map]
        if missing:
            print(f"   WARNING {d.name}: {len(missing)} entries without a key_map, scored unmapped: {missing}")
        bench, out_obi = unfolded(corrected, obi, key_map)
        write(runs_dir / "unfolded" / d.name / "assays_benchmark.json", bench)
        write(runs_dir / "unfolded" / d.name / "assays_OBI.json", out_obi)
        folded_b, folded_o = term_fold(bench, {k: v for k, v in out_obi.items()})
        write(runs_dir / "term_fold" / d.name / "assays_benchmark.json", folded_b)
        write(runs_dir / "term_fold" / d.name / "assays_OBI.json", folded_o)
        n_entries += len(bench)
        n_folded += len(bench) - len(folded_b)
    print(f"   unfolded: {n_entries} entries; term_fold: {n_entries - n_folded} ({n_folded} folded away)")


def run_report(runs_dir: Path = RUNS_DIR, comparison_dir: Path = COMPARISON_DIR) -> str:
    runs = run_names(runs_dir)
    text = "\n".join([
        "# Round-5 fold ablation: delivered v3 vs unfolded vs the old same-term fold", "",
        "`agent` is the delivered v3 corpus (round 5's identity fold); `unfolded` is round 3's "
        "registry with round 4's terms; `term_fold` folds every entry on a shared OBI term.", "",
        mode_tables(comparison_dir, runs_dir, run_calls={r: 0 for r in runs})]) + "\n"
    (comparison_dir / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").add_argument("--only")
    sub.add_parser("score")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.cmd == "build":
        build(only=args.only)
    elif args.cmd == "score":
        score_runs(RUNS_DIR, COMPARISON_DIR)
    else:
        print(run_report())


if __name__ == "__main__":
    main()
