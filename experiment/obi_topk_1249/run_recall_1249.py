#!/usr/bin/env python3
"""Stage 1 only: retrieval recall@K for the 1249 (noncompositional) vocabulary vs the live 701.

Free. No API call: query vectors come from experiment/obi_topk/query_embeddings.json (193
cached strings, vocabulary-independent) and term vectors from the arm's own embeddings file,
both already on disk. Replays the mapper's own
`_top_k_candidates -> _merge_candidates -> _with_pinned` at each K, with the paper-wording
reserve scaled with K exactly as experiment/obi_topk does (14 of 20 -> 21 of 30 -> 28 of 40).

Writes only under experiment/obi_topk_1249/. Nothing in experiment/obi_topk, data/ or the
result drive is touched.

    ./.venv/bin/python experiment/obi_topk_1249/run_recall_1249.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "apps" / "api", REPO_ROOT / "scripts",
          REPO_ROOT / "experiment" / "obi_vocab_v3", REPO_ROOT / "experiment" / "obi_topk"):
    sys.path.insert(0, str(p))

import run_topk                      # noqa: E402
from run_vocab_comparison import Vocabulary, curator_terms  # noqa: E402

OBI = REPO_ROOT / "data" / "OBI"
ARM_INDEX = {"pruned701": OBI / "obi_assay_pruned_index.json",
             "noncomp1249": OBI / "obi_assay_noncompositional_index.json"}
ARM_NAME = {"pruned701": "pruned", "noncomp1249": "noncompositional"}
OUT = HERE / "recall"


def main() -> None:
    cache = json.loads(run_topk.CACHE_PATH.read_text(encoding="utf-8"))
    pairing = json.loads(run_topk.PAIRING_REPORT.read_text(encoding="utf-8"))
    curated = {k: v["obi_id"] for k, v in curator_terms(pairing).items() if v.get("obi_id")}
    records = run_topk.entries(run_topk.SOURCE_DIR)
    OUT.mkdir(parents=True, exist_ok=True)

    results = {}
    for arm, index in ARM_INDEX.items():
        with Vocabulary(ARM_NAME[arm]):
            res = run_topk.recall(cache, curated, records, terms_path=index)
        results[arm] = res
        (OUT / f"recall_{arm}.json").write_text(
            json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (OUT / f"recall_{arm}.md").write_text(run_topk.render_recall(res), encoding="utf-8")

    ks = results["pruned701"]["ks"]
    lines = ["# recall@K: 701 vs 1249, assay_result_v3 (31 papers)", "",
             f"{results['pruned701']['scored_entries']} entries carry a curated OBI term. "
             "Stage 1 only -- is the curator's term on the list the picker would see.", "",
             "| K | slots | 701 on-list | 701 recall | 1249 on-list | 1249 recall | delta |",
             "|---|---|---|---|---|---|---|"]
    for k in ks:
        a = results["pruned701"]["per_k"][str(k)]
        b = results["noncomp1249"]["per_k"][str(k)]
        lines.append(f"| {k} | {a['primary_slots']} | {a['hits']} | {a['recall']:.1%} | "
                     f"{b['hits']} | {b['recall']:.1%} | {b['hits'] - a['hits']:+d} |")

    # the entry the K=20 benchmark run lost on the 1249 arm
    lines += ["", "## SDY1293 `microscopy assay` (the one entry 1249 lost at K=20)", "",
              "| K | on 701 list (rank) | on 1249 list (rank) |", "|---|---|---|"]
    for k in ks:
        def look(arm):
            for r in results[arm]["per_k"][str(k)]["rows"]:
                if "SDY1293" in r["registry"] and r["key"] == "microscopy assay":
                    return f"yes (#{r['rank']})" if r["hit"] else "no"
            return "n/a"
        lines.append(f"| {k} | {look('pruned701')} | {look('noncomp1249')} |")

    md = "\n".join(lines) + "\n"
    (OUT / "comparison.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
