#!/usr/bin/env python3
"""Stage 2: the OBI picker on the 1249 vocabulary with a widened candidate list (K=30).

Round 4 only, over the 31 v3 registries, exactly as experiment/obi_vocab_v3 runs an arm --
same input `assays.json`, same comparator -- with two things changed together:
the vocabulary (1249 noncompositional) and the list width (K=30, paper-wording reserve 21).

Query embeddings are served from experiment/obi_topk/query_embeddings.json, so the only paid
calls are the LLM picks. The full-list fallback is left ENABLED, because the two arms this is
compared against (701@K=20 = 141 exact, 1249@K=20 = 140 exact) both had it.

Writes only under experiment/obi_topk_1249/picks/. Nothing in data/, in the other experiment
folders, or on the result drive is touched.

    ./.venv/bin/python experiment/obi_topk_1249/run_pick_1249.py --dry-run
    ./.venv/bin/python experiment/obi_topk_1249/run_pick_1249.py --k 30
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts",
          REPO_ROOT / "experiment" / "obi_vocab_v3", REPO_ROOT / "experiment" / "obi_topk"):
    sys.path.insert(0, str(p))

import run_topk                                        # noqa: E402
from run_vocab_comparison import ARMS, Vocabulary, plan  # noqa: E402

PICKS_DIR = HERE / "picks"
SUFFIX = {"noncompositional": "1249", "pruned": "701"}


class WidenedK:
    """TOP_K=k with the paper-wording reserve scaled with it. Leaves _fulllist_pick alone."""

    def __init__(self, k: int):
        self.k = k

    def __enter__(self):
        from app.agent import assay_obi_mapper as m

        self.primary = run_topk.primary_slots(self.k)
        self._saved = (m._top_k_candidates, m._merge_candidates)
        top, merge, k, primary = m._top_k_candidates, m._merge_candidates, self.k, self.primary
        m._top_k_candidates = lambda query, k=k, **kw: top(query, k=k, **kw)
        m._merge_candidates = lambda first, *others, **kw: merge(first, *others, k=k, primary_slots=primary)
        return self

    def __exit__(self, *exc):
        from app.agent import assay_obi_mapper as m

        m._top_k_candidates, m._merge_candidates = self._saved


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", default="noncompositional", choices=sorted(ARMS))
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    arm = args.arm
    index = ARMS[arm]["index"]
    dirs = run_topk.registries(run_topk.SOURCE_DIR)

    if args.dry_run:
        total = 0
        for d in dirs:
            total += sum(c for _, c in plan(arm, _read(d / "assays.json")))
        print(f"arm={arm} ({len(_read(index))} terms)  K={args.k}  "
              f"paper-wording slots={run_topk.primary_slots(args.k)}")
        print(f"{len(dirs)} registries, ~{total} chat picks "
              f"(query embeddings served from cache, 0 embedding calls)")
        print("--dry-run: nothing called")
        return

    from app.agent import assay_trace
    from app.agent.assay_obi_mapper import enrich_assays_with_obi
    from app.agent.assay_service import obi_summary

    cache = _read(run_topk.CACHE_PATH)
    out_root = PICKS_DIR / f"k{args.k}_{SUFFIX[arm]}"
    picks = 0
    with Vocabulary(arm), run_topk.CachedQueries(cache), WidenedK(args.k):
        for d in dirs:
            out_dir = out_root / d.name
            if (out_dir / "assays_OBI.json").exists() and not args.force:
                print(f"   skip {d.name}: already mapped")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in ("assays.json", "assays_benchmark.json"):
                shutil.copyfile(d / name, out_dir / name)
            trace = assay_trace.start()
            try:
                obi = enrich_assays_with_obi(_read(d / "assays.json"), terms_path=index)
            finally:
                assay_trace.stop()
            (out_dir / "assays_OBI.json").write_text(
                json.dumps(obi, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            trace.write(out_dir / "raw.json")
            s = obi_summary(obi)
            picks += sum(1 for e in obi.values() if e.get("resource") != "exact_original")
            print(f"   {d.name}: {s['mapped']}/{s['total']} mapped {s['resources']}", flush=True)
            for key in s["unresolved"]:
                print(f"      {'OBI ERROR' if key in s['errors'] else 'UNMAPPED '}  {key}")
    print(f"arm={arm} K={args.k}: ~{picks} chat picks this run (embeddings were cached)")


if __name__ == "__main__":
    main()
