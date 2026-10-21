# OBI tree descent vs stored embedding mapping, three papers

*Experiment folder. Nothing here is on the serving path; `data/` and the production default
(`OBI_MAPPING_STRATEGY=embedding`) are untouched.*

Round 4 re-run with the `descend` strategy (one chat call per level of the OBI assay tree) on
the three papers whose stored embedding mapping disagreed most with the curator -- SDY1264,
SDY1373, SDY1260 -- and scored against `data/benchmark_assay/benchmark_assay_v4` beside the
stored mapping. The write-up, with every changed entry adjudicated against the ontology and
the paper, is `docs/obi_descent_vs_embedding_3papers.md`.

```
run_descent_comparison.py   map [--arm descend|hybrid|both] [--dry-run] [--only SDY] [--force] | score | report
tests/                      6 offline tests: ./.venv/bin/pytest experiment/obi_descent_3papers/tests
runs/embedding/<paper>/     the stored mapping, copied (assays.json, assays_benchmark.json, assays_OBI.json)
runs/descend/<paper>/       the root walk (same three files + raw.json with every level's candidates and reply)
runs/hybrid/<paper>/        the descent from the stored pick (raw.json's "obi_descend" round holds the walks)
comparison/{embedding,descend,hybrid}.{json,html}   the v2 comparator's report per arm
comparison/{diff.json,summary.md}                   the arms side by side, changed entries with their walks
```

Runs 2026-10-21. `descend` (root walk, 37 calls): 10/18 exact against embedding's 11/18; one
change right (SDY1260 anti-DT IgG by Luminex → antibody detection by CBA), three lost at the
first level because the curator's term sits in a different `is_a` branch than the one a reader
would enter. `hybrid` (the stored pick, then one descent from it, 11 calls): 11/18, level with
embedding -- the same CBA row won, one row over-specified onto a sole child (serum
neutralization → 96-well neutralization assay). Arms are selected with `map --arm`.
