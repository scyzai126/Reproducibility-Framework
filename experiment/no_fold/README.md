# Round-5 fold ablation

*2026-11-02. `build_unfolded.py`; results in `comparison/summary.md`. Free: no model call.*

Round 5 of the assay pipeline re-keys a finished registry by OBI label and folds two entries onto
one term only when their measurement identity (`standard_technique_name`, `sample_type`,
`readouts`) agrees (`docs/assay_entry_grain.md`). This arm scores the v3 corpus as it stood before
that round (`unfolded`) and as the superseded rule would have delivered it (`term_fold`: every
entry on a shared term folded into the first).

| | agent (delivered v3) | unfolded | term_fold |
|---|---|---|---|
| entries | 177 | 177 | 155 |
| matched / MISSED, default scorer | 156 / 1 | 156 / 1 | 151 / 2 |
| matched / MISSED, strict scorer | 156 / 2 | 156 / 2 | 151 / 7 |
| exact OBI term | 140 | 140 | 136 |
| precision | 88.1% | 88.1% | 97.4% |
| F1 default / strict | 0.934 / 0.931 | 0.934 / 0.931 | 0.981 / 0.965 |

**Round 5 folded 0 of 177 entries in v3**: every pair on a shared term differed on the identity
triple, so `unfolded` is the delivered registry under other keys and scores identically. The
contrast is `term_fold`, which removes 22 entries from 19 same-term groups. It gains precision
(97.4%) and loses 4 exact terms and, under the strict scorer, 5 curated rows: the curators write
two rows on one term in 5 of the 31 papers (four flow panels in SDY1289, two ELISPOTs in SDY984),
and the default scorer's leftover fold hides exactly that loss (MISSED 2 against strict 7). The
F1 the old rule shows under the default scorer, 0.981, is the number `docs/assay_scorer_strict_mode.md`
warns about.

```
./.venv/bin/python experiment/no_fold/build_unfolded.py build    # runs/{unfolded,term_fold}/
./.venv/bin/python experiment/no_fold/build_unfolded.py score    # comparison/<variant>{,_strict}.{json,html}
./.venv/bin/python experiment/no_fold/build_unfolded.py report   # comparison/summary.md
```

Tests: `tests/test_build_unfolded.py`.
